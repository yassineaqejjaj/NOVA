"""Nothing above the ceiling reaches an external model: org model, own key, voice, teaching, stores (NOV-76).

Synthetic fixtures only. ``Spy`` wraps the scripted model and counts what is actually sent.
"""

from __future__ import annotations

import uuid

import httpx
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.domain.llm_guardrail import CallScope
from nova.infra import db
from nova.infra.crypto import encrypt
from nova.infra.models import Artifact, ArtifactVersion, AuditEvent, Task, UserLLMConfig
from nova.services import llm_config, providers
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.execution_store import SqlExecutionStore
from nova.services.executions import build_deps, run_task
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app
from tests.support import fake_voice_server as fake
from tests.support.fakes import context_item


class Spy:
    """The organization's model as the platform sees it: every call that reaches it is counted."""

    def __init__(self, inner) -> None:
        self._inner, self.calls, self.model_name, self.prompts = inner, 0, inner.model_name, []

    def _seen(self, messages) -> None:
        self.calls += 1
        self.prompts.append("\n".join(m.content for m in messages))

    async def structured_output(self, messages, *a, **k):
        self._seen(messages)
        return await self._inner.structured_output(messages, *a, **k)

    async def generate(self, messages, *a, **k):
        self._seen(messages)
        return await self._inner.generate(messages, *a, **k)

    def stream(self, messages, *a, **k):
        self._seen(messages)
        return self._inner.stream(messages, *a, **k)


def _external(monkeypatch) -> None:
    """The organization's model is a hosted API (not declared internal)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.vendor.example/v1")
    monkeypatch.setattr(settings, "llm_local", False)
    assert not settings.llm_is_local


async def _ask(user, project) -> str:
    async with db.session_scope() as session:
        conversation = await create_conversation(session, user, project_id=project, title=None)
        _, _, task = await submit(
            session,
            user,
            conversation,
            ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
            {s.id for s in get_skill_registry().all()},
        )
        return str(task.id)


async def _audit(action: str) -> list[AuditEvent]:
    async with db.session_scope() as session:
        return list((await session.scalars(select(AuditEvent).where(AuditEvent.action == action))).all())


async def test_c2_context_with_an_external_model_sends_no_request(user, project, llm, orbit, forge, monkeypatch):
    _external(monkeypatch)
    spy = Spy(llm)
    providers.override("llm", spy)
    orbit.items = [context_item(1, "Synthetic internal note"), context_item(2, "Synthetic C2 note", classification=2)]
    task_id = await _ask(user, project)
    before = len(await _audit("llm.blocked"))

    assert await run_task(task_id, "start") == "failed"

    # Only the intent step ran, before any context existed: no request carries the restricted material
    assert spy.calls == 1 and not any("Synthetic" in p for p in spy.prompts)
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
    assert "C2" in task.error and "external model" in task.error and "Synthetic C2 note" not in task.error
    events = (await _audit("llm.blocked"))[before:]
    assert events and events[0].details["reason"] == "classification" and events[0].details["level"] == 2
    assert events[0].details["ceiling"] == 1 and events[0].target_id == task_id
    assert "Synthetic C2 note" not in str(events[0].details) + events[0].summary  # the reason, never the content


async def test_c3_context_is_refused_the_same_way(user, project, llm, orbit, forge, monkeypatch):
    _external(monkeypatch)
    spy = Spy(llm)
    providers.override("llm", spy)
    orbit.items = [context_item(1, "Synthetic secret", classification=3)]
    assert await run_task(await _ask(user, project), "start") == "failed"
    assert spy.calls == 1 and not any("Synthetic" in p for p in spy.prompts)


async def test_c1_context_still_works_with_an_external_model(user, project, llm, orbit, forge, monkeypatch):
    _external(monkeypatch)
    spy = Spy(llm)
    providers.override("llm", spy)
    assert await run_task(await _ask(user, project), "start") == "completed"
    assert spy.calls > 0


async def test_an_internal_model_may_see_c3(user, project, llm, orbit, forge, monkeypatch):
    spy = Spy(llm)
    providers.override("llm", spy)
    monkeypatch.setattr(get_settings(), "llm_local", True)  # declared inside the perimeter
    orbit.items = [context_item(1, "Synthetic secret", classification=3)]
    assert await run_task(await _ask(user, project), "start") == "completed"
    assert spy.calls > 0


async def test_the_ceiling_is_configurable(user, project, llm, orbit, forge, monkeypatch):
    _external(monkeypatch)
    monkeypatch.setattr(get_settings(), "llm_max_classification", 2)
    spy = Spy(llm)
    providers.override("llm", spy)
    orbit.items = [context_item(1, "Synthetic C2 note", classification=2)]
    assert await run_task(await _ask(user, project), "start") == "completed"
    assert spy.calls > 0


async def test_a_stored_restricted_artifact_raises_the_level_of_the_run(user, project):
    async with db.session_scope() as session:
        artifact = Artifact(
            type="prd",
            title="Synthetic restricted PRD",
            project_id=uuid.UUID(project),
            owner_id=uuid.UUID(user.user_id),
            current_version=1,
            classification=2,
        )
        session.add(artifact)
        await session.flush()
        from nova.artifacts.registry import get_artifact_registry
        from nova.domain.artifacts import empty_content

        content = empty_content(get_artifact_registry().get("prd"), "Synthetic restricted PRD")
        session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=1,
                content=content.model_dump(mode="json"),
                changed_sections=[],
                author_type="nova",
                summary="x",
                state="current",
            )
        )
        artifact_id = str(artifact.id)
    from dataclasses import replace

    scope = CallScope()
    store = SqlExecutionStore(replace(user, clearance=3), scope=scope)
    assert scope.level == 0
    await store.get_artifact(artifact_id, user.user_id)
    assert scope.level == 2  # an edit of a C2 Artifact is a C2 call even with no retrieved context
    scope = CallScope()
    await SqlExecutionStore(replace(user, clearance=3), scope=scope).list_artifact_outlines(user.user_id, project_id=project)
    assert scope.level == 2


async def test_the_guard_wraps_every_model_of_the_run(user, project, llm, monkeypatch):
    _external(monkeypatch)
    monkeypatch.setattr(get_settings(), "llm_fallback_models", ["backup-model"])
    deps = await build_deps(user.user_id, uuid.UUID(project), "interactive", task_id=None)
    deps.scope.raise_to(2)
    from nova.domain.llm import LLMMessage
    from nova.domain.llm_guardrail import ClassificationBlocked

    try:
        await deps.llm.generate([LLMMessage(role="user", content="x")])
    except ClassificationBlocked:
        pass
    else:
        raise AssertionError("fallback chain must sit behind the guard")


# --- Bring your own key ---------------------------------------------------------------------------------------


async def _own_model(user, *, provider: str, base_url: str) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(500)

    providers.override("llm_transport", httpx.MockTransport(handler))
    async with db.session_scope() as session:
        session.add(
            UserLLMConfig(
                user_id=uuid.UUID(user.user_id),
                provider=provider,
                model="own-model",
                base_url=base_url,
                key_ciphertext=encrypt("sk-synthetic-key-0123456789"),
                key_hint="6789",
            )
        )
    return seen


async def test_a_users_own_external_key_never_receives_c2(user, project, llm):
    from nova.domain.llm import LLMMessage
    from nova.domain.llm_guardrail import ClassificationBlocked

    seen = await _own_model(user, provider="anthropic", base_url="")
    deps = await build_deps(user.user_id, uuid.UUID(project), "interactive", task_id=None)
    assert deps.llm.model_name == "own-model"  # the run does use the user's own model...
    deps.scope.raise_to(2, "context")
    try:
        await deps.llm.generate([LLMMessage(role="user", content="Synthetic C2 note")])
    except ClassificationBlocked as refused:
        assert "anthropic/own-model" in str(refused)
    else:
        raise AssertionError("C2 must not be sent to the user's own external provider")
    assert seen == []  # ...but no request left for it
    deps.scope.level = 1
    assert await _call_fails_on_the_wire(deps) and len(seen) == 1  # C1 is allowed through (the mock then answers 500)


async def _call_fails_on_the_wire(deps) -> bool:
    from nova.domain.llm import LLMError, LLMMessage

    try:
        await deps.llm.generate([LLMMessage(role="user", content="Synthetic internal note")])
    except LLMError:
        return True
    return False


async def test_a_users_own_endpoint_is_internal_only_when_its_host_is_declared(user, monkeypatch):
    await _own_model(user, provider="custom", base_url="https://gpu.corp.example/v1")
    settings = get_settings()
    assert (await llm_config.destination_for_user(user.user_id)).local is False
    view = llm_config.public_view(await _config(user))
    assert view["max_classification"] == 1  # what the settings screen tells the user
    monkeypatch.setattr(settings, "llm_local_hosts", "gpu.corp.example")
    assert (await llm_config.destination_for_user(user.user_id)).local is True
    assert llm_config.public_view(await _config(user))["max_classification"] == 3


async def _config(user):
    async with db.session_scope() as session:
        return await llm_config.get_config(session, user.user_id)


# --- Voice ------------------------------------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _voice_client(app, monkeypatch, *, tts: str = "elevenlabs", selfhosted: bool = True) -> httpx.AsyncClient:
    from nova_api.routers import voice

    settings = get_settings()
    for key, value in {
        "voice_url": "http://voice.test" if selfhosted else "",
        "voice_token": fake.TOKEN,
        "voice_tts_provider": tts,
        "elevenlabs_api_key": fake.ELEVENLABS_KEY,
    }.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(voice, "TRANSPORT", httpx.ASGITransport(app=fake.app))
    fake.calls.clear()
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    login = await client.post("/api/v1/auth/dev-login", json={"email": f"{uuid.uuid4().hex[:8]}@example.com", "name": "V"})
    assert login.status_code == 200
    return client


async def test_voice_never_sends_c2_text_to_elevenlabs(app, monkeypatch):
    client = await _voice_client(app, monkeypatch)
    for level in (2, 3):
        spoken = await client.post("/api/v1/voice/speak", json={"text": "Synthetic C2 sentence", "classification": level})
        assert spoken.status_code == 200 and spoken.headers["content-type"] == "audio/wav"  # the self-hosted voice
    assert not [c for c in fake.calls if c.startswith("el-tts")]  # nothing went to the external service
    clear = await client.post("/api/v1/voice/speak", json={"text": "Hello", "classification": 1})
    assert clear.headers["content-type"] == "audio/mpeg" and any(c.startswith("el-tts") for c in fake.calls)


async def test_voice_refuses_c2_text_when_no_internal_voice_exists(app, monkeypatch):
    client = await _voice_client(app, monkeypatch, selfhosted=False)
    refused = await client.post("/api/v1/voice/speak", json={"text": "Synthetic C2 sentence", "classification": 2})
    assert refused.status_code == 403 and refused.json()["code"] == "classification_blocked"
    assert not [c for c in fake.calls if c.startswith("el-tts")]
    assert "Synthetic" not in refused.text


async def test_the_classification_of_the_spoken_text_is_required(app, monkeypatch):
    client = await _voice_client(app, monkeypatch)
    assert (await client.post("/api/v1/voice/speak", json={"text": "Hello"})).status_code == 422
    assert (await client.post("/api/v1/voice/speak", json={"text": "Hello", "classification": 9})).status_code == 422


# --- Teach NOVA -------------------------------------------------------------------------------------------------


async def test_teaching_from_edits_of_a_restricted_artifact_is_not_sent_to_an_external_model(user, project, llm, monkeypatch):
    from nova.domain.llm_guardrail import ClassificationBlocked
    from nova.services import teach

    _external(monkeypatch)
    spy = Spy(llm)
    providers.override("llm", spy)
    async with db.session_scope() as session:
        await teach.start(session, uuid.UUID(user.user_id))
    async with db.session_scope() as session:
        artifact = Artifact(
            type="prd", title="Synthetic restricted PRD", owner_id=uuid.UUID(user.user_id), current_version=2, classification=2
        )
        session.add(artifact)
        await session.flush()
        session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=2,
                content={},
                changed_sections=["summary"],
                author_type="user",
                author_id=uuid.UUID(user.user_id),
                summary="x",
                state="current",
            )
        )
    async with db.session_scope() as session:
        try:
            await teach.finish(session, uuid.UUID(user.user_id), description="", lang="en")
        except ClassificationBlocked:
            pass
        else:
            raise AssertionError("the restricted edit must not reach an external model")
    assert spy.calls == 0

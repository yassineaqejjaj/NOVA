"""Per-Skill model routing through the REAL provider code and a real HTTP server (no provider fake).

The inference server speaks the OpenAI-compatible protocol (tests/support/fake_llm_server) behind a recorder that
notes which ``model`` each request asked for: the routed Skill's generation must go to the routed model, every
other call to the main one, and a model that is not an allowed one must never be requested.
"""

from __future__ import annotations

import asyncio
import json
import socket
import uuid

import uvicorn
from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import LLMCall, Task
from nova.services import providers
from nova.services.conversations import ComposerInput, create_conversation, submit
from nova.services.executions import run_task
from nova.skills.registry import get_skill_registry
from tests.support.fake_llm_server import app as fake_inference_app


class Recorder:
    """ASGI wrapper: records the ``model`` of every chat completion, then lets the fake server answer."""

    def __init__(self, app, models: list[str]) -> None:
        self.app, self.models = app, models

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].endswith("/chat/completions"):
            body, more = b"", True
            while more:
                message = await receive()
                body += message.get("body", b"")
                more = message.get("more_body", False)
            self.models.append(json.loads(body).get("model"))

            async def replay():
                return {"type": "http.request", "body": body, "more_body": False}

            return await self.app(scope, replay, send)
        return await self.app(scope, receive, send)


async def test_a_routed_skill_is_written_by_its_model_over_real_http_and_others_keep_the_main_one(
    user, project, orbit, forge, monkeypatch
):
    models: list[str] = []
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(Recorder(fake_inference_app, models), host="127.0.0.1", port=port, log_level="warning")
    )
    serving = asyncio.create_task(server.serve())
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(0.05)
        assert server.started

        settings = get_settings()
        monkeypatch.setattr(settings, "llm_provider", "openai_compatible")
        monkeypatch.setattr(settings, "llm_base_url", f"http://127.0.0.1:{port}/v1")
        monkeypatch.setattr(settings, "llm_model", "main-model")
        monkeypatch.setattr(settings, "replay_models", ["cheap-model"])
        monkeypatch.setattr(settings, "llm_skill_models", {"prd": "cheap-model", "vision-to-backlog": "rogue-model"})
        providers._overrides.pop("llm", None)  # use the real provider built from the settings above
        providers._cache.pop("llm", None)

        async with db.session_scope() as session:
            conversation = await create_conversation(session, user, project_id=project, title=None)
            _, _, task = await submit(
                session,
                user,
                conversation,
                ComposerInput(text="Create a PRD for scheduled CSV exports in FORGE", project_id=project),
                {s.id for s in get_skill_registry().all()},
            )
            task_id = str(task.id)
        assert await run_task(task_id, "start") == "completed"
    finally:
        server.should_exit = True
        await serving
        providers._cache.pop("llm", None)

    assert "cheap-model" in models and "main-model" in models  # generation routed, everything else on the main model
    assert "rogue-model" not in models  # a model that is not allowed is never requested
    assert models.count("cheap-model") < len(models)
    async with db.session_scope() as session:
        recorded = set(await session.scalars(select(LLMCall.model).where(LLMCall.task_id == uuid.UUID(task_id))))
        assert (await session.get(Task, uuid.UUID(task_id))).usage["llm_calls"] == len(models)
    assert {"cheap-model", "main-model"} <= recorded  # the cost records name the model that really answered

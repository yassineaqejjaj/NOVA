"""Capture, training and SDLC ingestion register the same API endpoint and credential in FORGE (two domains)."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.infra import db
from nova.infra.models import AgentPolicy, IntegrationReference
from nova.integrations.forge.adapter import ForgeEvaluationSink
from nova.integrations.forge.connection import ForgeConfigurationError
from nova.services import providers, sdlc_forge, training
from nova.skills.registry import get_skill_registry

from .test_training import FakeForge

API, WEB = "https://nova-api.example", "https://nova-web.example"  # two domains: FORGE must call the API


@pytest.fixture
def forge(monkeypatch) -> FakeForge:
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_nova_endpoint", API)
    monkeypatch.setattr(settings, "forge_credential_id", "configured-credential")
    monkeypatch.setattr(settings, "public_url", WEB)
    fake = FakeForge()
    providers.override("forge_client", fake)
    return fake


@pytest_asyncio.fixture(autouse=True)
async def clean():
    async def wipe() -> None:
        async with db.session_scope() as session:
            await session.execute(delete(IntegrationReference).where(IntegrationReference.kind == "agent_version"))
            await session.execute(delete(AgentPolicy))

    await wipe()
    yield
    await wipe()


def sink(forge: FakeForge) -> ForgeEvaluationSink:
    providers.reset()
    providers.override("forge_client", forge)
    return ForgeEvaluationSink(get_settings(), get_skill_registry(), "model-a", client=forge)  # type: ignore[arg-type]


def registered(forge: FakeForge, slug: str) -> list[dict]:
    return forge.versions[forge.agents[slug]["id"]]


async def test_the_sink_registers_the_api_endpoint_and_the_credential_it_is_configured_with(forge):
    await sink(forge).agent_version_id()
    (version,) = registered(forge, "nova")
    assert version["endpoint"] == API and version["credential_id"] == "configured-credential"


async def test_the_provider_builds_the_sink_from_the_settings(forge):
    providers.reset()
    built = providers.evaluation()
    assert built.nova_inbound_url == API and built.credential_id == "configured-credential"


async def test_capture_training_and_sdlc_resolve_the_same_endpoint_and_credential(forge):
    await sink(forge).agent_version_id()
    settings = get_settings()
    async with db.session_scope() as session:
        policy = await learning_policy(session)
        await training.forge_version_id(forge, policy, settings, get_skill_registry())
    await sdlc_forge._agent_version(forge, "user-model")
    seen = {
        (v["endpoint"], v.get("credential_id")) for slug in ("nova", "nova-product", "nova-sdlc") for v in registered(forge, slug)
    }
    assert seen == {(API, "configured-credential")}


async def learning_policy(session):
    from nova.services import learning

    return await learning.ensure_base_policy(session, AgentProfile.product)


async def test_a_version_cached_without_credential_is_registered_again_with_it(forge, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_credential_id", "")
    first = await sink(forge).agent_version_id()
    assert "credential_id" not in registered(forge, "nova")[0]
    monkeypatch.setattr(settings, "forge_credential_id", "configured-credential")
    second = await sink(forge).agent_version_id()
    assert second != first
    assert registered(forge, "nova")[-1]["credential_id"] == "configured-credential"
    assert await sink(forge).agent_version_id() == second  # and that one is then reused


async def test_the_sdlc_agent_version_is_registered_again_when_the_endpoint_changes(forge, monkeypatch):
    first = await sdlc_forge._agent_version(forge, "user-model")
    monkeypatch.setattr(get_settings(), "forge_nova_endpoint", "https://other-api.example")
    second = await sdlc_forge._agent_version(forge, "user-model")
    assert second != first and registered(forge, "nova-sdlc")[-1]["endpoint"] == "https://other-api.example"


async def test_reexecution_capture_refuses_to_register_a_version_without_credential(forge, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_credential_id", "")
    with pytest.raises(ForgeConfigurationError, match="NOVA_FORGE_CREDENTIAL_ID"):
        await sink(forge).capture(_record())
    assert "nova" not in forge.agents  # nothing was registered in FORGE


def _record():
    from datetime import UTC, datetime

    from nova.domain.evaluation import ExecutionRecord

    now = datetime.now(UTC)
    return ExecutionRecord(
        task_id=str(uuid.uuid4()), trace_id=None, user_intent="x", origin="interactive", agent_version="0.1.0", model="m",
        status="completed", started_at=now, finished_at=now,
    )  # fmt: skip

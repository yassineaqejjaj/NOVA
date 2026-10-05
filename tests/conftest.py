"""Shared fixtures: SQLite database, in-memory checkpointer and pub/sub, fake LLM/ORBIT/FORGE adapters."""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

_DB = Path(tempfile.mkdtemp(prefix="nova-tests-")) / "nova.db"
os.environ.setdefault("NOVA_ENV", "test")
os.environ.setdefault("NOVA_DATABASE_URL", f"sqlite+aiosqlite:///{_DB}")
os.environ.setdefault("NOVA_AUTH_MODE", "dev")
os.environ.setdefault("NOVA_CELERY_TASK_ALWAYS_EAGER", "true")
os.environ.setdefault("NOVA_LLM_MODEL", "test-model")
# Tests never call external services, whatever the developer's .env enables (environment beats .env).
os.environ.update(
    {
        "NOVA_VOICE_TTS_PROVIDER": "selfhosted",
        "NOVA_VOICE_STT_PROVIDER": "selfhosted",
        "NOVA_ELEVENLABS_API_KEY": "",
        "NOVA_VOICE_URL": "",
        "NOVA_LLM_API_KEY": "",
        "NOVA_LLM_PROVIDER": "vllm",
        "NOVA_LLM_BASE_URL": "http://127.0.0.1:9/v1",
        "NOVA_SMTP_HOST": "",  # codes go to the in-memory outbox
        "NOVA_SMTP_FROM": "",
    }
)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402

from nova.domain.permissions import Principal  # noqa: E402
from nova.infra import db  # noqa: E402
from nova.infra.events import MemoryPublisher, set_publisher  # noqa: E402
from nova.infra.models import Project, ProjectMember, ProjectReference  # noqa: E402
from nova.services import providers  # noqa: E402
from nova.services.users import principal_for, upsert_user  # noqa: E402
from tests.support.fakes import FakeContextProvider, FakeEvaluationSink, ScriptedLLM  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def database():
    db.configure()
    async with db.engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.drop_all)
        await conn.run_sync(db.Base.metadata.create_all)
    url = os.environ["NOVA_DATABASE_URL"]
    if not url.startswith("sqlite"):  # NOVA_DATABASE_URL=postgresql+asyncpg://…/nova_test exercises the real checkpointer
        from nova.agent.runtime import setup_checkpointer

        await setup_checkpointer(url)
    yield
    await db.engine().dispose()


@pytest.fixture(autouse=True)
def adapters():
    llm, context, evaluation = ScriptedLLM(), FakeContextProvider(), FakeEvaluationSink()
    providers.reset()
    providers.override("llm", llm)
    providers.override("context", context)
    providers.override("evaluation", evaluation)
    publisher = MemoryPublisher()
    set_publisher(publisher)
    yield {"llm": llm, "context": context, "evaluation": evaluation, "publisher": publisher}
    providers.reset()
    set_publisher(None)


@pytest.fixture
def llm(adapters) -> ScriptedLLM:
    return adapters["llm"]


@pytest.fixture
def orbit(adapters) -> FakeContextProvider:
    return adapters["context"]


@pytest.fixture
def forge(adapters) -> FakeEvaluationSink:
    return adapters["evaluation"]


@pytest_asyncio.fixture
async def user() -> Principal:
    async with db.session_scope() as session:
        u = await upsert_user(
            session,
            subject=f"test-{uuid.uuid4()}",
            email=f"{uuid.uuid4().hex[:8]}@example.com",
            display_name="Yassine",
            realm_roles=["nova-user"],
            is_admin=False,
        )
        u.title = "Head of AI"
        return principal_for(u)


@pytest_asyncio.fixture
async def project(user: Principal) -> str:
    async with db.session_scope() as session:
        slug = f"forge-{uuid.uuid4().hex[:6]}"
        p = Project(slug=slug, name="FORGE", description="AI Evaluation Platform")
        session.add(p)
        await session.flush()
        session.add(ProjectReference(project_id=p.id, system="orbit", external_id="forge", label="FORGE"))
        session.add(ProjectMember(project_id=p.id, user_id=uuid.UUID(user.user_id), role="owner"))
        return str(p.id)


async def scalar(stmt):
    async with db.session_scope() as session:
        return await session.scalar(stmt)


__all__ = ["scalar", "select"]

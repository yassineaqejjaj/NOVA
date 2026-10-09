"""Start the NOVA API for E2E: fresh SQLite schema, then uvicorn (test doubles provide LLM and ORBIT)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import uvicorn

sys.path[:0] = [str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parents[2] / "apps" / "api")]

from nova.infra import db, models  # noqa: E402, F401 - models register the tables


async def reset() -> None:
    db.configure()
    async with db.engine().begin() as conn:
        await conn.run_sync(db.Base.metadata.drop_all)
        await conn.run_sync(db.Base.metadata.create_all)
    await db.engine().dispose()


if __name__ == "__main__":
    asyncio.run(reset())
    if os.environ.get("NOVA_E2E_FAKE_GITHUB"):  # engineering E2E: an in-memory GitHub instead of api.github.com
        from nova.services import providers
        from tests.support.fake_github import FakeForge, FakeGitHub

        github = FakeGitHub()
        providers.override("github", lambda token: github)
        providers.override("forge_client", FakeForge())  # finished runs are ingested by an in-memory FORGE
    uvicorn.run("nova_api.main:app", host="127.0.0.1", port=int(os.environ.get("E2E_API_PORT", "8293")), log_level="warning")

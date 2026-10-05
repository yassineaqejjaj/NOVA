"""NOVA API (FastAPI). REST ``/api/v1``, SSE execution streams, NOVA Agent Protocol ``/v1/agents/…``."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import text

from nova.agent.runtime import setup_checkpointer
from nova.config import get_settings
from nova.infra import db
from nova.infra.telemetry import configure_telemetry
from nova.services.accounts import ensure_demo_account
from nova.services.skills_sync import sync_skills
from nova.skills.registry import get_skill_registry
from nova_api import auth, errors
from nova_api.routers import (
    artifacts,
    context,
    conversations,
    executions,
    forge_protocol,
    me,
    missions,
    training,
    voice,
    work,
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_telemetry(service_name=f"{settings.otel_service_name}-api")
    db.configure()
    registry = get_skill_registry()  # fails fast on an invalid Skill library
    async with db.session_scope() as session:
        result = await sync_skills(session, registry)
    log.info("Skill catalog %s: %s skills (%s)", registry.catalog_digest(), len(registry.all()), result)
    if settings.demo_account_email and settings.demo_account_password:
        try:
            async with db.session_scope() as session:
                demo = await ensure_demo_account(session)
            log.info("Demo account ready: %s", demo.email if demo else None)
        except Exception:  # the identity service may be starting: never block the API on the demo account
            log.exception("Demo account could not be prepared")
    if not settings.database_url.startswith("sqlite"):
        await setup_checkpointer(settings.database_url)
    yield
    await db.engine().dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NOVA API",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/api/v1/docs",
        openapi_url="/api/v1/openapi.json",
        redoc_url=None,
    )
    errors.install(app)

    api = APIRouter(prefix="/api/v1")
    api.include_router(auth.router)
    for module in (me, work, conversations, executions, artifacts, context, voice, missions, training):
        api.include_router(module.router)
    app.include_router(api)
    app.include_router(forge_protocol.router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response

    @app.get("/health", include_in_schema=False)
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready", include_in_schema=False)
    async def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            async with db.engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        if not settings.database_url.startswith("sqlite"):
            try:
                import redis.asyncio as redis

                client = redis.from_url(settings.valkey_url)
                await client.ping()
                await client.aclose()
                checks["valkey"] = "ok"
            except Exception:
                checks["valkey"] = "unavailable"
        ok = all(v == "ok" for v in checks.values())
        return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)

    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready")
    return app


app = create_app()

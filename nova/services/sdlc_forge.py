"""Automatic ingestion of finished SDLC runs by FORGE, and follow-up of their evaluation.

A finished run (completed or failed; a cancelled one is the user's choice) is sent once to FORGE as an *observed run*
(``POST /runs/observed``, idempotent). FORGE scores it with its own pipeline; NOVA keeps the link and the score in
``integration_references`` and shows them on the run. Everything here is best effort: FORGE being down never affects a run.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from nova.config import get_settings
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import IntegrationReference, SdlcRun
from nova.integrations.forge import sdlc as mapping
from nova.integrations.forge.client import ForgeClient, ForgeError
from nova.services import providers

log = logging.getLogger(__name__)

KIND = "sdlc_run"
TERMINAL_FORGE = ("completed", "failed", "cancelled")
INGESTABLE = ("completed", "failed")


async def _cached(kind: str, nova_type: str, nova_id: str) -> str | None:
    async with session_scope() as session:
        row = await session.scalar(
            select(IntegrationReference).where(
                IntegrationReference.system == "forge",
                IntegrationReference.kind == kind,
                IntegrationReference.nova_type == nova_type,
                IntegrationReference.nova_id == nova_id,
            )
        )
        return row.external_id if row else None


async def _remember(kind: str, nova_type: str, nova_id: str, external_id: str, data: dict[str, Any] | None = None) -> None:
    async with session_scope() as session:
        session.add(
            IntegrationReference(
                system="forge", kind=kind, nova_type=nova_type, nova_id=nova_id, external_id=external_id, data=data or {}
            )
        )


async def _agent_version(client: ForgeClient, model: str, policy: dict[str, Any] | None = None) -> str:
    settings = get_settings()
    key = f"{settings.version}|{model}|p{int((policy or {}).get('version', 0))}"
    if cached := await _cached("agent_version", "sdlc_release", key):
        return cached
    agent = await client.find_agent(mapping.AGENT_SLUG) or await client.create_agent(mapping.agent_body())
    endpoint = settings.forge_nova_endpoint or settings.public_url
    body = mapping.agent_version_body(nova_version=settings.version, model=model, endpoint=endpoint, policy=policy)
    try:
        version = await client.create_agent_version(str(agent["id"]), body)
    except ForgeError as exc:
        if exc.status != 409:
            raise
        versions = await client.list_agent_versions(str(agent["id"]))
        version = next((v for v in versions if v.get("version") == body["version"]), None)
        if version is None:
            raise
    await _remember("agent_version", "sdlc_release", key, str(version["id"]), {"agent_id": str(agent["id"])})
    return str(version["id"])


async def _scenario(client: ForgeClient) -> str:
    if cached := await _cached("scenario", "sdlc", mapping.SCENARIO_SLUG):
        return cached
    scenario = await client.find_scenario(mapping.SCENARIO_SLUG) or await client.create_scenario(mapping.scenario_body())
    await _remember("scenario", "sdlc", mapping.SCENARIO_SLUG, str(scenario["id"]))
    return str(scenario["id"])


async def _evaluation_config(client: ForgeClient) -> str | None:
    """The rules-only evaluation config (created once; needs the FORGE maintainer role). Without it FORGE falls back to its
    default configuration, whose LLM judges would also grade the SDLC criteria."""
    if cached := await _cached("evaluation_config", "sdlc", mapping.CONFIG_KEY):
        return cached
    config = await client.find_evaluation_config(mapping.CONFIG_KEY)
    if config is None:
        try:
            config = await client.create_evaluation_config(mapping.evaluation_config_body())
        except ForgeError as exc:
            if exc.status not in (403, 409, 422):
                raise
            log.warning(
                "FORGE evaluation config %s could not be created (%s): using FORGE's default configuration",
                mapping.CONFIG_KEY,
                exc.message,
            )
            return None
    await _remember("evaluation_config", "sdlc", mapping.CONFIG_KEY, str(config["id"]))
    return str(config["id"])


def _reference_data(forge_run: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    run_id = str(forge_run.get("id"))
    return {
        "run_id": run_id,
        "scenario_id": scenario_id,
        "status": forge_run.get("status"),
        "composite_score": forge_run.get("composite_score"),
        "passed": forge_run.get("passed"),
        "url": f"{get_settings().forge_public_url.rstrip('/')}/runs/{run_id}",
        "synced_at": utcnow().isoformat(),
    }


def below_threshold(data: dict[str, Any]) -> bool:
    """FORGE finished scoring the run and it did not pass (its own verdict, else the configured threshold)."""
    score = data.get("composite_score")
    if score is None or data.get("status") not in ("completed", "failed"):
        return False
    if data.get("passed") is not None:
        return data["passed"] is False
    return float(score) < get_settings().sdlc_improvement_threshold


async def ingest(run_id: str) -> dict[str, Any] | None:
    """Send one finished run to FORGE (once). Returns the stored reference data, or ``None`` when nothing was sent."""
    client = providers.forge_client()
    if client is None:
        return None
    async with session_scope() as session:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
        if run is None or run.status not in INGESTABLE:
            return None
        existing = await session.scalar(
            select(IntegrationReference).where(
                IntegrationReference.system == "forge", IntegrationReference.kind == KIND, IntegrationReference.nova_id == run_id
            )
        )
        if existing is not None:
            return existing.data
    agent_version_id = await _agent_version(client, run.model, (run.context or {}).get("policy"))
    scenario_id = await _scenario(client)
    config_id = await _evaluation_config(client)
    forge_run = await client.create_observed_run(
        mapping.observed_run_body(run, agent_version_id=agent_version_id, scenario_id=scenario_id, evaluation_config_id=config_id)
    )
    data = _reference_data(forge_run, scenario_id)
    async with session_scope() as session:
        session.add(
            IntegrationReference(
                system="forge", kind=KIND, nova_type="sdlc_run", nova_id=run_id, external_id=data["run_id"], data=data
            )
        )
    log.info("SDLC run %s ingested by FORGE as %s", run_id, data["run_id"])
    return data


async def ingest_safely(run_id: str) -> None:
    """Called when a run ends: never raises (the maintenance sync retries what failed)."""
    try:
        await ingest(run_id)
    except Exception:  # FORGE must never affect a delivery run
        log.warning("FORGE ingestion of SDLC run %s failed; it will be retried", run_id, exc_info=True)


async def sync() -> int:
    """Maintenance: ingest finished runs that were never sent, then refresh the evaluation state of the sent ones."""
    client = providers.forge_client()
    if client is None:
        return 0
    since = utcnow() - timedelta(days=7)
    done = 0
    async with session_scope() as session:
        sent = set(
            await session.scalars(
                select(IntegrationReference.nova_id).where(
                    IntegrationReference.system == "forge", IntegrationReference.kind == KIND
                )
            )
        )
        missing = [
            str(r)
            for r in await session.scalars(select(SdlcRun.id).where(SdlcRun.status.in_(INGESTABLE), SdlcRun.finished_at >= since))
            if str(r) not in sent
        ]
        open_refs = list(
            await session.scalars(
                select(IntegrationReference).where(
                    IntegrationReference.system == "forge",
                    IntegrationReference.kind == KIND,
                    IntegrationReference.updated_at >= since,
                )
            )
        )
    for run_id in missing:
        try:
            await ingest(run_id)
        except ForgeError as exc:
            if exc.status in (404, 405):  # this FORGE has no observed runs yet: nothing to retry until it is upgraded
                log.info("FORGE does not support observed runs yet (%s): SDLC ingestion paused", exc.message)
                return done
            log.warning("FORGE ingestion of SDLC run %s failed: %s", run_id, exc.message)
            continue
        except Exception:
            log.warning("FORGE ingestion of SDLC run %s failed", run_id, exc_info=True)
            continue
        done += 1
    for ref in open_refs:
        if ref.data.get("status") in TERMINAL_FORGE and ref.data.get("composite_score") is not None:
            continue
        try:
            forge_run = await client.get_run(ref.external_id)
        except ForgeError:
            continue
        async with session_scope() as session:
            row = await session.get(IntegrationReference, ref.id)
            if row is not None:
                row.data = {
                    **row.data,
                    "status": forge_run.get("status"),
                    "composite_score": forge_run.get("composite_score"),
                    "passed": forge_run.get("passed"),
                    "synced_at": utcnow().isoformat(),
                }
                if "improvement" not in row.data and below_threshold(row.data):
                    row.data = {**row.data, "improvement": "pending"}  # a lesson will be drawn from this run
        done += 1
    from nova.services import sdlc_improvement

    try:
        await sdlc_improvement.improve()
    except Exception:
        log.warning("SDLC improvement pass failed", exc_info=True)
    return done


async def states(session: Any, run_ids: list[uuid.UUID]) -> dict[str, dict[str, Any]]:
    """FORGE evaluation state per run id, for the API."""
    if not run_ids:
        return {}
    rows = await session.scalars(
        select(IntegrationReference).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == KIND,
            IntegrationReference.nova_id.in_([str(i) for i in run_ids]),
        )
    )
    return {
        r.nova_id: {
            "status": r.data.get("status"),
            "composite_score": r.data.get("composite_score"),
            "passed": r.data.get("passed"),
            "url": r.data.get("url"),
            "ingested_at": aware(r.created_at).isoformat() if r.created_at else None,
        }
        for r in rows
    }

"""NOVA Agent Protocol — the endpoint FORGE's ``nova`` adapter calls (FORGE docs/AGENT_PROTOCOL.md §6).

``POST /v1/agents/{nova_agent_id}/runs`` (root path, not ``/api``). FORGE prepares the context (no ORBIT
call), NOVA runs the same LangGraph with ``execute_automatically`` and no external writes, and returns
the FAP response with inline events (no OTLP export for these runs: no double counting).
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.artifacts.registry import get_artifact_registry
from nova.artifacts.render import render_markdown
from nova.config import get_settings
from nova.domain.artifacts import ArtifactContent
from nova.domain.enums import AutonomyMode, ExecutionOrigin, TaskStatus
from nova.infra.db import get_session, session_scope
from nova.infra.models import Artifact, ArtifactVersion, ExecutionEvent, SkillExecution, Task
from nova.integrations.forge import mapper
from nova.integrations.forge.schemas import FapError, FapEvent, FapUsage, NovaRunRequest, NovaRunResponse
from nova.services.executions import run_task
from nova.services.users import service_user
from nova.skills.registry import get_skill_registry

router = APIRouter(tags=["nova-agent-protocol"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _error(status: int, type_: str, message: str, retryable: bool = False) -> JSONResponse:
    body = NovaRunResponse(error=FapError(type=type_, message=message, retryable=retryable))
    return JSONResponse(body.model_dump(mode="json"), status_code=status)


@router.post("/v1/agents/{nova_agent_id}/runs", response_model=NovaRunResponse)
async def run(
    nova_agent_id: str,
    body: NovaRunRequest,
    session: SessionDep,
    authorization: str = Header(default=""),
    traceparent: str | None = Header(default=None),
) -> Any:
    settings = get_settings()
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not token or not secrets.compare_digest(token, settings.forge_inbound_token):
        return _error(401, "UNAUTHORIZED", "Jeton NOVA invalide")
    if nova_agent_id != mapper.NOVA_AGENT_ID:
        return _error(404, "NOT_FOUND", f"Agent NOVA inconnu : {nova_agent_id}")
    prompt = body.input.text().strip()
    if not prompt:
        return _error(400, "EXECUTION_ERROR", "Entrée vide")
    if body.constraints:
        prompt += "\n\nConstraints:\n" + "\n".join(f"- {c}" for c in body.constraints)

    user = await service_user(session)
    task_input = {
        "origin": ExecutionOrigin.forge_protocol.value,
        "autonomy": AutonomyMode.execute_automatically.value,
        "intent": prompt,
        "context_mode": "none",
        "provided_context": [i.model_dump(mode="json") for i in mapper.provided_context(body)],
        "preferences": {"nova_name": "NOVA", "max_workflow_steps": min(body.budget.max_steps or 8, 8)},
    }
    task = Task(
        user_id=user.id,
        objective=prompt[:2000],
        origin=ExecutionOrigin.forge_protocol.value,
        autonomy=AutonomyMode.execute_automatically.value,
        input=task_input,
        status=TaskStatus.queued.value,
    )
    session.add(task)
    await session.commit()
    task_id = str(task.id)

    timeout = max(5.0, (body.budget.timeout_seconds or 120.0) - 5.0)
    carrier = {"traceparent": traceparent} if traceparent else None
    try:
        status = await asyncio.wait_for(run_task(task_id, "start", traceparent=carrier), timeout=timeout)
    except TimeoutError:
        return _error(200, "TIMEOUT", "Délai dépassé côté NOVA")
    return await _response(task_id, status)


async def _response(task_id: str, status: TaskStatus) -> NovaRunResponse:
    tid = uuid.UUID(task_id)
    async with session_scope() as session:
        task = await session.get(Task, tid)
        assert task is not None
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == tid))).all()
        outputs, output_json = [], {}
        for artifact in artifacts:
            version = await session.scalar(
                select(ArtifactVersion).where(
                    ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == artifact.current_version
                )
            )
            content = ArtifactContent.model_validate(version.content)
            outputs.append(render_markdown(content, get_artifact_registry().get(artifact.type)))
            output_json[artifact.type] = content.model_dump(mode="json")
        events = (
            await session.scalars(select(ExecutionEvent).where(ExecutionEvent.task_id == tid).order_by(ExecutionEvent.seq))
        ).all()
        fap = mapper.fap_events(
            [{"seq": e.seq, "type": e.type, "payload": e.payload, "created_at": e.created_at.isoformat()} for e in events]
        )
        executions = (await session.scalars(select(SkillExecution).where(SkillExecution.task_id == tid))).all()
        for ex in executions:
            fap.append(
                FapEvent(
                    id=f"skill-{ex.id}",
                    type="llm_call",
                    name=f"Skill {ex.skill_id}@{ex.skill_version}",
                    ended_at=ex.created_at.isoformat(),
                    status="ok" if ex.status == "completed" else "error",
                    attributes={
                        "model": ex.model,
                        "input_tokens": ex.tokens_in,
                        "output_tokens": ex.tokens_out,
                        "nova.skill": ex.skill_id,
                        "nova.skill_version": ex.skill_version,
                    },
                )
            )
        texts = [e.payload.get("block", {}).get("data", {}).get("markdown", "") for e in events if e.type == "block"]
        answer = next((t for t in reversed(texts) if t), "")
        usage = task.usage or {}
        skills = get_skill_registry()
        response = NovaRunResponse(
            output="\n\n".join(outputs) or answer,
            output_json=output_json or None,
            events=fap,
            usage=FapUsage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                model_calls=usage.get("model_calls", 0),
                tool_calls=sum(1 for e in fap if e.type == "tool_call"),
            ),
            model=task.model,
            metadata={
                "nova_version": get_settings().version,
                "nova_task_id": task_id,
                "trace_id": task.trace_id,
                "skills": [{"id": ex.skill_id, "version": ex.skill_version} for ex in executions],
                "skill_catalog": skills.catalog_digest(),
                "artifact_types": [a.type for a in artifacts],
            },
        )
        if status == TaskStatus.failed:
            response.error = FapError(type="EXECUTION_ERROR", message=task.error or "Échec de l'exécution NOVA", retryable=False)
        return response

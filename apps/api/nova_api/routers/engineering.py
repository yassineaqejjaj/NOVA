"""Engineering: the user's own LLM key, the GitHub link and the SDLC Autopilot runs."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.llm import LLMError
from nova.infra.crypto import decrypt
from nova.infra.db import get_session, utcnow
from nova.infra.models import SdlcRun
from nova.integrations.github.client import GitHubError
from nova.services import github_accounts, llm_config, sdlc
from nova.services.audit import audit
from nova.services.dispatch import dispatch_sdlc
from nova.services.sdlc_metrics import aggregate
from nova_api.auth import CurrentPrincipal
from nova_api.errors import ApiError

router = APIRouter(tags=["engineering"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]

GITHUB_STATUS = {
    "unauthorized": 409,
    "forbidden": 403,
    "not_found": 404,
    "invalid": 422,
    "conflict": 409,
    "rate_limited": 429,
    "unavailable": 503,
}


def _github_error(exc: GitHubError) -> ApiError:
    return ApiError(GITHUB_STATUS.get(exc.code, 400), f"github_{exc.code}", exc.message)


# --- The user's own LLM --------------------------------------------------------------------------------------------


class LLMConfigIn(BaseModel):
    provider: Literal["anthropic", "openai", "google", "mistral", "openrouter", "custom"]
    model: str = Field(default="", max_length=120)
    api_key: str | None = Field(default=None, max_length=500)
    base_url: str = Field(default="", max_length=500)
    # The prompts (code excerpts, specifications) are sent to the provider: the user must acknowledge it.
    acknowledge_data_sharing: bool = False


@router.get("/me/llm")
async def get_llm(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return llm_config.public_view(await llm_config.get_config(session, principal.user_id))


@router.put("/me/llm")
async def put_llm(body: LLMConfigIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    if not body.acknowledge_data_sharing:
        raise ApiError(
            422,
            "llm_acknowledgement_required",
            "Confirm that prompts will be sent to this provider (never use it for C2 confidential or C3 secret data).",
        )
    try:
        row = await llm_config.save_config(
            session, principal.user_id, provider=body.provider, model=body.model, api_key=body.api_key, base_url=body.base_url
        )
    except LLMError as exc:
        raise ApiError(422, "llm_invalid", str(exc)) from exc
    await audit(
        session,
        actor_id=principal.user_id,
        action="llm.configure",
        target_type="user",
        target_id=principal.user_id,
        summary=f"Own LLM configured: {row.provider} / {row.model}",
    )
    await session.commit()
    return llm_config.public_view(row)


@router.delete("/me/llm", status_code=204)
async def delete_llm(principal: CurrentPrincipal, session: SessionDep) -> None:
    if await llm_config.delete_config(session, principal.user_id):
        await audit(session, actor_id=principal.user_id, action="llm.remove", target_type="user", target_id=principal.user_id)
    await session.commit()


@router.post("/me/llm/test")
async def test_llm(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    config = await llm_config.get_config(session, principal.user_id)
    if config is None or not decrypt(config.key_ciphertext):
        raise ApiError(409, "llm_not_configured", "Add your API key first.")
    try:
        provider = await llm_config.provider_for_user(principal.user_id)
        assert provider is not None
        await llm_config.check_connection(provider)
    except LLMError as exc:
        raise ApiError(422, "llm_invalid", str(exc)) from exc
    return {"ok": True, "model": config.model}


# --- GitHub ----------------------------------------------------------------------------------------------------------


class GithubTokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)


@router.get("/me/github")
async def github_status(principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    return await github_accounts.status(session, principal.user_id)


@router.put("/me/github")
async def github_link(body: GithubTokenIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    try:
        result = await github_accounts.link(session, principal.user_id, body.token)
    except GitHubError as exc:
        raise (
            ApiError(409, "github_token_invalid", "GitHub rejected this token.")
            if exc.code == "unauthorized"
            else _github_error(exc)
        ) from exc
    await audit(
        session,
        actor_id=principal.user_id,
        action="github.link",
        target_type="user",
        target_id=principal.user_id,
        summary=f"Linked GitHub account {result['login']}",
    )
    await session.commit()
    return result


@router.delete("/me/github", status_code=204)
async def github_unlink(principal: CurrentPrincipal, session: SessionDep) -> None:
    if await github_accounts.unlink(session, principal.user_id):
        await audit(session, actor_id=principal.user_id, action="github.unlink", target_type="user", target_id=principal.user_id)
    await session.commit()


@router.get("/me/github/repos")
async def github_repos(principal: CurrentPrincipal) -> list[dict[str, Any]]:
    try:
        client = await github_accounts.client_for(principal.user_id)
    except GitHubError as exc:
        raise _github_error(exc) from exc
    try:
        return await client.list_repos()
    except GitHubError as exc:
        raise _github_error(exc) from exc
    finally:
        await client.aclose()


# --- SDLC Autopilot -------------------------------------------------------------------------------------------------


class RunIn(BaseModel):
    kind: Literal["feature", "bugfix", "refactor", "review"] = "feature"
    title: str = Field(default="", max_length=300)
    goal: str = Field(default="", max_length=8000)
    repo: str = Field(default="", max_length=300)
    base_branch: str | None = Field(default=None, max_length=200)
    autonomy: Literal["guided", "autopilot"] = "guided"
    auto_merge: bool = False
    deploy_hook: str | None = Field(default=None, max_length=1000)
    issue_url: str = Field(default="", max_length=500)
    pr_url: str = Field(default="", max_length=500)
    post_review: bool = False
    project_id: uuid.UUID | None = None


class ApproveIn(BaseModel):
    notes: str = Field(default="", max_length=4000)


class ReleaseIn(BaseModel):
    tag: str = Field(min_length=1, max_length=60)
    draft: bool = True


async def _owned(session: AsyncSession, principal: Any, run_id: str) -> SdlcRun:
    run = await sdlc.get_owned(session, principal.user_id, run_id)
    if run is None:
        raise ApiError(404, "not_found", "Not found, or you don't have access.")
    return run


def _guard(exc: Exception) -> ApiError:
    if isinstance(exc, sdlc.ConflictError):
        return ApiError(409, "conflict", str(exc))
    if isinstance(exc, GitHubError):
        return _github_error(exc)
    return ApiError(422, "run_error", str(exc))


@router.get("/sdlc/metrics")
async def run_metrics(
    principal: CurrentPrincipal, session: SessionDep, days: int = Query(default=30, ge=1, le=365)
) -> dict[str, Any]:
    """Evaluation of the user's runs over the last ``days`` days: success rate, CI repairs, cost per run."""
    since = utcnow() - timedelta(days=days)
    rows = await session.scalars(
        select(SdlcRun).where(SdlcRun.user_id == uuid.UUID(principal.user_id), SdlcRun.created_at >= since)
    )
    return {"days": days, **aggregate(list(rows))}


@router.get("/sdlc/runs")
async def list_runs(
    principal: CurrentPrincipal, session: SessionDep, limit: int = Query(default=50, ge=1, le=100)
) -> list[dict[str, Any]]:
    rows = await session.scalars(
        select(SdlcRun).where(SdlcRun.user_id == uuid.UUID(principal.user_id)).order_by(SdlcRun.created_at.desc()).limit(limit)
    )
    return [sdlc.view(r, detail=False) for r in rows]


@router.post("/sdlc/runs", status_code=201)
async def create_run(body: RunIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    if body.kind != "review" and not (body.goal.strip() or body.issue_url.strip()):
        raise ApiError(422, "goal_required", "Describe what NOVA should build or fix, or give a GitHub issue URL.")
    if body.kind != "review" and not body.repo.strip():
        raise ApiError(422, "repo_required", "Choose a repository.")
    try:
        run = await sdlc.create_run(
            session,
            principal.user_id,
            kind=body.kind,
            title=body.title,
            goal=body.goal,
            repo=body.repo,
            base_branch=body.base_branch,
            autonomy=body.autonomy,
            auto_merge=body.auto_merge,
            deploy_hook=body.deploy_hook,
            issue_url=body.issue_url,
            pr_url=body.pr_url,
            post_review=body.post_review,
            project_id=body.project_id,
        )
    except (GitHubError, sdlc.RunError) as exc:
        raise _guard(exc) from exc
    await session.commit()
    await dispatch_sdlc(str(run.id))
    await session.refresh(run)
    return sdlc.view(run)


@router.get("/sdlc/runs/{run_id}")
async def get_run(run_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    await session.refresh(run)
    return sdlc.view(run)


@router.post("/sdlc/runs/{run_id}/approve")
async def approve_run(run_id: str, body: ApproveIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    gate = run.gate
    try:
        await sdlc.approve(session, run, notes=body.notes)
    except sdlc.ConflictError as exc:
        raise _guard(exc) from exc
    await audit(
        session,
        actor_id=principal.user_id,
        action=f"sdlc.approve.{gate}",
        target_type="sdlc_run",
        target_id=run_id,
        summary=f"Approved {gate} on {run.repo}",
    )
    await session.commit()
    await dispatch_sdlc(run_id)
    await session.refresh(run)
    return sdlc.view(run)


@router.post("/sdlc/runs/{run_id}/cancel")
async def cancel_run(run_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    try:
        await sdlc.cancel(run)
    except sdlc.ConflictError as exc:
        raise _guard(exc) from exc
    await audit(session, actor_id=principal.user_id, action="sdlc.cancel", target_type="sdlc_run", target_id=run_id)
    await session.commit()
    return sdlc.view(run)


@router.post("/sdlc/runs/{run_id}/retry")
async def retry_run(run_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    try:
        await sdlc.retry(run)
    except sdlc.ConflictError as exc:
        raise _guard(exc) from exc
    await session.commit()
    await dispatch_sdlc(run_id)
    await session.refresh(run)
    return sdlc.view(run)


@router.post("/sdlc/runs/{run_id}/release")
async def release_run(run_id: str, body: ReleaseIn, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    try:
        await sdlc.publish_release(run, tag=body.tag, draft=body.draft)
    except (sdlc.ConflictError, sdlc.RunError, GitHubError) as exc:
        raise _guard(exc) from exc
    await audit(
        session,
        actor_id=principal.user_id,
        action="sdlc.release",
        target_type="sdlc_run",
        target_id=run_id,
        summary=f"{'Draft release' if body.draft else 'Release'} {body.tag} on {run.repo}",
    )
    await session.commit()
    return sdlc.view(run)


@router.post("/sdlc/runs/{run_id}/deploy")
async def deploy_run(run_id: str, principal: CurrentPrincipal, session: SessionDep) -> dict[str, Any]:
    run = await _owned(session, principal, run_id)
    try:
        await sdlc.trigger_deploy(run)
    except (sdlc.ConflictError, sdlc.RunError) as exc:
        raise _guard(exc) from exc
    await audit(
        session,
        actor_id=principal.user_id,
        action="sdlc.deploy",
        target_type="sdlc_run",
        target_id=run_id,
        summary=f"Deploy hook for {run.repo}",
    )
    await session.commit()
    return sdlc.view(run)

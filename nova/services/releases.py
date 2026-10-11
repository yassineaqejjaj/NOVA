"""Releases of learned policies: canary → verdict → approval → active, with rollback (domain/release.py).

A candidate FORGE validated does not reach everyone at once. It is exposed to a stable share of users, its
executions are compared with the others', and only a healthy canary moves on — to an administrator when the
organization asks for approval, otherwise straight to everyone. A degraded canary is withdrawn
automatically; an active release can be rolled back at any time. Every transition is audited.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.domain.agents import AGENTS, AgentProfile
from nova.domain.release import (
    OPEN_STATUSES,
    TRAFFIC_ORIGINS,
    CanaryVerdict,
    Cohort,
    ReleaseStatus,
    canary_verdict,
)
from nova.infra.db import utcnow
from nova.infra.models import AgentPolicy, Release, Task, TrainingCycle
from nova.services import learning
from nova.services.audit import audit

log = logging.getLogger(__name__)
FINAL = ("completed", "failed")


class ReleaseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code, self.message = code, message


def _label(policy: AgentPolicy) -> str:
    return f"{policy.agent} v{policy.version}"


async def _record(session: AsyncSession, release: Release, action: str, actor_id: str | None, summary: str) -> None:
    await audit(
        session,
        actor_id=actor_id,
        action=f"release.{action}",
        target_type="release",
        target_id=str(release.id),
        summary=f"{AGENTS[AgentProfile(release.agent)].name} · {release.label} : {summary}"[:500],
        details={"status": release.status, "policy_id": str(release.policy_id), "canary_percent": release.canary_percent},
    )


async def _close_open(session: AsyncSession, agent: str, *, keep: uuid.UUID | None = None) -> None:
    """One open release per agent: a newer candidate replaces an unfinished one."""
    open_releases = (
        await session.scalars(select(Release).where(Release.agent == agent, Release.status.in_([s.value for s in OPEN_STATUSES])))
    ).all()
    for old in open_releases:
        if old.id == keep:
            continue
        old.status, old.reason, old.decided_at, old.decided_by = (
            ReleaseStatus.rejected.value,
            "Remplacée par une version candidate plus récente.",
            utcnow(),
            "system",
        )
        policy = await session.get(AgentPolicy, old.policy_id)
        if policy is not None and policy.status == "candidate":
            policy.status = "rejected"
        await _record(session, old, "superseded_by_newer", None, "remplacée avant la fin du déploiement")


async def start(session: AsyncSession, candidate: AgentPolicy, cycle: TrainingCycle | None, evidence: dict[str, Any]) -> Release:
    """Begin the release of a FORGE-validated candidate (canary first when configured)."""
    settings = get_settings()
    await _close_open(session, candidate.agent)
    baseline = (await learning.active_policies(session)).get(candidate.agent)
    release = Release(
        agent=candidate.agent,
        policy_id=candidate.id,
        baseline_policy_id=baseline.id if baseline else None,
        label=_label(candidate),
        status=ReleaseStatus.canary.value,
        canary_percent=settings.release_canary_percent,
        evidence=evidence,
        canary_started_at=utcnow(),
    )
    session.add(release)
    await session.flush()
    if settings.release_canary_percent > 0:
        release.reason = f"Déploiement progressif : {settings.release_canary_percent} % des utilisateurs."
        learning.invalidate()
        await _record(session, release, "canary_started", None, release.reason)
        return release
    release.canary_percent = 0
    await _after_healthy(session, release, "Aucun déploiement progressif configuré.")
    return release


async def _after_healthy(session: AsyncSession, release: Release, why: str) -> None:
    if get_settings().release_approval == "full":
        release.status, release.reason = ReleaseStatus.awaiting_approval.value, why + " En attente d'approbation."
        learning.invalidate()  # the canary share keeps running until a decision
        await _record(session, release, "awaiting_approval", None, release.reason)
        return
    await _activate(session, release, None, why)


async def _activate(session: AsyncSession, release: Release, actor_id: str | None, why: str) -> None:
    policy = await session.get(AgentPolicy, release.policy_id)
    if policy is None:
        raise ReleaseError("not_found", "La version de cette release est introuvable.")
    await learning.activate(session, policy)
    others = (
        await session.scalars(
            select(Release).where(
                Release.agent == release.agent, Release.status == ReleaseStatus.active.value, Release.id != release.id
            )
        )
    ).all()
    for other in others:
        other.status = ReleaseStatus.superseded.value
    release.status, release.reason, release.decided_by, release.decided_at = (
        ReleaseStatus.active.value,
        why,
        actor_id or "system",
        utcnow(),
    )
    if policy.cycle_id:
        cycle = await session.get(TrainingCycle, policy.cycle_id)
        if cycle is not None:
            cycle.status = "promoted"
    learning.invalidate()
    await _record(session, release, "activated", actor_id, why)


async def activate_directly(session: AsyncSession, policy: AgentPolicy, actor_id: str | None) -> Release:
    """An administrator applied a policy by hand: no canary (the human decision is the approval), but recorded."""
    baseline = (await learning.active_policies(session)).get(policy.agent)
    await _close_open(session, policy.agent)
    release = Release(
        agent=policy.agent,
        policy_id=policy.id,
        baseline_policy_id=baseline.id if baseline and baseline.id != policy.id else None,
        label=_label(policy),
        status=ReleaseStatus.canary.value,
        canary_percent=0,
        evidence={"manual": True, "score": policy.score},
    )
    session.add(release)
    await session.flush()
    await _activate(session, release, actor_id, "Appliquée par un administrateur.")
    return release


async def stats(session: AsyncSession, release: Release) -> tuple[Cohort, Cohort]:
    """``(canary, control)``: final executions with and without the release since the canary began."""
    since = release.canary_started_at or release.created_at

    async def cohort(*conditions: Any) -> Cohort:
        base = [Task.status.in_(FINAL), Task.origin.in_(TRAFFIC_ORIGINS), Task.created_at >= since, *conditions]
        runs = await session.scalar(select(func.count(Task.id)).where(*base)) or 0
        failed = await session.scalar(select(func.count(Task.id)).where(*base, Task.status == "failed")) or 0
        return Cohort(runs=int(runs), failed=int(failed))

    return await cohort(Task.release_id == release.id), await cohort(
        or_(Task.release_id.is_(None), Task.release_id != release.id)
    )


async def evaluate(session: AsyncSession, release: Release) -> CanaryVerdict:
    """Compare a running canary with the control and act: roll back, wait for approval, or go live."""
    settings = get_settings()
    canary, control = await stats(session, release)
    verdict = canary_verdict(
        canary, control, min_runs=settings.release_canary_min_runs, max_increase=settings.release_max_failure_increase
    )
    if release.status != ReleaseStatus.canary.value:
        return verdict
    if verdict.outcome == "degraded":
        await rollback(session, release.id, None, verdict.reason)
    elif verdict.outcome == "healthy":
        await _after_healthy(session, release, verdict.reason)
    return verdict


async def evaluate_open(session: AsyncSession) -> int:
    """Evaluate every running canary (called when an execution settles); returns how many changed state."""
    running = (await session.scalars(select(Release).where(Release.status == ReleaseStatus.canary.value))).all()
    changed = 0
    for release in running:
        before = release.status
        await evaluate(session, release)
        changed += release.status != before
    return changed


async def approve(session: AsyncSession, release_id: uuid.UUID, actor_id: str | None) -> Release:
    release = await session.get(Release, release_id, with_for_update=True)
    if release is None:
        raise ReleaseError("not_found", "Release introuvable.")
    if release.status != ReleaseStatus.awaiting_approval.value:
        raise ReleaseError("conflict", "Seule une release dont le déploiement progressif est sain peut être approuvée.")
    await _activate(session, release, actor_id, "Approuvée par un administrateur.")
    return release


async def rollback(session: AsyncSession, release_id: uuid.UUID, actor_id: str | None, reason: str = "") -> Release:
    """Withdraw a release: a canary / awaiting one stops, an active one gives way to its baseline."""
    release = await session.get(Release, release_id, with_for_update=True)
    if release is None:
        raise ReleaseError("not_found", "Release introuvable.")
    policy = await session.get(AgentPolicy, release.policy_id)
    if release.status in (ReleaseStatus.canary.value, ReleaseStatus.awaiting_approval.value):
        if policy is not None and policy.status == "candidate":
            policy.status = "rejected"
        if policy is not None and policy.cycle_id:
            cycle = await session.get(TrainingCycle, policy.cycle_id)
            if cycle is not None and cycle.status == "validated":
                cycle.status = "rejected"
    elif release.status == ReleaseStatus.active.value:
        baseline = await session.get(AgentPolicy, release.baseline_policy_id) if release.baseline_policy_id else None
        if baseline is None:
            raise ReleaseError("conflict", "Aucune version précédente à rétablir.")
        await learning.activate(session, baseline)
        if policy is not None:
            policy.status = "rejected"
    else:
        raise ReleaseError("conflict", "Cette release n'est pas en cours de déploiement ni active.")
    release.status = ReleaseStatus.rolled_back.value
    release.reason = reason or "Retirée par un administrateur."
    release.decided_by, release.decided_at = actor_id or "system", utcnow()
    learning.invalidate()
    await _record(session, release, "rolled_back", actor_id, release.reason)
    return release


async def mark_policy_rolled_back(session: AsyncSession, policy_id: uuid.UUID, actor_id: str | None) -> None:
    """The legacy per-agent rollback replaced a policy: its active release (if any) is closed accordingly."""
    release = await session.scalar(
        select(Release).where(Release.policy_id == policy_id, Release.status == ReleaseStatus.active.value)
    )
    if release is not None:
        release.status, release.reason = ReleaseStatus.rolled_back.value, "Retour à la version précédente."
        release.decided_by, release.decided_at = actor_id or "system", utcnow()
        await _record(session, release, "rolled_back", actor_id, release.reason)


#: FORGE alerts that justify withdrawing a live release; cost and latency rises are reported, not acted on.
ROLLBACK_ALERTS = ("pass_rate_drop", "failure_rate_rise")


async def _baseline_release_id(session: AsyncSession, release: Release) -> str | None:
    """The release that served the policy this one replaced (``None``: runs before any release)."""
    if release.baseline_policy_id is None:
        return None
    previous = await session.scalar(
        select(Release)
        .where(Release.policy_id == release.baseline_policy_id, Release.id != release.id)
        .order_by(Release.created_at.desc())
    )
    return str(previous.id) if previous is not None else None


async def watch_active(session: AsyncSession, client: Any) -> list[dict[str, Any]]:
    """Ask FORGE whether each recently activated release is degrading real traffic; roll back when it clearly is.

    FORGE compares the release's observed runs with its baseline's (significant drop *and* a minimum effect,
    never an alert on too few runs). The verdict is kept on the release; only a drop in success rate or a rise
    in failures withdraws it, and only when ``release_health_rollback`` is on.
    """
    settings = get_settings()
    since = utcnow() - timedelta(days=settings.release_watch_days)
    live = (
        await session.scalars(select(Release).where(Release.status == ReleaseStatus.active.value, Release.decided_at >= since))
    ).all()
    results: list[dict[str, Any]] = []
    for release in live:
        try:
            health = await client.compare_releases(
                str(release.id), await _baseline_release_id(session, release), days=settings.release_watch_days
            )
        except Exception as exc:  # FORGE being down must not disturb NOVA, nor roll anything back
            log.warning("FORGE health of release %s unavailable: %s", release.id, exc)
            continue
        alerts = [a for a in health.get("alerts") or [] if a.get("kind") in ROLLBACK_ALERTS]
        release.evidence = {
            **release.evidence,
            "health": {
                "status": health.get("status"),
                "reason": health.get("reason"),
                "alerts": [a.get("message") for a in health.get("alerts") or []],
                "checked_at": utcnow().isoformat(),
            },
        }
        acted = False
        if health.get("status") == "degraded" and alerts and settings.release_health_rollback:
            try:
                await rollback(session, release.id, None, "FORGE : " + " ".join(a["message"] for a in alerts))
                acted = True
            except ReleaseError as exc:
                log.warning("Release %s could not be rolled back: %s", release.id, exc.message)
        else:
            await _record(session, release, "health_checked", None, f"FORGE : {health.get('status')}")
        results.append({"release_id": str(release.id), "status": health.get("status"), "rolled_back": acted})
    return results


async def watch() -> int:
    """Periodic entry point (worker beat): returns how many releases were rolled back."""
    from nova.infra.db import session_scope
    from nova.services import providers

    client = providers.forge_watch_client()
    if client is None:
        return 0
    async with session_scope() as session:
        return sum(1 for r in await watch_active(session, client) if r["rolled_back"])

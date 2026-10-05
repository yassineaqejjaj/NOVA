"""FORGE training loop: every specialist agent is re-trained on all of its Skills (docs/TRAINING.md).

One *cycle* per agent, advanced by the worker (``nova.advance_training``), each step idempotent:

1. ``queued`` → the agent's active policy (v0 the first time) is registered in FORGE as an agent version, every
   Skill of the agent gets its service scenario (synthetic C1 project, Skill forced, Skill criteria and checks),
   and FORGE runs the baseline on all of them → ``evaluating``;
2. ``evaluating`` → once FORGE has evaluated the runs, its feedback reports are distilled into lessons
   (per Skill, and per agent when shared by several Skills) → a candidate policy, registered as a new FORGE
   agent version, and a FORGE experiment baseline vs candidate on the same scenarios → ``experimenting``;
   nothing to learn → ``no_change``;
3. ``experimenting`` → when the experiment is finished, the candidate is promoted automatically if FORGE
   validates it (``promotion_decision``) → ``promoted``, otherwise ``rejected`` (the active policy stays).

Lessons only reach production through a FORGE experiment, and a promotion can be rolled back.
"""

from __future__ import annotations

import logging
import statistics
import uuid
from datetime import timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings, get_settings
from nova.domain.agents import AGENTS, AgentProfile
from nova.domain.learning import (
    MAX_SKILL_LESSONS,
    AgentLearning,
    SkillFeedback,
    distill,
    lesson_from_recommendation,
    promotion_decision,
)
from nova.domain.llm import LLMMessage
from nova.domain.skills import SkillSpec
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import AgentPolicy, TrainingCycle
from nova.integrations.forge import mapper
from nova.integrations.forge.client import ForgeClient, ForgeError
from nova.services import learning, providers
from nova.services.audit import audit
from nova.skills.registry import SkillRegistry, get_skill_registry

log = logging.getLogger(__name__)

OPEN_STATUSES = ("queued", "evaluating", "experimenting")
TERMINAL_RUN = ("completed", "failed", "cancelled")
TERMINAL_EXPERIMENT_FAILURES = ("failed", "cancelled")


class TrainingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# --- Configuration ----------------------------------------------------------------------------------


def missing_configuration(settings: Settings | None = None) -> list[str]:
    """What prevents training from running (shown in the UI); empty when ready."""
    settings = settings or get_settings()
    missing = []
    if not settings.training_enabled:
        missing.append("NOVA_TRAINING_ENABLED")
    if not settings.forge_api_key:
        missing.append("NOVA_FORGE_API_KEY")
    if not settings.forge_credential_id:
        missing.append("NOVA_FORGE_CREDENTIAL_ID")
    if not settings.llm_model:
        missing.append("NOVA_LLM_MODEL")
    return missing


def forge_client(settings: Settings | None = None) -> ForgeClient:
    override = providers._overrides.get("forge_client")
    if override is not None:
        return override
    settings = settings or get_settings()
    return ForgeClient(settings.forge_base_url, settings.forge_api_key, timeout=settings.forge_timeout_seconds)


def nova_endpoint(settings: Settings) -> str:
    return settings.forge_nova_endpoint or settings.public_url.replace(":3200", ":8200")


def agent_skills(registry: SkillRegistry, profile: AgentProfile, limit: int = 0) -> list[SkillSpec]:
    """The services of an agent: every non-system Skill it owns."""
    skills = sorted((s for s in registry.all() if s.agent == profile and not s.system), key=lambda s: s.id)
    return skills[:limit] if limit else skills


# --- Starting cycles ----------------------------------------------------------------------------------


async def open_cycle(session: AsyncSession, profile: AgentProfile) -> TrainingCycle | None:
    return await session.scalar(
        select(TrainingCycle).where(TrainingCycle.agent == profile.value, TrainingCycle.status.in_(OPEN_STATUSES))
    )


async def start_cycle(
    session: AsyncSession, profile: AgentProfile, *, trigger: str = "manual", requested_by: str | None = None
) -> TrainingCycle:
    if missing := missing_configuration():
        raise TrainingError("not_configured", "Entraînement non configuré : " + ", ".join(missing))
    if await open_cycle(session, profile):
        raise TrainingError("conflict", f"Un cycle d'entraînement est déjà en cours pour le {AGENTS[profile].name}.")
    cycle = TrainingCycle(
        agent=profile.value,
        trigger=trigger,
        requested_by=uuid.UUID(requested_by) if requested_by else None,
        result={},
    )
    session.add(cycle)
    await session.flush()
    await audit(
        session,
        actor_id=requested_by,
        action="training.started",
        target_type="training_cycle",
        target_id=str(cycle.id),
        summary=f"Cycle d'entraînement FORGE du {AGENTS[profile].name} ({trigger})",
    )
    return cycle


async def start_due_cycles() -> int:
    """Scheduled training: one cycle per agent every ``training_interval_days``."""
    settings = get_settings()
    if settings.training_interval_days <= 0 or missing_configuration(settings):
        return 0
    since = utcnow() - timedelta(days=settings.training_interval_days)
    started = 0
    async with session_scope() as session:
        for profile in AgentProfile:
            last = await session.scalar(
                select(TrainingCycle)
                .where(TrainingCycle.agent == profile.value)
                .order_by(TrainingCycle.created_at.desc())
                .limit(1)
            )
            if last is not None and (last.status in OPEN_STATUSES or aware(last.created_at) >= since):
                continue
            await start_cycle(session, profile, trigger="scheduled")
            started += 1
    return started


# --- Advancing cycles ---------------------------------------------------------------------------------


async def tick() -> int:
    """Worker entry point: start due cycles, then advance every open cycle by one step."""
    started = await start_due_cycles()
    async with session_scope() as session:
        ids = (await session.scalars(select(TrainingCycle.id).where(TrainingCycle.status.in_(OPEN_STATUSES)))).all()
    advanced = 0
    for cycle_id in ids:
        try:
            if await advance(cycle_id):
                advanced += 1
        except Exception:  # one broken cycle must not block the others
            log.exception("Training cycle %s could not advance", cycle_id)
    return started + advanced


async def advance(cycle_id: uuid.UUID) -> bool:
    """Advance one cycle by one step; ``True`` when its status changed."""
    settings = get_settings()
    client = forge_client(settings)
    async with session_scope() as session:
        cycle = await session.get(TrainingCycle, cycle_id, with_for_update=True)
        if cycle is None or cycle.status not in OPEN_STATUSES:
            return False
        before = cycle.status
        if utcnow() - aware(cycle.created_at) > timedelta(hours=settings.training_cycle_timeout_hours):
            await _finish(session, cycle, "failed", error="Délai du cycle dépassé : FORGE n'a pas terminé l'évaluation.")
            return True
        try:
            if cycle.status == "queued":
                await _setup(session, cycle, client, settings)
            elif cycle.status == "evaluating":
                await _evaluate(session, cycle, client, settings)
            elif cycle.status == "experimenting":
                await _decide(session, cycle, client, settings)
        except ForgeError as exc:
            if exc.status == 0 or exc.status >= 500 or exc.status == 429:
                log.warning("Training cycle %s: FORGE unavailable (%s), will retry", cycle_id, exc.message)
                return False
            await _finish(session, cycle, "failed", error=f"FORGE a refusé la requête ({exc.status}) : {exc.message}")
        return cycle.status != before


async def _finish(session: AsyncSession, cycle: TrainingCycle, status: str, *, error: str | None = None) -> None:
    cycle.status = status
    cycle.error = error
    cycle.finished_at = utcnow()
    if status in ("failed", "cancelled", "rejected") and cycle.candidate_policy_id:
        candidate = await session.get(AgentPolicy, cycle.candidate_policy_id)
        if candidate is not None and candidate.status == "candidate":
            candidate.status = "rejected"
    await audit(
        session,
        actor_id=None,
        action=f"training.{status}",
        target_type="training_cycle",
        target_id=str(cycle.id),
        summary=(error or cycle.result.get("decision", {}).get("reason") or status)[:500],
        details={"agent": cycle.agent, "experiment": cycle.forge_experiment_id},
    )


async def _forge_agent(client: ForgeClient, profile: AgentProfile) -> dict[str, Any]:
    slug = mapper.specialist_agent_id(profile)
    agent = await client.find_agent(slug)
    if agent is None:
        try:
            agent = await client.create_agent(mapper.training_agent_body(profile))
        except ForgeError as exc:
            if exc.status != 409:
                raise
            agent = await client.find_agent(slug)
            if agent is None:
                raise
    return agent


async def forge_version_id(client: ForgeClient, policy: AgentPolicy, settings: Settings, registry: SkillRegistry) -> str:
    """FORGE agent version of a policy, registered again when its configuration (model, catalog, budget…) changed.

    Baseline and candidate of a cycle are built from the same settings, so they differ only by their lessons.
    """
    profile = AgentProfile(policy.agent)
    body = mapper.training_version_body(
        profile=profile,
        policy_id=str(policy.id),
        policy_version=policy.version,
        standards=list(policy.standards),
        lessons=dict(policy.skills),
        skills=agent_skills(registry, profile),
        catalog_digest=registry.catalog_digest(),
        nova_version=settings.version,
        model=settings.llm_model,
        nova_base_url=nova_endpoint(settings),
        credential_id=settings.forge_credential_id or None,
        timeout_seconds=settings.training_run_timeout_seconds,
    )
    key = mapper.version_key(body)
    if policy.forge_agent_version_id and policy.forge_version_key == key:
        return policy.forge_agent_version_id
    agent = await _forge_agent(client, profile)
    try:
        version = await client.create_agent_version(str(agent["id"]), body)
    except ForgeError as exc:
        if exc.status != 409:
            raise
        versions = await client.list_agent_versions(str(agent["id"]))
        version = next((v for v in versions if v.get("version") == body["version"]), None)
        if version is None:
            raise
    policy.forge_agent_version_id = str(version["id"])
    policy.forge_version_key = key
    return policy.forge_agent_version_id


async def _scenario_id(client: ForgeClient, skill: SkillSpec) -> str:
    slug = mapper.training_scenario_slug(skill)
    found = await client.find_scenario(slug)
    if found is not None:
        return str(found["id"])
    try:
        created = await client.create_scenario(mapper.training_scenario_body(skill))
    except ForgeError as exc:
        if exc.status != 409:
            raise
        found = await client.find_scenario(slug)
        if found is None:
            raise
        return str(found["id"])
    return str(created["id"])


async def _setup(session: AsyncSession, cycle: TrainingCycle, client: ForgeClient, settings: Settings) -> None:
    profile = AgentProfile(cycle.agent)
    registry = get_skill_registry()
    skills = agent_skills(registry, profile, settings.training_max_skills)
    if not skills:
        await _finish(session, cycle, "no_change", error=None)
        cycle.result = {**cycle.result, "decision": {"promote": False, "reason": "Aucune compétence à entraîner."}}
        return
    baseline = await learning.ensure_base_policy(session, profile)
    version_id = await forge_version_id(client, baseline, settings, registry)
    suite = [{"id": s.id, "version": s.version, "scenario_id": await _scenario_id(client, s)} for s in skills]
    by_scenario = {item["scenario_id"]: item["id"] for item in suite}
    runs = await client.create_runs(
        mapper.training_runs_body(
            version_id, [item["scenario_id"] for item in suite], settings.training_repetitions, str(cycle.id)
        )
    )
    cycle.baseline_policy_id = baseline.id
    cycle.result = {**cycle.result, "baseline_version_id": version_id}
    cycle.skills = suite
    cycle.baseline_runs = [{"run_id": str(r["id"]), "skill_id": by_scenario.get(str(r.get("scenario_id")))} for r in runs or []]
    cycle.status = "evaluating"


class _Lessons(BaseModel):
    lessons: list[str] = Field(default_factory=list, max_length=MAX_SKILL_LESSONS)


def condense_messages(skill: SkillSpec, raw: list[str], weaknesses: list[str], current: list[str]) -> list[LLMMessage]:
    system = (
        "You improve the instructions of a specialist AI agent from its evaluation results. Write at most "
        f"{MAX_SKILL_LESSONS} short imperative lessons in English (one sentence each) the agent must apply the next "
        "time it runs this Skill. Lessons must be general: never mention the evaluation project, its names, figures "
        "or documents, and never copy evaluation content. Keep still-relevant current lessons, merge duplicates, "
        "drop anything vague. Only keep what the agent can apply by itself in its answer (content, structure, "
        "citations, assumptions, precision); ignore advice about latency, infrastructure, retrieval systems or models. "
        "Return an empty list when nothing actionable remains."
    )
    user = (
        f"SKILL: {skill.name} — {skill.purpose}\n"
        f"CURRENT LESSONS:\n{chr(10).join('- ' + x for x in current) or '- none'}\n"
        f"EVALUATION WEAKNESSES:\n{chr(10).join('- ' + x for x in weaknesses[:10]) or '- none'}\n"
        f"EVALUATOR RECOMMENDATIONS:\n{chr(10).join('- ' + x for x in raw[:10]) or '- none'}"
    )
    return [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)]


async def _condense(skill: SkillSpec, item: SkillFeedback, current: AgentLearning) -> list[str] | None:
    """Model-condensed lessons for one Skill (best effort: the deterministic lessons are used on failure).

    The model sees every FORGE recommendation (whatever its category) and the weak criteria, and keeps only what
    the agent's instructions can address; the deterministic path only keeps prompt-category recommendations.
    """
    raw = [
        lesson_from_recommendation(rec)
        or f"{rec.get('category')}: {rec.get('title')} — {rec.get('description') or ''}".strip(" —")
        for rec in item.recommendations
        if rec.get("title") or rec.get("description")
    ]
    if not raw and not item.weaknesses:
        return None
    try:
        result = await providers.llm().structured_output(
            condense_messages(skill, raw, item.weaknesses, current.skills.get(skill.id, [])), _Lessons
        )
    except Exception:  # the model is optional here: fall back to the deterministic lessons
        log.warning("Lesson condensation failed for %s; using FORGE recommendations as-is", skill.id)
        return None
    return [x for x in result.value.lessons if x.strip()] or None


async def _evaluate(session: AsyncSession, cycle: TrainingCycle, client: ForgeClient, settings: Settings) -> None:
    runs = []
    for ref in cycle.baseline_runs:
        run = await client.get_run(ref["run_id"])
        if run.get("status") not in TERMINAL_RUN:
            return  # FORGE is still executing or evaluating: next tick
        runs.append((ref, run))
    if not runs:
        await _finish(session, cycle, "failed", error="FORGE n'a créé aucune exécution.")
        return

    registry = get_skill_registry()
    profile = AgentProfile(cycle.agent)
    baseline = await session.get(AgentPolicy, cycle.baseline_policy_id) if cycle.baseline_policy_id else None
    current = learning.learning(baseline) if baseline else AgentLearning()

    per_skill: dict[str, SkillFeedback] = {}
    run_scores: dict[str, list[float]] = {}
    failures = 0
    for ref, run in runs:
        skill_id = ref.get("skill_id")
        if not skill_id:
            continue
        item = per_skill.setdefault(skill_id, SkillFeedback(skill_id=skill_id))
        if run.get("status") != "completed":
            failures += 1
            continue
        score = run.get("composite_score")
        if isinstance(score, int | float):
            run_scores.setdefault(skill_id, []).append(float(score))
            item.score = statistics.fmean(run_scores[skill_id])
        report = await client.run_feedback(ref["run_id"])
        if report:
            item.report_id = item.report_id or str(report.get("id"))
            item.weaknesses += [str(w) for w in report.get("weaknesses") or []]
            item.recommendations += list(report.get("recommendations") or [])

    feedback = list(per_skill.values())
    rewritten: dict[str, list[str]] = {}
    for item in feedback:
        if registry.has(item.skill_id) and (lessons := await _condense(registry.get(item.skill_id), item, current)):
            rewritten[item.skill_id] = lessons
    distilled = distill(feedback, current, rewritten=rewritten)
    scores = {f.skill_id: f.score for f in feedback}
    known = [s for s in scores.values() if isinstance(s, int | float)]
    cycle.result = {
        **cycle.result,
        "baseline": {"scores": scores, "mean": statistics.fmean(known) if known else None, "failed_runs": failures},
        "changed_skills": distilled.changed_skills,
        "new_standards": distilled.new_standards,
        "report_ids": distilled.report_ids[:50],
    }
    if baseline is not None and known:
        baseline.score = statistics.fmean(known)  # latest FORGE measure of the active policy
    if not distilled.changed:
        cycle.result = {
            **cycle.result,
            "decision": {"promote": False, "reason": "FORGE n'a relevé aucune leçon applicable aux consignes."},
        }
        await _finish(session, cycle, "no_change")
        return

    candidate = AgentPolicy(
        agent=profile.value,
        version=await learning.next_version(session, profile),
        status="candidate",
        standards=distilled.standards,
        skills=distilled.skills,
        recommendations=distilled.other_recommendations,
        parent_id=baseline.id if baseline else None,
        cycle_id=cycle.id,
        summary=(
            f"{len(distilled.changed_skills)} compétence(s) ajustée(s)"
            + (f", {len(distilled.new_standards)} nouveau(x) standard(s)" if distilled.new_standards else "")
        ),
    )
    session.add(candidate)
    await session.flush()
    candidate_version_id = await forge_version_id(client, candidate, settings, registry)
    baseline_version_id = cycle.result.get("baseline_version_id") or (baseline.forge_agent_version_id if baseline else None)
    if not baseline_version_id:
        await _finish(session, cycle, "failed", error="Version de référence FORGE introuvable.")
        return
    experiment = await client.create_experiment(
        mapper.training_experiment_body(
            profile=profile,
            cycle_id=str(cycle.id),
            baseline_version_id=baseline_version_id,
            candidate_version_id=candidate_version_id,
            scenario_ids=[item["scenario_id"] for item in cycle.skills],
            repetitions=settings.training_repetitions,
            candidate_version=candidate.version,
            changed_skills=distilled.changed_skills,
            source_feedback_report_id=distilled.report_ids[0] if distilled.report_ids else None,
        )
    )
    cycle.candidate_policy_id = candidate.id
    cycle.forge_experiment_id = str(experiment["id"])
    cycle.status = "experimenting"


async def _decide(session: AsyncSession, cycle: TrainingCycle, client: ForgeClient, settings: Settings) -> None:
    assert cycle.forge_experiment_id
    experiment = await client.get_experiment(cycle.forge_experiment_id)
    status = experiment.get("status")
    if status in TERMINAL_EXPERIMENT_FAILURES:
        await _finish(session, cycle, "failed", error=f"L'expérience FORGE s'est terminée en « {status} ».")
        return
    if status != "completed":
        return
    comparison = await client.experiment_comparison(cycle.forge_experiment_id)
    decision = promotion_decision(comparison)
    skill_of = {item["scenario_id"]: item["id"] for item in cycle.skills}
    composite = comparison.get("composite") or {}
    cycle.result = {
        **cycle.result,
        "experiment": {
            "recommendation": (comparison.get("recommendation") or {}).get("recommendation"),
            "summary": (comparison.get("recommendation") or {}).get("summary"),
            "baseline_mean": composite.get("baseline_mean"),
            "candidate_mean": composite.get("candidate_mean"),
            "delta": composite.get("delta"),
            "regressions": [skill_of.get(str(r.get("scenario_id")), r.get("slug")) for r in comparison.get("regressions") or []],
            "improvements": [
                skill_of.get(str(r.get("scenario_id")), r.get("slug")) for r in comparison.get("improvements") or []
            ],
        },
        "decision": decision.model_dump(),
    }
    candidate = await session.get(AgentPolicy, cycle.candidate_policy_id) if cycle.candidate_policy_id else None
    if candidate is None:
        await _finish(session, cycle, "failed", error="Version candidate introuvable.")
        return
    if not decision.promote:
        await _finish(session, cycle, "rejected")
        return
    candidate.score = composite.get("candidate_mean")
    if not settings.training_auto_promote:
        cycle.result = {**cycle.result, "awaiting_approval": True}
        await _finish(session, cycle, "validated")
        return
    await learning.activate(session, candidate)
    await _finish(session, cycle, "promoted")


# --- Manual actions -----------------------------------------------------------------------------------


async def promote(session: AsyncSession, policy_id: uuid.UUID, actor_id: str | None) -> AgentPolicy:
    """Apply a validated candidate (when automatic promotion is off) or re-apply a retired policy."""
    policy = await session.get(AgentPolicy, policy_id)
    if policy is None:
        raise TrainingError("not_found", "Version introuvable.")
    if policy.status not in ("candidate", "retired"):
        raise TrainingError("conflict", "Seule une version candidate validée ou une version retirée peut être appliquée.")
    if policy.status == "candidate":
        cycle = await session.get(TrainingCycle, policy.cycle_id) if policy.cycle_id else None
        if cycle is None or cycle.status != "validated":
            raise TrainingError("conflict", "Cette version n'a pas été validée par FORGE.")
        cycle.status = "promoted"
    await learning.activate(session, policy)
    await audit(
        session,
        actor_id=actor_id,
        action="training.policy_activated",
        target_type="agent_policy",
        target_id=str(policy.id),
        summary=f"{AGENTS[AgentProfile(policy.agent)].name} : version apprise v{policy.version} appliquée",
    )
    return policy


async def rollback(session: AsyncSession, profile: AgentProfile, actor_id: str | None) -> AgentPolicy:
    """Return to the policy the active one replaced."""
    active = await session.scalar(select(AgentPolicy).where(AgentPolicy.agent == profile.value, AgentPolicy.status == "active"))
    if active is None or active.parent_id is None:
        raise TrainingError("conflict", "Aucune version précédente à rétablir.")
    previous = await session.get(AgentPolicy, active.parent_id)
    if previous is None:
        raise TrainingError("conflict", "La version précédente est introuvable.")
    await learning.activate(session, previous)
    await audit(
        session,
        actor_id=actor_id,
        action="training.rolled_back",
        target_type="agent_policy",
        target_id=str(previous.id),
        summary=f"{AGENTS[profile].name} : retour à la version v{previous.version} (v{active.version} retirée)",
    )
    return previous


async def cancel(session: AsyncSession, cycle_id: uuid.UUID, actor_id: str | None) -> TrainingCycle:
    cycle = await session.get(TrainingCycle, cycle_id, with_for_update=True)
    if cycle is None:
        raise TrainingError("not_found", "Cycle introuvable.")
    if cycle.status not in OPEN_STATUSES:
        raise TrainingError("conflict", "Ce cycle est déjà terminé.")
    if cycle.forge_experiment_id:
        try:
            await forge_client().cancel_experiment(cycle.forge_experiment_id)
        except ForgeError as exc:  # the cycle is cancelled on NOVA's side anyway
            log.warning("Could not cancel FORGE experiment %s: %s", cycle.forge_experiment_id, exc.message)
    await _finish(session, cycle, "cancelled", error=None)
    cycle.requested_by = cycle.requested_by or (uuid.UUID(actor_id) if actor_id else None)
    return cycle

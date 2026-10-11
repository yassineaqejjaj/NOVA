"""Run manifest: the one record that ties an execution to everything that shaped it.

ORION needs a common key across NOVA, ORBIT and FORGE (agent version, context snapshot, policy, model,
experiment, release). Those facts already exist in separate places; the manifest gathers them once per run
so replay, experiments and KPIs can join on it. Identifiers that a later phase fills (experiment, eval
suite, release) are carried as ``None`` until then.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nova.domain.state import NovaState

MANIFEST_SCHEMA = 1


def snapshot_id(name: str | None, version: int | None) -> str | None:
    """Canonical snapshot identifier, the same ``name@vN`` form ORBIT uses in its ``context.served`` events."""
    if not name:
        return None
    return f"{name}@v{version}" if version is not None else f"{name}@latest"


class ManifestContext(BaseModel):
    retrieval_id: str | None = None  # ORBIT request_id
    project_slug: str | None = None  # ORBIT project the context came from
    snapshot_id: str | None = None  # name@vN
    snapshot_name: str | None = None
    snapshot_version: int | None = None
    items: int = 0
    max_classification: int = 0
    token_budget: int | None = None


class ManifestPolicy(BaseModel):
    policy_id: str | None = None
    version: int = 0


class ManifestSkill(BaseModel):
    skill_id: str
    version: str | None = None


class RunManifest(BaseModel):
    schema_version: int = MANIFEST_SCHEMA
    run_id: str  # the task id (= LangGraph thread id)
    trace_id: str | None = None
    origin: str
    agent_version: str
    model: str | None = None
    context: ManifestContext = Field(default_factory=ManifestContext)
    policies: dict[str, ManifestPolicy] = Field(default_factory=dict)  # per agent profile
    skills: list[ManifestSkill] = Field(default_factory=list)
    # Filled by later ORION phases (experiments, evaluation suites, releases); None until then.
    experiment_id: str | None = None
    eval_suite_id: str | None = None
    release_id: str | None = None
    replay_of: str | None = None  # run_id of the execution this one replays
    overrides: dict[str, str] = Field(default_factory=dict)  # what a replay changed: context, model, snapshot, policy


def build_run_manifest(
    *,
    run_id: str,
    trace_id: str | None,
    origin: str,
    agent_version: str,
    model: str | None,
    learning: dict[str, Any] | None,
    skills: list[tuple[str, str | None]],
    retrieval_id: str | None,
    snapshot_name: str | None,
    snapshot_version: int | None,
    items: int,
    max_classification: int,
    token_budget: int | None,
    ids: dict[str, str | None] | None = None,
    overrides: dict[str, str] | None = None,
    project_slug: str | None = None,
) -> RunManifest:
    """Assemble the manifest from already-known facts (no I/O)."""
    policies = {
        str(profile): ManifestPolicy(policy_id=raw.get("policy_id"), version=int(raw.get("version") or 0))
        for profile, raw in (learning or {}).items()
        if isinstance(raw, dict)
    }
    manifest = RunManifest(
        run_id=run_id,
        trace_id=trace_id,
        origin=origin,
        agent_version=agent_version,
        model=model,
        context=ManifestContext(
            retrieval_id=retrieval_id,
            project_slug=project_slug,
            snapshot_id=snapshot_id(snapshot_name, snapshot_version),
            snapshot_name=snapshot_name,
            snapshot_version=snapshot_version,
            items=items,
            max_classification=max_classification,
            token_budget=token_budget,
        ),
        policies=policies,
        skills=[ManifestSkill(skill_id=s, version=v) for s, v in skills],
        overrides=dict(overrides or {}),
    )
    for key, value in (ids or {}).items():
        if key in ("experiment_id", "eval_suite_id", "release_id", "replay_of"):
            setattr(manifest, key, value)
    return manifest


def manifest_from_state(
    state: NovaState,
    *,
    agent_version: str,
    token_budget: int | None,
    snapshot_name: str | None = None,
    snapshot_version: int | None = None,
    ids: dict[str, str | None] | None = None,
    overrides: dict[str, str] | None = None,
) -> RunManifest:
    """The manifest of an execution state; the snapshot comes from the stored ORBIT context reference."""
    return build_run_manifest(
        run_id=state.task_id,
        trace_id=state.trace_id,
        origin=state.origin.value,
        agent_version=agent_version,
        model=state.model,
        learning=state.learning,
        skills=[(o.skill_id, o.skill_version) for o in state.step_outputs.values()],
        retrieval_id=state.context_retrieval_id,
        snapshot_name=snapshot_name,
        snapshot_version=snapshot_version,
        items=len(state.context_items),
        max_classification=max((i.classification for i in state.context_items), default=0),
        token_budget=token_budget,
        ids=ids,
        overrides=overrides,
        project_slug=state.project_slug,
    )

"""What NOVA really runs for a FORGE call, and which parts of the FORGE agent version it cannot honour.

FORGE describes the agent it evaluates (version label, model, system prompt, tools). NOVA runs its *current* runtime:
it never pins an older release, swaps the model or takes a foreign prompt. A call that asks for any of these is refused
(``unsupported_override``) instead of being executed and reported as if it had run as asked. The response tells apart
the version FORGE **declared**, the version NOVA **executed** (a fingerprint of the runtime) and the overrides it
**accepted** (policy, forced Skill, budgets).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from nova.config import Settings
from nova.domain.agents import AgentProfile, agent_instructions
from nova.integrations.forge import mapper
from nova.integrations.forge.schemas import FapAgent


@dataclass(frozen=True)
class Runtime:
    nova_version: str
    runtime_commit: str
    skill_catalog: str
    provider: str
    model: str


def current_runtime(settings: Settings, catalog_digest: str, model: str) -> Runtime:
    commit = settings.build_commit or os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")
    return Runtime(settings.version, commit[:12], catalog_digest, settings.llm_provider, model)


def current_label(runtime: Runtime) -> str:
    """The label of the FORGE agent version NOVA registers for this runtime (``mapper.release_label``)."""
    return mapper.release_label(runtime.nova_version, runtime.model, runtime.skill_catalog, runtime.provider)


def override_conflicts(
    agent: FapAgent, runtime: Runtime, *, profile: AgentProfile | None, standards: list[str] | None, policy_version: int | None
) -> list[tuple[str, str, str]]:
    """``(field, requested, current)`` for every part of the FORGE agent NOVA does not run as declared."""
    conflicts: list[tuple[str, str, str]] = []
    if agent.version:
        if profile is None:
            expected, same = current_label(runtime), agent.version == current_label(runtime)
        else:  # a specialist version is "<policy version>.<fingerprint>" (mapper.training_version_body)
            expected = f"{policy_version}.*"
            same = policy_version is None or agent.version.startswith(f"{policy_version}.")
        if not same:
            conflicts.append(("agent.version", agent.version, expected))
    model = agent.model or {}
    if model.get("model") and (
        model["model"] != runtime.model or (model.get("provider") or runtime.provider) != runtime.provider
    ):
        conflicts.append(("agent.model", f"{model.get('provider')}/{model['model']}", f"{runtime.provider}/{runtime.model}"))
    expected_prompt = agent_instructions(profile, standards) if profile else ""
    if (agent.system_prompt or "").strip() not in ("", expected_prompt.strip()):
        conflicts.append(("agent.system_prompt", "a system prompt NOVA does not use", "NOVA's own agent instructions"))
    if agent.tools:
        conflicts.append(("agent.tools", f"{len(agent.tools)} tool(s)", "the tools of NOVA's Skills"))
    return conflicts


def executed_fingerprint(runtime: Runtime, policy_id: str | None, parameters: dict[str, Any]) -> dict[str, Any]:
    """What ran: the runtime, the lessons applied and the parameters of the run, with a short hash of all of it."""
    executed = {**asdict(runtime), "policy_id": policy_id, "parameters": parameters}
    digest = hashlib.sha256(json.dumps(executed, sort_keys=True).encode()).hexdigest()[:12]
    return {**executed, "version": f"{runtime.nova_version}+{digest}"}

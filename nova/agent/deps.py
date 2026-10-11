"""Runtime dependencies of the graph (LangGraph ``context``), never stored in the checkpointed state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from nova.agent.ports import ExecutionStore
from nova.agent.tools.registry import ToolRegistry
from nova.artifacts.registry import ArtifactRegistry
from nova.config import Settings
from nova.domain.context import ContextProvider
from nova.domain.design import DesignProvider
from nova.domain.evaluation import EvaluationSink
from nova.domain.llm import LLMProvider
from nova.domain.permissions import Permission
from nova.skills.registry import SkillRegistry


@dataclass
class AgentDeps:
    settings: Settings
    llm: LLMProvider
    context: ContextProvider
    skills: SkillRegistry
    artifacts: ArtifactRegistry
    tools: ToolRegistry
    store: ExecutionStore
    evaluation: EvaluationSink | None = None
    design: DesignProvider | None = None  # Figma; None: tools answer 'Connect Figma in Settings'
    permissions: frozenset[Permission] = frozenset()  # effective permissions of the user on the project
    skill_llms: dict[str, LLMProvider] = field(default_factory=dict)  # per-Skill model for generation steps
    skill_scores: dict[str, float] = field(default_factory=dict)  # FORGE composite per Skill (dynamic assembly)
    composition_priors: Callable[[str], Awaitable[dict[str, float]]] | None = None  # bonuses per Skill for a category

    def llm_for(self, skill_id: str) -> LLMProvider:
        """The model that writes a Skill's output: its routed model when configured, else the main one."""
        return self.skill_llms.get(skill_id, self.llm)

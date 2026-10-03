"""Runtime dependencies of the graph (LangGraph ``context``), never stored in the checkpointed state."""

from __future__ import annotations

from dataclasses import dataclass

from nova.agent.ports import ExecutionStore
from nova.agent.tools.registry import ToolRegistry
from nova.artifacts.registry import ArtifactRegistry
from nova.config import Settings
from nova.domain.context import ContextProvider
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
    permissions: frozenset[Permission] = frozenset()  # effective permissions of the user on the project

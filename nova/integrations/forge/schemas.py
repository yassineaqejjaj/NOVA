"""FORGE Agent Protocol v1 / NOVA Agent Protocol payloads (FORGE docs/AGENT_PROTOCOL.md §1, §2, §4, §6)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

FAP_VERSION = "forge-agent-protocol/v1"


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class FapMessage(_In):
    role: str
    content: str = ""


class FapInput(_In):
    prompt: str | None = None
    messages: list[FapMessage] = Field(default_factory=list)
    nova_skill: str | None = None  # training scenarios force the Skill under evaluation (FORGE passes input through)

    def text(self) -> str:
        if self.prompt:
            return self.prompt
        users = [m.content for m in self.messages if m.role == "user"]
        return users[-1] if users else ""


class FapDocument(_In):
    id: str | None = None
    title: str = ""
    content: str = ""
    source: str | None = None


class FapContext(_In):
    documents: list[FapDocument] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class FapAgent(_In):
    name: str | None = None
    slug: str | None = None
    version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class FapBudget(_In):
    max_tokens: int | None = None
    max_cost: float | None = None
    max_steps: int | None = None
    timeout_seconds: float | None = None


class NovaRunRequest(_In):
    """FAP request body + ``nova_agent_id`` (+ ``options``) sent by FORGE's ``nova`` adapter."""

    protocol: str = FAP_VERSION
    run_id: str | None = None
    trace_id: str | None = None
    repetition: int = 0
    attempt: int = 1
    scenario_version_id: str | None = None
    input: FapInput = Field(default_factory=FapInput)
    context: FapContext = Field(default_factory=FapContext)
    constraints: list[str] = Field(default_factory=list)
    agent: FapAgent = Field(default_factory=FapAgent)
    budget: FapBudget = Field(default_factory=FapBudget)
    nova_agent_id: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class FapEvent(BaseModel):
    id: str
    parent_id: str | None = None
    type: str
    name: str
    started_at: str | None = None
    ended_at: str | None = None
    status: str = "ok"
    input: Any = None
    output: Any = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class FapUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    tool_calls: int = 0


class FapError(BaseModel):
    type: str
    message: str
    retryable: bool = False


class NovaRunResponse(BaseModel):
    protocol: str = FAP_VERSION
    output: str = ""
    output_json: dict[str, Any] | None = None
    events: list[FapEvent] = Field(default_factory=list)
    usage: FapUsage = Field(default_factory=FapUsage)
    model: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: FapError | None = None

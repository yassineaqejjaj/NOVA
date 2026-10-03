"""Tool Registry — NOVA never executes arbitrary tools.

Every tool declares: name, description, input/output schema, required permission, timeout, retry
policy, audit behavior and whether it writes to an external system (→ approval policy). A Skill can
only use the tools it declares, and retrieved content can never add a tool.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from nova.domain.outputs import ToolRequest, ToolResult
from nova.domain.permissions import Permission

if TYPE_CHECKING:
    from nova.agent.deps import AgentDeps
    from nova.domain.state import NovaState


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.5
    retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)


@dataclass(frozen=True)
class ToolContext:
    state: NovaState
    deps: AgentDeps
    skill_id: str | None = None


Handler = Callable[[ToolContext, Any], Awaitable[BaseModel]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    permission: Permission
    handler: Handler
    timeout_seconds: float = 20.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    audit: bool = True
    external_write: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
            "output_schema": self.output_model.model_json_schema(),
            "permission": self.permission.value,
            "timeout_seconds": self.timeout_seconds,
            "max_attempts": self.retry.max_attempts,
            "audit": self.audit,
            "external_write": self.external_write,
        }


class ToolDenied(Exception):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool
        return tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolDenied(f"Unknown tool '{name}'") from exc

    def authorize(self, request: ToolRequest, *, allowed: list[str], permissions: frozenset[Permission]) -> ToolDefinition:
        """Raise ``ToolDenied`` unless the tool is registered, declared by the Skill and permitted."""
        if request.tool not in allowed:
            raise ToolDenied(f"Tool '{request.tool}' is not declared by this Skill")
        tool = self.get(request.tool)
        if tool.permission not in permissions:
            raise ToolDenied(f"Missing permission '{tool.permission}' for tool '{tool.name}'")
        return tool

    async def execute(self, tool: ToolDefinition, request: ToolRequest, ctx: ToolContext) -> tuple[ToolResult, float]:
        started = time.perf_counter()
        try:
            args = tool.input_model.model_validate(request.arguments)
        except ValidationError as exc:
            return ToolResult(tool=tool.name, status="error", error=f"Invalid arguments: {exc.errors()[:3]}"), 0.0
        attempt = 0
        while True:
            attempt += 1
            try:
                output = await asyncio.wait_for(tool.handler(ctx, args), timeout=tool.timeout_seconds)
                result = ToolResult(tool=tool.name, status="ok", output=output.model_dump(mode="json"))
                break
            except tool.retry.retry_on as exc:
                if attempt >= tool.retry.max_attempts:
                    result = ToolResult(tool=tool.name, status="error", error=_safe_error(exc))
                    break
                await asyncio.sleep(tool.retry.backoff_seconds * attempt)
            except ToolDenied as exc:
                result = ToolResult(tool=tool.name, status="denied", error=str(exc))
                break
            except Exception as exc:
                result = ToolResult(tool=tool.name, status="error", error=_safe_error(exc))
                break
        return result, (time.perf_counter() - started) * 1000


def _safe_error(exc: Exception) -> str:
    message = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
    return message[:300]


@lru_cache
def get_tool_registry() -> ToolRegistry:
    from nova.agent.tools.builtin import register_builtin_tools

    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry

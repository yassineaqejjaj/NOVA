"""LLM port. NOVA is never coupled to one inference engine (vLLM is the first implementation)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

from nova.domain.outputs import TokenUsage

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LLMResult(BaseModel):
    text: str
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str | None = None
    latency_ms: float = 0.0


class StructuredResult[T: BaseModel](BaseModel):
    value: T
    model: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    repaired: bool = False


class LLMError(Exception):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    async def generate(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> LLMResult: ...

    def stream(
        self, messages: list[LLMMessage], *, temperature: float | None = None, max_tokens: int | None = None
    ) -> AsyncIterator[str]: ...

    async def structured_output(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_schema: dict | None = None,
    ) -> StructuredResult[T]: ...

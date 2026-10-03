"""Conversation blocks — NOVA replies are block-based, not a plain message list.

Each block has a stable ``key`` inside its message so that execution can upsert it while streaming
(the plan block is updated as steps complete, the progress block grows, …).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nova.domain.enums import BlockType


class Block(BaseModel):
    key: str
    type: BlockType
    data: dict[str, Any] = Field(default_factory=dict)


class ProgressLine(BaseModel):
    """Operational summary — never raw model reasoning."""

    key: str
    label: str
    status: str  # queued | running | completed | failed | skipped
    detail: str = ""


def text_block(markdown: str, key: str = "text") -> Block:
    return Block(key=key, type=BlockType.text, data={"markdown": markdown})


def warning_block(title: str, message: str, actions: list[dict[str, str]] | None = None, key: str = "warning") -> Block:
    return Block(key=key, type=BlockType.warning, data={"title": title, "message": message, "actions": actions or []})


def error_block(title: str, message: str, actions: list[dict[str, str]] | None = None) -> Block:
    return Block(key="error", type=BlockType.error, data={"title": title, "message": message, "actions": actions or []})

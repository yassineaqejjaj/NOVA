"""Design port: what NOVA needs from a design tool (implemented by the Figma adapter, MCP first)."""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol
from urllib.parse import parse_qs, urlsplit

from pydantic import BaseModel, Field


class DesignError(Exception):
    """``code``: not_connected | forbidden | not_found | unavailable | write_unavailable | invalid."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


class DesignRef(BaseModel):
    file_key: str
    node_id: str | None = None  # "1:2" form
    url: str | None = None


class DesignNode(BaseModel):
    id: str
    name: str = ""
    type: str = ""
    children: list[DesignNode] = Field(default_factory=list)
    text: str | None = None
    width: float | None = None
    height: float | None = None


class DesignVariable(BaseModel):
    name: str
    type: str = ""
    value: Any = None


class DesignSnapshot(BaseModel):
    file_name: str = ""
    nodes: list[DesignNode] = Field(default_factory=list)
    variables: list[DesignVariable] = Field(default_factory=list)
    screenshot_url: str | None = None
    source: Literal["mcp", "rest"] = "rest"
    truncated: bool = False


class ElementSpec(BaseModel):
    id: str = ""
    type: str = "text"
    label: str = ""
    region: Literal["header", "sidebar", "body", "footer"] = "body"
    row: int = 0
    span: int = Field(default=12, ge=1, le=12)
    variant: str | None = None
    state: str | None = None


class ScreenSpec(BaseModel):
    id: str = ""
    name: str
    fidelity: Literal["wireframe", "lowfi", "hifi"] = "wireframe"
    device: Literal["mobile", "tablet", "desktop"] = "desktop"
    purpose: str = ""
    states: list[str] = Field(default_factory=list)
    notes: str = ""
    elements: list[ElementSpec] = Field(default_factory=list)


class TokenSpec(BaseModel):
    name: str
    category: Literal["color", "typography", "spacing", "radius", "shadow"] = "color"
    value: str = ""
    usage: str = ""


class PushResult(BaseModel):
    external_id: str
    status: str = "pushed"
    url: str | None = None
    file_key: str | None = None


class FigmaStatus(BaseModel):
    linked: bool = False
    mode: Literal["oauth", "token"] | None = None
    mcp: bool = False
    can_write: bool = False
    figma_handle: str | None = None
    oauth_available: bool = False


class DesignProvider(Protocol):
    async def status(self, user_id: str) -> FigmaStatus: ...

    async def get_design(self, user_id: str, ref: DesignRef) -> DesignSnapshot: ...

    async def push_screens(
        self, user_id: str, title: str, screens: list[ScreenSpec], tokens: list[TokenSpec], file_key: str | None = None
    ) -> PushResult: ...


_PATH = re.compile(r"^/(?:design|file|proto|board|make)/([A-Za-z0-9]+)(?:/branch/([A-Za-z0-9]+))?")


def parse_figma_url(url: str) -> DesignRef | None:
    """``figma.com/design/:key/:name?node-id=1-2`` (also /file, /proto, branch URLs) → file key + node id ``1:2``."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if host != "figma.com" and not host.endswith(".figma.com"):
        return None
    match = _PATH.match(parts.path)
    if not match:
        return None
    key = match.group(2) or match.group(1)  # a branch has its own file key
    node = (parse_qs(parts.query).get("node-id") or [None])[0]
    node_id = node.replace("-", ":") if node else None
    return DesignRef(file_key=key, node_id=node_id, url=url.strip())

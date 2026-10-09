"""``DesignProvider`` on Figma: hosted MCP server for OAuth links, REST API for personal-token links (read only)."""

from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import timedelta
from typing import Any

import httpx

from nova.config import Settings
from nova.domain.design import (
    DesignError,
    DesignNode,
    DesignRef,
    DesignSnapshot,
    DesignVariable,
    FigmaStatus,
    PushResult,
    ScreenSpec,
    TokenSpec,
)
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import FigmaAccount
from nova.integrations.figma.mcp import McpClient
from nova.integrations.figma.oauth import FigmaOAuth, OAuthTokens
from nova.integrations.figma.rest import MAX_DEPTH, MAX_NAME, MAX_NODES, FigmaRestClient

DEVICE_WIDTH = {"mobile": 390, "tablet": 820, "desktop": 1440}
REFRESH_MARGIN = timedelta(seconds=60)

# Tool names are discovered with tools/list and picked defensively (the server's schemas may change).
READ_TOOLS = {
    "metadata": ("get_metadata",),
    "variables": ("get_variable_defs", "get_variables"),
    "context": ("get_design_context",),
}
WRITE_TOOLS = ("use_figma",)
CREATE_FILE_TOOLS = ("create_new_file",)


# --- Prompt building (pure, deterministic) ----------------------------------------------------------


def build_push_instruction(title: str, screens: list[ScreenSpec], tokens: list[TokenSpec]) -> str:
    """Compact instruction + JSON spec for Figma's write tool: auto-layout frames per region and row."""
    spec: dict[str, Any] = {
        "title": title,
        "tokens": [{k: v for k, v in t.model_dump().items() if v} for t in tokens],
        "screens": [],
    }
    for screen in screens:
        regions: dict[str, dict[int, list[dict[str, Any]]]] = {}
        for el in screen.elements:
            item = {"type": el.type, "label": el.label, "span": el.span}
            if el.variant:
                item["variant"] = el.variant
            if el.state:
                item["state"] = el.state
            regions.setdefault(el.region, {}).setdefault(el.row, []).append(item)
        spec["screens"].append(
            {
                "name": screen.name,
                "fidelity": screen.fidelity,
                "device": screen.device,
                "width": DEVICE_WIDTH[screen.device],
                "purpose": screen.purpose,
                "states": screen.states,
                "regions": [
                    {"region": region, "rows": [rows[r] for r in sorted(rows)]}
                    for region, rows in sorted(
                        regions.items(), key=lambda kv: ("header", "sidebar", "body", "footer").index(kv[0])
                    )
                ],
            }
        )
    return (
        f"Create the design '{title}' in Figma. For each screen in the spec create a top-level frame named after the "
        "screen, using the given width, a vertical auto layout and one child frame per region (header, sidebar, body, "
        "footer) in that order. Inside a region create one horizontal auto-layout frame per row (in order); elements "
        "sharing a row sit side by side and fill space proportionally to 'span' (12 = full width). Fidelity 'wireframe' "
        "means grey boxes with short placeholder labels, 'lowfi' neutral UI with the real labels, 'hifi' the tokens "
        "applied. Create the tokens as local variables (name, value) and bind them in hi-fi screens. "
        "Do not invent content beyond the spec.\nSPEC:\n" + json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    )


# --- Tool result normalization (defensive) ----------------------------------------------------------


def _trim(name: Any) -> str:
    return str(name or "")[:MAX_NAME]


def _node_from_json(raw: dict[str, Any], budget: list[int], depth: int = 0) -> DesignNode | None:
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    node = DesignNode(
        id=str(raw.get("id", "")),
        name=_trim(raw.get("name")),
        type=str(raw.get("type", "")),
        text=str(raw["characters"])[:200] if raw.get("characters") else None,
        width=raw.get("width"),
        height=raw.get("height"),
    )
    if depth < MAX_DEPTH:
        for child in raw.get("children") or []:
            if isinstance(child, dict) and (n := _node_from_json(child, budget, depth + 1)):
                node.children.append(n)
    return node


def _node_from_xml(el: ET.Element, budget: list[int], depth: int = 0) -> DesignNode | None:
    if budget[0] <= 0:
        return None
    budget[0] -= 1

    def num(key: str) -> float | None:
        try:
            return float(el.attrib[key])
        except (KeyError, ValueError):
            return None

    node = DesignNode(
        id=el.attrib.get("id", ""),
        name=_trim(el.attrib.get("name")),
        type=el.attrib.get("type") or el.tag.upper(),
        text=(el.text or "").strip()[:200] or None,
        width=num("width"),
        height=num("height"),
    )
    if depth < MAX_DEPTH:
        for child in el:
            if n := _node_from_xml(child, budget, depth + 1):
                node.children.append(n)
    return node


def normalize_metadata(payload: Any, budget: list[int]) -> list[DesignNode]:
    """``get_metadata`` returns a JSON node tree or an XML-like outline; anything else yields no nodes."""
    if isinstance(payload, dict):
        roots = payload.get("nodes") if isinstance(payload.get("nodes"), list) else [payload.get("document") or payload]
        return [n for r in roots if isinstance(r, dict) and (n := _node_from_json(r, budget))]
    if isinstance(payload, list):
        return [n for r in payload if isinstance(r, dict) and (n := _node_from_json(r, budget))]
    if isinstance(payload, str) and "<" in payload:
        try:
            root = ET.fromstring(f"<root>{payload}</root>")
        except ET.ParseError:
            return []
        return [n for child in root if (n := _node_from_xml(child, budget))]
    return []


def normalize_variables_payload(payload: Any) -> list[DesignVariable]:
    """``get_variable_defs`` → ``{ "color/primary": "#fff", ... }`` (or a list of ``{name,type,value}``)."""
    out: list[DesignVariable] = []
    if isinstance(payload, dict):
        for name, value in payload.items():
            if isinstance(value, dict) and "value" in value:
                out.append(DesignVariable(name=str(name), type=str(value.get("type", "")), value=value["value"]))
            else:
                out.append(DesignVariable(name=str(name), type=_guess_type(value), value=value))
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict) and item.get("name"):
                out.append(DesignVariable(name=str(item["name"]), type=str(item.get("type", "")), value=item.get("value")))
    elif isinstance(payload, str):
        for line in payload.splitlines():  # "name: value" lines
            name, sep, value = line.partition(":")
            if sep and name.strip():
                out.append(DesignVariable(name=name.strip(), value=value.strip()))
    return out[:200]


def _guess_type(value: Any) -> str:
    if isinstance(value, str) and value.startswith("#"):
        return "COLOR"
    return {bool: "BOOLEAN", int: "FLOAT", float: "FLOAT", str: "STRING"}.get(type(value), "")


def _schema_props(tool: dict[str, Any]) -> dict[str, Any]:
    schema = tool.get("inputSchema") or tool.get("input_schema") or {}
    return schema.get("properties") or {}


def _pick_property(tool: dict[str, Any] | None, candidates: tuple[str, ...], default: str) -> str:
    props = _schema_props(tool or {})
    for name in candidates:
        if name in props:
            return name
    lowered = {k.lower(): k for k in props}
    for name in candidates:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return default


def _find_tool(tools: list[dict[str, Any]], names: tuple[str, ...]) -> dict[str, Any] | None:
    by_name = {str(t.get("name")): t for t in tools}
    return next((by_name[n] for n in names if n in by_name), None)


_KEY_RE = re.compile(r"figma\.com/(?:design|file|proto|board)/([A-Za-z0-9]+)")


def _extract_file(result: Any) -> tuple[str | None, str | None]:
    """(file_key, url) from a tool result (JSON object or text)."""
    if isinstance(result, dict):
        key = next((str(result[k]) for k in ("file_key", "fileKey", "key", "id") if result.get(k)), None)
        url = next((str(result[k]) for k in ("url", "file_url", "fileUrl", "link") if result.get(k)), None)
        if not key and url and (m := _KEY_RE.search(url)):
            key = m.group(1)
        return key, url
    text = str(result or "")
    match = _KEY_RE.search(text)
    url_match = re.search(r"https://[^\s\"')]*figma\.com/\S+", text)
    return (match.group(1) if match else None), (url_match.group(0) if url_match else None)


# --- Provider ---------------------------------------------------------------------------------------


class FigmaDesignProvider:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._transport = transport
        self.oauth = FigmaOAuth(settings, transport=transport)

    # --- Credentials -------------------------------------------------------------------------------

    async def _account(self, user_id: str) -> FigmaAccount | None:
        async with session_scope() as session:
            return await session.get(FigmaAccount, uuid.UUID(user_id))

    async def _credentials(self, user_id: str) -> tuple[str, str]:
        """→ (mode, access token); refreshes an expired OAuth token and persists the new one."""
        account = await self._account(user_id)
        if account is None or not account.token_ciphertext:
            raise DesignError("not_connected", "Connect Figma in Settings")
        token = decrypt(account.token_ciphertext)
        if not token:
            raise DesignError("not_connected", "Connect Figma in Settings")
        if account.mode == "oauth" and account.expires_at and aware(account.expires_at) - REFRESH_MARGIN <= utcnow():
            refresh = decrypt(account.refresh_ciphertext) if account.refresh_ciphertext else None
            if not refresh:
                raise DesignError("not_connected", "Your Figma session expired: reconnect Figma in Settings")
            tokens = await self.oauth.refresh(refresh)
            await self.save_oauth(user_id, tokens)
            token = tokens.access_token
        return account.mode, token

    async def save_oauth(self, user_id: str, tokens: OAuthTokens, *, figma_user_id: str = "", handle: str = "") -> None:
        async with session_scope() as session:
            account = await session.get(FigmaAccount, uuid.UUID(user_id))
            if account is None:
                account = FigmaAccount(user_id=uuid.UUID(user_id), mode="oauth")
                session.add(account)
            account.mode = "oauth"
            account.token_ciphertext = encrypt(tokens.access_token)
            account.refresh_ciphertext = encrypt(tokens.refresh_token) if tokens.refresh_token else None
            account.expires_at = tokens.expires_at
            account.scope = tokens.scope[:500]
            if figma_user_id:
                account.figma_user_id = figma_user_id
            if handle:
                account.handle = handle[:200]

    async def save_token(self, user_id: str, token: str, *, figma_user_id: str, handle: str) -> None:
        async with session_scope() as session:
            account = await session.get(FigmaAccount, uuid.UUID(user_id))
            if account is None:
                account = FigmaAccount(user_id=uuid.UUID(user_id), mode="token")
                session.add(account)
            account.mode = "token"
            account.token_ciphertext = encrypt(token)
            account.refresh_ciphertext = None
            account.expires_at = None
            account.scope = ""
            account.figma_user_id = figma_user_id[:64]
            account.handle = handle[:200]

    async def unlink(self, user_id: str) -> None:
        async with session_scope() as session:
            account = await session.get(FigmaAccount, uuid.UUID(user_id))
            if account:
                await session.delete(account)

    async def validate_token(self, token: str) -> dict[str, Any]:
        client = FigmaRestClient(
            self.settings.figma_api_url, token, timeout=self.settings.figma_timeout_seconds, transport=self._transport
        )
        try:
            return await client.me()
        finally:
            await client.aclose()

    # --- Port --------------------------------------------------------------------------------------

    async def status(self, user_id: str) -> FigmaStatus:
        account = await self._account(user_id)
        linked = bool(account and account.token_ciphertext)
        oauth = linked and account is not None and account.mode == "oauth"
        return FigmaStatus(
            linked=linked,
            mode=account.mode if linked and account and account.mode in ("oauth", "token") else None,  # type: ignore[arg-type]
            mcp=oauth,
            can_write=oauth,
            figma_handle=(account.handle or None) if linked and account else None,
            oauth_available=self.oauth.available,
        )

    def _mcp(self, token: str) -> McpClient:
        return McpClient(
            self.settings.figma_mcp_url, token, timeout=self.settings.figma_timeout_seconds, transport=self._transport
        )

    async def get_design(self, user_id: str, ref: DesignRef) -> DesignSnapshot:
        mode, token = await self._credentials(user_id)
        if mode == "oauth":
            return await self._get_design_mcp(token, ref)
        rest = FigmaRestClient(
            self.settings.figma_api_url, token, timeout=self.settings.figma_timeout_seconds, transport=self._transport
        )
        try:
            return await rest.snapshot(ref.file_key, ref.node_id)
        finally:
            await rest.aclose()

    async def _get_design_mcp(self, token: str, ref: DesignRef) -> DesignSnapshot:
        async with self._mcp(token) as mcp:
            tools = await mcp.list_tools()
            budget = [MAX_NODES]
            nodes: list[DesignNode] = []
            variables: list[DesignVariable] = []
            name = ""
            meta_tool = _find_tool(tools, READ_TOOLS["metadata"]) or _find_tool(tools, READ_TOOLS["context"])
            if meta_tool is None:
                raise DesignError("unavailable", "Figma MCP does not expose a read tool for designs")
            payload = await mcp.call_tool(str(meta_tool["name"]), self._read_args(meta_tool, ref))
            nodes = normalize_metadata(payload, budget)
            if isinstance(payload, dict):
                name = _trim(payload.get("name") or payload.get("file_name"))
            var_tool = _find_tool(tools, READ_TOOLS["variables"])
            if var_tool:
                try:
                    variables = normalize_variables_payload(
                        await mcp.call_tool(str(var_tool["name"]), self._read_args(var_tool, ref))
                    )
                except DesignError as exc:  # variables are optional context
                    if exc.code == "not_connected":
                        raise
            return DesignSnapshot(
                file_name=name or (nodes[0].name if nodes else ""),
                nodes=nodes,
                variables=variables,
                source="mcp",
                truncated=budget[0] <= 0,
            )

    @staticmethod
    def _read_args(tool: dict[str, Any], ref: DesignRef) -> dict[str, Any]:
        """Fill the arguments the tool declares (unknown schema: the usual ``fileKey`` / ``nodeId``)."""
        props = _schema_props(tool)
        values = {("fileKey", "file_key"): ref.file_key, ("nodeId", "node_id"): ref.node_id, ("url", "figma_url"): ref.url}
        args: dict[str, Any] = {}
        for names, value in values.items():
            if value is None:
                continue
            picked = _pick_property(tool, names, "")
            if picked:
                args[picked] = value
            elif not props and names[0] != "url":
                args[names[0]] = value
        return args

    async def push_screens(
        self, user_id: str, title: str, screens: list[ScreenSpec], tokens: list[TokenSpec], file_key: str | None = None
    ) -> PushResult:
        mode, token = await self._credentials(user_id)
        if mode != "oauth":
            raise DesignError(
                "write_unavailable",
                "Writing to Figma needs the Figma MCP connection (OAuth); only a personal token is linked, which is read-only.",
            )
        if not screens:
            raise DesignError("invalid", "The Artifact has no screens to push")
        async with self._mcp(token) as mcp:
            tools = await mcp.list_tools()
            write = _find_tool(tools, WRITE_TOOLS)
            if write is None:
                raise DesignError("write_unavailable", "The connected Figma MCP server does not expose a write tool")
            url: str | None = None
            if not file_key:
                create = _find_tool(tools, CREATE_FILE_TOOLS)
                if create is None:
                    raise DesignError("write_unavailable", "Provide a Figma file key: NOVA cannot create new Figma files here")
                name_prop = _pick_property(create, ("name", "fileName", "file_name", "title"), "name")
                created = await mcp.call_tool(str(create["name"]), {name_prop: title[:200]})
                file_key, url = _extract_file(created)
                if not file_key:
                    raise DesignError("unavailable", "Figma did not return the new file", retryable=True)
            instruction = build_push_instruction(title, screens, tokens)
            text_prop = _pick_property(write, ("prompt", "instruction", "instructions", "description", "task"), "prompt")
            key_prop = _pick_property(write, ("fileKey", "file_key"), "fileKey")
            result = await mcp.call_tool(str(write["name"]), {key_prop: file_key, text_prop: instruction})
            _, result_url = _extract_file(result)
            url = result_url or url or f"https://www.figma.com/design/{file_key}"
            return PushResult(external_id=str(file_key), status="pushed", url=url, file_key=str(file_key))

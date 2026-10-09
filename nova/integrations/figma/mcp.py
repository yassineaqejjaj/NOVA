"""Generic MCP client over Streamable HTTP (JSON-RPC 2.0), used for Figma's hosted MCP server."""

from __future__ import annotations

import json
from typing import Any

import httpx

from nova.domain.design import DesignError

PROTOCOL_VERSION = "2025-06-18"


class McpClient:
    """One short-lived session per instance: ``initialize`` is sent lazily before the first call."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
        client_name: str = "nova",
    ) -> None:
        self.url = url
        self._token = token
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport)
        self._session_id: str | None = None
        self._initialized = False
        self._next_id = 0
        self._client_name = client_name
        self._tools: list[dict[str, Any]] | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> McpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # --- Transport -------------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        try:
            response = await self._client.post(self.url, json=payload, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise DesignError("unavailable", "Figma did not answer in time", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise DesignError("unavailable", "Figma MCP is unreachable", retryable=True) from exc
        status = response.status_code
        if status == 401:
            raise DesignError("not_connected", "Figma authorization expired: reconnect Figma in Settings")
        if status == 403:
            raise DesignError("forbidden", "Figma refused access to this resource")
        if status == 404:
            raise DesignError("not_found", "Figma resource or MCP session not found")
        if status in (408, 425, 429) or status >= 500:
            raise DesignError("unavailable", f"Figma MCP unavailable ({status})", retryable=True)
        if status >= 400:
            raise DesignError("invalid", f"Figma MCP rejected the request ({status})")
        return response

    @staticmethod
    def _messages(response: httpx.Response) -> list[dict[str, Any]]:
        """JSON body or SSE stream (``data:`` lines; an event may span several ``data:`` lines)."""
        ctype = response.headers.get("content-type", "")
        text = response.text
        if not text.strip():
            return []
        if "text/event-stream" in ctype:
            messages: list[dict[str, Any]] = []
            data: list[str] = []

            def flush() -> None:
                if data:
                    try:
                        parsed = json.loads("\n".join(data))
                    except ValueError:
                        parsed = None
                    if isinstance(parsed, dict):
                        messages.append(parsed)
                    elif isinstance(parsed, list):
                        messages.extend(m for m in parsed if isinstance(m, dict))
                    data.clear()

            for line in text.splitlines():
                if not line.strip():
                    flush()
                elif line.startswith("data:"):
                    data.append(line[5:].removeprefix(" "))
            flush()
            return messages
        try:
            parsed = response.json()
        except ValueError as exc:
            raise DesignError("unavailable", "Figma MCP returned an unreadable response", retryable=True) from exc
        return [parsed] if isinstance(parsed, dict) else [m for m in parsed if isinstance(m, dict)]

    async def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._next_id += 1
        request_id = self._next_id
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = await self._post(payload)
        session = response.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        for message in self._messages(response):
            if message.get("id") != request_id:
                continue
            if message.get("error"):
                error = message["error"] if isinstance(message["error"], dict) else {}
                raise DesignError(_code_for_rpc_error(error), str(error.get("message") or "Figma MCP error"))
            return message.get("result")
        raise DesignError("unavailable", "Figma MCP sent no result", retryable=True)

    async def _notify(self, method: str) -> None:
        await self._post({"jsonrpc": "2.0", "method": method})

    # --- MCP -------------------------------------------------------------------------------------

    async def initialize(self) -> dict[str, Any]:
        if self._initialized:
            return {}
        result = await self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": "1"},
            },
        )
        self._initialized = True
        await self._notify("notifications/initialized")
        return result or {}

    async def list_tools(self) -> list[dict[str, Any]]:
        if self._tools is None:
            await self.initialize()
            result = await self._rpc("tools/list", {})
            self._tools = [t for t in (result or {}).get("tools", []) if isinstance(t, dict)]
        return self._tools

    async def tool_names(self) -> set[str]:
        return {str(t.get("name")) for t in await self.list_tools()}

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Call a tool; returns the parsed JSON of the first text content (else the text, else structured content)."""
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        text = "\n".join(
            str(c.get("text", "")) for c in result.get("content", []) if isinstance(c, dict) and c.get("type") == "text"
        )
        if result.get("isError"):
            raise DesignError(_code_for_text(text), text[:300] or f"Figma tool {name} failed")
        if result.get("structuredContent") not in (None, {}):
            return result["structuredContent"]
        try:
            return json.loads(text)
        except ValueError:
            return text

    async def call_tool_raw(self, name: str, arguments: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Content blocks of a tool result (text/image), for tools returning screenshots."""
        await self.initialize()
        result = await self._rpc("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        if result.get("isError"):
            text = " ".join(str(c.get("text", "")) for c in result.get("content", []) if isinstance(c, dict))
            raise DesignError(_code_for_text(text), text[:300] or f"Figma tool {name} failed")
        return [c for c in result.get("content", []) if isinstance(c, dict)]


def _code_for_rpc_error(error: dict[str, Any]) -> str:
    code = error.get("code")
    if code in (-32001, -32002):
        return "not_found"
    if code == -32600 or code == -32602:
        return "invalid"
    return _code_for_text(str(error.get("message") or ""))


def _code_for_text(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("unauthor", "not authenticated", "token expired", "invalid token")):
        return "not_connected"
    if any(k in low for k in ("forbidden", "permission", "no access", "not allowed")):
        return "forbidden"
    if "not found" in low or "does not exist" in low:
        return "not_found"
    if any(k in low for k in ("rate limit", "timeout", "temporar")):
        return "unavailable"
    return "invalid"

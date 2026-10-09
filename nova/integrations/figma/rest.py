"""Degraded Figma access: REST API with the user's personal access token (read only)."""

from __future__ import annotations

from typing import Any

import httpx

from nova.domain.design import DesignError, DesignNode, DesignSnapshot, DesignVariable

MAX_NODES = 120
MAX_DEPTH = 6
MAX_NAME = 80


def _error(response: httpx.Response) -> DesignError:
    status = response.status_code
    if status == 401:
        return DesignError("not_connected", "The Figma token is invalid or expired: update it in Settings")
    if status == 403:
        return DesignError("forbidden", "This Figma token cannot access that file (or variables need an Enterprise plan)")
    if status == 404:
        return DesignError("not_found", "Figma file or node not found")
    if status in (408, 425, 429) or status >= 500:
        return DesignError("unavailable", f"Figma unavailable ({status})", retryable=True)
    return DesignError("invalid", f"Figma rejected the request ({status})")


def normalize_node(raw: dict[str, Any], budget: list[int], depth: int = 0) -> DesignNode | None:
    """Bounded tree: at most ``MAX_NODES`` nodes and ``MAX_DEPTH`` levels, names truncated."""
    if budget[0] <= 0:
        return None
    budget[0] -= 1
    box = raw.get("absoluteBoundingBox") or {}
    node = DesignNode(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", ""))[:MAX_NAME],
        type=str(raw.get("type", "")),
        text=str(raw["characters"])[:200] if raw.get("characters") else None,
        width=box.get("width"),
        height=box.get("height"),
    )
    if depth < MAX_DEPTH:
        for child in raw.get("children") or []:
            if isinstance(child, dict) and (n := normalize_node(child, budget, depth + 1)):
                node.children.append(n)
    return node


def normalize_variables(payload: dict[str, Any]) -> list[DesignVariable]:
    meta = payload.get("meta") or {}
    collections = meta.get("variableCollections") or {}
    out: list[DesignVariable] = []
    for var in (meta.get("variables") or {}).values():
        if not isinstance(var, dict):
            continue
        collection = collections.get(var.get("variableCollectionId")) or {}
        mode = collection.get("defaultModeId")
        values = var.get("valuesByMode") or {}
        value = values.get(mode) if mode in values else next(iter(values.values()), None)
        if isinstance(value, dict) and {"r", "g", "b"} <= value.keys():
            value = "#{:02x}{:02x}{:02x}".format(*(round(float(value[c]) * 255) for c in "rgb"))
        out.append(DesignVariable(name=str(var.get("name", "")), type=str(var.get("resolvedType", "")), value=value))
    return out[:200]


class FigmaRestClient:
    def __init__(
        self, base_url: str, token: str, *, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)
        self._token = token

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self._client.get(path, params=params, headers={"X-Figma-Token": self._token})
        except httpx.HTTPError as exc:
            raise DesignError("unavailable", "Figma is unreachable", retryable=True) from exc
        if response.status_code >= 400:
            raise _error(response)
        try:
            body = response.json()
        except ValueError as exc:
            raise DesignError("unavailable", "Figma returned an unreadable response", retryable=True) from exc
        return body if isinstance(body, dict) else {}

    async def me(self) -> dict[str, Any]:
        return await self._get("/v1/me")

    async def snapshot(self, file_key: str, node_id: str | None) -> DesignSnapshot:
        budget = [MAX_NODES]
        if node_id:
            data = await self._get(f"/v1/files/{file_key}/nodes", {"ids": node_id, "depth": MAX_DEPTH})
            roots = [v.get("document") for v in (data.get("nodes") or {}).values() if isinstance(v, dict) and v.get("document")]
        else:
            data = await self._get(f"/v1/files/{file_key}", {"depth": 2})
            roots = (data.get("document") or {}).get("children") or []
        nodes = [n for r in roots if isinstance(r, dict) and (n := normalize_node(r, budget))]
        try:
            variables = normalize_variables(await self._get(f"/v1/files/{file_key}/variables/local"))
        except DesignError as exc:  # variables API is Enterprise-only: never fail the whole read
            if exc.code in ("not_connected", "unavailable"):
                raise
            variables = []
        return DesignSnapshot(
            file_name=str(data.get("name", ""))[:MAX_NAME],
            nodes=nodes,
            variables=variables,
            source="rest",
            truncated=budget[0] <= 0,
        )

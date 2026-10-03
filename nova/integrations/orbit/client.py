"""HTTP client for ORBIT's REST API v1 (contract: ORBIT docs/API.md)."""

from __future__ import annotations

from typing import Any, Literal

import httpx

from nova.domain.context import ContextError

API = "/api/v1"


class OrbitAuth:
    """Credentials for one call: a delegated user session (JWT) or a project agent key."""

    def __init__(self, mode: Literal["session", "agent_key"], secret: str, on_behalf_of: str | None = None) -> None:
        self.mode = mode
        self.secret = secret
        self.on_behalf_of = on_behalf_of

    def headers(self) -> dict[str, str]:
        if self.mode == "agent_key":
            return {"X-Orbit-Key": self.secret}
        return {"Authorization": f"Bearer {self.secret}"}


def _error(response: httpx.Response) -> ContextError:
    try:
        detail = str(response.json().get("detail") or "")
    except ValueError:
        detail = ""
    status = response.status_code
    if status == 401:
        return ContextError("unauthorized", detail or "ORBIT session expired")
    if status == 403:
        return ContextError("forbidden", detail or "Insufficient permissions in ORBIT")
    if status == 404:
        return ContextError("not_found", detail or "Not found in ORBIT")
    if status in (408, 425, 429) or status >= 500:
        return ContextError("unavailable", detail or f"ORBIT unavailable ({status})", retryable=True)
    return ContextError("invalid", detail or f"ORBIT rejected the request ({status})")


class OrbitClient:
    def __init__(self, base_url: str, *, timeout: float = 20.0, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, auth: OrbitAuth | None, **kwargs: Any) -> httpx.Response:
        headers = auth.headers() if auth else {}
        try:
            response = await self._client.request(method, f"{API}{path}", headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise ContextError("unavailable", "ORBIT is unreachable", retryable=True) from exc
        if response.status_code >= 400:
            raise _error(response)
        return response

    # --- Auth ------------------------------------------------------------------------------------

    async def login(self, email: str, password: str) -> tuple[dict[str, Any], str]:
        """``POST /auth/login`` → (user, session JWT from the ``orbit_session`` cookie). Password is not kept."""
        response = await self._request("POST", "/auth/login", None, json={"email": email, "password": password})
        token = response.cookies.get("orbit_session")
        if not token:
            raise ContextError("invalid", "ORBIT did not return a session")
        return response.json(), token

    async def me(self, auth: OrbitAuth) -> dict[str, Any]:
        return (await self._request("GET", "/auth/me", auth)).json()

    # --- Context ---------------------------------------------------------------------------------

    async def context(self, auth: OrbitAuth, slug: str, body: dict[str, Any]) -> dict[str, Any]:
        return (await self._request("POST", f"/projects/{slug}/context", auth, json=body)).json()

    async def context_feedback(self, auth: OrbitAuth, slug: str, request_id: str, body: dict[str, Any]) -> None:
        await self._request("POST", f"/projects/{slug}/context/requests/{request_id}/feedback", auth, json=body)

    async def projects(self, auth: OrbitAuth) -> list[dict[str, Any]]:
        return (await self._request("GET", "/projects", auth)).json()

    async def changes(self, auth: OrbitAuth, slug: str, params: dict[str, Any]) -> dict[str, Any]:
        return (await self._request("GET", f"/projects/{slug}/changes", auth, params=params)).json()

    async def search(self, auth: OrbitAuth, slug: str, query: str, limit: int) -> list[dict[str, Any]]:
        return (await self._request("GET", f"/projects/{slug}/search", auth, params={"q": query, "limit": limit})).json()

    async def create_memory(self, auth: OrbitAuth, slug: str, body: dict[str, Any]) -> dict[str, Any]:
        return (await self._request("POST", f"/projects/{slug}/memory", auth, json=body)).json()

    async def create_text_document(self, auth: OrbitAuth, slug: str, body: dict[str, Any]) -> dict[str, Any]:
        return (await self._request("POST", f"/projects/{slug}/documents/text", auth, json=body)).json()

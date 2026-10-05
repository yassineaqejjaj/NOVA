"""HTTP client for FORGE's REST API v1 (contract: FORGE docs/ARCHITECTURE.md §12)."""

from __future__ import annotations

from typing import Any

import httpx

API = "/api/v1"


class ForgeError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class ForgeClient:
    def __init__(
        self, base_url: str, api_key: str, *, timeout: float = 20.0, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        headers = {"X-Forge-Key": api_key} if api_key else {}
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._client.request(method, f"{API}{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise ForgeError(0, f"FORGE unreachable ({exc.__class__.__name__})") from exc
        if response.status_code >= 400:
            try:
                detail = str(response.json().get("detail") or "")
            except ValueError:
                detail = response.text[:200]
            raise ForgeError(response.status_code, detail or f"FORGE error {response.status_code}")
        return response.json() if response.content else None

    async def find_agent(self, slug: str) -> dict[str, Any] | None:
        page = await self._request("GET", "/agents", params={"q": slug, "archived": "all", "page_size": 50})
        return next((a for a in page.get("items", []) if a.get("slug") == slug), None)

    async def create_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/agents", json=body)

    async def list_agent_versions(self, agent_id: str) -> list[dict[str, Any]]:
        data = await self._request("GET", f"/agents/{agent_id}/versions")
        return data.get("items", data) if isinstance(data, dict) else data

    async def create_agent_version(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/agents/{agent_id}/versions", json=body)

    async def create_scenario(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/scenarios", json=body)

    async def create_runs(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        return await self._request("POST", "/runs", json=body)

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/runs/{run_id}")

    async def human_evaluation(self, run_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", f"/runs/{run_id}/human-evaluations", json=body)

    # --- Training loop -------------------------------------------------------------------------------

    async def find_scenario(self, slug: str) -> dict[str, Any] | None:
        page = await self._request("GET", "/scenarios", params={"q": slug, "page_size": 50})
        return next((s for s in page.get("items", []) if s.get("slug") == slug), None)

    async def run_feedback(self, run_id: str) -> dict[str, Any] | None:
        """Latest FeedbackReport of a run (``None`` while FORGE has not produced one)."""
        try:
            return await self._request("GET", f"/runs/{run_id}/feedback")
        except ForgeError as exc:
            if exc.status == 404:
                return None
            raise

    async def create_experiment(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/experiments", json=body)

    async def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/experiments/{experiment_id}")

    async def experiment_comparison(self, experiment_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/experiments/{experiment_id}/comparison")

    async def cancel_experiment(self, experiment_id: str) -> None:
        await self._request("POST", f"/experiments/{experiment_id}/cancel")

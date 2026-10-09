"""GitHub REST client (personal access token), limited to what NOVA's SDLC Autopilot needs.

Writes go through the Git Data API so one step is one atomic commit on a ``nova/*`` branch.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

API_URL = "https://api.github.com"
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class GitHubError(Exception):
    """``code``: unauthorized | forbidden | not_found | invalid | conflict | rate_limited | unavailable."""

    def __init__(self, code: str, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status

    @property
    def retryable(self) -> bool:
        return self.code in ("unavailable", "rate_limited")


def parse_repo(text: str) -> str | None:
    """``owner/name`` or any github.com repository / PR / issue URL → ``owner/name``."""
    text = text.strip()
    if _REPO.match(text):
        return text.removesuffix(".git")
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if len(segments) < 2:
        return None
    full = f"{segments[0]}/{segments[1].removesuffix('.git')}"
    return full if _REPO.match(full) else None


def parse_github_ref(url: str, kind: str) -> tuple[str, int] | None:
    """``https://github.com/o/r/pull/12`` (kind ``pull``) or ``/issues/7`` (kind ``issues``) → (``o/r``, number)."""
    match = re.match(rf"^https?://(?:www\.)?github\.com/([\w.-]+/[\w.-]+)/{kind}/(\d+)", url.strip())
    return (match.group(1), int(match.group(2))) if match else None


@dataclass
class CheckSummary:
    state: str  # none | pending | success | failure
    total: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)  # [{name, title, summary, annotations: [...]}]
    pending: list[str] = field(default_factory=list)


class GitHubClient:
    def __init__(
        self, token: str, *, api_url: str = API_URL, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None
    ):
        self._client = httpx.AsyncClient(
            base_url=api_url.rstrip("/"),
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "NOVA-SDLC",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self, method: str, path: str, *, expect_text: bool = False, accept: str | None = None, **kwargs: Any
    ) -> Any:
        headers = {"Accept": accept} if accept else None
        try:
            response = await self._client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubError("unavailable", f"GitHub is unreachable ({exc.__class__.__name__})") from exc
        status = response.status_code
        if status >= 400:
            try:
                detail = str(response.json().get("message") or "")
            except ValueError:
                detail = response.text[:200]
            if status == 401:
                raise GitHubError("unauthorized", "GitHub rejected the token (expired or revoked).", status)
            if status == 403 and response.headers.get("x-ratelimit-remaining") == "0":
                raise GitHubError("rate_limited", "GitHub rate limit reached. Try again later.", status)
            if status == 403:
                raise GitHubError("forbidden", f"GitHub denied access: {detail or 'insufficient token permissions'}", status)
            if status == 404:
                raise GitHubError("not_found", "Not found on GitHub (check the repository name and the token's access).", status)
            if status in (409, 405):
                raise GitHubError("conflict", detail or "Conflict", status)
            if status == 422:
                raise GitHubError("invalid", detail or "GitHub rejected the request", status)
            raise GitHubError("unavailable" if status >= 500 else "invalid", detail or f"GitHub error {status}", status)
        if expect_text:
            return response.text
        if status == 204 or not response.content:
            return {}
        return response.json()

    # --- Identity and repositories ---------------------------------------------------------------------------

    async def viewer(self) -> dict[str, Any]:
        try:
            response = await self._client.get("/user")
        except httpx.HTTPError as exc:
            raise GitHubError("unavailable", f"GitHub is unreachable ({exc.__class__.__name__})") from exc
        if response.status_code == 401:
            raise GitHubError("unauthorized", "GitHub rejected this token.", 401)
        if response.status_code >= 400:
            raise GitHubError("invalid", f"GitHub error {response.status_code}", response.status_code)
        data = response.json()
        return {
            "login": data.get("login", ""),
            "name": data.get("name") or "",
            "scopes": response.headers.get("x-oauth-scopes", ""),
        }

    async def list_repos(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._request(
            "GET",
            "/user/repos",
            params={"sort": "pushed", "per_page": min(limit, 100), "affiliation": "owner,collaborator,organization_member"},
        )
        return [
            {
                "full_name": r["full_name"],
                "private": bool(r.get("private")),
                "default_branch": r.get("default_branch", "main"),
                "description": r.get("description") or "",
                "can_push": bool((r.get("permissions") or {}).get("push")),
            }
            for r in data
            if not r.get("archived")
        ]

    async def repo(self, full_name: str) -> dict[str, Any]:
        r = await self._request("GET", f"/repos/{full_name}")
        return {
            "full_name": r["full_name"],
            "default_branch": r.get("default_branch", "main"),
            "private": bool(r.get("private")),
            "can_push": bool((r.get("permissions") or {}).get("push")),
            "description": r.get("description") or "",
        }

    # --- Reading code -----------------------------------------------------------------------------------------

    async def branch_sha(self, repo: str, branch: str) -> str:
        ref = await self._request("GET", f"/repos/{repo}/git/ref/heads/{quote(branch, safe='/')}")
        return ref["object"]["sha"]

    async def tree(self, repo: str, sha: str) -> tuple[list[dict[str, Any]], bool]:
        data = await self._request("GET", f"/repos/{repo}/git/trees/{sha}", params={"recursive": "1"})
        entries = [
            {"path": e["path"], "size": e.get("size", 0), "mode": e.get("mode", "100644")}
            for e in data.get("tree", [])
            if e.get("type") == "blob"
        ]
        return entries, bool(data.get("truncated"))

    async def file_text(self, repo: str, path: str, ref: str) -> str | None:
        try:
            data = await self._request("GET", f"/repos/{repo}/contents/{quote(path, safe='/')}", params={"ref": ref})
        except GitHubError as exc:
            if exc.code == "not_found":
                return None
            raise
        if isinstance(data, list) or data.get("encoding") != "base64":
            return None
        try:
            return base64.b64decode(data.get("content", "")).decode("utf-8")
        except UnicodeDecodeError:
            return None

    async def issue(self, repo: str, number: int) -> dict[str, Any]:
        d = await self._request("GET", f"/repos/{repo}/issues/{number}")
        return {
            "title": d.get("title", ""),
            "body": d.get("body") or "",
            "url": d.get("html_url", ""),
            "is_pr": "pull_request" in d,
        }

    # --- Writing code -----------------------------------------------------------------------------------------

    async def create_branch(self, repo: str, name: str, sha: str) -> None:
        await self._request("POST", f"/repos/{repo}/git/refs", json={"ref": f"refs/heads/{name}", "sha": sha})

    async def delete_branch(self, repo: str, name: str) -> None:
        await self._request("DELETE", f"/repos/{repo}/git/refs/heads/{quote(name, safe='/')}")

    async def commit_files(
        self,
        repo: str,
        branch: str,
        parent_sha: str,
        message: str,
        changes: list[dict[str, str]],
        modes: dict[str, str] | None = None,
    ) -> str:
        """One commit on ``branch`` with ``changes`` ([{path, action, content}]); returns the new commit sha."""
        modes = modes or {}
        parent = await self._request("GET", f"/repos/{repo}/git/commits/{parent_sha}")
        entries: list[dict[str, Any]] = []
        for change in changes:
            if change["action"] == "delete":
                entries.append({"path": change["path"], "mode": "100644", "type": "blob", "sha": None})
                continue
            blob = await self._request(
                "POST", f"/repos/{repo}/git/blobs", json={"content": change["content"], "encoding": "utf-8"}
            )
            entries.append(
                {"path": change["path"], "mode": modes.get(change["path"], "100644"), "type": "blob", "sha": blob["sha"]}
            )
        tree = await self._request("POST", f"/repos/{repo}/git/trees", json={"base_tree": parent["tree"]["sha"], "tree": entries})
        commit = await self._request(
            "POST", f"/repos/{repo}/git/commits", json={"message": message, "tree": tree["sha"], "parents": [parent_sha]}
        )
        await self._request(
            "PATCH", f"/repos/{repo}/git/refs/heads/{quote(branch, safe='/')}", json={"sha": commit["sha"], "force": False}
        )
        return commit["sha"]

    # --- Pull requests ----------------------------------------------------------------------------------------

    async def create_pr(self, repo: str, *, title: str, body: str, head: str, base: str, draft: bool = False) -> dict[str, Any]:
        d = await self._request(
            "POST", f"/repos/{repo}/pulls", json={"title": title, "body": body, "head": head, "base": base, "draft": draft}
        )
        return {"number": d["number"], "url": d["html_url"], "head_sha": d["head"]["sha"]}

    async def pr(self, repo: str, number: int) -> dict[str, Any]:
        d = await self._request("GET", f"/repos/{repo}/pulls/{number}")
        return {
            "number": d["number"],
            "title": d.get("title", ""),
            "body": d.get("body") or "",
            "url": d.get("html_url", ""),
            "state": d.get("state", ""),
            "merged": bool(d.get("merged")),
            "mergeable": d.get("mergeable"),
            "mergeable_state": d.get("mergeable_state", ""),
            "head_sha": d["head"]["sha"],
            "head_ref": d["head"]["ref"],
            "base_ref": d["base"]["ref"],
        }

    async def pr_diff(self, repo: str, number: int) -> str:
        return await self._request("GET", f"/repos/{repo}/pulls/{number}", expect_text=True, accept="application/vnd.github.diff")

    async def comment(self, repo: str, number: int, body: str) -> str:
        d = await self._request("POST", f"/repos/{repo}/issues/{number}/comments", json={"body": body[:60000]})
        return d.get("html_url", "")

    async def review(self, repo: str, number: int, body: str) -> str:
        d = await self._request("POST", f"/repos/{repo}/pulls/{number}/reviews", json={"body": body[:60000], "event": "COMMENT"})
        return d.get("html_url", "")

    async def merge(self, repo: str, number: int, *, title: str, message: str = "", method: str = "squash") -> str:
        d = await self._request(
            "PUT",
            f"/repos/{repo}/pulls/{number}/merge",
            json={"merge_method": method, "commit_title": title[:250], "commit_message": message[:60000]},
        )
        return d.get("sha", "")

    # --- Checks -----------------------------------------------------------------------------------------------

    async def checks(self, repo: str, sha: str) -> CheckSummary:
        runs = (await self._request("GET", f"/repos/{repo}/commits/{sha}/check-runs", params={"per_page": 100})).get(
            "check_runs", []
        )
        status = await self._request("GET", f"/repos/{repo}/commits/{sha}/status")
        statuses = status.get("statuses", [])
        total = len(runs) + len(statuses)
        if total == 0:
            return CheckSummary(state="none")
        pending = [r["name"] for r in runs if r.get("status") != "completed"] + [
            s["context"] for s in statuses if s.get("state") == "pending"
        ]
        failures: list[dict[str, Any]] = []
        for run in runs:
            if run.get("status") == "completed" and run.get("conclusion") in (
                "failure",
                "timed_out",
                "cancelled",
                "action_required",
            ):
                output = run.get("output") or {}
                annotations: list[dict[str, Any]] = []
                if (output.get("annotations_count") or 0) > 0:
                    try:
                        raw = await self._request(
                            "GET", f"/repos/{repo}/check-runs/{run['id']}/annotations", params={"per_page": 20}
                        )
                        annotations = [
                            {"path": a.get("path"), "line": a.get("start_line"), "message": (a.get("message") or "")[:500]}
                            for a in raw
                        ]
                    except GitHubError:
                        pass
                failures.append(
                    {
                        "name": run["name"],
                        "conclusion": run.get("conclusion"),
                        "title": output.get("title") or "",
                        "summary": (output.get("summary") or output.get("text") or "")[:2000],
                        "annotations": annotations,
                    }
                )
        failures += [
            {"name": s["context"], "conclusion": "failure", "title": s.get("description") or "", "summary": "", "annotations": []}
            for s in statuses
            if s.get("state") in ("failure", "error")
        ]
        if failures:
            return CheckSummary(state="failure", total=total, failures=failures, pending=pending)
        return CheckSummary(state="pending" if pending else "success", total=total, pending=pending)

    # --- Releases ---------------------------------------------------------------------------------------------

    async def create_release(self, repo: str, *, tag: str, name: str, body: str, target: str, draft: bool = True) -> str:
        d = await self._request(
            "POST",
            f"/repos/{repo}/releases",
            json={"tag_name": tag, "name": name, "body": body, "target_commitish": target, "draft": draft},
        )
        return d.get("html_url", "")

"""GitHub client: CI failures come with the job log excerpt that explains them."""

from __future__ import annotations

import httpx

from nova.integrations.github.client import GitHubClient, summarize_log

LOG = "\n".join(
    [
        "2026-10-09T11:15:50.1Z ##[group]Run uv sync",
        "2026-10-09T11:15:51.1Z  + ruff==0.16.10",
        "2026-10-09T11:15:52.1Z (node:1) [DEP0169] DeprecationWarning: url.parse() is deprecated",
        "2026-10-09T11:16:05.3Z \x1b[31mtests/unit/test_readme.py:12:1: I001 Import block is un-sorted\x1b[0m",
        "2026-10-09T11:16:05.3Z Found 1 error.",
        "2026-10-09T11:16:05.4Z ##[error]Process completed with exit code 1.",
    ]
)


def test_log_summary_keeps_the_errors_and_drops_noise():
    out = summarize_log(LOG)
    assert "I001 Import block is un-sorted" in out and "Found 1 error." in out
    assert "\x1b" not in out and "2026-10-09T" not in out and "##[group]" not in out
    assert len(summarize_log("error\n" * 5000, limit=500)) <= 500


async def test_checks_attach_the_job_log_of_failed_github_actions_runs():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/check-runs"):
            return httpx.Response(
                200,
                json={
                    "check_runs": [
                        {
                            "id": 7,
                            "name": "backend",
                            "status": "completed",
                            "conclusion": "failure",
                            "app": {"slug": "github-actions"},
                            "output": {"title": "backend", "summary": "", "annotations_count": 0},
                        },
                        {
                            "id": 8,
                            "name": "Vercel",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"slug": "vercel"},
                            "output": {},
                        },
                    ]
                },
            )
        if path.endswith("/status"):
            return httpx.Response(200, json={"statuses": []})
        if path.endswith("/actions/jobs/7/logs"):
            return httpx.Response(302, headers={"location": "https://logs.example.com/7.txt"})
        if request.url.host == "logs.example.com":
            assert "authorization" not in request.headers  # the token never follows the redirect
            return httpx.Response(200, text=LOG)
        return httpx.Response(404)

    client = GitHubClient("ghp_test", transport=httpx.MockTransport(handler))
    summary = await client.checks("o/r", "abc")
    assert summary.state == "failure" and [f["name"] for f in summary.failures] == ["backend"]
    assert "I001 Import block is un-sorted" in summary.failures[0]["log"]


async def test_unreadable_job_log_degrades_to_an_empty_excerpt():
    client = GitHubClient(
        "ghp_test", transport=httpx.MockTransport(lambda r: httpx.Response(403, json={"message": "Resource not accessible"}))
    )
    assert await client.job_log("o/r", 7) == ""

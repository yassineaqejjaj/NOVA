"""In-memory GitHub and a scripted model for the SDLC Autopilot tests."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from nova.domain.llm import StructuredResult
from nova.domain.outputs import TokenUsage
from nova.domain.sdlc import (
    ChangeSet,
    DesignOutput,
    FileChange,
    Finding,
    PlannedChange,
    PullRequestText,
    ReleaseNotesOutput,
    ReviewOutput,
    SpecOutput,
)
from nova.integrations.github.client import CheckSummary, GitHubError

BASE_FILES = {
    "README.md": "# Demo\nA demo app.\n",
    "package.json": '{"name": "demo", "scripts": {"test": "vitest"}}\n',
    "src/greet.ts": "export function greet(name: string) {\n  return `Hello ${name}`;\n}\n",
    "src/greet.test.ts": "import { greet } from './greet';\ntest('greet', () => expect(greet('a')).toBe('Hello a'));\n",
}


class FakeGitHub:
    """Implements the subset of ``GitHubClient`` used by the SDLC engine."""

    def __init__(self) -> None:
        self.branches: dict[str, dict[str, str]] = {"main": dict(BASE_FILES)}
        self.commits: list[tuple[str, str, list[dict[str, str]]]] = []
        self.prs: dict[int, dict[str, Any]] = {}
        self.comments: list[tuple[int, str]] = []
        self.reviews: list[tuple[int, str]] = []
        self.releases: list[dict[str, Any]] = []
        self.deleted_branches: list[str] = []
        self.check_script: list[CheckSummary] = [CheckSummary(state="success", total=2)]
        self.check_calls = 0
        self.merge_conflict = False
        self.can_push = True
        self.issue_data = {
            "title": "Add farewell",
            "body": "We need a farewell function.",
            "url": "https://github.com/o/r/issues/7",
            "is_pr": False,
        }
        self._sha = 0
        self.shas: dict[str, str] = {}
        self.sha_branch: dict[str, str] = {}

    def _new_sha(self, branch: str) -> str:
        self._sha += 1
        sha = f"{self._sha:040x}"
        self.shas[branch] = sha
        self.sha_branch[sha] = branch
        return sha

    async def aclose(self) -> None:
        return None

    async def viewer(self) -> dict[str, Any]:
        return {"login": "octo", "name": "Octo", "scopes": "repo"}

    async def list_repos(self, limit: int = 50) -> list[dict[str, Any]]:
        return [{"full_name": "o/r", "private": True, "default_branch": "main", "description": "", "can_push": True}]

    async def repo(self, full_name: str) -> dict[str, Any]:
        if full_name == "o/missing":
            raise GitHubError("not_found", "Not found on GitHub", 404)
        return {"full_name": full_name, "default_branch": "main", "private": True, "can_push": self.can_push, "description": ""}

    async def issue(self, repo: str, number: int) -> dict[str, Any]:
        return self.issue_data

    async def branch_sha(self, repo: str, branch: str) -> str:
        if branch not in self.branches:
            raise GitHubError("not_found", "no such branch", 404)
        return self.shas.get(branch) or self._new_sha(branch)

    async def tree(self, repo: str, sha: str) -> tuple[list[dict[str, Any]], bool]:
        files = self.branches[self.sha_branch[sha]]
        return [{"path": p, "size": len(t), "mode": "100644"} for p, t in files.items()], False

    async def file_text(self, repo: str, path: str, ref: str) -> str | None:
        files = self.branches[self.sha_branch.get(ref, ref)]
        return files.get(path)

    async def create_branch(self, repo: str, name: str, sha: str) -> None:
        if name in self.branches:
            raise GitHubError("invalid", "Reference already exists", 422)
        self.branches[name] = dict(self.branches[self.sha_branch[sha]])
        self.shas[name] = sha

    async def delete_branch(self, repo: str, name: str) -> None:
        self.deleted_branches.append(name)

    async def commit_files(
        self, repo: str, branch: str, parent_sha: str, message: str, changes: list[dict[str, str]], modes: Any = None
    ) -> str:
        files = self.branches[branch]
        for change in changes:
            if change["action"] == "delete":
                files.pop(change["path"], None)
            else:
                files[change["path"]] = change["content"]
        self.commits.append((branch, message, changes))
        return self._new_sha(branch)

    async def create_pr(self, repo: str, *, title: str, body: str, head: str, base: str, draft: bool = False) -> dict[str, Any]:
        number = len(self.prs) + 1
        self.prs[number] = {"title": title, "body": body, "head": head, "base": base, "merged": False}
        return {"number": number, "url": f"https://github.com/{repo}/pull/{number}", "head_sha": self.shas[head]}

    async def pr(self, repo: str, number: int) -> dict[str, Any]:
        pr = self.prs.get(number) or {
            "title": "External PR",
            "body": "Fixes things",
            "head": "feature",
            "base": "main",
            "merged": False,
        }
        return {
            "number": number,
            "title": pr["title"],
            "body": pr["body"],
            "url": f"https://github.com/{repo}/pull/{number}",
            "state": "closed" if pr["merged"] else "open",
            "merged": pr["merged"],
            "mergeable": not self.merge_conflict,
            "mergeable_state": "clean",
            "head_sha": self.shas.get(pr["head"], "f" * 40),
            "head_ref": pr["head"],
            "base_ref": pr["base"],
        }

    async def pr_diff(self, repo: str, number: int) -> str:
        return "diff --git a/src/greet.ts b/src/greet.ts\n+export function farewell() {}\n"

    async def comment(self, repo: str, number: int, body: str) -> str:
        self.comments.append((number, body))
        return f"https://github.com/{repo}/pull/{number}#issuecomment-1"

    async def review(self, repo: str, number: int, body: str) -> str:
        self.reviews.append((number, body))
        return f"https://github.com/{repo}/pull/{number}#pullrequestreview-1"

    async def merge(self, repo: str, number: int, *, title: str, message: str = "", method: str = "squash") -> str:
        pr = self.prs[number]
        pr["merged"] = True
        self.branches["main"] = dict(self.branches[pr["head"]])
        return self._new_sha("main")

    async def checks(self, repo: str, sha: str) -> CheckSummary:
        result = self.check_script[min(self.check_calls, len(self.check_script) - 1)]
        self.check_calls += 1
        return result

    async def create_release(self, repo: str, *, tag: str, name: str, body: str, target: str, draft: bool = True) -> str:
        self.releases.append({"tag": tag, "name": name, "body": body, "target": target, "draft": draft})
        return f"https://github.com/{repo}/releases/tag/{tag}"


class SdlcLLM:
    """Scripted model: one handler per output schema (override ``handlers`` in a test to change behavior)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.change_queue: list[ChangeSet] = []
        self.review_queue: list[ReviewOutput] = []
        self.handlers: dict[str, Any] = {
            "SpecOutput": lambda: SpecOutput(
                summary="Add a farewell function",
                user_stories=["As a user I want to say goodbye"],
                acceptance_criteria=["farewell('a') returns 'Bye a'"],
            ),
            "DesignOutput": lambda: DesignOutput(
                approach="Add farewell next to greet",
                files_to_read=["src/greet.ts", "src/not-there.ts"],
                changes=[PlannedChange(path="src/greet.ts", action="modify", reason="add farewell")],
                test_plan=["unit test"],
            ),
            "PullRequestText": lambda: PullRequestText(title="feat: add farewell", body="## Summary\nAdds farewell."),
            "ReleaseNotesOutput": lambda: ReleaseNotesOutput(version="v1.1.0", title="Farewell", notes="- Adds farewell()"),
        }

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, messages: Any, **_: Any) -> Any:
        raise NotImplementedError

    async def structured_output(self, messages: list[Any], schema: type[BaseModel], **_: Any) -> StructuredResult:
        name = schema.__name__
        self.calls.append((name, messages[-1].content))
        if name == "ChangeSet":
            value = self.change_queue.pop(0) if self.change_queue else self._default_change(messages)
        elif name == "ReviewOutput":
            value = self.review_queue.pop(0) if self.review_queue else ReviewOutput(verdict="approve", summary="Looks good.")
        else:
            value = self.handlers[name]()
        return StructuredResult(
            value=value, model="fake-model", usage=TokenUsage(input_tokens=100, output_tokens=50, model_calls=1)
        )

    @staticmethod
    def _default_change(messages: list[Any]) -> ChangeSet:
        text = messages[0].content
        if "STAGE: TESTS" in text:
            return ChangeSet(
                summary="Test farewell",
                commit_message="test: cover farewell",
                changes=[
                    FileChange(
                        path="src/farewell.test.ts",
                        action="create",
                        content="import { farewell } from './greet';\ntest('farewell', () => expect(farewell('a')).toBe('Bye a'));\n",
                    )
                ],
            )
        if "STAGE: FIX" in text:
            return ChangeSet(
                summary="Fix the reported problem",
                commit_message="fix: address feedback",
                changes=[
                    FileChange(
                        path="src/greet.ts",
                        action="modify",
                        content="export function greet(name: string) {\n  return `Hello ${name}`;\n}\nexport function farewell(name: string) {\n  return `Bye ${name}`;\n}\n// fixed\n",
                    )
                ],
            )
        return ChangeSet(
            summary="Add farewell",
            commit_message="feat: add farewell",
            changes=[
                FileChange(
                    path="src/greet.ts",
                    action="modify",
                    content="export function greet(name: string) {\n  return `Hello ${name}`;\n}\nexport function farewell(name: string) {\n  return `Bye ${name}`;\n}\n",
                )
            ],
        )


SDLC_SCHEMAS = {"SpecOutput", "DesignOutput", "ChangeSet", "PullRequestText", "ReviewOutput", "ReleaseNotesOutput"}


def sdlc_response(name: str, system_prompt: str) -> dict[str, Any]:
    """Default answer of the scripted model for one SDLC schema (also served by the E2E fake inference server)."""
    model = SdlcLLM()
    if name == "ChangeSet":
        return model._default_change([type("M", (), {"content": system_prompt})()]).model_dump()
    if name == "ReviewOutput":
        return ReviewOutput(verdict="approve", summary="Looks good.").model_dump()
    return model.handlers[name]().model_dump()


__all__ = ["SDLC_SCHEMAS", "FakeGitHub", "Finding", "SdlcLLM", "sdlc_response"]

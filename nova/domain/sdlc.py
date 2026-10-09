"""SDLC Autopilot domain: stages, structured model outputs and the safety rules applied to generated changes."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class RunKind(StrEnum):
    feature = "feature"
    bugfix = "bugfix"
    refactor = "refactor"
    review = "review"  # review an existing pull request


class Autonomy(StrEnum):
    guided = "guided"  # approve the plan, then the merge
    autopilot = "autopilot"  # only the merge (unless auto_merge)


class RunStatus(StrEnum):
    queued = "queued"
    running = "running"
    waiting_user = "waiting_user"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class StageStatus(StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    skipped = "skipped"
    failed = "failed"
    waiting = "waiting"


STAGES = ["spec", "design", "implement", "tests", "pull_request", "review", "ci", "merge", "release"]
REVIEW_STAGES = ["review"]
STAGE_ORDER = {kind: (REVIEW_STAGES if kind == RunKind.review else STAGES) for kind in RunKind}

MAX_FIX_ROUNDS = 2


# --- Structured outputs of the model -------------------------------------------------------------------------


class SpecOutput(BaseModel):
    summary: str = Field(description="What will be built or fixed and why, in 2-4 sentences")
    root_cause: str = Field(default="", description="Bug fixes only: the most likely root cause, with evidence")
    user_stories: list[str] = Field(default_factory=list, description="'As a … I want … so that …'")
    acceptance_criteria: list[str] = Field(description="Testable, one behavior each")
    out_of_scope: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class PlannedChange(BaseModel):
    path: str
    action: Literal["create", "modify", "delete"] = "modify"
    reason: str = ""


class DesignOutput(BaseModel):
    approach: str = Field(description="The technical approach and why, 3-8 sentences")
    files_to_read: list[str] = Field(
        default_factory=list,
        description="Existing repository files (exact paths from the tree) needed to implement safely, at most 12",
    )
    changes: list[PlannedChange] = Field(default_factory=list, description="Planned file changes")
    test_plan: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str
    action: Literal["create", "modify", "delete"] = "modify"
    content: str = Field(default="", description="The COMPLETE new content of the file (empty for delete)")


class ChangeSet(BaseModel):
    summary: str = Field(description="What changed, in 1-3 sentences")
    commit_message: str = Field(description="Conventional commit message, subject line <= 72 chars")
    changes: list[FileChange]


class PullRequestText(BaseModel):
    title: str = Field(max_length=200)
    body: str


class Finding(BaseModel):
    severity: Literal["blocker", "major", "minor", "nit"]
    path: str = ""
    line: int | None = None
    message: str
    suggestion: str = ""


class ReviewOutput(BaseModel):
    verdict: Literal["approve", "request_changes"]
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class ReleaseNotesOutput(BaseModel):
    version: str = Field(description="Suggested semantic version tag, e.g. v1.4.0 (or empty when unknown)")
    title: str
    notes: str = Field(description="Markdown release notes: highlights, fixes, breaking changes, upgrade notes")


# --- Safety rules for generated changes ------------------------------------------------------------------------

MAX_FILES = 25
MAX_FILE_BYTES = 120_000
MAX_TOTAL_BYTES = 400_000
READ_FILE_BYTES = 40_000
READ_TOTAL_BYTES = 220_000

_BLOCKED_PREFIXES = (".git/", ".github/workflows/", ".github/actions/", "node_modules/", ".venv/")
_BLOCKED_NAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "poetry.lock",
    "cargo.lock",
    "go.sum",
    "gemfile.lock",
    "composer.lock",
    "id_rsa",
    "id_ed25519",
}
_BLOCKED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".keystore")
_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]
_BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".mp4", ".woff", ".woff2", ".ttf")


class UnsafeChange(Exception):
    pass


def normalize_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    parts = cleaned.split("/")
    if not cleaned or cleaned.startswith("/") or ".." in parts or "" in parts or "\x00" in cleaned:
        raise UnsafeChange(f"Invalid path: {path!r}")
    return cleaned


def check_path_allowed(path: str) -> None:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if any(lowered.startswith(prefix) for prefix in _BLOCKED_PREFIXES) or "/node_modules/" in f"/{lowered}":
        raise UnsafeChange(f"Changes to {path} are not allowed (protected location)")
    if name in _BLOCKED_NAMES or name.startswith(".env") or lowered.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeChange(f"Changes to {path} are not allowed (secrets or lock file)")
    if lowered.endswith(_BINARY_SUFFIXES):
        raise UnsafeChange(f"{path} is a binary file: NOVA only writes text")


def validate_changeset(changeset: ChangeSet, existing: dict[str, str], tree: set[str]) -> list[FileChange]:
    """Return the safe, normalized changes or raise ``UnsafeChange`` (the message is fed back to the model).

    ``tree``: every path of the repository at the base; ``existing``: the text of the files NOVA read, used to refuse a
    rewrite that silently discards most of a file.
    """
    if not changeset.changes:
        raise UnsafeChange("The change set is empty")
    if len(changeset.changes) > MAX_FILES:
        raise UnsafeChange(f"Too many files ({len(changeset.changes)} > {MAX_FILES}): split the work")
    seen: set[str] = set()
    total = 0
    safe: list[FileChange] = []
    for change in changeset.changes:
        path = normalize_path(change.path)
        if path in seen:
            raise UnsafeChange(f"{path} appears twice in the change set")
        seen.add(path)
        check_path_allowed(path)
        if change.action == "delete":
            if path not in tree:
                raise UnsafeChange(f"Cannot delete {path}: it does not exist")
            safe.append(FileChange(path=path, action="delete"))
            continue
        size = len(change.content.encode())
        if size > MAX_FILE_BYTES:
            raise UnsafeChange(f"{path} is too large ({size} bytes): split it")
        total += size
        if total > MAX_TOTAL_BYTES:
            raise UnsafeChange("The change set is too large: do less in one run")
        if not change.content.strip():
            raise UnsafeChange(f"{path} has no content")
        for pattern in _SECRET_PATTERNS:
            if pattern.search(change.content):
                raise UnsafeChange(f"{path} contains what looks like a secret: never write credentials")
        previous = existing.get(path)
        if path in tree and previous is None:
            raise UnsafeChange(
                f"{path} exists but was not read: NOVA cannot rewrite a file it has not seen. "
                "Only modify files from the provided file contents; create new files elsewhere"
            )
        if previous is not None and len(previous) > 1500 and len(change.content) < len(previous) * 0.3:
            raise UnsafeChange(
                f"{path}: the new content is much shorter than the existing file ({len(change.content)} vs {len(previous)} "
                "characters). Return the COMPLETE file, not an excerpt"
            )
        safe.append(FileChange(path=path, action="modify" if path in tree else "create", content=change.content))
    return safe


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].strip("-") or "change"

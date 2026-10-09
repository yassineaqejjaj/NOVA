"""SDLC Autopilot: runs one change through spec → design → implement → tests → PR → review → CI → merge → release.

A run is advanced one stage (or one CI poll) at a time by ``advance`` (Celery task ``nova.sdlc_advance``). Between
stages nothing is held in memory: the run row is the state, so a crashed worker loses at most one stage.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select, update

from nova.config import get_settings
from nova.domain.llm import LLMError, LLMProvider
from nova.domain.outputs import TokenUsage
from nova.domain.sdlc import (
    MAX_FIX_ROUNDS,
    READ_FILE_BYTES,
    READ_TOTAL_BYTES,
    STAGE_ORDER,
    ChangeSet,
    DesignOutput,
    PullRequestText,
    ReleaseNotesOutput,
    ReviewOutput,
    RunKind,
    RunStatus,
    SpecOutput,
    StageStatus,
    UnsafeChange,
    normalize_path,
    slugify,
    validate_changeset,
)
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import SdlcRun
from nova.integrations.github.client import GitHubClient, GitHubError, parse_github_ref, parse_repo
from nova.services import github_accounts, providers
from nova.services import sdlc_prompts as prompts
from nova.services.audit import audit

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
CI_POLL_SECONDS = 30.0
CI_MAX_POLLS = 60
CI_NO_CHECKS_POLLS = 3
MAX_LOG = 300
MAX_DIFF_CHARS = 100_000
MAX_TREE_LINES = 1500
_NOISE = re.compile(
    r"(^|/)(node_modules|dist|build|\.next|__pycache__|\.venv|vendor|coverage|\.git)/|"
    r"\.(png|jpe?g|gif|webp|ico|pdf|zip|gz|mp4|woff2?|ttf|lock|map|min\.js)$|(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|uv\.lock)$",
    re.IGNORECASE,
)
_MANIFESTS = ("package.json", "pyproject.toml", "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "Gemfile", "composer.json")
_CONVENTIONS = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md")
_TEST_PATH = re.compile(
    r"(^|/)(tests?|__tests__|spec|e2e)/|[._-](test|spec)\.[a-z]+$|(^|/)test_[^/]+\.py$|_test\.(go|py)$", re.IGNORECASE
)


def _n(count: int, noun: str, plural: str | None = None) -> str:
    return f"{count} {noun if count == 1 else (plural or noun + 's')}"


class RunError(Exception):
    """A user-visible failure of a stage (the message is shown as is)."""


class ConflictError(Exception):
    """The requested action does not apply to the run in its current state."""


# --- Result of a stage --------------------------------------------------------------------------------------------


@dataclass
class StageResult:
    status: str = "done"  # done | skipped | repeat | gate
    summary: str = ""
    output: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)  # merged into run.context
    fields: dict[str, Any] = field(default_factory=dict)  # run columns
    delay: float = 0.0
    gate: str | None = None
    logs: list[str] = field(default_factory=list)


@dataclass
class Ctx:
    run: SdlcRun
    gh: GitHubClient
    llm: LLMProvider
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    logs: list[str] = field(default_factory=list)

    @property
    def c(self) -> dict[str, Any]:
        return self.run.context or {}

    def log(self, message: str) -> None:
        self.logs.append(message)

    async def ask(self, messages: list[Any], schema: type, *, max_tokens: int | None = None) -> Any:
        try:
            result = await self.llm.structured_output(messages, schema, max_tokens=max_tokens)
        except LLMError as exc:
            raise RunError(f"The model could not complete this step: {exc}") from exc
        self.usage = self.usage.add(result.usage)
        self.model = result.model
        return result.value


# --- Repository helpers -----------------------------------------------------------------------------------------


@dataclass
class Snapshot:
    sha: str
    entries: list[dict[str, Any]]
    truncated: bool

    @property
    def paths(self) -> set[str]:
        return {e["path"] for e in self.entries}

    @property
    def modes(self) -> dict[str, str]:
        return {e["path"]: e["mode"] for e in self.entries}


async def snapshot(ctx: Ctx, ref: str) -> Snapshot:
    sha = await ctx.gh.branch_sha(ctx.run.repo, ref)
    entries, truncated = await ctx.gh.tree(ctx.run.repo, sha)
    return Snapshot(sha, entries, truncated)


def tree_listing(snap: Snapshot, limit: int = MAX_TREE_LINES) -> str:
    paths = [e["path"] for e in snap.entries if not _NOISE.search(e["path"])]
    if len(paths) > limit:
        paths = sorted(paths, key=lambda p: (p.count("/"), p))[:limit]
    return "\n".join(sorted(paths)) + ("\n(tree truncated)" if snap.truncated or len(snap.entries) > limit else "")


async def overview(ctx: Ctx, snap: Snapshot) -> str:
    repo = ctx.run.repo
    parts = [f"REPOSITORY: {repo} (base branch {ctx.run.base_branch})", "FILE TREE:\n" + tree_listing(snap)]
    known = snap.paths
    for name in ("README.md", "readme.md", *_MANIFESTS, *_CONVENTIONS):
        if name in known:
            text = await ctx.gh.file_text(repo, name, snap.sha)
            if text:
                limit = 5000 if name.lower() == "readme.md" else 3500
                parts.append(prompts.file_block(name, text[:limit] + ("\n…(truncated)" if len(text) > limit else "")))
    return "\n\n".join(parts)


async def read_files(ctx: Ctx, snap: Snapshot, paths: list[str], ref: str | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    total = 0
    for raw in paths:
        try:
            path = normalize_path(raw)
        except UnsafeChange:
            continue
        if path in out or path not in snap.paths or _NOISE.search(path):
            continue
        text = await ctx.gh.file_text(ctx.run.repo, path, ref or snap.sha)
        if text is None:
            continue
        if len(text) > READ_FILE_BYTES:
            ctx.log(f"{path} is too large to be rewritten safely ({len(text)} characters): skipped")
            continue
        total += len(text)
        if total > READ_TOTAL_BYTES:
            break
        out[path] = text
    return out


async def ask_changeset(
    ctx: Ctx,
    build: Any,
    snap: Snapshot,
    read: dict[str, str],
    *,
    allow_empty: bool = False,
    only_tests: bool = False,
) -> tuple[ChangeSet | None, list[Any]]:
    """Ask for a change set, validate it, and feed rejections back to the model once."""
    feedback = ""
    for attempt in range(2):
        changeset: ChangeSet = await ctx.ask(build(feedback), ChangeSet, max_tokens=16000)
        if allow_empty and not changeset.changes:
            return changeset, []
        try:
            safe = validate_changeset(changeset, read, snap.paths)
            if only_tests:
                offenders = [c.path for c in safe if not _TEST_PATH.search(c.path)]
                if offenders:
                    raise UnsafeChange(f"Only test files may be changed in this stage: {', '.join(offenders[:5])}")
            return changeset, safe
        except UnsafeChange as exc:
            feedback = str(exc)
            ctx.log(
                f"Change set rejected ({exc}); asking the model to correct it" if attempt == 0 else f"Change set rejected: {exc}"
            )
    raise RunError(f"NOVA could not produce a safe change set: {feedback}")


async def commit(ctx: Ctx, branch: str, message: str, safe: list[Any], snap: Snapshot) -> str:
    parent = await ctx.gh.branch_sha(ctx.run.repo, branch)
    return await ctx.gh.commit_files(
        ctx.run.repo,
        branch,
        parent,
        message.strip().splitlines()[0][:200] if message.strip() else "chore: NOVA change",
        [c.model_dump() for c in safe],
        snap.modes,
    )


def _issue_text(run: SdlcRun) -> str:
    issue = (run.context or {}).get("issue") or {}
    return f"{issue.get('title', '')}\n\n{issue.get('body', '')}".strip() if issue else ""


# --- Stages -------------------------------------------------------------------------------------------------------


async def stage_spec(ctx: Ctx) -> StageResult:
    run = ctx.run
    snap = await snapshot(ctx, run.base_branch)
    ov = await overview(ctx, snap)
    spec: SpecOutput = await ctx.ask(prompts.spec_messages(run.kind, run.title, run.goal, _issue_text(run), ov), SpecOutput)
    return StageResult(
        summary=spec.summary,
        output=spec.model_dump(),
        context={"spec": spec.model_dump()},
        logs=[f"Specification written: {_n(len(spec.acceptance_criteria), 'acceptance criterion', 'acceptance criteria')}"],
    )


async def stage_design(ctx: Ctx) -> StageResult:
    run = ctx.run
    snap = await snapshot(ctx, run.base_branch)
    ov = await overview(ctx, snap)
    design: DesignOutput = await ctx.ask(prompts.design_messages(run.kind, run.title, ctx.c.get("spec", {}), ov), DesignOutput)
    known = snap.paths
    design.files_to_read = [p for p in dict.fromkeys(design.files_to_read) if p in known][:12]
    result = StageResult(
        summary=design.approach[:300],
        output=design.model_dump(),
        context={"design": design.model_dump()},
        logs=[f"Design ready: {_n(len(design.changes), 'planned change')}, {_n(len(design.files_to_read), 'file')} to read"],
    )
    if run.autonomy == "guided":
        result.gate = "plan"
        result.logs.append("Waiting for your approval of the plan (guided mode)")
    return result


def _branch_name(run: SdlcRun) -> str:
    return f"nova/{run.kind}-{slugify(run.title, 32)}-{str(run.id)[:6]}"


async def stage_implement(ctx: Ctx) -> StageResult:
    run = ctx.run
    snap = await snapshot(ctx, run.base_branch)
    ov = await overview(ctx, snap)
    design = ctx.c.get("design", {})
    wanted = list(design.get("files_to_read", [])) + [c["path"] for c in design.get("changes", []) if c.get("action") != "create"]
    read = await read_files(ctx, snap, wanted)
    branch = run.branch or _branch_name(run)
    changeset, safe = await ask_changeset(
        ctx,
        lambda fb: prompts.implement_messages(
            run.kind, run.title, ctx.c.get("spec", {}), design, ctx.c.get("user_notes", ""), ov, read, fb
        ),
        snap,
        read,
    )
    assert changeset is not None
    try:
        await ctx.gh.create_branch(run.repo, branch, snap.sha)
    except GitHubError as exc:
        if exc.code != "invalid":  # "Reference already exists": a retry reuses its own branch
            raise
    head = await commit(ctx, branch, changeset.commit_message, safe, snap)
    changes = [{"path": c.path, "action": c.action} for c in safe]
    return StageResult(
        summary=changeset.summary,
        output={"branch": branch, "commit": head, "changes": changes, "commit_message": changeset.commit_message},
        context={"changes": changes, "commit_message": changeset.commit_message},
        fields={"branch": branch, "head_sha": head},
        logs=[f"Committed {_n(len(safe), 'file')} on {branch}"],
    )


async def stage_tests(ctx: Ctx) -> StageResult:
    run = ctx.run
    snap = await snapshot(ctx, run.branch)
    test_paths = [p for p in sorted(snap.paths) if _TEST_PATH.search(p) and not _NOISE.search(p)]
    changed = await read_files(ctx, snap, [c["path"] for c in ctx.c.get("changes", []) if c["action"] != "delete"])
    stems = {re.sub(r"\W", "", p.rsplit("/", 1)[-1].rsplit(".", 1)[0]).lower() for p in changed}
    near = [p for p in test_paths if any(s and s in re.sub(r"\W", "", p.lower()) for s in stems)]
    samples = await read_files(ctx, snap, (near + test_paths)[:2])
    read = {**samples, **changed}
    changeset, safe = await ask_changeset(
        ctx,
        lambda fb: prompts.tests_messages(run.kind, ctx.c.get("spec", {}), changed, samples, test_paths, fb),
        snap,
        read,
        allow_empty=True,
        only_tests=True,
    )
    assert changeset is not None
    if not safe:
        return StageResult(status="skipped", summary=changeset.summary or "No test added", logs=["No tests added"])
    head = await commit(ctx, run.branch, changeset.commit_message or "test: add tests", safe, snap)
    tests = [{"path": c.path, "action": c.action} for c in safe]
    return StageResult(
        summary=changeset.summary,
        output={"tests": tests, "commit": head},
        context={"tests": tests},
        fields={"head_sha": head},
        logs=[f"Committed {_n(len(safe), 'test file')}"],
    )


async def stage_pull_request(ctx: Ctx) -> StageResult:
    run = ctx.run
    text: PullRequestText = await ctx.ask(
        prompts.pr_messages(
            run.kind, run.title, ctx.c.get("spec", {}), ctx.c.get("design", {}), ctx.c.get("changes", []), ctx.c.get("tests", [])
        ),
        PullRequestText,
    )
    body = text.body.strip()
    issue_ref = parse_github_ref(run.issue_url, "issues") if run.issue_url else None
    if issue_ref and issue_ref[0] == run.repo and run.kind in ("feature", "bugfix"):
        body += f"\n\nCloses #{issue_ref[1]}"
    web = get_settings().public_url.rstrip("/")
    body += f"\n\n---\n_Opened by [NOVA]({web}/engineering/{run.id}) (SDLC Autopilot)._"
    pr = await ctx.gh.create_pr(run.repo, title=text.title, body=body, head=run.branch, base=run.base_branch)
    return StageResult(
        summary=f"Pull request #{pr['number']} opened",
        output={"number": pr["number"], "url": pr["url"], "title": text.title},
        context={"pr_title": text.title, "pr_body": body},
        fields={"pr_number": pr["number"], "pr_url": pr["url"], "head_sha": pr["head_sha"]},
        logs=[f"Opened pull request #{pr['number']}"],
    )


def _blocking(review: ReviewOutput) -> list[Any]:
    return [f for f in review.findings if f.severity in ("blocker", "major")]


def _format_review(review: ReviewOutput) -> str:
    lines = [
        f"**NOVA review — {'changes requested' if review.verdict == 'request_changes' else 'approved'}**",
        "",
        review.summary,
    ]
    for f in review.findings:
        where = f" `{f.path}{':' + str(f.line) if f.line else ''}`" if f.path else ""
        lines.append(f"- **{f.severity}**{where}: {f.message}" + (f"\n  - Suggestion: {f.suggestion}" if f.suggestion else ""))
    return "\n".join(lines)


async def _review_once(ctx: Ctx, repo: str, number: int, title: str, body: str, spec: dict | None) -> tuple[ReviewOutput, str]:
    diff = await ctx.gh.pr_diff(repo, number)
    truncated = len(diff) > MAX_DIFF_CHARS
    review: ReviewOutput = await ctx.ask(
        prompts.review_messages(ctx.run.title, title, body, diff[:MAX_DIFF_CHARS], truncated, spec), ReviewOutput
    )
    return review, diff


_PATH_TOKEN = re.compile(r"[\w@.+/-]+\.[A-Za-z0-9]{1,8}")


async def _fix(ctx: Ctx, reason: str, details: str, finding_paths: list[str]) -> str:
    run = ctx.run
    snap = await snapshot(ctx, run.branch)
    changed_paths = [c["path"] for c in ctx.c.get("changes", []) + ctx.c.get("tests", []) if c["action"] != "delete"]
    # Files named in the failure output (a linter, a stack trace) are read too, when they exist on the branch
    mentioned = [m.lstrip("./") for m in _PATH_TOKEN.findall(details) if m.lstrip("./") in snap.paths]
    read = await read_files(ctx, snap, list(dict.fromkeys([*finding_paths, *mentioned, *changed_paths])))
    changeset, safe = await ask_changeset(
        ctx,
        lambda fb: prompts.fix_messages(reason, details, ctx.c.get("spec", {}), read, tree_listing(snap, 300), fb),
        snap,
        read,
    )
    assert changeset is not None
    head = await commit(ctx, run.branch, changeset.commit_message or f"fix: {reason}", safe, snap)
    ctx.log(f"Fix committed ({_n(len(safe), 'file')}): {changeset.summary[:160]}")
    return head


async def stage_review(ctx: Ctx) -> StageResult:
    run = ctx.run
    standalone = run.kind == RunKind.review
    number = run.pr_number
    assert number is not None
    pr = await ctx.gh.pr(run.repo, number) if standalone else None
    title = pr["title"] if pr else ctx.c.get("pr_title", run.title)
    body = pr["body"] if pr else ctx.c.get("pr_body", "")
    spec = None if standalone else ctx.c.get("spec")
    rounds: list[dict[str, Any]] = []
    head = run.head_sha
    review, _ = await _review_once(ctx, run.repo, number, title, body, spec)
    for round_no in range(1 + (0 if standalone else MAX_FIX_ROUNDS)):
        rounds.append(
            {"verdict": review.verdict, "summary": review.summary, "findings": [f.model_dump() for f in review.findings]}
        )
        blocking = _blocking(review)
        if standalone or not blocking or round_no >= MAX_FIX_ROUNDS:
            break
        details = "\n".join(
            f"- [{f.severity}] {f.path}{':' + str(f.line) if f.line else ''}: {f.message} {f.suggestion}" for f in blocking
        )
        ctx.log(f"Review found {len(blocking)} blocking findings: fixing (round {round_no + 1}/{MAX_FIX_ROUNDS})")
        head = await _fix(ctx, "code review findings", details, [f.path for f in blocking if f.path])
        review, _ = await _review_once(ctx, run.repo, number, title, body, spec)
    final_blocking = _blocking(review)
    posted = ""
    if not standalone or ctx.c.get("post_review"):
        try:
            posted = await (
                ctx.gh.review(run.repo, number, _format_review(review))
                if standalone
                else ctx.gh.comment(run.repo, number, _format_review(review))
            )
        except GitHubError as exc:
            ctx.log(f"The review could not be posted on GitHub: {exc.message}")
    return StageResult(
        summary=review.summary,
        output={
            "verdict": review.verdict,
            "findings": [f.model_dump() for f in review.findings],
            "rounds": rounds,
            "comment_url": posted,
        },
        context={"review": {"blocking": len(final_blocking), "verdict": review.verdict, "summary": review.summary}},
        fields={"head_sha": head} if head != run.head_sha else {},
        logs=[f"Review: {review.verdict}, {len(review.findings)} findings ({len(final_blocking)} blocking)"],
    )


async def stage_ci(ctx: Ctx) -> StageResult:
    run = ctx.run
    polls = int(ctx.c.get("ci_polls", 0)) + 1
    fix_rounds = int(ctx.c.get("ci_fix_rounds", 0))
    sha = run.head_sha
    summary = await ctx.gh.checks(run.repo, sha)
    seen = bool(ctx.c.get("ci_seen")) or summary.total > 0
    state = {"ci_polls": polls, "ci_seen": seen}
    if summary.state == "success":
        return StageResult(
            summary=f"All {summary.total} checks passed",
            output={"state": "success", "checks": summary.total, "fix_rounds": fix_rounds},
            context={"ci_polls": 0, "ci": "success", "ci_seen": True},
            logs=[f"CI green ({summary.total} checks)"],
        )
    if summary.state == "none":
        if not seen and polls >= CI_NO_CHECKS_POLLS:
            return StageResult(
                status="skipped",
                summary="No CI checks configured on this repository",
                output={"state": "none"},
                context={"ci_polls": 0, "ci": "none"},
            )
        if polls >= CI_MAX_POLLS:
            raise RunError("CI did not report on the latest commit in time. Retry once it completes.")
        return StageResult(status="repeat", delay=CI_POLL_SECONDS, context=state, summary="Waiting for CI to start…")
    if summary.state == "pending":
        if polls >= CI_MAX_POLLS:
            raise RunError("CI did not finish in time. Retry once it completes.")
        return StageResult(
            status="repeat", delay=CI_POLL_SECONDS, context=state, summary=f"CI running: {', '.join(summary.pending[:3])}"
        )
    # failure
    if fix_rounds >= MAX_FIX_ROUNDS:
        names = ", ".join(f["name"] for f in summary.failures)
        raise RunError(f"CI still failing after {MAX_FIX_ROUNDS} automatic fixes ({names}). Open the pull request to take over.")
    details = "\n\n".join(
        f"CHECK {f['name']} ({f['conclusion']}): {f['title']}\n{f['summary']}\n"
        + "\n".join(f"- {a['path']}:{a['line']}: {a['message']}" for a in f["annotations"])
        + (
            f"\nJOB LOG (excerpt):\n{f['log']}"
            if f.get("log")
            else "\n(the job log is not readable: the token may lack the Actions read permission)"
        )
        for f in summary.failures
    )
    ctx.log(f"CI failed ({', '.join(f['name'] for f in summary.failures)}): fixing (round {fix_rounds + 1}/{MAX_FIX_ROUNDS})")
    paths = [a["path"] for f in summary.failures for a in f["annotations"] if a.get("path")]
    head = await _fix(ctx, "failing CI checks", details, paths)
    return StageResult(
        status="repeat",
        delay=CI_POLL_SECONDS,
        summary=f"CI failed: pushed fix {fix_rounds + 1}",
        context={"ci_polls": 0, "ci_fix_rounds": fix_rounds + 1, "ci_seen": True},
        fields={"head_sha": head},
    )


async def stage_merge(ctx: Ctx) -> StageResult:
    run = ctx.run
    number = run.pr_number
    assert number is not None
    pr = await ctx.gh.pr(run.repo, number)
    if pr["merged"]:
        return StageResult(
            summary="Already merged", output={"merge_sha": run.merge_sha}, logs=["The pull request was already merged"]
        )
    if pr["state"] == "closed":
        raise RunError("The pull request was closed without being merged.")
    clean = ctx.c.get("review", {}).get("blocking", 0) == 0 and ctx.c.get("ci") in ("success", "none")
    if not ((run.auto_merge and clean) or ctx.c.get("merge_approved")):
        reason = "auto-merge is off" if not run.auto_merge else "blocking findings or CI are not clean"
        return StageResult(
            status="gate",
            gate="merge",
            summary=f"Waiting for your approval to merge ({reason})",
            logs=["Waiting for merge approval"],
        )
    if pr["mergeable"] is False:
        raise RunError("The pull request has conflicts with the base branch. Resolve them on GitHub, then retry.")
    if pr["mergeable"] is None and int(ctx.c.get("merge_polls", 0)) < 4:
        return StageResult(
            status="repeat",
            delay=5.0,
            context={"merge_polls": int(ctx.c.get("merge_polls", 0)) + 1},
            summary="GitHub is computing mergeability…",
        )
    try:
        sha = await ctx.gh.merge(run.repo, number, title=f"{ctx.c.get('pr_title', run.title)} (#{number})")
    except GitHubError as exc:
        if exc.code in ("conflict", "forbidden", "invalid"):
            raise RunError(
                f"GitHub refused the merge: {exc.message}. Merge it from GitHub (branch protection?), then retry to continue."
            ) from exc
        raise
    try:
        if run.branch.startswith("nova/"):
            await ctx.gh.delete_branch(run.repo, run.branch)
    except GitHubError:
        pass
    return StageResult(
        summary=f"Merged into {run.base_branch}",
        output={"merge_sha": sha},
        fields={"merge_sha": sha},
        context={"merge_polls": 0},
        logs=[f"Merged pull request #{number}"],
    )


async def stage_release(ctx: Ctx) -> StageResult:
    run = ctx.run
    notes: ReleaseNotesOutput = await ctx.ask(
        prompts.release_messages(
            run.title, ctx.c.get("pr_title", run.title), ctx.c.get("pr_body", ""), ctx.c.get("review", {}).get("summary", "")
        ),
        ReleaseNotesOutput,
    )
    return StageResult(
        summary=f"Release notes ready ({notes.version or 'no version suggested'})",
        output=notes.model_dump(),
        context={"release": notes.model_dump()},
    )


HANDLERS = {
    "spec": stage_spec,
    "design": stage_design,
    "implement": stage_implement,
    "tests": stage_tests,
    "pull_request": stage_pull_request,
    "review": stage_review,
    "ci": stage_ci,
    "merge": stage_merge,
    "release": stage_release,
}


# --- Run lifecycle ------------------------------------------------------------------------------------------------


def _stage_entry(key: str) -> dict[str, Any]:
    return {"key": key, "status": StageStatus.pending.value, "summary": "", "output": {}, "started_at": None, "finished_at": None}


def _now() -> str:
    return utcnow().isoformat()


def view(run: SdlcRun, *, detail: bool = True, forge: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(run.id),
        "kind": run.kind,
        "title": run.title,
        "goal": run.goal,
        "repo": run.repo,
        "base_branch": run.base_branch,
        "branch": run.branch,
        "autonomy": run.autonomy,
        "auto_merge": run.auto_merge,
        "has_deploy_hook": bool(run.deploy_hook_ciphertext),
        "status": run.status,
        "stage": run.stage,
        "gate": run.gate,
        "issue_url": run.issue_url,
        "pr_number": run.pr_number,
        "pr_url": run.pr_url,
        "merge_sha": run.merge_sha,
        "release_url": run.release_url,
        "model": run.model,
        "usage": run.usage or {},
        "error": run.error,
        "created_at": aware(run.created_at).isoformat() if run.created_at else None,
        "updated_at": aware(run.updated_at).isoformat() if run.updated_at else None,
        "finished_at": aware(run.finished_at).isoformat() if run.finished_at else None,
        "stages": [{k: v for k, v in s.items() if detail or k != "output"} for s in (run.stages or [])],
    }
    from nova.services.sdlc_metrics import run_evaluation

    data["evaluation"] = run_evaluation(run)
    data["forge"] = forge
    if detail:
        data["log"] = run.log or []
        data["release"] = (run.context or {}).get("release")
    return data


async def create_run(
    session: Any,
    user_id: str,
    *,
    kind: str,
    title: str,
    goal: str,
    repo: str,
    base_branch: str | None,
    autonomy: str,
    auto_merge: bool,
    deploy_hook: str | None,
    issue_url: str,
    pr_url: str,
    post_review: bool,
    project_id: uuid.UUID | None,
) -> SdlcRun:
    kind_enum = RunKind(kind)
    token = await github_accounts.token_for(user_id)
    if not token:
        raise GitHubError("unauthorized", "Connect GitHub in Settings first.")
    gh = github_accounts.make_client(token)
    context: dict[str, Any] = {}
    pr_number: int | None = None
    try:
        if kind_enum == RunKind.review:
            ref = parse_github_ref(pr_url, "pull")
            if ref is None:
                raise RunError("Enter a pull request URL (https://github.com/owner/repo/pull/123).")
            repo, pr_number = ref
            context["post_review"] = post_review
        else:
            parsed = parse_repo(repo)
            if parsed is None:
                raise RunError("Choose a repository (owner/name).")
            repo = parsed
        info = await gh.repo(repo)
        if kind_enum != RunKind.review and not info["can_push"]:
            raise GitHubError("forbidden", "Your GitHub token cannot push to this repository (write access required).")
        if issue_url:
            ref = parse_github_ref(issue_url, "issues")
            if ref is None:
                raise RunError("The issue must be a GitHub issue URL.")
            issue = await gh.issue(*ref)
            context["issue"] = {"title": issue["title"], "body": issue["body"][:8000]}
            if not goal.strip():
                goal = issue["title"]
            if not title.strip():
                title = issue["title"]
        pr_info = await gh.pr(repo, pr_number) if pr_number else None
    finally:
        await gh.aclose()
    if not title.strip():
        title = (goal.strip().splitlines() or ["Change"])[0][:120]
    run = SdlcRun(
        user_id=uuid.UUID(user_id),
        project_id=project_id,
        kind=kind_enum.value,
        title=title.strip()[:300],
        goal=goal.strip(),
        repo=repo,
        base_branch=(base_branch or info["default_branch"]).strip(),
        autonomy=autonomy,
        auto_merge=auto_merge and kind_enum != RunKind.review,
        deploy_hook_ciphertext=encrypt(deploy_hook.strip()) if deploy_hook and deploy_hook.strip() else None,
        issue_url=issue_url.strip(),
        pr_number=pr_number,
        pr_url=pr_info["url"] if pr_info else "",
        head_sha=pr_info["head_sha"] if pr_info else "",
        status=RunStatus.queued.value,
        stage=STAGE_ORDER[kind_enum][0],
        stages=[_stage_entry(k) for k in STAGE_ORDER[kind_enum]],
        log=[{"at": _now(), "level": "info", "message": "Run created"}],
        context=context,
        usage={},
    )
    session.add(run)
    await session.flush()
    await audit(
        session,
        actor_id=user_id,
        action="sdlc.create",
        target_type="sdlc_run",
        target_id=str(run.id),
        summary=f"{kind} run on {repo}: {run.title}",
        project_id=project_id,
    )
    return run


async def _claim(run_id: str) -> SdlcRun | None:
    now = utcnow()
    async with session_scope() as session:
        result = await session.execute(
            update(SdlcRun)
            .where(
                SdlcRun.id == uuid.UUID(run_id),
                SdlcRun.status.in_([RunStatus.queued.value, RunStatus.running.value]),
                (SdlcRun.lease_until.is_(None)) | (SdlcRun.lease_until < now),
            )
            .values(status=RunStatus.running.value, lease_until=now + LEASE)
        )
        if result.rowcount != 1:
            return None
        return await session.get(SdlcRun, uuid.UUID(run_id))


def _pending_stage(run: SdlcRun) -> dict[str, Any] | None:
    for stage in run.stages or []:
        if stage["status"] not in (StageStatus.done.value, StageStatus.skipped.value):
            return stage
    return None


def _append_log(run: SdlcRun, level: str, message: str) -> None:
    entries = list(run.log or [])
    entries.append({"at": _now(), "level": level, "message": message[:500]})
    run.log = entries[-MAX_LOG:]


def _set_stage(run: SdlcRun, key: str, **values: Any) -> None:
    run.stages = [{**s, **values} if s["key"] == key else s for s in run.stages]


def _friendly(exc: Exception) -> str:
    if isinstance(exc, RunError):
        return str(exc)
    if isinstance(exc, GitHubError):
        return exc.message
    if isinstance(exc, UnsafeChange):
        return str(exc)
    if isinstance(exc, LLMError):
        return f"The model could not be reached or answered incorrectly: {exc}"
    if isinstance(exc, httpx.HTTPError):
        return "A service NOVA depends on is unreachable. Retry in a moment."
    return "An unexpected error interrupted the run. Retry; completed stages are kept."


async def advance(run_id: str) -> float | None:
    """Run the next stage. Returns seconds to wait before the next call, or ``None`` when the run waits or is over."""
    run = await _claim(run_id)
    if run is None:
        return None
    stage = _pending_stage(run)
    user_id = str(run.user_id)
    if stage is None:
        await _finish(run_id, RunStatus.completed)
        return None
    key = stage["key"]
    gh = llm = None
    try:
        gh = await github_accounts.client_for(user_id)
        llm = await providers.llm_for_user(user_id)
        ctx = Ctx(run=run, gh=gh, llm=llm)
        await _mark_running(run_id, key)
        result = await HANDLERS[key](ctx)
    except Exception as exc:
        if not isinstance(exc, (RunError, GitHubError, UnsafeChange, LLMError, httpx.HTTPError)):
            log.exception("SDLC run %s failed in stage %s", run_id, key)
        await _fail(run_id, key, _friendly(exc))
        return None
    finally:
        if gh is not None:
            await gh.aclose()
    delay = await _persist(run_id, key, result, ctx)
    if delay is None:
        await _evaluate(run_id)  # a finished run is handed to FORGE (no-op while it is running, waiting or cancelled)
    return delay


async def _mark_running(run_id: str, key: str) -> None:
    async with session_scope() as session:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
        if run is None or run.status != RunStatus.running.value:
            return
        run.stage = key
        current = next(s for s in run.stages if s["key"] == key)
        if current["status"] in (StageStatus.pending.value, StageStatus.failed.value, StageStatus.waiting.value):
            first = current["status"] != StageStatus.waiting.value
            _set_stage(
                run,
                key,
                status=StageStatus.running.value,
                started_at=_now() if first else current["started_at"],
                finished_at=None,
            )
            if first:
                _append_log(run, "info", f"Stage {key} started")


async def _persist(run_id: str, key: str, result: StageResult, ctx: Ctx) -> float | None:
    async with session_scope() as session:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
        if run is None or run.status != RunStatus.running.value:  # cancelled meanwhile: drop the result
            return None
        run.context = {**(run.context or {}), **result.context}
        for name, value in result.fields.items():
            setattr(run, name, value)
        for line in [*ctx.logs, *result.logs]:
            _append_log(run, "info", line)
        usage = dict(run.usage or {})
        for field_name in ("input_tokens", "output_tokens", "model_calls"):
            usage[field_name] = int(usage.get(field_name, 0)) + getattr(ctx.usage, field_name)
        run.usage = usage
        run.model = ctx.model or run.model
        run.lease_until = None
        if result.status == "repeat":
            _set_stage(run, key, summary=result.summary)
            return result.delay
        if result.status == "gate":
            _set_stage(run, key, status=StageStatus.waiting.value, summary=result.summary)
            run.status, run.gate = RunStatus.waiting_user.value, result.gate
            return None
        stage_status = StageStatus.skipped if result.status == "skipped" else StageStatus.done
        _set_stage(run, key, status=stage_status.value, summary=result.summary, output=result.output, finished_at=_now())
        if result.gate:  # a finished stage that asks for approval before the next one (plan)
            run.status, run.gate = RunStatus.waiting_user.value, result.gate
            nxt = _pending_stage(run)
            run.stage = nxt["key"] if nxt else key
            return None
        nxt = _pending_stage(run)
        if nxt is None:
            run.status, run.finished_at = RunStatus.completed.value, utcnow()
            _append_log(run, "info", "Run completed")
            return None
        run.stage = nxt["key"]
        return 0.0


async def _fail(run_id: str, key: str, message: str) -> None:
    async with session_scope() as session:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
        if run is None:
            return
        run.status, run.error, run.lease_until, run.finished_at = RunStatus.failed.value, message, None, utcnow()
        _set_stage(run, key, status=StageStatus.failed.value, summary=message, finished_at=_now())
        _append_log(run, "error", f"Stage {key} failed: {message}")
    await _evaluate(run_id)


async def _finish(run_id: str, status: RunStatus) -> None:
    async with session_scope() as session:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
        if run is not None:
            run.status, run.lease_until, run.finished_at = status.value, None, utcnow()
    await _evaluate(run_id)


async def _evaluate(run_id: str) -> None:
    from nova.services.sdlc_forge import ingest_safely

    await ingest_safely(run_id)


async def run_until_pause(run_id: str, *, sleep: bool = False) -> None:
    """Advance until the run waits, finishes or fails (eager mode: no waiting between CI polls)."""
    import asyncio

    while (delay := await advance(run_id)) is not None:
        if delay > 0 and sleep:
            await asyncio.sleep(delay)


# --- User actions -------------------------------------------------------------------------------------------------


async def get_owned(session: Any, user_id: str, run_id: str) -> SdlcRun | None:
    try:
        run = await session.get(SdlcRun, uuid.UUID(run_id))
    except ValueError:
        return None
    return run if run is not None and str(run.user_id) == user_id else None


async def approve(session: Any, run: SdlcRun, *, notes: str = "") -> None:
    if run.status != RunStatus.waiting_user.value or not run.gate:
        raise ConflictError("This run is not waiting for your approval.")
    context = dict(run.context or {})
    if run.gate == "plan" and notes.strip():
        context["user_notes"] = notes.strip()[:4000]
    if run.gate == "merge":
        context["merge_approved"] = True
    run.context = context
    _append_log(run, "info", f"Approved: {run.gate}")
    run.gate, run.status, run.lease_until = None, RunStatus.queued.value, None


async def cancel(run: SdlcRun) -> None:
    if run.status in (RunStatus.completed.value, RunStatus.cancelled.value):
        raise ConflictError("This run is already over.")
    run.status, run.gate, run.lease_until, run.finished_at = RunStatus.cancelled.value, None, None, utcnow()
    _append_log(run, "info", "Cancelled by the user (branch and pull request are left as they are)")


async def retry(run: SdlcRun) -> None:
    if run.status != RunStatus.failed.value:
        raise ConflictError("Only a failed run can be retried.")
    stage = next((s for s in run.stages if s["status"] == StageStatus.failed.value), None) or _pending_stage(run)
    if stage is not None:
        _set_stage(run, stage["key"], status=StageStatus.pending.value, summary="", finished_at=None)
        run.stage = stage["key"]
    context = dict(run.context or {})
    context.update({"ci_polls": 0, "ci_fix_rounds": 0, "merge_polls": 0})
    run.context = context
    run.status, run.error, run.finished_at, run.lease_until = RunStatus.queued.value, "", None, None
    _append_log(run, "info", "Retry requested")


async def publish_release(run: SdlcRun, *, tag: str, draft: bool) -> str:
    release = (run.context or {}).get("release")
    if not run.merge_sha or not release:
        raise ConflictError("The change must be merged and its release notes written first.")
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,60}$", tag):
        raise RunError("Invalid tag name.")
    gh = await github_accounts.client_for(str(run.user_id))
    try:
        url = await gh.create_release(
            run.repo, tag=tag, name=release.get("title") or tag, body=release.get("notes", ""), target=run.merge_sha, draft=draft
        )
    finally:
        await gh.aclose()
    run.release_url = url
    _append_log(run, "info", f"{'Draft release' if draft else 'Release'} {tag} created")
    return url


async def trigger_deploy(run: SdlcRun) -> None:
    from nova.agent.providers.catalog import validate_base_url

    if not run.deploy_hook_ciphertext:
        raise ConflictError("No deploy hook is configured for this run.")
    if not run.merge_sha:
        raise ConflictError("Merge the change before deploying.")
    url = decrypt(run.deploy_hook_ciphertext)
    if not url:
        raise RunError("The stored deploy hook can no longer be read.")
    try:
        url = validate_base_url(url, allow_private=get_settings().env != "production")
    except LLMError as exc:
        raise RunError(f"Deploy hook refused: {exc}") from exc
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=False, transport=providers.http_transport()) as client:
            response = await client.post(
                url, json={"repo": run.repo, "sha": run.merge_sha, "branch": run.base_branch, "run_id": str(run.id)}
            )
    except httpx.HTTPError as exc:
        raise RunError(f"The deploy hook is unreachable ({exc.__class__.__name__}).") from exc
    if response.status_code >= 400:
        raise RunError(f"The deploy hook answered {response.status_code}.")
    _append_log(run, "info", f"Deploy hook triggered ({response.status_code})")


async def requeue_stale(max_age_minutes: int = 3) -> list[str]:
    """Runs a crashed worker left mid-flight (lease expired): ids to dispatch again."""
    now = utcnow()
    async with session_scope() as session:
        rows = await session.scalars(
            select(SdlcRun.id).where(
                SdlcRun.status.in_([RunStatus.queued.value, RunStatus.running.value]),
                SdlcRun.updated_at < now - timedelta(minutes=max_age_minutes),
                (SdlcRun.lease_until.is_(None)) | (SdlcRun.lease_until < now),
            )
        )
        return [str(i) for i in rows]

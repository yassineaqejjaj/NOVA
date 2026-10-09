"""Safety rules for generated changes, URL parsing and provider request shaping."""

from __future__ import annotations

import pytest

from nova.agent.providers.catalog import validate_base_url
from nova.agent.providers.openai import OpenAIProvider
from nova.domain.llm import LLMError, LLMMessage
from nova.domain.sdlc import ChangeSet, FileChange, UnsafeChange, slugify, validate_changeset
from nova.integrations.github.client import parse_github_ref, parse_repo

TREE = {"src/a.ts", "README.md", "src/big.ts"}
BIG = "x" * 3000


def cs(*changes: FileChange) -> ChangeSet:
    return ChangeSet(summary="s", commit_message="m", changes=list(changes))


def ok(path: str, content: str = "export const a = 1;\n", action: str = "modify") -> FileChange:
    return FileChange(path=path, action=action, content=content)


@pytest.mark.parametrize(
    "path",
    [
        "../etc/passwd",
        "/abs/path",
        "a//b",
        ".git/config",
        ".github/workflows/ci.yml",
        "package-lock.json",
        ".env",
        ".env.production",
        "keys/server.pem",
        "img/logo.png",
        "web/node_modules/x/index.js",
    ],
)
def test_dangerous_paths_are_refused(path):
    with pytest.raises(UnsafeChange):
        validate_changeset(cs(ok(path, action="create")), {}, TREE)


def test_secrets_in_content_are_refused():
    for secret in ("-----BEGIN RSA PRIVATE KEY-----", "ghp_" + "a" * 36, "AKIA" + "A" * 16, "sk-ant-" + "a" * 30):
        with pytest.raises(UnsafeChange, match="secret"):
            validate_changeset(cs(ok("src/new.ts", f"const k = '{secret}';", "create")), {}, TREE)


def test_existing_file_must_have_been_read():
    with pytest.raises(UnsafeChange, match="not read"):
        validate_changeset(cs(ok("src/a.ts")), {}, TREE)


def test_truncated_rewrite_is_refused():
    with pytest.raises(UnsafeChange, match="shorter"):
        validate_changeset(cs(ok("src/big.ts", "// rest unchanged")), {"src/big.ts": BIG}, TREE)


def test_actions_are_normalized_from_the_real_tree():
    safe = validate_changeset(cs(ok("src/a.ts", action="create"), ok("src/new.ts", action="modify")), {"src/a.ts": "old"}, TREE)
    assert {c.path: c.action for c in safe} == {"src/a.ts": "modify", "src/new.ts": "create"}


def test_limits_and_deletes():
    with pytest.raises(UnsafeChange, match="empty"):
        validate_changeset(cs(), {}, TREE)
    with pytest.raises(UnsafeChange, match="Too many"):
        validate_changeset(cs(*[ok(f"f{i}.ts", action="create") for i in range(26)]), {}, TREE)
    with pytest.raises(UnsafeChange, match="twice"):
        validate_changeset(cs(ok("n.ts", action="create"), ok("n.ts", action="create")), {}, TREE)
    with pytest.raises(UnsafeChange, match="does not exist"):
        validate_changeset(cs(FileChange(path="nope.ts", action="delete")), {}, TREE)
    assert validate_changeset(cs(FileChange(path="README.md", action="delete")), {}, TREE)[0].action == "delete"


def test_parsers():
    assert parse_repo("o/r") == "o/r"
    assert parse_repo("https://github.com/o/r.git") == "o/r"
    assert parse_repo("https://github.com/o/r/pull/3") == "o/r"
    assert parse_repo("https://evil.example/o/r") is None
    assert parse_github_ref("https://github.com/o/r/pull/12", "pull") == ("o/r", 12)
    assert parse_github_ref("https://github.com/o/r/issues/7", "pull") is None
    assert slugify("Add *Farewell* feature!!") == "add-farewell-feature"


def test_base_url_validation():
    assert validate_base_url("http://localhost:11434/v1", allow_private=True)
    for url in (
        "http://example.com/v1",
        "https://localhost/v1",
        "https://svc.railway.internal/v1",
        "https://127.0.0.1/v1",
        "https://10.0.0.5/v1",
        "ftp://x/y",
    ):
        with pytest.raises(LLMError):
            validate_base_url(url, allow_private=False)


def test_openai_reasoning_models_use_the_new_parameters():
    msgs = [LLMMessage(role="user", content="hi")]
    gpt5 = OpenAIProvider("https://api.openai.com/v1", "gpt-5", api_key="k")._payload(msgs, 0.2, 100)
    assert "max_completion_tokens" in gpt5 and "max_tokens" not in gpt5 and "temperature" not in gpt5
    gpt41 = OpenAIProvider("https://api.openai.com/v1", "gpt-4.1", api_key="k")._payload(msgs, 0.2, 100)
    assert gpt41["temperature"] == 0.2 and gpt41["max_completion_tokens"] == 100

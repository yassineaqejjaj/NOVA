"""The root README stays accurate with the repository."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"

FENCE = "```"

SKILLS_COUNT_RE = re.compile(
    r"\b(\d+)\+?\s+(?:\w+\s+)?skills\b",
    re.IGNORECASE,
)
ARTIFACTS_COUNT_RE = re.compile(
    r"\b(\d+)\+?\s+(?:\w+\s+)?artifact types\b",
    re.IGNORECASE,
)
PASSWORD_QUOTED_RE = re.compile(
    r"(?<!\w)password(?!\w)[\s:=*]*`([^`\n]+)`",
    re.IGNORECASE,
)
PASSWORD_ASSIGN_RE = re.compile(
    r"[A-Za-z0-9_]*password[A-Za-z0-9_]*\s*[=:]\s*([^\s`]+)",
    re.IGNORECASE,
)
SEPARATOR_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
HEADING_RE = re.compile(r"^(#{1,6})\s+\S")
VARIABLE_RE = re.compile(r"\bNOVA_(?:LLM|DOCKER)_[A-Z0-9_]+\b")


# ----------------------------------------------------------------------- helpers
@pytest.fixture(scope="module")
def text() -> str:
    assert README.is_file(), "README.md must stay at the repository root"
    return README.read_text(encoding="utf-8")


def _split_fences(content: str) -> tuple[list[str], list[tuple[str, str]], bool]:
    """Split content into prose lines, (info, body) code blocks and a closed flag."""
    outside: list[str] = []
    blocks: list[tuple[str, str]] = []
    in_fence = False
    info = ""
    body: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith(FENCE):
            if not in_fence:
                in_fence = True
                info = stripped[len(FENCE) :].strip()
                body = []
            else:
                in_fence = False
                blocks.append((info, "\n".join(body)))
            continue
        if in_fence:
            body.append(line)
        else:
            outside.append(line)
    return outside, blocks, not in_fence


def _prose(content: str) -> str:
    return "\n".join(_split_fences(content)[0])


def _code(content: str) -> str:
    return "\n".join(body for _, body in _split_fences(content)[1])


def _raw_section(content: str, title: str) -> str:
    """Body of the `## ...` section whose heading contains `title`."""
    parts = re.split(r"^## ", content, flags=re.MULTILINE)
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        if title.lower() in heading.lower():
            return body
    raise AssertionError(f"no '## {title}' section in README")


def _section(content: str, title: str) -> str:
    """Prose of a section (code blocks removed)."""
    return _raw_section(_prose(content), title)


def section_with_subsections(content: str, title: str) -> str:
    """Raw text of a section including its code blocks and subsections."""
    return _raw_section(content, title)


def _compose_text() -> str:
    path = ROOT / "docker-compose.yml"
    assert path.is_file(), "docker-compose.yml is missing"
    return path.read_text(encoding="utf-8")


def _env_example() -> str:
    path = ROOT / ".env.example"
    assert path.is_file(), ".env.example is missing"
    return path.read_text(encoding="utf-8")


def _nova_sources() -> str:
    files = (ROOT / "nova").rglob("*.py")
    return "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files)


# ----------------------------------------------------------------- title, tagline
def test_readme_starts_with_title_and_short_pitch(text: str) -> None:
    first = next(line for line in text.splitlines() if line.strip())
    assert re.match(r"^# \S", first), "the README must start with an H1 title"
    assert "NOVA" in first

    lines = _prose(text).splitlines()
    start = lines.index(first) + 1
    intro: list[str] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        intro.append(line)
    pitch = " ".join(intro)
    assert "ORION" in pitch
    assert "personal" in pitch.lower()
    assert "product agent" in pitch.lower()
    assert len(pitch) <= 600, "the pitch must stay short"


# -------------------------------------------------------------------- ORION roles
def test_orion_section_presents_nova_orbit_forge_with_repo_links(text: str) -> None:
    section = _section(text, "ORION")
    for name in ("NOVA", "ORBIT", "FORGE"):
        assert name in section
    assert "https://github.com/yassineaqejjaj/ORBIT" in section
    assert "https://github.com/yassineaqejjaj/FORGE" in section


# ----------------------------------------------------------------------- features
@pytest.mark.parametrize(
    "keyword",
    [
        "composer",
        "langgraph",
        "orchestration",
        "sub-agent",
        "engineering",
        "sdlc",
        "skills",
        "artifacts",
        "transparency",
        "security",
        "open source",
    ],
)
def test_main_features_are_listed(text: str, keyword: str) -> None:
    assert keyword in _section(text, "What it does").lower()


# ------------------------------------------------------------------------ figures
def _count_skills() -> int:
    dirs = (d for d in (ROOT / "skills").iterdir() if d.is_dir())
    return sum(1 for d in dirs if (d / "skill.yaml").is_file())


def _count_artifact_types() -> int:
    types = ROOT / "artifacts" / "types"
    return sum(1 for p in types.iterdir() if p.suffix in {".yaml", ".yml"})


def test_cited_skill_and_artifact_counts_match_the_repository(text: str) -> None:
    prose = _prose(text)
    for match in SKILLS_COUNT_RE.finditer(prose):
        assert int(match.group(1)) == _count_skills(), match.group(0)
    for match in ARTIFACTS_COUNT_RE.finditer(prose):
        assert int(match.group(1)) == _count_artifact_types(), match.group(0)


def _find_sections(node: object) -> list | None:
    if isinstance(node, dict):
        value = node.get("sections")
        if isinstance(value, list):
            return value
        for child in node.values():
            found = _find_sections(child)
            if found is not None:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _find_sections(child)
            if found is not None:
                return found
    return None


def test_cited_prd_section_count_matches_the_prd_type(text: str) -> None:
    match = re.search(r"PRD has (\d+) sections", _prose(text))
    if not match:
        return  # figure removed: nothing to verify
    candidates = sorted((ROOT / "artifacts" / "types").glob("prd*.y*ml"))
    assert candidates, "README cites PRD sections but there is no PRD type"
    data = yaml.safe_load(candidates[0].read_text(encoding="utf-8"))
    sections = _find_sections(data)
    if sections is None:
        pytest.skip("PRD type does not expose a 'sections' list")
    assert int(match.group(1)) == len(sections)


# ---------------------------------------------------------------------- quick start
def test_quick_start_commands(text: str) -> None:
    section = _section(text, "Quick start")
    code = _code(section_with_subsections(text, "Quick start"))
    assert "cp .env.example .env" in code
    assert "docker compose up -d --build" in code
    assert "python -m nova.seed" in code
    assert "NOVA_DEMO_PASSWORD" in section


def test_quick_start_matches_compose_and_env_example(text: str) -> None:
    compose = yaml.safe_load(_compose_text())
    services = compose["services"]
    _env_example()
    quick = section_with_subsections(text, "Quick start")
    match = re.search(r"docker compose exec (\w+) python -m nova\.seed", quick)
    assert match, "the seed command must run in a compose service"
    assert match.group(1) in services
    expected = ("postgres", "valkey", "keycloak", "api", "worker", "beat", "web", "voice")
    for service in expected:
        assert service in services, service


def test_compose_profiles_mentioned_in_readme_exist(text: str) -> None:
    compose = _compose_text()
    quick = section_with_subsections(text, "Quick start")
    for profile in ("gpu", "cpu-llm", "observability"):
        assert profile in quick
        assert profile in compose, profile


# ------------------------------------------------------------------ inference config
def test_inference_section_documents_vllm_and_openai_compatible(text: str) -> None:
    quick = section_with_subsections(text, "Quick start")
    assert "vLLM" in quick
    assert "Ollama" in quick
    assert "OpenAI-compatible" in quick


def test_documented_llm_and_docker_variables_exist_in_the_repository(text: str) -> None:
    names = set(VARIABLE_RE.findall(text))
    assert {"NOVA_LLM_PROVIDER", "NOVA_LLM_BASE_URL", "NOVA_LLM_MODEL"} <= names
    assert "NOVA_DOCKER_LLM_BASE_URL" in names
    corpus = _env_example() + "\n" + _compose_text()
    sources = _nova_sources()
    for name in sorted(names):
        field = name.removeprefix("NOVA_").lower()
        used = name in corpus or name in sources or field in sources
        assert used, f"{name} is not used anywhere"


# ---------------------------------------------------------------------- local URLs
def _section_urls(content: str) -> set[str]:
    return set(re.findall(r"http://localhost:\d+[^\s)>|`]*", content))


def test_local_urls_are_documented(text: str) -> None:
    urls = _section_urls(section_with_subsections(text, "Quick start"))
    assert "http://localhost:3200" in urls
    assert "http://localhost:8200/api/v1/docs" in urls
    assert "http://localhost:8200/v1/agents/nova-orchestrator/runs" in urls
    assert "http://localhost:8280" in urls


def test_local_ports_appear_in_compose_or_env() -> None:
    corpus = _compose_text() + "\n" + _env_example()
    for port in ("3200", "8200", "8280"):
        assert port in corpus, f"port {port} is documented but not configured"


# ------------------------------------------------------------------ repository layout
def test_repository_layout_paths_exist(text: str) -> None:
    raw = section_with_subsections(text, "Repository")
    block = raw.split(FENCE)[1].split("\n", 1)[1]
    lines = [line for line in block.splitlines() if line.strip()]
    paths = [line.split()[0].rstrip("/") for line in lines]
    expected = {
        "apps/api",
        "apps/web",
        "nova",
        "services/worker",
        "skills",
        "artifacts/types",
        "infrastructure",
        "docs",
        "tests",
    }
    assert expected <= set(paths)
    for path in paths:
        assert (ROOT / path).exists(), f"{path} is listed but does not exist"


# ------------------------------------------------------------------ tests and lint
def test_tests_and_lint_commands_are_defined(text: str) -> None:
    section = section_with_subsections(text, "Tests and lint")
    code = _code(section)
    assert "pytest" in code
    assert "ruff check" in code
    assert "ruff format --check" in code

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "pytest" in pyproject
    assert "[tool.ruff" in pyproject

    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    for script in re.findall(r"npm run ([\w:-]+)", code):
        assert script in scripts, f"npm script '{script}' is not in package.json"
    assert "test:e2e" in code


def test_every_npm_script_in_readme_exists(text: str) -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    for script in re.findall(r"npm run ([\w:-]+)", _code(text)):
        assert script in scripts, script


@pytest.mark.parametrize("module", ["nova.seed", "nova.skills.build"])
def test_python_modules_run_by_readme_exist(text: str, module: str) -> None:
    assert f"python -m {module}" in _code(text)
    base = ROOT.joinpath(*module.split("."))
    assert base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def test_ci_workflow_mentioned_in_readme_exists(text: str) -> None:
    assert ".github/workflows/ci.yml" in text
    assert (ROOT / ".github" / "workflows" / "ci.yml").is_file()


# ----------------------------------------------------------------------------- links
REQUIRED_DOCS = [
    "docs/ARCHITECTURE.md",
    "docs/DEPLOYMENT.md",
    "docs/ENGINEERING.md",
    "docs/OPERATIONS.md",
    "docs/SKILLS.md",
    "docs/TRAINING.md",
    "docs/VOICE.md",
    "docs/integration-analysis.md",
    "OPEN_SOURCE_COMPONENTS.md",
]

EXTERNAL_LINK_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|#|//)", flags=re.IGNORECASE)


def _relative_links(content: str) -> list[str]:
    links = re.findall(r"\]\(([^)\s]+)\)", _prose(content))
    return [unquote(link.split("#", 1)[0]) for link in links if not EXTERNAL_LINK_RE.match(link)]


def test_all_relative_links_point_to_existing_files(text: str) -> None:
    links = _relative_links(text)
    assert links, "the README should link to the documentation"
    for link in links:
        assert (ROOT / link).exists(), f"broken relative link: {link}"


@pytest.mark.parametrize("doc", REQUIRED_DOCS)
def test_documentation_links_are_present_and_valid(text: str, doc: str) -> None:
    assert doc in _relative_links(text)
    assert (ROOT / doc).is_file()


# -------------------------------------------------------------------------- no secrets
SECRET_PATTERNS = [
    r"ghp_[A-Za-z0-9]{20,}",
    r"github_pat_[A-Za-z0-9_]{20,}",
    r"\bsk-[A-Za-z0-9_-]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"xox[baprs]-[A-Za-z0-9-]{10,}",
]

# The only literal password values the README may contain: the public demo ones
# (or the name of the variable that holds them).
ALLOWED_PASSWORD_VALUES = {"NOVA_DEMO_PASSWORD", "nova-demo", "orbit-demo"}


def test_readme_contains_no_secret(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        assert not re.search(pattern, text), f"secret-like value matches {pattern}"


def test_readme_only_keeps_public_demo_credentials(text: str) -> None:
    assert "yassine" in text
    assert "NOVA_DEMO_PASSWORD" in text
    for email in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):
        assert email.endswith(".example"), f"real e-mail address in README: {email}"

    # 1) prose: the word "password" followed by a quoted literal
    quoted = PASSWORD_QUOTED_RE.findall(text)
    assert quoted, "the README should state which demo password value to use"
    for value in quoted:
        assert value.strip() in ALLOWED_PASSWORD_VALUES, f"unexpected value: {value!r}"

    # 2) assignments such as `SOME_PASSWORD=value` or `password: value`
    for match in PASSWORD_ASSIGN_RE.finditer(text):
        value = match.group(1).strip("`'\"")
        assert value in ALLOWED_PASSWORD_VALUES, f"literal password: {match.group(0)!r}"


# --------------------------------------------------------------------------- production
def test_production_section_keeps_public_url_and_points_to_deployment_doc(
    text: str,
) -> None:
    section = _section(text, "Production")
    assert "https://nova-six-orcin-96.vercel.app" in section
    assert "docs/DEPLOYMENT.md" in section


# ------------------------------------------------------------------------ valid Markdown
def test_code_blocks_are_closed_and_have_a_language(text: str) -> None:
    _, blocks, closed = _split_fences(text)
    assert closed, "unclosed code block"
    assert blocks
    for info, body in blocks:
        assert info, f"code block without a language: {body.splitlines()[:1]}"


def _heading_levels(content: str) -> list[int]:
    levels = []
    for line in _prose(content).splitlines():
        found = HEADING_RE.match(line)
        if found:
            levels.append(len(found.group(1)))
    return levels


def test_heading_hierarchy_is_consistent(text: str) -> None:
    headings = _heading_levels(text)
    assert headings
    assert headings[0] == 1
    assert headings.count(1) == 1, "exactly one H1"
    for previous, current in zip(headings, headings[1:], strict=False):
        assert current <= previous + 1, "heading levels must not be skipped"


def _cells(row: str) -> int:
    row = re.sub(r"`[^`]*`", "x", row.strip())
    row = re.sub(r"<[^>]*>", "x", row)
    row = row.replace(r"\|", "")
    return row.strip("|").count("|") + 1


def test_tables_are_well_formed(text: str) -> None:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in _prose(text).splitlines():
        if line.strip().startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    assert tables, "the README should contain at least one table"
    for table in tables:
        assert len(table) >= 2
        assert SEPARATOR_RE.match(table[1]), "the second table row must be a separator"
        width = _cells(table[0])
        for row in table:
            assert _cells(row) == width, f"inconsistent column count: {row}"

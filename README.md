# NOVA — Personal AI Product Agent

> **One collaborator. One NOVA.** Express what you want to achieve; NOVA finds the context, picks the
> method, runs the workflow and produces durable, editable product work.

NOVA is part of **ORION**:

| | Responsibility |
|---|---|
| **NOVA** acts | intent, planning, Skills, execution, Artifacts |
| **ORBIT** knows | context, memory, knowledge, permissions, citations ([repo](https://github.com/yassineaqejjaj/ORBIT)) |
| **FORGE** learns | traces, evaluation, regressions, improvement ([repo](https://github.com/yassineaqejjaj/FORGE)) |

NOVA never duplicates ORBIT or FORGE: it retrieves context **as the user** through ORBIT's API and is
evaluated by FORGE through FORGE's existing `nova` adapter. See
[`docs/integration-analysis.md`](docs/integration-analysis.md) for the contracts and the documented gaps.

## What it does

```
Intent → ORBIT context → Plan → Skill selection → Execution → Artifact → (approval) → FORGE trace
```

* **Composer** — natural intent, `/skill` shortcuts, project, Auto / Explicit / No context, attachments,
  Artifact references, ORBIT context pinning.
* **LangGraph runtime** — typed `NovaState`, branching, retries, Postgres checkpoints, human-in-the-loop
  (questions, workflow confirmation, approvals), resumable background execution (Celery + Valkey), live SSE.
* **NOVA Core orchestration** — the intent becomes a task, decomposed into sub-objectives, routed to specialist agents;
  a Research agent brings ORBIT context, a Validation agent verifies every deliverable (one revision when needed),
  agents hand off to each other, NOVA supervises it all live.
* **Sub-agents** — NOVA orchestrates four specialist agents (Product, Project, Design, Engineering); every step of a
  workflow runs under the persona and quality bar of the agent owning its Skill, shown live with its activity and timing.
  The user's profile (onboarding, Settings) chooses the lead agent.
* **64 Skills** — versioned workflows for Product, Project, Design and Engineering work (strategy, discovery,
  prioritization, definition, delivery, analysis, communication), composed into editable workflows.
* **Artifacts** — 54 structured types (PRD with 23 sections, backlog, sprint plan…), Lexical editing, autosave,
  version history and compare, section-level AI regeneration, comments, citations, export.
* **Transparency** — which ORBIT context was used (classification, freshness, relevance), recorded provenance
  ("why did you include this?"), never raw model reasoning.
* **Security** — Keycloak OIDC/SSO, RBAC, ORBIT ACL propagation, C0–C3 classification awareness, tool registry,
  autonomy policy, prompt-injection defenses, audit log, PII redaction.
* **Open source only** — vLLM (or any OpenAI-compatible server), PostgreSQL, Valkey, Keycloak, OpenTelemetry.
  Runs offline. See [`OPEN_SOURCE_COMPONENTS.md`](OPEN_SOURCE_COMPONENTS.md).

## Production

Live on **Vercel** (web) + **Railway** (API, worker, beat, Keycloak, Valkey, PostgreSQL):
<https://nova-six-orcin-96.vercel.app>, connected to the deployed ORBIT and FORGE. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the topology, variables, release process and how to connect FORGE.

## Quick start (Docker)

Prerequisites: Docker (Compose v2). ORBIT and FORGE run from their own repositories.

```bash
cp .env.example .env
docker compose up -d --build                 # postgres, valkey, keycloak, api, worker, beat, web
docker compose exec api python -m nova.seed  # demo data (Yassine · Head of AI, projects NOVA/ORBIT/FORGE)
```

Open <http://localhost:3200> and sign in with Keycloak user **`yassine`** / password `NOVA_DEMO_PASSWORD`
(`nova-demo` by default). Then **Settings → ORBIT** to link your ORBIT account (local ORBIT demo:
`camille.martin@nordalis.example` / `orbit-demo`).

**Inference** — NOVA needs an OpenAI-compatible server:

| Setup | Settings |
|---|---|
| GPU (vLLM, recommended) | `docker compose --profile gpu up -d vllm` · `NOVA_LLM_PROVIDER=vllm` · `NOVA_LLM_BASE_URL=http://vllm:8000/v1` · `NOVA_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct` |
| Laptop (Ollama on the host) | `NOVA_LLM_PROVIDER=openai_compatible` · `NOVA_LLM_MODEL=qwen3:8b` · `NOVA_LLM_BASE_URL=http://localhost:11434/v1` (host processes) · `NOVA_DOCKER_LLM_BASE_URL=http://host.docker.internal:11434/v1` (containers) |

`.env` describes the host; inside Compose, `NOVA_DOCKER_*` variables (`AUTH_MODE`, `ORBIT_BASE_URL`, `FORGE_BASE_URL`,
`LLM_BASE_URL`) provide the container-network equivalents — ORBIT and FORGE are reached through `host.docker.internal`.

| URL | |
|---|---|
| http://localhost:3200 | NOVA |
| http://localhost:8200/api/v1/docs | API (OpenAPI) |
| http://localhost:8200/v1/agents/nova-orchestrator/runs | NOVA Agent Protocol (called by FORGE) |
| http://localhost:8280 | Keycloak (admin / `KEYCLOAK_ADMIN_PASSWORD`) |

### Connect FORGE

1. In FORGE, create an API key (role `evaluator`, or `editor` to allow production capture) and set
   `NOVA_FORGE_API_KEY`.
2. In FORGE, create a `nova` credential whose secret is `NOVA_FORGE_INBOUND_TOKEN` and whose base URL reaches
   NOVA's API (e.g. `http://host.docker.internal:8200`).
3. NOVA registers itself as agent `nova` on its first capture; FORGE evaluates NOVA through the
   NOVA Agent Protocol. `NOVA_FORGE_CAPTURE_POLICY` (`off | on_feedback | sampled | all`) controls which
   production executions become FORGE evaluation runs.

## Development (host)

```bash
uv sync && npm install
docker compose up -d postgres valkey
cp .env.example .env   # set NOVA_AUTH_MODE=dev for the local sign-in form
export PYTHONPATH=.:apps/api:services/worker
uv run alembic upgrade head && uv run python -m nova.seed
uv run uvicorn nova_api.main:app --port 8200 --reload
uv run celery -A nova_worker.app worker -Q executions,maintenance --loglevel INFO
npm run dev            # http://localhost:3200
```

On macOS, set `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES` for the Celery worker.

## Tests

```bash
uv run pytest                                   # unit + integration (SQLite, in-memory checkpointer)
NOVA_DATABASE_URL=postgresql+asyncpg://nova:nova@localhost:5435/nova_test uv run pytest   # real Postgres checkpointer
uv run ruff check . && uv run python -m nova.skills.build --check
npm run typecheck && npm run lint
npm run test:e2e                                # Playwright (starts API, web and test doubles for LLM/ORBIT)
```

## Repository

```
apps/web            Next.js 15 · React 19 · Tailwind v4 · shadcn/ui (packages/ui) · TanStack Query · Zustand · Lexical · Framer Motion
apps/api            FastAPI app (nova_api): auth (OIDC BFF), routers, SSE, NOVA Agent Protocol
services/worker     Celery (nova_worker): executions, schedules, FORGE refresh, retention
nova/               core: domain · agent (graph, nodes, tools, providers) · skills · artifacts · integrations/{orbit,forge} · infra · services
skills/             64 Skills (skill.yaml, instructions.md, input/output JSON Schemas, evaluation.yaml)
artifacts/types/    38 Artifact types
packages/schemas    item-kind JSON Schemas shared by API and editor
infrastructure/     docker, keycloak realm, kubernetes manifests
docs/               integration-analysis.md, ARCHITECTURE.md, SKILLS.md, OPERATIONS.md
tests/              unit, integration, support (test doubles)
```

## Documentation

* [Integration analysis](docs/integration-analysis.md) — ORBIT & FORGE contracts, gaps, differences with the brief
* [Architecture](docs/ARCHITECTURE.md) — execution model, Skills, Artifacts, data model, API, security
* [Skills](docs/SKILLS.md) — writing and versioning Skills
* [Deployment](docs/DEPLOYMENT.md) — Railway + Vercel production setup, releases, FORGE/ORBIT connection
* [Operations](docs/OPERATIONS.md) — production configuration, scaling, observability

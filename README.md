# NOVA — Personal AI Product Agent

> **One collaborator. One NOVA.** Express what you want to achieve; NOVA finds the context, picks the
> method, coordinates a team of specialist agents and delivers durable, editable product work.

NOVA is the personal product agent of the **ORION** ecosystem. It turns an intent into a plan, runs versioned
Skills and delivers structured, editable Artifacts (PRD, backlog, sprint plan…), even merged pull requests.

## Project snapshot

<!-- portfolio-summary:start -->

![NOVA project cover](docs/assets/github-cover.svg)

> **Agent orchestration** | **Status:** Public beta. Verify deployment status before relying on it.
>
> [Live application](https://nova-six-orcin-96.vercel.app) · [Architecture](docs/ARCHITECTURE.md) · [Demo / verification](docs/STATUS.md) · [Source code](https://github.com/yassineaqejjaj/NOVA)

[![GitHub Actions](https://github.com/yassineaqejjaj/NOVA/actions/workflows/ci.yml/badge.svg)](https://github.com/yassineaqejjaj/NOVA/actions/workflows/ci.yml)

[Technical case study and measurement plan](docs/PORTFOLIO_CASE_STUDY.md)

<!-- portfolio-summary:end -->

![NOVA — Today](docs/screenshots/today.webp)

NOVA is not a single chatbot: it is an **orchestrator** that understands an intent, grounds it in your real project
data, delegates to specialists, supervises the work and hands you a finished, reviewable deliverable.

---

## Table of contents

* [Why NOVA](#why-nova)
* [The product](#the-product)
* [How it works](#how-it-works)
* [Architecture](#architecture)
* [ORION: NOVA, ORBIT and FORGE](#orion-nova-orbit-and-forge)
* [What it does](#what-it-does)
* [Security and governance](#security-and-governance)
* [Production](#production) · [Quick start](#quick-start-docker) · [Development](#development-host)
* [Repository](#repository) · [Documentation](#documentation)

## Why NOVA

| Without NOVA | With NOVA |
|---|---|
| Product work starts from a blank page and scattered context | Every task is anchored in your real ORBIT project data, with your permissions |
| Generic prompts, inconsistent output | Versioned **Skills** with schemas and a quality bar, run by the right specialist agent |
| Output is a chat message you must copy somewhere | Output is a structured, versioned, editable **Artifact** with citations |
| Recurring work is asked again every week | **Routines** run on a schedule and drop the result in your Inbox |
| AI actions are opaque | Plans, approvals, provenance ("why did you include this?") and audit log |

## The product

### A product team, orchestrated

NOVA is the only agent you talk to. It frames the request, plans, delegates to specialists, supervises and assembles
the result. Work is organised in layers: **Orchestration** (NOVA), **Context** (a Research agent that brings ORBIT
context, with your rights) and **Specialists** (Product, Project, Design, Engineering — one agent per profile, each
owning its Skills). A Validation agent verifies every deliverable before it reaches you.

![The product team](docs/screenshots/product-team.webp)

### Today and Inbox — start the day with what needs a human

Today and the Inbox surface what needs you: questions, plans and milestones, deliverables to review, engineering runs
waiting at a gate (plan, merge — with the PR's preview link) and Artifacts whose cited ORBIT sources changed. The
Composer takes natural intent, `/skill` shortcuts, project, Auto / Explicit / No context, attachments, Artifact
references and ORBIT context pinning. Impact is tracked (time saved, tasks, deliverables, decisions).

### Skills — versioned product workflows

Strategy, discovery, prioritization, definition, delivery, analysis, communication: **Skills** are versioned
workflows that NOVA chooses and combines for you — you never have to pick one, but you can. Each Skill lives in
`skills/<name>/` with instructions, input/output JSON Schemas and an evaluation file (see
[`docs/SKILLS.md`](docs/SKILLS.md)).

![Skills](docs/screenshots/skills.webp)

### Engineering — an autonomous SDLC

Give NOVA an intent or a GitHub issue: it specifies, designs, codes, tests, opens the pull request, reviews it, repairs
CI and merges. **Guided** mode makes you validate the plan and the merge; **Autopilot** goes on its own up to the merge.
Bring your own LLM key and GitHub token (Settings). See [`docs/ENGINEERING.md`](docs/ENGINEERING.md).

![Engineering](docs/screenshots/engineering.webp)

### Routines — work that should not be asked twice

Schedule recurring work (daily product pulse, weekly product brief, sprint preparation, backlog quality, weekly
product update, interview synthesis). NOVA runs it on schedule and delivers the result to your Inbox.

![Routines](docs/screenshots/routines.webp)

### Voice — hands-free

Speak to NOVA and listen to your daily brief. Speech recognition and voice use an external service (ElevenLabs);
confidential answers are never read aloud.

<p align="center"><img src="docs/screenshots/voice.webp" alt="Voice mode" width="720"></p>

### And also

* **Artifacts** — structured types defined in `artifacts/types/` (PRD, backlog, sprint plan…), Lexical editing,
  autosave, version history and compare, section-level AI regeneration, comments, citations, export.
  **Living Artifacts** check the ORBIT sources they cite against ORBIT's change feed (as the user) and offer to update
  only the affected sections — a proposed version, never applied silently.
* **Time Machine** — replay a finished run with the same sources, a fresh ORBIT retrieval or none, another
  allow-listed model or another agent's lessons, then compare side by side: cost, time, context and a before/after of
  every changed section. A replay never writes to external systems.
* **Transparency** — which ORBIT context was used (classification, freshness, relevance) and recorded provenance;
  never raw model reasoning.

## How it works

```text
Intent → ORBIT context → Plan → Skill selection → Execution → Validation → Artifact → (approval) → FORGE trace
```

1. **Understand** — the intent is classified (run a workflow, edit an Artifact, explain provenance, question…).
2. **Ground** — the Research agent retrieves relevant ORBIT context *as the user*, with classification and citations.
3. **Plan and delegate** — the task is decomposed into sub-objectives and routed to specialist agents; every step runs
   under the persona and quality bar of the agent owning its Skill, with live activity and timing.
4. **Validate** — the Validation agent verifies each deliverable (one revision when needed).
5. **Deliver** — a structured Artifact, with human-in-the-loop questions, confirmations and approvals when policy requires.
6. **Learn** — the execution is traced to FORGE for evaluation.

## Architecture

NOVA is a layered system: a Next.js front end, a FastAPI backend, a resumable LangGraph runtime executed by Celery
workers, and ports/adapters towards ORBIT (context), FORGE (evaluation), the LLM and third-party tools.

```mermaid
flowchart TB
    user(["👤 User"])

    subgraph web["Web — Next.js 15 · React 19 · Tailwind v4"]
        ui["Today · Inbox · Composer · Artifacts editor<br/>Engineering · Routines · Skills · Voice"]
        bff["/api proxy · OIDC BFF"]
    end

    subgraph api["API — FastAPI"]
        routers["Routers"]
        services["Services (use cases)"]
        sse["SSE live stream"]
        proto["NOVA Agent Protocol<br/>/v1/agents/…/runs"]
    end

    subgraph runtime["Worker — Celery + LangGraph"]
        orch["Orchestrator graph<br/>intent → context → plan → skills → execute → validate → artifact"]
        agents["Specialist agents<br/>Product · Project · Design · Engineering<br/>+ Research · Validation"]
        sdlc["Engineering SDLC<br/>spec → code → test → PR → review → CI repair → merge"]
        beat["Beat — routines, FORGE refresh, retention"]
    end

    subgraph core["Core — nova/"]
        domain["domain<br/>(pure models, rules, ports)"]
        skills["Skills registry<br/>skills/*"]
        arts["Artifact types<br/>artifacts/types/*"]
        adapters["Adapters<br/>orbit · forge · github · figma"]
    end

    subgraph data["State and infra"]
        pg[("PostgreSQL<br/>data + LangGraph checkpoints")]
        valkey[("Valkey<br/>broker + pub/sub")]
        kc["Keycloak<br/>OIDC · SSO · RBAC"]
        otel["OpenTelemetry"]
    end

    llm["LLM — vLLM / Ollama / OpenAI-compatible / Anthropic"]
    voice["Voice service<br/>STT · TTS"]
    orbit["ORBIT<br/>context · memory · ACL · citations"]
    forge["FORGE<br/>traces · evals · experiments"]
    gh["GitHub"]

    user --> ui --> bff --> routers
    kc -.-> bff
    routers --> services
    services --> pg
    services -- "enqueue" --> valkey --> orch
    orch --> agents
    orch --> sdlc
    orch <-->|checkpoints| pg
    orch -- "events" --> valkey --> sse --> ui
    beat --> valkey
    agents --> skills
    agents --> arts
    agents --> domain
    agents --> adapters
    adapters -- "context as the user" --> orbit
    adapters -- "traces, experiments" --> forge
    forge -- "evaluates via" --> proto
    proto --> orch
    sdlc --> gh
    agents --> llm
    ui --> voice
    orch --> otel -. "OTLP" .-> forge
```

Layering is enforced by tests (`tests/unit/test_architecture.py`): `domain` stays pure (no FastAPI, SQLAlchemy, httpx
or LangGraph), `agent` depends only on domain ports, and nothing outside `integrations` knows ORBIT or FORGE payload
shapes. The full execution model, data model and API are in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## ORION: NOVA, ORBIT and FORGE

| | Responsibility |
|---|---|
| **NOVA** acts | intent, planning, Skills, execution, Artifacts |
| **ORBIT** knows | context, memory, knowledge, permissions, citations ([repo](https://github.com/yassineaqejjaj/ORBIT)) |
| **FORGE** learns | traces, evaluation, regressions, improvement ([repo](https://github.com/yassineaqejjaj/FORGE)) |

NOVA never duplicates ORBIT or FORGE: it retrieves context **as the user** through ORBIT's API and is evaluated by
FORGE through FORGE's existing `nova` adapter. See [`docs/integration-analysis.md`](docs/integration-analysis.md)
for the contracts and the documented gaps.

### Who learns what

"FORGE learns" is a product shorthand. Nobody trains model weights:

| | Does | Does not |
|---|---|---|
| **FORGE** | evaluates executions (rules, judges, human feedback), runs baseline-vs-candidate experiments, produces evidence and feedback reports | does not change NOVA's behaviour by itself |
| **NOVA** | distils FORGE's evidence into short **lessons** (a versioned *policy* of instructions), deploys them through a proof gate, a canary and an approval, and can roll them back | does not fine-tune a model |
| **ORBIT** | keeps the **governed learnings** (validated memory, decisions) that NOVA retrieves as context, with their permissions and classification | does not evaluate NOVA |

See [`docs/TRAINING.md`](docs/TRAINING.md#who-learns-what) and the state of every link in [`docs/STATUS.md`](docs/STATUS.md).

## What it does

* **Composer** — natural intent, `/skill` shortcuts, project, Auto / Explicit / No context, attachments, Artifact references.
* **LangGraph runtime** — typed `NovaState`, conditional branching, retries, Postgres checkpoints, human-in-the-loop
  (questions, workflow confirmation, approvals), resumable background execution (Celery + Valkey), live SSE.
* **Multi-agent orchestration** — four sub-agents (Product, Project, Design, Engineering); task decomposition, routing to specialists, agent hand-offs, a Research agent for
  context, a Validation agent for quality, live supervision by NOVA.
* **Engineering (SDLC)** — specification, code, tests, pull request, review, CI repair and merge, with approval gates.
* **Skills and Artifacts** — versioned Skills and typed Artifacts loaded from `skills/` and `artifacts/types/`.
* **Transparency and security** — recorded provenance, Keycloak SSO, RBAC and ORBIT ACL propagation (see below).
* **Ports and adapters** — domain ports implemented by ORBIT, FORGE, GitHub and Figma adapters; LLM providers are
  swappable (vLLM, any OpenAI-compatible server, Anthropic).
* **Open source stack** — vLLM, PostgreSQL, Valkey, Keycloak, OpenTelemetry. Can run offline with a self-hosted model.
  See [`OPEN_SOURCE_COMPONENTS.md`](OPEN_SOURCE_COMPONENTS.md).
* **Quality** — unit and integration tests, Playwright end-to-end tests, Skills consistency check, lint and typecheck in
  CI; Nova Evals for quality evaluation.

## Security and governance

Keycloak OIDC/SSO, RBAC, ORBIT ACL propagation, C0–C3 classification awareness, tool registry, autonomy policy,
prompt-injection defenses, audit log, PII redaction. External actions always follow the company policy.

## Production

Live on **Vercel** (web) + **Railway** (API, worker, beat, Keycloak, Valkey, PostgreSQL):
<https://nova-six-orcin-96.vercel.app>, connected to the deployed ORBIT and FORGE. See
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the topology, variables, release process and how to connect FORGE.
Kubernetes manifests are described in [`infrastructure/kubernetes/README.md`](infrastructure/kubernetes/README.md).

## Quick start (Docker)

Prerequisites: Docker (Compose v2). ORBIT and FORGE run from their own repositories.

```bash
cp .env.example .env
docker compose up -d --build                 # postgres, valkey, keycloak, api, worker, beat, web, voice
docker compose exec api python -m nova.seed  # demo data (Yassine · Head of AI, projects NOVA/ORBIT/FORGE)
```

Open <http://localhost:3200> and sign in with Keycloak user **`yassine`** / password `NOVA_DEMO_PASSWORD`
(`nova-demo` by default). Then **Settings → ORBIT** to link your ORBIT account (local ORBIT demo:
`camille.martin@nordalis.example` / `orbit-demo`).

### Inference

NOVA needs an OpenAI-compatible server:

| Setup | Settings |
|---|---|
| GPU (vLLM, recommended) | `docker compose --profile gpu up -d vllm` · `NOVA_LLM_PROVIDER=vllm` · `NOVA_LLM_BASE_URL=http://vllm:8000/v1` · `NOVA_LLM_MODEL=Qwen/Qwen2.5-7B-Instruct` |
| Laptop (Ollama on the host) | `NOVA_LLM_PROVIDER=openai_compatible` · `NOVA_LLM_MODEL=qwen3:8b` · `NOVA_LLM_BASE_URL=http://localhost:11434/v1` (host processes) · `NOVA_DOCKER_LLM_BASE_URL=http://host.docker.internal:11434/v1` (containers) |

`.env` describes the host; inside Compose, `NOVA_DOCKER_*` variables (`AUTH_MODE`, `ORBIT_BASE_URL`, `FORGE_BASE_URL`,
`LLM_BASE_URL`) provide the container-network equivalents — ORBIT and FORGE are reached through `host.docker.internal`.
Other options (for example the Anthropic provider) are described in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

Optional Compose profiles: `gpu` (vLLM), `cpu-llm` (Ollama in a container), `observability` (Jaeger).

### Local URLs

| URL | Service |
|---|---|
| <http://localhost:3200> | NOVA (web) |
| <http://localhost:8200/api/v1/docs> | API (OpenAPI) |
| <http://localhost:8200/v1/agents/nova-orchestrator/runs> | NOVA Agent Protocol (called by FORGE) |
| <http://localhost:8280> | Keycloak (admin / `KEYCLOAK_ADMIN_PASSWORD`) |

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

## Tests and lint

```bash
uv run pytest                                   # unit + integration (SQLite, in-memory checkpointer)
NOVA_DATABASE_URL=postgresql+asyncpg://nova:nova@localhost:5435/nova_test uv run pytest   # real Postgres checkpointer
uv run ruff check . && uv run ruff format --check .
uv run python -m nova.skills.build --check      # Skills consistency
npm run typecheck && npm run lint               # web
npm run test:e2e                                # Playwright (starts API, web and test doubles for LLM/ORBIT)
```

The same checks run in CI (`.github/workflows/ci.yml`).

## Repository

```text
apps/web            Next.js 15 · React 19 · Tailwind v4 · shadcn/ui (packages/ui) · TanStack Query · Zustand · Lexical · Framer Motion
apps/api            FastAPI app (nova_api): auth (OIDC BFF), routers, SSE, NOVA Agent Protocol
services/worker     Celery (nova_worker): executions, schedules, FORGE refresh, retention
services/voice      Speech-to-text / text-to-speech service (nova_voice)
nova/               core: domain · agent (graph, nodes, tools, providers) · skills · artifacts · integrations/{orbit,forge,figma,github} · infra · services
skills/             Skills (skill.yaml, instructions.md, input/output JSON Schemas, evaluation.yaml)
artifacts/types/    Artifact type definitions
infrastructure/     docker, keycloak realm, kubernetes manifests, railway images
alembic/            database migrations
docs/               architecture, deployment, engineering, operations, skills, training, voice, integration analysis
tests/              unit, integration, support (test doubles)
```

## Documentation

* [`docs/STATUS.md`](docs/STATUS.md): what is implemented, tested, on `main` and deployed, per ORION link and key capability.
* [ADR 001 — federated identity (OIDC) and shared workspace/project](docs/adr/001-identite-federee.md) — framing and contracts only (in French), no authentication change
* [Contracts and traversal tests](docs/CONTRACTS.md) — protocol compatibility matrix, shared fixtures ORBIT → FORGE → NOVA
* [Integration analysis](docs/integration-analysis.md) — ORBIT & FORGE contracts, gaps, differences with the brief
* [Architecture](docs/ARCHITECTURE.md) — execution model, Skills, Artifacts, data model, API, security
* [Skills](docs/SKILLS.md) — writing and versioning Skills
* [Engineering (SDLC Autopilot)](docs/ENGINEERING.md) — features, roadmap, safety rails
* [Training with FORGE](docs/TRAINING.md) — every specialist agent re-trained on all its Skills, validated by FORGE experiments
* [Voice](docs/VOICE.md) — speech-to-text and text-to-speech
* [Figma design](docs/design-figma.md) — Figma design integration notes
* [Deployment](docs/DEPLOYMENT.md) — Railway + Vercel production setup, releases, FORGE/ORBIT connection
* [Operations](docs/OPERATIONS.md) — production configuration, scaling, observability
* [Open source components](OPEN_SOURCE_COMPONENTS.md) — third-party components used by NOVA

# NOVA — Architecture

> NOVA acts. ORBIT knows. FORGE learns.
>
> This document is the implementation contract. The integration facts it relies on are established in
> [`integration-analysis.md`](integration-analysis.md).

## 1–3. ORBIT, FORGE and the available contracts

See `integration-analysis.md` §1 (ORBIT), §2 (FORGE), §3 (gaps). Summary of the contracts NOVA uses:

| Direction | Contract | Status |
|---|---|---|
| NOVA → ORBIT | `POST /projects/{slug}/context`, `/ask`, `/context/requests/{id}[/feedback]`, `GET /projects`, `/changes`, `/search`, `/auth/login`, `/auth/me`, `POST /memory` (proposed), `POST /documents/text` | existing |
| FORGE → NOVA | NOVA Agent Protocol `POST /v1/agents/{nova_agent_id}/runs` (FAP v1 + `nova_agent_id`) | existing (FORGE `nova` adapter) — implemented by NOVA |
| NOVA → FORGE | `POST /agents`, `POST /agents/{id}/versions`, `POST /scenarios`, `POST /runs`, `GET /runs/{id}`, `POST /runs/{id}/human-evaluations`, OTLP `/v1/traces` | existing |
| NOVA → FORGE | observed production runs | **gap G-F1** (documented extension) |

## 4. NOVA architecture

```
                         ┌───────────────── NOVA ─────────────────┐
 Browser ── web (Next.js) ─┤ /api/* proxy → api (FastAPI)           │
                         │   routers → services → domain ← ports   │
                         │   SSE stream ◄── Valkey pub/sub         │
                         │   Celery tasks ──► worker (LangGraph)   │
                         │        │ NovaState checkpoints (Postgres)│
                         │        ├─ LLMProvider ──► vLLM (OpenAI-compatible)
                         │        ├─ ContextProvider ──► ORBIT      │
                         │        └─ EvaluationSink ──► FORGE      │
                         └─────────────────────────────────────────┘
 Keycloak (OIDC) ◄── BFF login                 OTel ──► OTLP collector / FORGE
```

Layering (enforced by tests in `tests/unit/test_architecture.py`):

* `nova/domain` — pure Pydantic models and rules (state, plans, skills, artifacts, permissions,
  ports as `Protocol`s). No FastAPI, SQLAlchemy, httpx, LangGraph.
* `nova/agent` — LangGraph graph, nodes, tools, LLM providers. Depends on `domain` ports only.
* `nova/skills`, `nova/artifacts` — registries loading the versioned specs from `/skills` and `/artifacts`.
* `nova/integrations/{orbit,forge}` — adapters implementing `domain` ports. Nothing outside
  `integrations` imports ORBIT/FORGE payload shapes.
* `nova/infra` — database (SQLAlchemy models, repositories), Valkey, Celery, security, telemetry.
* `nova/services` — use cases (conversations, executions, artifacts, projects, today, search…).
* `nova_api` (apps/api) — FastAPI routers, schemas, auth; `nova_worker` (services/worker) — Celery app.

One primary agent (the **NOVA Orchestrator**) with capability boundaries = Skill categories
(strategy, discovery, prioritization, definition, delivery, analysis, communication, artifact).
No agent-to-agent conversations.

## 5. LangGraph execution model

```
START → understand_intent ─┬─► retrieve_orbit_context ─► plan_execution ─► select_skills
                           │                                                    │
                           │        ┌─────────── request_user_input ◄── missing info (interrupt)
                           │        ▼                                           │
                           │   execute_skill ◄──────────────┐                   │
                           │        │ tool requests          │ next step         │
                           │        ▼                        │                   │
                           │   execute_tools ────────────────┘                   │
                           │        │ all steps done                             │
                           │        ▼                                            │
                           ├─► answer_question (provenance / Q&A, no artifact)   │
                           │                                                     │
                           └─► generate_artifact ─► request_approval (interrupt if policy)
                                                        ▼
                                                    finalize ─► emit_forge_trace ─► END
```

* **State**: `NovaState` (Pydantic, `nova/domain/state.py`) — typed, no free-form dicts for
  critical fields. Persisted by `AsyncPostgresSaver` (langgraph-checkpoint-postgres), thread id =
  `workflow_execution.id`.
* **Branching**: conditional edges on `IntentClassification.kind` (`run_workflow`, `edit_artifact`,
  `explain_provenance`, `question`, `smalltalk`) and on step outcomes.
* **Retries**: LangGraph `RetryPolicy` on LLM/ORBIT nodes (transient errors), Celery retries for
  infrastructure failures (worker crash, broker loss).
* **Human approval / user input**: `interrupt()`; resumed with `Command(resume=…)` via
  `POST /api/v1/executions/{id}/resume`.
* **Failures / partial completion**: each step persists its output; a failed step marks the task
  `failed` with completed steps and artifacts kept; `retry` resumes from the last checkpoint.
* **Background**: every execution runs in a Celery task; the API only enqueues and streams.
* **Progress**: nodes emit `ExecutionEvent`s (persisted in `execution_events`, published on
  Valkey `nova:exec:{id}`); the SSE endpoint replays from the DB then follows pub/sub. Progress is
  only what actually happened (no timers, no simulated steps).

## 5b. NOVA Core: orchestration of the agents

NOVA Core (the graph of §5) is the coordinator of the constellation NOVA / ORBIT / FORGE:

| Orchestration | What NOVA does | Where |
|---|---|---|
| Task planning | turns the intent into a task: goal, deliverables (artifact types), questions when inputs are missing | `understand_intent`, `plan_execution` |
| Objective decomposition | one step per Skill, each with a **sub-objective** (`goal`) and a reason (`rationale`) | `PlanOutput.steps[].goal` |
| Assignment & routing | each step goes to the specialist agent owning its Skill; the persona opens every prompt of the step | `skill.agent`, `agent_instructions` |
| Research | the **Research agent** retrieves the project context from ORBIT (as the user) | `retrieve_orbit_context` |
| Verification | the **Validation agent** runs the Skill's checks (FORGE rule types run locally: sections present, citations, length, no PII, every section filled) and grades its criteria with the model; on failure NOVA sends the step back **once** to the specialist with precise fixes, then re-checks | `validate_step`, `nova/agent/validation.py` |
| Inter-agent communication | after each deliverable, a **handoff** (summary + review notes) is passed to the next agent and shown | `_handoff`, `_previous_outputs` |
| Monitoring & supervision | live status, timing, validation and revisions per step; pause / continue / cancel; FORGE evaluates the whole run | plan block, `/tasks`, FORGE trace |

Each step's report (`task_steps.report`: goal, rationale, validation, handoff) is stored and exposed by `/tasks`.
`NOVA_VALIDATION_REVIEW=false` keeps only the deterministic checks (one model call less per step);
`NOVA_MAX_REVISIONS` (default 1) bounds the revisions.

## 5c. Sub-agents and profiles

NOVA is the **orchestrator**: it understands the request, retrieves context and plans the workflow. Each step is then
carried out by the **specialist sub-agent** that owns the step's Skill (`agent:` in `skill.yaml`;
`nova/domain/agents.py`): **Product** (value, outcomes, requirements), **Project** (delivery, plans, risks, roles,
status), **Design** (research, journeys, content, usability) and **Engineering** (architecture, interfaces, quality,
estimates). The agent is not a label: its mission and professional standards open the system prompt of every model
call of the step. Plan blocks and `/tasks` expose `agent`, `started_at` and `finished_at` per step; the UI shows the
orchestrator and its sub-agents live (`components/agents/sub-agents.tsx`), with each agent's current activity taken
from the progress lines of its step (`<step>:<sub-step>`).

The user's **profile** (`user_preferences.profile`, chosen in onboarding and Settings) selects the lead agent: the
planner prefers its Skills when several fit, and Home suggests its requests. Every profile can still use every Skill.

| Agent | Skills (examples) |
|---|---|
| Product | PRD, vision → backlog, OKRs, prioritization (RICE, WSJF, Kano…), metrics, release notes |
| Project | project charter, project plan, status report, RAID log, RACI, retrospective, sprint planning, risks, dependencies |
| Design | design brief, usability test plan, UX writing, design review, personas, journeys, research plans |
| Engineering | technical design, ADR, API design, test strategy, incident postmortem, effort estimation, NFRs |

## 6. Skill specification

A Skill is a **versioned product workflow**, stored as a directory under `/skills/<id>/`:

| File | Content |
|---|---|
| `skill.yaml` | `id, name, version (semver), category, summary, purpose, triggers[], inputs[] {name, description, required, ask}, expected_context {orbit_intent, scopes, source_kinds, token_budget, query_hint}, methodology {name, references, principles[]}, steps[] {id, title, instruction}, tools[], outputs {artifact_type, sections[]}, autonomy {external_writes}, composes_with[]` |
| `instructions.md` | Method guidance for the model (trust level: Skill instructions) |
| `input.schema.json` | JSON Schema of the inputs |
| `output.schema.json` | JSON Schema of the structured output (generated from the artifact type sections, kept in sync by test) |
| `evaluation.yaml` | Criteria + deterministic checks, mapped to FORGE rule types (`sections_present`, `citation_required`, `required_fields`, `no_pii`, …) |

The **Skill registry** loads, validates and content-hashes every Skill at startup and syncs
`skills`/`skill_versions` (a changed hash without a version bump is rejected). Routing =
deterministic candidate scoring (triggers, category, artifact type, project context) → the model
chooses **among candidates only** → ids validated. **Workflow composition**: the planner may chain
Skills (`composes_with` hints); the resulting workflow is persisted, visible and editable
(`PATCH /api/v1/workflows/{id}` before or between steps).

## 7. Artifact specification

Artifact **types** live in `/artifacts/types/<type>.yaml`: `type, name, description, sections[] {key, title, kind, item_kind?, description}`.
Section kinds:

* `rich_text` → `{"blocks": [{"type": "paragraph|heading|bullet|numbered|quote", "text", "citations": ["S1"]}]}`
  (portable block model; the Lexical editor converts to/from it).
* `items` → `{"items": [<item>]}` with typed item kinds defined once in `/packages/schemas/items/*.json`
  (requirement, story, epic, initiative, objective, key_result, metric, risk, dependency, assumption,
  decision, question, hypothesis, experiment, scored_item, checklist_item, milestone, journey_step,
  insight, persona_attribute…). Items have stable `id`s, optional `parent_id` (backlog hierarchy) and `citations`.

Artifact instance: `{id, type, title, status, version, project_id, sections: {key: SectionContent}, metadata}`.
Every save creates an immutable `artifact_versions` row (full content, `changed_sections`, author
`user|nova`, `skill_execution_id`, summary). Section-level AI updates touch only the requested keys.
Comments are anchored to `(section_key, item_id?)`. Citations resolve to `context_retrieval_references`.

## 8. Database schema (PostgreSQL, Alembic)

```
users(id, subject UNIQUE (OIDC sub), email, display_name, role, title, created_at, last_seen_at)
user_preferences(user_id PK, nova_name, avatar, tone, preferred_methods[], artifact_format,
                 default_autonomy, teams[], onboarding_completed_at, updated_at)
projects(id, slug UNIQUE, name, description, created_by, created_at, updated_at)
project_members(project_id, user_id, role owner|editor|viewer, source nova|orbit, PK)
project_references(id, project_id, system orbit|forge, external_id, label, url, created_at)
conversations(id, user_id, project_id?, title, created_at, updated_at, archived)
messages(id, conversation_id, role user|nova, created_at, execution_id?)
message_blocks(id, message_id, position, type, payload jsonb)
workflows(id, project_id?, created_by, objective, steps jsonb, source planned|user, created_at, updated_at)
workflow_executions(id, workflow_id?, task_id, thread_id, status, current_step, error, started_at, finished_at)
tasks(id, user_id, project_id?, conversation_id?, objective, status, autonomy, trace_id,
      progress_done, progress_total, scheduled_for?, created_at, started_at, finished_at)
task_steps(id, task_id, position, step_key, title, skill_id?, status, detail, started_at, finished_at)
skills(id PK text, name, category, current_version, summary, updated_at)
skill_versions(id, skill_id, version, content_hash UNIQUE(skill_id, version), spec jsonb, created_at)
skill_executions(id, task_id, step_id?, skill_id, skill_version, status, input jsonb, output jsonb,
                 model, tokens_in, tokens_out, duration_ms, error, created_at)
artifacts(id, type, title, status, project_id?, owner_id, conversation_id?, current_version,
          classification, created_at, updated_at)
artifact_versions(id, artifact_id, version, content jsonb, changed_sections[], author_type,
                  author_id?, skill_execution_id?, summary, created_at)
artifact_comments(id, artifact_id, section_key, item_id?, author_id, body, resolved, created_at)
context_retrieval_references(id, task_id?, conversation_id?, user_id, system 'orbit', project_slug,
                  retrieval_id, trace_id?, query, items jsonb (citation, ids, title, uri, classification,
                  score, date, excerpt), warnings[], max_classification, created_at)
tool_executions(id, task_id, skill_execution_id?, tool, input jsonb, output jsonb, status,
                approved_by?, duration_ms, error, created_at)
execution_events(id, task_id, seq, type, payload jsonb, created_at)  UNIQUE(task_id, seq)
feedback(id, user_id, rating useful|not_useful, comment, conversation_id?, message_id?, task_id?,
         skill_id?, skill_version?, artifact_id?, trace_id?, created_at)
integration_references(id, system, kind, nova_type, nova_id, external_id, data jsonb, created_at, updated_at)
orbit_accounts(user_id PK, orbit_user_id, orbit_email, clearance, token_ciphertext, expires_at, linked_at)
audit_events(id, actor_id?, action, target_type, target_id, summary, details jsonb, created_at)
```

No ORBIT knowledge is copied: `context_retrieval_references.items` keeps only what is needed to
display and cite what was *served* to this user (title, ids, uri, short excerpt) — retention is
configurable (`NOVA_CONTEXT_REFERENCE_RETENTION_DAYS`). No FORGE trace is duplicated: NOVA stores the
FORGE run id / scenario id in `integration_references`.

## 9. Main API contracts (`/api/v1`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/auth/login`, `/auth/callback`, `POST /auth/logout`, `POST /auth/dev-login` (dev only) | OIDC BFF |
| GET/PATCH | `/me`, `/me/preferences` | Identity, personal NOVA |
| POST/DELETE | `/me/orbit` | Link / unlink ORBIT account |
| GET | `/today` | Greeting data + contextual recommendations |
| GET/POST | `/conversations`, GET `/conversations/{id}` | Conversations with blocks |
| POST | `/conversations/{id}/messages` | Send an intent → `{message, task}`; execution starts |
| GET | `/executions/{task_id}/events` (SSE) | Live execution stream (replay + follow) |
| POST | `/executions/{task_id}/resume`, `/cancel`, `/retry` | Approval / answers / control |
| GET | `/tasks?status=`, `/tasks/{id}` | Work |
| GET/POST | `/projects`, GET `/projects/{id}`, `/projects/{id}/context` | Projects |
| GET | `/skills`, `/skills/{id}` | Skill catalog |
| GET/PATCH | `/workflows/{id}` | Visible, editable workflow |
| GET/POST | `/artifacts`, GET/PATCH `/artifacts/{id}`, GET `/artifacts/{id}/versions[/{v}]`, `/artifacts/{id}/compare?from=&to=`, POST `/artifacts/{id}/sections/{key}/regenerate`, GET/POST `/artifacts/{id}/comments`, GET `/artifacts/{id}/export?format=md|json`, GET `/artifacts/{id}/provenance` | Artifacts |
| GET/POST/DELETE | `/context?project=&q=`, `/context/references/{id}` | ORBIT context surface |
| POST | `/feedback` | Feedback |
| GET | `/activity`, `/search?q=` | Activity, global search |
| POST | `/v1/agents/{nova_agent_id}/runs` (root, not `/api`) | NOVA Agent Protocol for FORGE |

Errors: `{"detail": "...", "code": "...", "actions": [...]}` — never stack traces.

## 10. Monorepo structure

```
nova/
  apps/web            Next.js 15 + React 19 + Tailwind v4 + shadcn/ui + TanStack Query + Zustand + Lexical + Framer Motion
  apps/api            FastAPI app (nova_api): routers, schemas, auth
  services/worker     Celery app (nova_worker)
  nova/               Python core package: domain, agent, skills, artifacts, integrations, infra, services
    agent/{graph,nodes,state,tools,providers}
    integrations/{orbit,forge}
  skills/             Skill library (one directory per Skill)
  artifacts/types/    Artifact type definitions
  packages/schemas    JSON Schemas shared by backend and frontend (items, blocks, events)
  packages/config     Shared lint/TS config
  infrastructure/{docker,kubernetes,keycloak}
  tests/{unit,integration,e2e}
  docs/
  docker-compose.yml  .env.example  README.md  OPEN_SOURCE_COMPONENTS.md
```

The Python core lives in one package (`nova/`) used by both the API and the worker; the brief's
`agent/`, `integrations/`, `skills/`, `artifacts/` folders exist inside it (code) and at the root
(specs: `skills/`, `artifacts/types/`).

## 11. Security model

* **Authentication**: Keycloak OIDC Authorization Code + PKCE, handled by the API as a BFF. The browser
  only holds an httpOnly, SameSite=Lax `nova_session` cookie (NOVA-signed, short TTL, refreshed).
  API clients may send a Keycloak access token (`Authorization: Bearer`, validated against JWKS,
  issuer and audience). `NOVA_AUTH_MODE=dev` enables a local dev login (refused when `NOVA_ENV=production`).
* **RBAC**: realm roles `nova-admin`, `nova-user`; project roles `owner|editor|viewer` (NOVA projects
  linked to ORBIT projects inherit the ORBIT membership role on sync). Every service call checks
  `Permission`s (`artifact.read`, `artifact.write`, `context.read`, `context.write_external`,
  `task.execute`, `admin.*`).
* **ORBIT ACL propagation**: ORBIT is always called as the user (delegated session) or on behalf of the
  user; NOVA never caches ORBIT content across users; C2/C3 content triggers warnings in the UI and
  the Artifact inherits the max classification of its sources.
* **Autonomy**: `suggest | assist (default) | execute_with_approval | execute_automatically`. Tools
  flagged `external_write` always require approval unless `NOVA_POLICY_ALLOW_AUTO_EXTERNAL_WRITES=true`
  (organization policy). Personalization can never lower policy.
* **Tool registry**: only registered tools; each declares input/output schema, permission, timeout,
  retry, audit behavior, `external_write`. A Skill may use only the tools it declares.
* **Prompt-injection defense**: trust hierarchy System → Organization → Skill → User → Retrieved context
  → Tool results, encoded in the system prompt; ORBIT content and tool results are wrapped as quoted
  data (`<data source=… trust="untrusted">`), scanned by an injection detector (flagged items are shown
  with a warning), and can never add tools, change autonomy or permissions (enforced in code, not in
  prompts). Citations are validated against the retrieval.
* **Secrets**: from env / Kubernetes secrets only; ORBIT session tokens encrypted with Fernet
  (`NOVA_SECRETS_KEY`); dev secrets refused in production.
* **Audit & retention**: `audit_events` for logins, links, executions, approvals, external writes,
  artifact changes; configurable retention for context references and execution events.
* **PII redaction** in logs and telemetry (`nova/infra/redaction.py`, configurable patterns), never
  log tokens.

## 12. Open-source dependencies

See [`OPEN_SOURCE_COMPONENTS.md`](../OPEN_SOURCE_COMPONENTS.md) (every runtime dependency, license,
purpose). No proprietary runtime dependency; the stack runs offline.

## 13. Implementation plan

Phases 0–9 of the brief, in order: integration analysis → foundation (monorepo, Docker, FastAPI,
Next.js, Postgres, Valkey, Keycloak, design system, schemas) → core (conversation, composer, SSE,
NovaState, LangGraph, LLM abstraction, vLLM) → ORBIT adapter → Skills → Artifacts → Work (Celery) →
FORGE → product polish → hardening.

## 14. Integration gaps

See `integration-analysis.md` §3 (G-O1…G-O6, G-F1…G-F5).


## Languages (EN / FR)

* **Interface** — `apps/web/src/lib/i18n`: each feature declares `defineMessages({ en, fr })` next to its code
  (TypeScript forces the French table to cover every English key) and reads it with `useT()`. Dates and relative
  times (`lib/format.ts`) follow the language. The language is a user preference (`user_preferences.language`,
  Settings → Language) applied on every device; without one, the browser language is used. The landing page shares
  the same preference.
* **Server text** — Home recommendations and Timeline events are produced in the user's language (`nova/i18n.py`,
  preference first, then `Accept-Language`).
* **Catalog** — display translations live in `artifacts/types/i18n/fr.yaml` (types, sections) and
  `skills/i18n/fr.yaml` (Skill names, summaries); the API returns them as `translations`. Prompts, schemas and
  Skill content hashes always use the canonical English definitions.
* **Content** — what users, ORBIT or the model write is never translated; NOVA answers in the language of the request.
* **Orb color** — `user_preferences.orb_color` (coral, rose, violet, ocean, emerald, amber, graphite), Settings → NOVA’s orb.

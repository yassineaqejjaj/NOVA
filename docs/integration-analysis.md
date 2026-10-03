# NOVA — Integration analysis (ORBIT & FORGE)

> Phase 0 deliverable. Written **after** inspecting the ORBIT and FORGE repositories, before any
> integration code. Where the NOVA brief and the existing code disagree, **the code wins** and the
> difference is recorded in §3.
>
> Repositories inspected (local clones, up to date with `origin/main` on 2026-10-03):
>
> | Repo | Remote | Commit |
> |---|---|---|
> | ORBIT | `github.com/yassineaqejjaj/ORBIT` | `999b539` |
> | FORGE | `github.com/yassineaqejjaj/FORGE` | `b7ac8cb` |
>
> Files read: `README.md`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/FEATURES.md` (ORBIT);
> `README.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_PROTOCOL.md` (FORGE); and the code that backs
> the contracts NOVA relies on (`app/deps.py`, `app/api/*`, `app/schemas/context.py`,
> `app/features/{feed,ask}` for ORBIT; `forge/adapters/{nova,base}.py`, `forge/api/deps.py`,
> `forge/api/schemas/{runs,agents,scenarios,api_keys,reviews}.py`, `forge/services/trace_ingest.py`,
> `forge/domain/{enums,defaults}.py` for FORGE).

---

## 1. ORBIT

### 1.1 Architecture

ORBIT is the governed **context and memory layer** for AI agents.

| Service | Tech | Role |
|---|---|---|
| `api` | FastAPI (Python 3.12) | REST `/api/v1`, MCP server `/mcp` (streamable HTTP), `/metrics`, `/health`, `/ready` |
| `worker` | same image | Ingestion pipeline (extract → PII → classify → chunk → embed → index → extract memory), Postgres `SKIP LOCKED` queue |
| `postgres` 17 | | Source of truth (documents, versions, chunks, memory, context requests, snapshots, audit, change events) |
| `opensearch` 2.19 | | BM25 (French analyzer) + k-NN |
| `valkey` 8 | | Short-term session memory (TTL) |
| `web` | Next.js 15 | ORBIT UI (host port 3000) |

Host ports: api `8000`, web `3000`, postgres `5433`, opensearch `9201`, valkey `6380`.
Fully self-hostable, works offline; an LLM is **optional** (OpenAI-compatible: vLLM, Ollama, LiteLLM).

### 1.2 Relevant services and APIs for NOVA

Base path `/api/v1`. JSON, `snake_case`. Errors are `{"detail": "<French message>", "code": "not_found|forbidden|validation_error|conflict|unauthorized"}`.
**All input models use `extra="forbid"`** — NOVA must never send unknown fields.

| NOVA need | ORBIT endpoint | Caller allowed |
|---|---|---|
| Governed context for a task (with citations, exclusions, warnings) | `POST /projects/{slug}/context` → `ContextPackage` | user session **or** project agent key |
| Feedback on a served context | `POST /projects/{slug}/context/requests/{id}/feedback` `{rating 1–5, comment?, item_flags?}` | user or agent |
| Re-read a past context package (provenance) | `GET /projects/{slug}/context/requests/{id}` | **user only** |
| Cited Q&A over project knowledge | `POST /projects/{slug}/ask` → `{answer, citations: ContextItem[], confidence, mode, request_id}` | user or agent |
| Pinned shared context | `GET /projects/{slug}/snapshots/{name}/{version}` | user or agent |
| Short-term session turns | `POST /projects/{slug}/sessions/{session_id}/turns` | user (editor) or agent |
| Propose a memory item (decision, requirement…) | `POST /projects/{slug}/memory` (agent ⇒ forced `proposed`) | editor or agent |
| Write an Artifact back as a document | `POST /projects/{slug}/documents/text` | editor or agent |
| Projects of the user | `GET /projects` → `ProjectSummary[]` | **user only** |
| Project overview (alerts, latest decisions) | `GET /projects/{slug}/overview` | **user only** |
| Change feed (Today recommendations) | `GET /projects/{slug}/changes?since=&types=` → `Page<ChangeEvent>` | **user only** |
| Hybrid search (Search, Add context) | `GET /projects/{slug}/search?q=&limit=` → `SearchHit[]` | **user only** |
| Memory list / detail with provenance | `GET /projects/{slug}/memory`, `GET /projects/{slug}/memory/{id}` | **user only** |
| Document detail | `GET /projects/{slug}/documents/{id}` | **user only** |
| Who am I in ORBIT | `GET /auth/me` → `User {id, email, full_name, clearance, is_admin}` | user |
| Meta (reason-code labels, models) | `GET /meta` | public |

The MCP server exposes the same core (`get_context`, `search_sources`, `propose_memory`, …) but only
with an agent key; NOVA uses REST (typed, richer payloads, user-session capable).

### 1.3 Authentication

* **Users**: email + password (argon2) → `POST /auth/login` sets an httpOnly cookie `orbit_session`
  containing an HS256 JWT (TTL `ORBIT_JWT_TTL_MINUTES`, default 720). `Authorization: Bearer <jwt>`
  is accepted too. The JWT is revoked if the password changes. **No OIDC / Keycloak** (on ORBIT's roadmap).
* **Agents**: API key `orb_<prefix8>_<secret32>` via `X-Orbit-Key` or `Authorization: Bearer orb_…`.
  **A key belongs to exactly one project** and gets role `editor` on it. It is only accepted on the
  endpoints declared `agents=True` (table above). An agent acts `on_behalf_of` a project member
  (ORBIT user UUID); without it, it only sees `project:*` content.

### 1.4 Retrieval mechanism

`POST /context` runs the governed assembly: understand → retrieve (BM25 + k-NN chunks, memory,
session, pinned snapshot) → RRF fuse → rerank → **govern** (FORGOTTEN → ACL → CLASSIFICATION → SCOPE →
EXPIRED → STALE → SUPERSEDED → LOW_SCORE) → select (conflicts, dedup, MMR, token budget) → compress →
package (Markdown with stable `[S1]…[Sn]` citations). Each served item is a `ContextItem`:

```
citation, candidate_type (chunk|memory|session), id, document_id?, memory_item_id?, title,
source_kind?, memory_kind?, memory_scope?, uri?, version?, excerpt, tokens, scores{…, final},
classification (0..3), date, pii_redacted, reason_code, reason_detail
```

The package also carries `request_id` (the retrieval ID NOVA stores), `trace_id`, `warnings`
(e.g. C2/C3 notices), `exclusion_summary`, `excluded` (redacted when the caller lacks access),
`tokens_used`, `timings`. `ContextRequestIn` accepts `task`, `intent` (`general|specification|design|engineering|research|analysis|validation`),
`token_budget` (500–32000), `scopes`, `source_kinds`, `max_classification`, `session_id`,
`base_snapshot`, `save_snapshot`, `explain`, `on_behalf_of`.

### 1.5 Permissions

* Project roles `owner ⊃ editor ⊃ viewer`; non-members get `404` (existence not revealed).
* Classification C0 Public, C1 Internal, **C2 Confidential, C3 Secret**: content is served only if
  `classification ≤ min(user clearance, agent clearance, request max_classification)`.
* Content ACLs (`project:*`, `role:owner|editor`, `user:<uuid>`) on documents, chunks, memory.
* Non-leak principle: ACL/classification exclusions are redacted for callers without access.
* PII is always redacted in served context (`pii_redacted: true`).

**Consequence for NOVA**: ACL propagation is achieved by **always calling ORBIT as (or on behalf of)
the end user**. NOVA never widens access and never caches ORBIT content across users.

### 1.6 Useful schemas

`ContextPackage`, `ContextItem`, `ExcludedItem`, `ProjectSummary`, `User`, `ChangeEventOut`
(`id, project_id, type, type_label, title, summary, target_type, target_id, classification, actor_label, created_at, data`),
`AskOut`, `SearchHit` (`chunk_id, document_id, document_title, source_kind, text, score, section, source_updated_at`),
`MemoryItem`. Change types: `memory.{created,validated,superseded,obsoleted,forgotten,conflict_detected,conflict_resolved}`,
`document.{ingested,new_version,forgotten,stale}`, `snapshot.created`, `connector.synced`.

### 1.7 Integration approach

`nova/integrations/orbit/` = `client.py` (HTTP, auth, error mapping), `schemas.py` (mirrors of the
ORBIT payloads NOVA consumes, `extra="ignore"` on input so ORBIT can add fields), `mapper.py`
(ORBIT → NOVA domain), `adapter.py` (implements NOVA's `ContextProvider` port).

* **Credentials** — resolved per user and per project by `OrbitCredentialResolver`:
  1. **Delegated user session** (preferred): during onboarding the user links their ORBIT account;
     NOVA's backend performs `POST /auth/login`, keeps only the returned session JWT (encrypted at rest,
     never the password), records its expiry, and uses it as `Authorization: Bearer`. This unlocks the
     user-only endpoints and gives exact ACL propagation.
  2. **Project agent key + `on_behalf_of`** (fallback / service mode): `ORBIT_AGENT_KEYS` maps an ORBIT
     project slug to the key of a "NOVA" agent created by the project owner; `on_behalf_of` = the
     user's linked ORBIT UUID. Only the agent endpoints are used in this mode.
* **Context retrieval** → `POST /projects/{slug}/context` with `explain=false`, `token_budget` from
  the Skill's `expected_context`, `intent` mapped from the Skill category, `session_id` = NOVA
  conversation id. The `request_id` is stored as `context_retrieval_references.retrieval_id`.
* **Citations** — NOVA keeps ORBIT's `[S#]` labels per retrieval; generated Artifact items cite those
  labels, NOVA validates them against the retrieval (unknown labels are dropped) and persists
  `{retrieval_id, citation, orbit item id, document_id/memory_item_id, title, uri, classification}`.
* **Today recommendations** → `GET /projects/{slug}/changes?since=` for each linked project, mapped
  by deterministic rules to suggested intents (see `integrations/orbit/mapper.py`).
* **Feedback** → user feedback on a message that used context is forwarded to
  `POST /context/requests/{id}/feedback` (`useful` → 5, `not useful` → 2).
* **Write-back** (approval-gated): proposing a decision to ORBIT memory (`POST /memory`, always
  `proposed`) and publishing an Artifact as a document (`POST /documents/text`).
* **Errors**: `401` → "ORBIT session expired, reconnect"; `403/404` → "insufficient permissions"
  (NOVA offers *Request access*, *Choose another source*, *Retry*); network → retryable.

---

## 2. FORGE

### 2.1 Architecture

FORGE is the **evaluation laboratory**. The central entity is the **Evaluation Run** = scenario
(version) + agent (version) + evaluation configuration + execution trace + evaluations + scores,
frozen in a reproducible manifest.

| Service | Role | Host port |
|---|---|---|
| `api` | REST `/api/v1`, **OTLP `/v1/traces`**, `/metrics` | 8100 |
| `runner-worker` | `execution` queue: calls the agents under evaluation | — |
| `evaluation-worker` | rules, LLM judges, scores, aggregations | — |
| `postgres` 17, `valkey` 8 | | 5434, 6381 |
| `web` | Next.js | 3100 |

Strict layering (`domain` is pure), French user-facing texts, every mutation audited.

### 2.2 Trace model

`ExecutionTrace` + ordered `TraceEvent`s (`seq` 1..n) of type
`run_started | context_prepared | reasoning | message | llm_call | tool_call | tool_result | retrieval | memory | agent_handoff | decision | error | final_answer | run_completed | custom`,
each with `name, started_at/ended_at, status, input, output, attributes{model, input_tokens, output_tokens, cost, tool, documents, agent, error_type…}`.
Traces reach FORGE three ways:

1. **Inline** in the agent's response to a FORGE call (FAP `events`, NOVA `handoffs`/`agents`).
2. **Pushed JSON**: `POST /api/v1/runs/{run_id}/events`.
3. **OTLP/HTTP**: `POST /v1/traces` (protobuf or JSON) with GenAI semantic conventions
   (`gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.*`, `gen_ai.tool.name`,
   `gen_ai.agent.name`, `forge.event.type`, `forge.documents`…). A span is attached to a run when its
   `trace_id` equals `run.otel_trace_id` (sent to the agent in `traceparent`) or it carries
   `forge.run_id`. **Spans without a matching run are counted as orphans and dropped**
   (`partialSuccess.rejectedSpans`).

### 2.3 Evaluation model

Rules (deterministic: sections present, citations, JSON schema, no PII, tool usage, latency, cost,
canaries…) + LLM judges (rubric, justification, evidence linked to trace events, confidence;
multi-judge aggregation) + human evaluations → criterion scores → 8 dimensions (quality, coherence,
reasoning, safety, robustness, cost, latency, **ux**) → composite with gates → error taxonomy →
`FeedbackReport` (machine-readable recommendations "consumable by NOVA"). Benchmarks (N×M×K),
experiments (baseline vs candidate with paired statistics and regression detection), calibration.
UX criteria include `ux.clarity`, `ux.correction_effort`, **`ux.perceived_usefulness`**.

### 2.4 Telemetry ingestion — the NOVA contract that already exists

FORGE already ships a **`nova` adapter** (`forge/adapters/nova.py`, protocol doc §6):

* FORGE calls `POST {nova_base_url}/v1/agents/{nova_agent_id}/runs` with the **FORGE Agent
  Protocol v1** body (`protocol, run_id, trace_id, repetition, attempt, scenario_version_id, input{prompt|messages}, context{documents[], facts[]}, constraints[], agent{name, slug, version, system_prompt, model, tools, parameters, memory, orchestration}, budget{max_tokens, max_cost, max_steps, timeout_seconds}`)
  + `nova_agent_id` + optional `options` (`adapter_config.nova_options`), with headers
  `traceparent`, `X-Forge-Run-Id`, `X-Forge-Scenario-Version`, `X-Forge-Repetition`, `X-Forge-Attempt`,
  `Authorization: Bearer <credential api_key>`.
* NOVA answers with FAP fields (`output`, `output_json`, `events`, `usage`, `cost`, `model`, `metadata`)
  + optional `handoffs[]` / `agents[]`.
* Errors: HTTP 4xx = definitive, 408/425/429/5xx = retryable, or `200 {"error": {type, message, retryable}}`.
* Same steps must not be reported both inline and via OTLP.

### 2.5 Authentication

Users: email/password → cookie `forge_session` (HS256 JWT). **API keys** `fgk_<prefix>_<secret>` via
`Authorization: Bearer` or `X-Forge-Key`, carrying a role (`viewer ⊂ evaluator ⊂ editor ⊂ maintainer ⊂ admin`),
a clearance (0–3) and optional scopes; a `["traces:write"]` key can only push traces. No OIDC.
FORGE stores the credential it uses to call NOVA (provider kind `nova`) encrypted.

### 2.6 Relevant schemas

`AgentCreateIn {name, slug?, description, provider, tags, metadata}`;
`AgentVersionCreateIn {version?, adapter_kind="nova", endpoint?, adapter_config{nova_agent_id, path?, nova_options?}, credential_id?, model?, system_prompt?, tools?, context_config?, orchestration_config?, budget?, metadata?, changelog}`
(immutable, content-hashed; identical version → `409`);
`ScenarioCreateIn {slug?, name, category, visibility, classification 0–3, tags, content{input, context{documents[]}, constraints, expected_behavior?, criteria?, rules?}}`;
`RunCreateIn {agent_version_id, scenario_ids|scenario_version_ids, repetitions, evaluation_config_id?, tags}` → `RunOut[]`
(`status`, `composite_score`, `passed`, `gate_failed`, `error_type`, `latency_ms`, `cost`, `total_tokens`);
`GET /runs/{id}/feedback` (FeedbackReport); `HumanEvaluationIn {scores[{criterion_key, score, comment?}], comment?}`
on `POST /runs/{id}/human-evaluations` (role evaluator+).

### 2.7 Integration approach

`nova/integrations/forge/` = `client.py`, `schemas.py`, `mapper.py`, `adapter.py`, plus the inbound
protocol router `apps/api/nova_api/routers/forge_protocol.py`.

1. **Inbound — NOVA Agent Protocol (existing contract, implemented as-is)**: NOVA exposes
   `POST /v1/agents/{nova_agent_id}/runs`. `nova_agent_id` identifies a NOVA agent profile
   (`nova-orchestrator` = the standard NOVA runtime). NOVA runs the **same LangGraph** with the
   FORGE-prepared context (FORGE context, not ORBIT — reproducibility), `autonomy=execute_automatically`,
   no external writes, and returns `output` (Markdown rendering of the Artifact), `output_json`
   (the structured Artifact), inline `events` (`retrieval`, `decision` for Skill selection, `llm_call`
   with tokens, `tool_call`/`tool_result`, `error`), `usage`, `model`, `metadata{nova_version, skills[{id, version}], workflow, artifact_type}`.
   NOVA continues the incoming `traceparent` for its own OTel spans but does **not** export them to
   FORGE for those runs (no double counting). Auth: a NOVA service token configured in FORGE's `nova`
   credential (`NOVA_FORGE_INBOUND_TOKEN`).
2. **Agent registry sync**: NOVA registers itself (`POST /agents`, slug `nova`) and one immutable
   **agent version per NOVA release × model × Skill-catalog hash** (`adapter_kind=nova`,
   `adapter_config.nova_agent_id`, `metadata.skills{id: version}`). `409` = already registered.
3. **Outbound telemetry**: every NOVA execution produces OpenTelemetry spans with GenAI semantic
   conventions + `nova.*` attributes (intent, skill id/version, workflow, ORBIT retrieval ids, artifact
   ids, feedback). They are exported to `OTEL_EXPORTER_OTLP_ENDPOINT` (any OTLP backend). Pointing it
   at FORGE `/v1/traces` attaches spans only for FORGE-initiated runs (see gap G-F1).
4. **Production capture (existing APIs)**: per `FORGE_CAPTURE_POLICY` (`off | on_feedback | sampled | all`)
   a production execution is turned into a FORGE **scenario** (`category="nova-production"`,
   `visibility=public`, `classification` = max classification of the ORBIT context used, input = user
   intent, context = the ORBIT excerpts served, constraints = Skill expectations) and a **run** against
   the registered NOVA agent version. FORGE then calls NOVA back through (1) and evaluates.
   The FORGE run id/score is stored in `integration_references` and shown in Work ("FORGE evaluation state").
   Note: this is a *replay* evaluation of the same input/context, not of the exact production output.
5. **Feedback**: "Useful / Not useful" on a captured execution → FORGE human evaluation on
   `ux.perceived_usefulness` (5 / 1, comment = "What should NOVA improve?"). Not-useful feedback with
   `on_feedback` policy triggers the capture.

---

## 3. Integration gaps

| # | NOVA requirement | Existing capability | Missing capability | Recommended approach | Repository impacted |
|---|---|---|---|---|---|
| G-O1 | SSO: NOVA users authenticate with Keycloak/OIDC and ORBIT must enforce *their* ACL | ORBIT has its own email/password + HS256 JWT; agent keys with `on_behalf_of` | ORBIT cannot validate a Keycloak token; no token exchange | **Now (NOVA-only)**: delegated ORBIT session linked at onboarding, or agent key + `on_behalf_of`. **Recommended thin extension**: ORBIT accepts OIDC bearer tokens from the same Keycloak realm (JWKS validation, user matched by email) — already on ORBIT's roadmap ("Identité d'entreprise : Keycloak / OIDC") | ORBIT (`app/deps.py`, `app/security.py`) |
| G-O2 | One personal NOVA across many projects | Agent keys are bound to **one** project | No multi-project agent identity | Delegated user session covers all the user's projects; in service mode `ORBIT_AGENT_KEYS` holds one key per project | none (config) |
| G-O3 | Search ORBIT / show project list / Today feed with an agent identity | `GET /projects`, `/search`, `/changes`, `/overview`, `/memory/*` are **user-only** | Agent access to these endpoints | Use the delegated session; when absent, NOVA degrades (no Today feed, no search) and shows "Connect ORBIT" | none |
| G-O4 | Map NOVA user ↔ ORBIT user (for `on_behalf_of`) | `GET /auth/me` (user), `GET /users` (admin only) | Lookup by email for agents | Store `orbit_user_id` captured from `/auth/me` when the account is linked | none |
| G-O5 | "Why did you include this requirement?" provenance | `ContextItem` carries ids, title, uri, excerpt, classification; `GET /context/requests/{id}` (user only) | — | NOVA stores the cited items per Artifact item at generation time; re-reads the ORBIT request when a session exists | none |
| G-O6 | Recommendations such as "Sprint planning is tomorrow" | No calendar/ceremony data in ORBIT | Calendar/sprint calendar source | Not faked: only change-feed, overview alerts and NOVA's own state drive recommendations. A calendar connector would belong in ORBIT | ORBIT (future connector) |
| G-F1 | **NOVA emits production execution telemetry to FORGE** | OTLP ingestion attaches spans only to FORGE runs; orphans are dropped | Ingestion of *observed* (production) executions | **Now**: production capture = scenario + replay run via existing APIs (§2.7-4); OTel spans exported to any OTLP backend. **Recommended thin extension**: an `observed` run origin (`RunOrigin.production`) created from an external trace (`POST /api/v1/runs/observed` taking an agent version, an input, the produced output and FAP events), evaluated by the unchanged pipeline (it already reads trace + manifest) | FORGE (`domain/enums.py`, `services/runs.py`, `api/routers/runs.py`) |
| G-F2 | Skill-level evaluation and comparison | Agent versions are content-hashed; `metadata` and `orchestration_config` are free-form | First-class "Skill" dimension in FORGE analytics | NOVA puts `{skill_id: version}` in agent-version `metadata` and run `tags` (`skill:<id>@<version>`); FORGE results can be filtered by tag. A first-class skill filter would be a FORGE analytics change | FORGE (analytics, optional) |
| G-F3 | Link NOVA user feedback to evaluation | Human evaluations need role `evaluator+`; `ux.perceived_usefulness` criterion exists | — | NOVA's FORGE key has role `evaluator` (or `editor`); feedback mapped to that criterion on the captured run | none |
| G-F4 | Model / model version in traces | `ModelSpec` on agent versions; `gen_ai.request.model` on spans | — | NOVA registers model id per agent version and sets GenAI attributes on spans | none |
| G-F5 | FORGE calling NOVA needs NOVA auth | FORGE sends `Authorization: Bearer <credential api_key>` | — | NOVA validates a static service token (`NOVA_FORGE_INBOUND_TOKEN`) on the protocol route only; executions run as a dedicated service principal with no ORBIT write tools | none |

### 3.1 Differences between the NOVA brief and the code (code wins)

* The brief suggests `ORBIT_BASE_URL` / `FORGE_BASE_URL`; ORBIT and FORGE use `ORBIT_*` / `FORGE_*`
  prefixes for their own settings. NOVA uses `NOVA_ORBIT_BASE_URL` / `NOVA_FORGE_BASE_URL` (all NOVA
  settings are `NOVA_*`-prefixed) to avoid clashing when the stacks share an `.env`.
* The brief says "FORGE should receive the relevant trace information". FORGE today only evaluates
  runs it orchestrates (G-F1); NOVA therefore uses replay capture and documents the extension instead
  of inventing a parallel trace store.
* The brief's Keycloak SSO cannot extend to ORBIT/FORGE yet (G-O1). NOVA itself uses Keycloak.
* ORBIT and FORGE user-facing texts are **French**; NOVA displays ORBIT warnings/labels verbatim.
* Port allocation: ORBIT 3000/8000, FORGE 3100/8100 → NOVA uses **web 3200, api 8200**, postgres 5435,
  valkey 6382, keycloak 8280.
* Both platforms enforce classification C0–C3 and show a C2/C3 warning banner; NOVA does the same
  for any context or Artifact that contains C2 (Confidential) or C3 (Secret) material.

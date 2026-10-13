# NOVA — status of the ORION links and key capabilities

> One row per link or capability. **Implemented / tested / on `main` / deployed** are four different facts: a feature
> can be coded and tested yet not released. This matrix is filled as of **13 October 2026** and updated at every release.

## How to read it

| Column | Meaning |
|---|---|
| **Implemented** | the code exists on the integration branch `preprod` (a short PR reference says which change introduced it) |
| **Tested** | an automated test covers it (file named), and CI on the PR was green |
| **On `main`** | the code is on `main` (commit `b7d8be1`, 13 October 2026, before the freeze) |
| **Deployed** | running in production. **Nothing has been deployed since the freeze started**: what is *not* on `main` is **not deployed**. What is on `main` is expected to be live (NOVA's `api`, `worker`, `beat` and the web app deploy on every merge to `main`, see [`DEPLOYMENT.md`](DEPLOYMENT.md)) but this document did not re-check production; a feature that ships disabled is marked *off by default* |

Freeze rule: pre-production only. Changes below marked "preprod only" go to production with the Friday-morning release.

## ORION links

| Link | Implemented | Tested | On `main` | Deployed |
|---|---|---|---|---|
| **NOVA → ORBIT**: context retrieval as the user (delegated session, ACL propagation, citations) | yes | `tests/unit/test_orbit_contract.py`, `test_orbit_snapshots.py`, e2e | yes | yes (expected) |
| **NOVA → ORBIT**: pinned snapshots, projects, changes, search, overview | yes | `tests/integration/test_orbit_snapshots.py`, `tests/unit/test_orbit_snapshots.py` | yes | yes (expected) |
| **NOVA → ORBIT**: write-back (memory proposals, text documents), behind the approval policy | yes | `tests/unit/test_policy_and_tools.py` | yes | yes (expected) |
| **ORBIT identity**: effective mode, session expiry, clearance, last exchange, **signalled and audited switch to the project agent key** (`/me/links`, Settings → Links) | yes (NOV-93) | `tests/unit/test_orbit_link_health.py`, `tests/integration/test_links_api.py`, e2e `Settings → Links` | no (preprod only) | no |
| **ORBIT `GET /agents/self`** (validate the project key, its scope and clearance) | NOVA side only, read defensively (404/403 = "not available") | `tests/unit/test_orbit_link_health.py` | no | no. The ORBIT endpoint itself is a separate ORBIT change and **is not delivered by this work** |
| **ORBIT clearance enforced on derived content** (Artifacts, lists, replay, stored extracts; `NOVA_DEFAULT_CLEARANCE`) | yes (NOV-75) | `tests/integration/test_clearance.py` | no | no |
| **FORGE → NOVA**: NOVA Agent Protocol (FAP v1) | yes | `tests/integration/test_graph_execution.py`, `test_training.py` | yes | yes (expected) |
| **FORGE → NOVA**: C0–C3 classification kept on context FORGE hands over, unclassified read as C3 (NOV-68) | yes | `tests/integration/test_forge_classification.py`, `tests/unit/test_forge_provided_context.py` | no | no |
| **NOVA → FORGE**: agent registration, one immutable version per release × model × catalog | yes | `tests/unit/test_forge_connection.py`, `tests/integration/test_forge_endpoint.py` | yes | yes (expected) |
| **NOVA → FORGE**: one callback endpoint and credential for capture, training and SDLC, with explicit configuration errors (NOV-70); release label that distinguishes the model (NOV-71) | yes | `tests/unit/test_forge_connection.py`, `tests/integration/test_forge_endpoint.py`, `tests/unit/test_forge_production.py` | no | no |
| **NOVA → FORGE**: capture by **re-execution** (replay), default | yes | `tests/integration/test_improvement.py`, `test_feedback_regression.py` | yes | yes (default mode) |
| **NOVA → FORGE**: **observed** production runs (`NOVA_FORGE_CAPTURE_MODE=observed`) | yes | `tests/integration/test_observed_capture.py`, `tests/unit/test_forge_production.py` | yes | shipped **off by default**: enabling it is an operations step ([`DEPLOYMENT.md`](DEPLOYMENT.md)) |
| **NOVA → FORGE**: SDLC runs ingested as observed runs (`NOVA_FORGE_SDLC_INGEST`) | yes | `tests/integration/test_sdlc.py`, `test_sdlc_improvement.py` | yes | yes (expected) |
| **NOVA → FORGE**: user feedback as human evaluation; an unhelpful rating promoted to a regression scenario | yes | `tests/integration/test_feedback_regression.py` | yes | yes (expected) |
| **FORGE link health** (last exchange, endpoint, credential present, callback problems; administrators) | yes (NOV-93) | `tests/unit/test_forge_link_health.py`, `tests/integration/test_links_api.py` | no | no |
| **FORGE → NOVA protocol pinning**: executed version reported, received budgets applied, unsupported overrides refused (NOV-72) | PR #35 **open**, not in `preprod` at the time of writing | its own tests (`tests/integration/test_forge_protocol_pinning.py`), CI of the PR | no | no |
| **Classification ceiling on output to LLMs** (`NOVA_LLM_MAX_CLASSIFICATION`, BYOK, voice) (NOV-76) | PR #34 **open**, not in `preprod` at the time of writing | its own tests (`tests/integration/test_llm_guardrail.py`), CI of the PR | no | no |
| **FORGE capture outbox** (queue of captures when FORGE is unreachable) | **not in `preprod` at the time of writing** (separate ticket); the links screen shows the queue as "not available" | — | no | no |
| **FORGE calibrated promotion gate** (FORGE side of the proof NOVA asks for) | **not in NOVA's scope here**; NOVA's gate sits behind an interface and is tested against a fake FORGE | `tests/unit/test_policy_gate.py` | no | no |

## Key capabilities

| Capability | Implemented | Tested | On `main` | Deployed |
|---|---|---|---|---|
| **Training loop** (FORGE experiments, promotion by `promotion_decision`) | yes | `tests/integration/test_training.py` | yes | yes (expected) |
| **Releases**: canary → verdict → approval → rollback; FORGE health watch of live releases | yes | `tests/integration/test_releases.py` | yes | yes (expected); watch needs observed capture, off by default |
| **Proof before activation** (policy gate: gain, no regression, independent evaluations, fail-closed; `NOVA_POLICY_GATE_MODE`, default `warn`) (NOV-85) | yes | `tests/unit/test_policy_gate.py`, `test_training.py`, `test_sdlc_improvement.py` | no | no. In `enforce` the SDLC agent has **no proof source yet** (needs FORGE's gate): keep `warn` |
| **SDLC Autopilot** (spec → PR → review → CI → merge → release) | yes | `tests/integration/test_sdlc.py`, e2e | yes | yes (expected) |
| **SDLC auto-merge requires a green CI**; tests written / executed / passed shown separately (NOV-84, `NOVA_SDLC_REQUIRE_CI`) | yes | `tests/integration/test_sdlc.py`, `tests/unit/test_sdlc_domain.py` | no | no |
| **SDLC self-improvement** (lessons from low-scored runs → policy → release) | yes | `tests/integration/test_sdlc_improvement.py` | yes | yes (expected) |
| **Generated files out of git** (`apps/web/.next-dev-auth`, a stray `apps/<home path>` copy) (NOV-92) | **not done**: stopped on a finding, see below | — | no | — |

### Why NOV-92 is not done

Untracking `apps/web/.next-dev-auth/` and `apps/Yassine AQEJJAJ/…` was stopped before any change, as planned for a finding:
the tracked dev build holds **Next.js preview-mode key material** (`previewModeId`, `previewModeSigningKey`,
`previewModeEncryptionKey` in `prerender-manifest.json`) and an **encryption key** in the server reference manifests. They
are random per-build development keys, not credentials of an external service, but they are committed; and
`apps/web/tsconfig.json` still lists `.next-dev-auth/types/**/*.ts` in `include`. Untracking does not remove them from
history. Decision needed from the team: untrack (and rotate nothing, the keys are throwaway) or also rewrite history.

## Settings introduced by this work

| Variable | Default | What it does |
|---|---|---|
| `NOVA_SDLC_REQUIRE_CI` | `true` | auto-merge needs a green CI; `false` restores "no CI is accepted". A run may opt in with `allow_merge_without_ci` ([`ENGINEERING.md`](ENGINEERING.md#merging-and-ci)) |
| `NOVA_POLICY_GATE_MODE` | `warn` | `enforce` holds a learned policy without out-of-production proof (also when FORGE is unreachable), `warn` records it and goes on, `off` skips ([`TRAINING.md`](TRAINING.md#proof-before-activation-the-policy-gate)) |
| `NOVA_POLICY_GATE_MIN_GAIN` | `0.02` | composite score (0–1) the candidate must gain |
| `NOVA_POLICY_GATE_MIN_EVALUATIONS` | `3` | independent scored runs per arm |
| `NOVA_FORGE_NOVA_ENDPOINT`, `NOVA_FORGE_CREDENTIAL_ID` | empty | how FORGE calls NOVA back: required and validated, one resolution for capture, training and SDLC (NOV-70); shown in Settings → Links for administrators |
| `NOVA_DEFAULT_CLEARANCE` | `1` | clearance (0–3) of a user with no linked ORBIT account, for derived content (NOV-75) |
| `NOVA_POLICY_MAX_CLASSIFICATION` | `3` | context above this level is refused, including context FORGE hands over (NOV-68) |
| `NOVA_ORBIT_AGENT_KEYS` | empty | `slug:key` per project; when a session expires NOVA falls back to it, now signalled and audited (NOV-93) |

## Updating this matrix

At every release: re-read `origin/main` and `origin/preprod`, flip *On `main`* for what was merged, and only flip
*Deployed* once the release is live and its health endpoint answers. A row is never "deployed" because it is "on main"
alone: say how it was checked.

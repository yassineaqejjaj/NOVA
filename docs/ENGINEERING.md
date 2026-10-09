# NOVA for engineering — autonomous SDLC

Goal: from a one-line intent (or a GitHub issue) NOVA carries a change through the whole software development
lifecycle — **specify → design → implement → test → pull request → review → CI (with self-repair) → merge → release →
deploy** — pausing only where a human decision is wanted.

## Main features for engineering users

| # | Feature | SDLC phase | Status |
|---|---|---|---|
| 1 | **Your own model** — bring your LLM API key (Anthropic, OpenAI, Google Gemini, Mistral, OpenRouter, any OpenAI-compatible endpoint); encrypted, per user, tested before saving | all | ✅ v1 |
| 2 | **GitHub connection** — personal access token, encrypted, scopes checked; repositories listed from Settings | all | ✅ v1 |
| 3 | **Spec** — user stories, acceptance criteria, scope, risks, open questions (from an intent or a GitHub issue) | requirements | ✅ v1 |
| 4 | **Technical design** — approach, files to read and change, test plan, risks, from the real repository tree | design | ✅ v1 |
| 5 | **Implementation** — NOVA reads the relevant files, writes the change set, commits it on a `nova/…` branch (never on the default branch) | build | ✅ v1 |
| 6 | **Tests** — unit/integration tests written in the project's own conventions and committed with the change | test | ✅ v1 |
| 7 | **Pull request** — title, description with acceptance checklist and test plan | build | ✅ v1 |
| 8 | **AI code review** — diff review with severity-ranked findings, posted on the PR; blocking findings are fixed automatically (2 rounds max) | review | ✅ v1 |
| 9 | **PR review on demand** — review any existing pull request by URL, optionally posting the review | review | ✅ v1 |
| 10 | **CI watch & self-repair** — NOVA waits for checks, reads failures and annotations, pushes a fix (2 rounds max) | test / integrate | ✅ v1 |
| 11 | **Guarded merge** — always asks for approval unless you opted in to auto-merge (green CI + no blocking finding) | integrate | ✅ v1 |
| 12 | **Release notes & GitHub release** — notes from the merged change, draft release | release | ✅ v1 |
| 13 | **Deploy hook** — trigger your deployment webhook (explicit action) | deploy | ✅ v1 |
| 14 | **Bug-fix mode** — root-cause analysis first, regression test required | operate | ✅ v1 |
| 15 | **Autonomy levels** — *Guided* (approve the plan and the merge) or *Autopilot* (only the merge) | governance | ✅ v1 |
| 16 | **Run evaluation** — success rate, merged rate, CI green first time, CI repairs and review fixes per run, your interventions, tokens and time per run, where runs stop, by model (Engineering → Performance, `GET /api/v1/sdlc/metrics`) | governance | ✅ |
| 17 | **Audit & safety rails** — every external write audited; `.github/workflows`, secrets, lock files and path traversal refused; branch-only writes; classification warning when an external model is used | governance | ✅ v1 |

## Roadmap

| Release | Theme | Content |
|---|---|---|
| **v1 — Autopilot (shipped)** | End-to-end loop on GitHub | Everything above |
| **v1.1** | Sandbox | Run tests/linters in an isolated container before pushing; stack-aware (npm, pytest, go) so CI is confirmed, not only awaited |
| **v1.2** | More forges & trackers | GitLab and Bitbucket, Jira/Linear issue import and status sync, Slack notifications |
| **v1.3** | Operate | Incident intake from Sentry/Datadog alerts → bug-fix run, post-mortem artifact, deploy verification and automatic rollback proposal |
| **v2.0** | Team-scale delivery | Multi-repo changes, monorepo awareness, parallel runs, per-team budgets and model routing, FORGE ingestion of runs (see below) |

## How it works

```
Intent / issue ─► Spec ─► Design ─(approve, guided)─► Implement ─► Tests ─► Pull request ─► Review ─► CI ─► (approve) Merge ─► Release ─► Deploy
                                                         ▲                         │ blocking findings        │ red checks
                                                         └────────── fix commit ◄──┴──────────────────────────┘ (≤ 2 rounds each)
```

* A **run** (`sdlc_runs`) holds the goal, the repository, the autonomy level and one entry per stage (status, summary,
  structured output). The Celery worker advances it one step at a time (`nova.sdlc_advance`); waiting for CI re-schedules
  itself instead of holding a worker.
* The **model** is the user's own when configured (Settings → AI model), else the organization default. Keys are
  encrypted with `NOVA_SECRETS_KEY` (Fernet) and never returned by the API (only the last four characters).
* **GitHub** access uses the user's token through the Git Data API (one atomic commit per step). NOVA only ever writes
  to its own `nova/*` branch, then to the pull request, comments, and (after approval) the merge.

## Safety

* Paths are validated (no `..`, no absolute paths, no `.git/`), `.github/workflows/`, `.env*`, keys and lock files are
  refused, size and file-count limits apply, and a rewrite that deletes most of an existing file is rejected.
* External writes are audited (`sdlc.*`). Merge needs approval unless the run was created with auto-merge.
* **Classification.** With an external model the repository excerpts and any context are sent to that provider.
  Do not run NOVA on C2 (confidential) or C3 (secret) code with an external provider key: Settings shows this warning
  and the API requires explicit acknowledgement when a key is saved.

## Evaluating runs

Each run carries its own evaluation, computed from the run record (`nova/services/sdlc_metrics.py`): outcome, merged,
CI green first time, CI repair rounds, review fix rounds, blocking findings, human interventions (approvals, retries),
tokens, model calls and duration. `GET /api/v1/sdlc/metrics?days=30` aggregates them per user: success rate (finished
runs, cancelled ones excluded), merged rate, first-pass CI rate, average repairs, average tokens and time to deliver,
failures by stage and results by model. Cost is expressed in tokens: provider prices change, so NOVA does not guess
a currency amount.

**FORGE ingestion (automatic).** When a run ends (completed or failed; a cancelled one is the user's choice) NOVA sends it
to FORGE once as an *observed run* (`POST /api/v1/runs/observed`, FORGE PR "observed runs", contract in FORGE
`docs/OBSERVED_RUNS.md`), idempotent on `external_id = nova-sdlc:<run id>`. FORGE scores it with its own pipeline; NOVA
keeps the link and the score and shows them on the run and in Performance (average FORGE score, pass rate).

* **What is sent**: outcome, delivery metrics (CI/review repairs, interventions, tokens, duration), stage summaries
  (400 characters each), the goal and repository name, with e-mail/secret redaction. **Never code, diffs or file
  contents** (repositories may be C2/C3).
* **Scoring**: the scenario `nova-sdlc-delivery` carries five rules on the result — delivered, merged, CI green first
  time, no review fix needed, ≤ 2 human interventions — and the configuration `nova-delivery` has no LLM judge, weights
  quality 0.8 / autonomy 0.2, pass threshold 70, and caps an unmerged change at 60. NOVA creates both once. The
  configuration needs the FORGE **maintainer** role: with an `editor`/`evaluator` key NOVA falls back to FORGE's default
  configuration (LLM judges) and says so in the log.
* **Resilience**: FORGE being down or older never affects a run; `nova.sdlc_forge_sync` (every 5 min) retries what was
  not sent and refreshes scores, and pauses while FORGE answers 404/405 on the endpoint.
* Disable with `NOVA_FORGE_SDLC_INGEST=false`. Needs `NOVA_FORGE_API_KEY` (already used by the existing capture).

## Continuous improvement of the engineering agent

When FORGE scores a run **below its threshold** (its own pass/fail verdict, else `NOVA_SDLC_IMPROVEMENT_THRESHOLD`,
70), NOVA improves its SDLC agent and deploys the result automatically. No model weights change: the agent's *policy* is
a versioned set of short lessons injected into the stage prompts (`agent_policies`, agent `sdlc`).

```
run finished ─► FORGE scores it ─► below threshold? ─► evidence ─► lessons ─► policy v(N+1) deployed
                                                          │                         │
                                  FORGE scores · errors · recommendations           ├─ new runs start with v(N+1)
                                  + NOVA facts (failed stage, repairs, findings)    ├─ FORGE gets them under agent version p(N+1)
                                                                                    └─ guard: clearly worse than v(N)? roll back
```

1. **Evidence** (never code): FORGE's per-criterion scores, classified errors and feedback recommendations for the run,
   plus NOVA's own facts — failed stage, CI/review repairs, interventions, blocking review findings (short, scanned for
   injection). Pending runs are processed together (up to 8), every 5 minutes (`nova.sdlc_forge_sync`).
2. **Lessons**: the run owner's model proposes at most 6 general, imperative lessons (≤ 240 characters) per pass, each for
   one stage (`spec`, `design`, `implement`, `tests`, `pull_request`, `review`, `fix`, `release`) or for all of them.
   Problems a prompt cannot fix (tooling, model, CI setup) become *advice for the team*.
3. **Filters** — a lesson applies to **every user's runs**, so it must be general: no URL, file path, secret, repository
   name or instruction-like text; duplicates and lessons already rejected by a rollback are dropped; at most 5 per stage and
   8 general ones (the oldest makes room).
4. **Deployment**: a new policy version is created and activated at once (`NOVA_SDLC_IMPROVEMENT_AUTO_DEPLOY=false` keeps it as
   a candidate for an administrator). A run snapshots the active policy when it is created, so it keeps its lessons even if a
   version is deployed meanwhile. FORGE receives the run under agent version `<nova>+p<N>+<model>` whose metadata lists the lessons:
   FORGE's agent view compares the scores version by version.
5. **Guard**: once the new version has ≥ 3 FORGE-scored runs (`NOVA_SDLC_IMPROVEMENT_ROLLBACK_MIN_RUNS`) and its average is more than
   10 points (`…_ROLLBACK_DROP`) below its parent's, it is rejected and the parent is back; its lessons are never proposed again.
   Administrators can also roll back or deploy a version by hand (Engineering → Continuous improvement, `POST /api/v1/sdlc/policy/...`).

Every deployment and rollback is audited (`sdlc.policy.activate`). Disable the whole loop with `NOVA_SDLC_IMPROVEMENT=false`.

**Why it is safe enough to be automatic.** Lessons are short sentences, filtered, bounded and reversible; the evidence is wrapped
as untrusted data and cannot reach the prompts except through those filters; and a version is judged by FORGE on real runs,
not by itself. What it cannot do: validate a lesson *before* deployment (an SDLC run cannot be replayed on a user's repository),
so validation is by observation, and a bad version can cost a few runs before the guard reverts it.

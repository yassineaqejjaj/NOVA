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

**FORGE.** FORGE evaluates runs it orchestrates and cannot ingest observed production executions yet (gap G-F1 in
`integration-analysis.md`); replaying an SDLC run through the NOVA Agent Protocol would re-run it against a real
repository. The figures therefore stay in NOVA and are exportable as JSON; forwarding them to FORGE needs the
`observed` run origin proposed in G-F1.

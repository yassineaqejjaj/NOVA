# Training NOVA's agents with FORGE

FORGE **evaluates** each specialist agent (Product, Project, Design, Engineering) on **every one of its Skills**;
NOVA **learns** from FORGE's feedback and applies a lesson **only after a FORGE experiment validated it**.
No model weights change: an agent's *policy* is a versioned set of lessons injected into its instructions, so
every change is measurable, explainable and reversible.

```
         ┌──────────── NOVA ────────────┐                    ┌──────────── FORGE ────────────┐
cycle →  │ policy vN (active)           │── agent version ─► │ nova-<agent> · pN             │
         │ 1 service scenario per Skill │── scenarios ─────► │ nova-train-<skill>-<hash>     │
         │                              │── baseline runs ─► │ runs ⇄ NOVA Agent Protocol    │
         │ distill feedback → lessons   │◄─ feedback ─────── │ rules + judges → reports      │
         │ policy vN+1 (candidate)      │── experiment ────► │ baseline vN vs candidate vN+1 │
         │ promote / reject             │◄─ comparison ───── │ ship · caution · inconclusive │
         └──────────────────────────────┘                    └───────────────────────────────┘
```

## Who learns what

"FORGE learns" is a product shorthand. No model weights change anywhere:

* **FORGE evaluates.** It scores executions (deterministic rules, judges, human feedback), compares a baseline and a
  candidate in an experiment, and produces evidence: scores, feedback reports, recommendations, release comparisons.
* **NOVA distils and deploys.** It turns that evidence into short, general **lessons**, a versioned *policy* injected
  into the agent's instructions, and ships it through the proof gate, the canary, the approval and the rollback below.
* **ORBIT keeps governed learnings.** Validated memory and decisions are retrieved by NOVA as context, with their
  permissions, classification and citations; ORBIT does not evaluate NOVA and NOVA does not rewrite ORBIT's knowledge
  (write-back is proposed and goes through the approval policy).

## What an agent learns

| Level | Where it goes | Example |
|---|---|---|
| **Skill lesson** | appended to the Skill's instructions, and checked by the Validation agent | "Give every acceptance criterion concrete example values." |
| **Agent standard** | a lesson found on ≥ 3 Skills of the agent, added to its professional standards | "State assumptions and open questions instead of inventing facts." |
| **Advice for the team** | FORGE recommendations a prompt cannot apply (retrieval, tools, model, orchestration, latency) | kept on the policy and shown in the UI, never applied automatically |

Lessons come from FORGE feedback reports: the deterministic recommendations (`system_prompt`, `output_format`,
`rule`, `context`; priorities P0/P1), optionally condensed by NOVA's model into short, general, imperative
lessons (max 5 per Skill, 6 standards per agent). Evidence excerpts are **never** copied into lessons.

## A cycle

`services/training.py`, advanced every 2 minutes by the worker (`nova.advance_training`); each step is idempotent.

1. **queued** — the agent's active policy (v0 the first time: no lessons) is registered in FORGE as agent
   version `p<version>.<catalog>` of agent `nova-<agent>`; each Skill gets its **service scenario**
   (`category=nova-training`, synthetic project *Relais*, C1, the Skill forced through `input.nova_skill`,
   the Skill's own criteria and checks as FORGE criteria and rules); FORGE runs the baseline → **evaluating**.
2. **evaluating** — once FORGE has evaluated every run, the reports are distilled into a **candidate** policy,
   registered as a new FORGE agent version, and a FORGE **experiment** baseline vs candidate is created on all
   the agent's scenarios (a lesson must not degrade the other Skills) → **experimenting**. Nothing to learn →
   **no_change**.
3. **experimenting** — when the experiment is finished:
   * `ship` → **promoted** (the candidate becomes active);
   * `ship_with_caution` → promoted only if the composite score improves and no scenario regresses critically;
   * `inconclusive`, `do_not_ship` → **rejected** (the active policy stays).

With `NOVA_TRAINING_AUTO_PROMOTE=false`, a validated candidate waits for an administrator (**validated**).
A cycle that does not finish within `NOVA_TRAINING_CYCLE_TIMEOUT_HOURS` fails; FORGE unavailability is retried.

Every execution snapshots the active policies at start (`NovaState.learning`, also stored on the task), so a
resumed execution keeps its lessons and FORGE knows which policy it evaluated (`metadata.policies`).

## NOVA Agent Protocol

| `nova_agent_id` | Runs |
|---|---|
| `nova-orchestrator` | the whole NOVA (planner + every specialist), active policies |
| `nova-product`, `nova-project`, `nova-design`, `nova-engineering` | one specialist alone: planning restricted to its Skills |

* `input.nova_skill` (passed through by FORGE) forces one Skill; it must belong to the agent.
* `options.policy_id` (from the agent version's `adapter_config.nova_options`) applies that policy instead of the
  active one, for its agent only.
* `context` keeps its classification (C0-C3): each `documents[]` entry may carry `classification`
  (`citation`, `document_id` and `version` are optional too), `context.max_classification` is the maximum FORGE
  prepared and `context.orbit_context` is ORBIT's assembled context text (a string, or `{text, max_classification}`),
  which the run reads as one more source. A source keeps its level (raised to `max_classification` when that is
  higher); **a document, fact or ORBIT text without a level is C3** (fail closed, never C1). The run, its Artifacts
  and its records then inherit that level, tools that write to an external system are withheld at C3, and context
  above `NOVA_POLICY_MAX_CLASSIFICATION` is refused (`403 CLASSIFICATION_REFUSED`). The training pack is not
  classified yet, so its runs read as C3 (harmless: synthetic data, no external write).
* NOVA's citation labels are rewritten for FORGE: `[S1]` → `[source: <FORGE document id>]`, the form FORGE's
  citation rules recognise (NOVA's own Artifacts are unchanged).

## Operating it

Settings (all `NOVA_*`, see `.env.example`):

| Setting | Default | |
|---|---|---|
| `FORGE_API_KEY` | — | FORGE key with role **editor** (creates agents, scenarios, runs, experiments) |
| `FORGE_CREDENTIAL_ID` | — | id of FORGE's `nova` credential (secret = `NOVA_FORGE_INBOUND_TOKEN`) |
| `FORGE_NOVA_ENDPOINT` | derived (local dev only) | NOVA API URL as reachable from FORGE's runner; the same URL is registered by production capture, training and SDLC ingestion. Required outside local development: the web URL is not the API |
| `TRAINING_ENABLED` | `true` | |
| `TRAINING_INTERVAL_DAYS` | `0` | `0` = cycles started by an administrator; `N` = automatic cycle per agent every N days |
| `TRAINING_REPETITIONS` | `1` | runs per Skill and per arm |
| `TRAINING_MAX_SKILLS` | `0` | `0` = every Skill of the agent (use a small value to try it out) |
| `TRAINING_AUTO_PROMOTE` | `true` | |

Cost per cycle ≈ (Skills × repetitions) baseline runs + 2 × (Skills × repetitions) experiment runs, each a
full NOVA execution plus FORGE's judges. With 33 Product Skills and 1 repetition: ~99 NOVA executions.

UI: **Team → Training with FORGE** (`/team/training`): active version, lessons per Skill, last scores, cycles
and their FORGE experiments, advice for the team. Administrators can start a cycle (one agent or all), cancel
it, apply a retired version again or restore the previous one. API: `GET /api/v1/training`,
`GET /api/v1/training/agents/{agent}`, `POST …/agents/{agent}/cycles`, `POST …/cycles`,
`POST …/cycles/{id}/cancel`, `POST …/agents/{agent}/rollback`, `POST …/policies/{id}/activate`.

## Data classification

Training scenarios use a **synthetic C1 project** only (`nova/domain/training_pack.py`): no ORBIT content is
sent to FORGE for training. Production captures (`NOVA_FORGE_CAPTURE_POLICY`) keep the classification of the
ORBIT context they used and are created **private** in FORGE when it is C2 (confidential) or C3 (secret).

---

## Proof before activation: the policy gate

The canary is a second line, not the first. Before a candidate meets any user, FORGE must have shown, **outside
production**, that it beats the active policy (`domain/policy_gate.py`, `services/policy_gate.py`). A candidate is judged on:

* a **minimal gain** on the composite score (`NOVA_POLICY_GATE_MIN_GAIN`, default 0.02 on a 0-1 scale);
* **no regression** on the validation scenarios (the promoted regression scenarios of FORGE are guard scenarios);
* a **minimal number of independent evaluations** per arm (`NOVA_POLICY_GATE_MIN_EVALUATIONS`, default 3);
* **independence**: scenarios (or runs) the lessons were made from never count as validation. The training loop
  validates on the Skills it did not learn from; the SDLC agent declares the FORGE runs behind its lessons.

`NOVA_POLICY_GATE_MODE` sets what a shortfall does:

| Mode | Candidate without sufficient proof |
|---|---|
| `warn` (default in pre-production) | the release goes on; the shortfall is kept in the release (`evidence.gate`) and audited (`release.gate_warning`) |
| `enforce` | **not activated**: the release is held `awaiting_proof` with the reasons (Team → Training, Engineering → Continuous improvement); no user is served it. **Fail-closed**: FORGE unreachable, or no proof source, counts as no proof |
| `off` | no check |

A held candidate is asked again at every improvement pass of the SDLC agent and released (canary, then approval) as
soon as the proof is sufficient; an administrator can also withdraw it (`POST /releases/{id}/rollback`) or apply the
version by hand. Generalisation (approval `full`) still only follows a healthy canary.

Status: the training loop's proof is real (its FORGE experiment). The SDLC agent has no replayable scenario yet:
its proof source (`providers.policy_proof_source`) is meant to be served by FORGE's calibrated promotion gate and is
**empty today**, so `enforce` holds every SDLC candidate until it is plugged in; keep `warn` until then.

## Releases: canary, approval, rollback

A candidate policy FORGE validated no longer reaches everyone at once (`services/releases.py`,
`domain/release.py`):

1. **Canary** — it is served to a *stable* share of users (`NOVA_RELEASE_CANARY_PERCENT`, default 10; the same
   user always gets the same version). FORGE evaluation calls and replays never see it.
2. **Verdict** — once the canary has `NOVA_RELEASE_CANARY_MIN_RUNS` final executions (default 20), its failure
   rate is compared with the other executions of the same period. More than
   `NOVA_RELEASE_MAX_FAILURE_INCREASE` (default +10 points) worse → **rolled back automatically**.
3. **Approval** — a healthy canary waits for an administrator (`NOVA_RELEASE_APPROVAL=full`, default) before
   reaching everyone; `none` lets it go live by itself. `NOVA_RELEASE_CANARY_PERCENT=0` skips the canary.
4. **Rollback** — an administrator can withdraw a release at any time; an active one gives way to the policy it
   replaced.

Every execution records the release it ran under (`tasks.release_id`, `run_manifest.release_id`, and per agent in
`run_manifest.policies`), and FORGE receives it with the run (`release:<id>` tag, `release_id` link). Applying a
policy by hand (`POST /training/policies/{id}/activate`) skips the canary — the human decision is the approval —
but is recorded as a release. API: `GET /releases`, `GET /releases/{id}`, `POST /releases/{id}/evaluate|approve|rollback`
(decisions are admin-only). The SDLC agent keeps its own guard (`services/sdlc_improvement.py`).

### Observed capture (`NOVA_FORGE_CAPTURE_MODE=observed`)

By default a captured execution is *re-executed* inside FORGE under whichever version is active at that moment:
its score says nothing about the release the user actually got. In `observed` mode FORGE instead receives what
really happened — outcome, skills, tokens, steps, the run manifest (agent version, snapshot, policies, release) —
as an observed run scored by deterministic rules on a small structured result (`nova-production` config; no answer
or context text, and no request text unless `NOVA_FORGE_CAPTURE_INTENT=true`). Failures are reported too. Releases can then be compared on real
traffic (FORGE `GET /analytics/releases/compare`).

> **What leaves NOVA.** Never the answer or the context. The user's request is sent (redacted of personal data) only
> with `NOVA_FORGE_CAPTURE_INTENT=true`; by default FORGE receives which Skills ran, not what was asked, because a
> request can hold confidential (C2) or secret (C3) material.

### FORGE watch of a live release

An activated release stays under watch for `NOVA_RELEASE_WATCH_DAYS` (default 7). Every 10 minutes the worker
asks FORGE (`GET /analytics/releases/compare`) to compare the release's **observed** runs with those of the
release it replaced (see *Observed capture*): only a *significant* drop in success rate or rise in failures, and
a minimum effect, counts; too few runs never raises an alert. In that case the release is **rolled back
automatically** (the previous policy is restored, the reason is kept and audited) unless
`NOVA_RELEASE_HEALTH_ROLLBACK=false`. Cost and latency rises are shown on the release but never withdraw it. Every
check is stored on the release (`evidence.health`) and shown on the training page. FORGE being unreachable changes
nothing. Runs are attributed to the release they were served under whether it was a canary or already active
(`tasks.release_id`); the canary's control group is everyone not served by that release.

### Checking the loop against a real FORGE

`tests/cross_instance/test_forge_roundtrip.py` drives NOVA against a **real** FORGE: 12 healthy executions under a
first release, 12 failing ones under a second, observed capture into FORGE, evaluation by FORGE's worker, FORGE's
release comparison and NOVA's automatic rollback. It is skipped unless a FORGE is reachable:

    NOVA_E2E_FORGE_URL=http://127.0.0.1:8101 NOVA_E2E_FORGE_KEY=fgk_… uv run pytest tests/cross_instance -q

The FORGE needs its API **and** a worker, a key with the admin role (the first capture creates the scenario and the
rules-only evaluation config) and a throwaway database: the test writes agents, scenarios and runs into it.

### The SDLC agent goes through releases too

A new SDLC policy (lessons learned from runs FORGE scored below its threshold) is no longer applied at once: with
`NOVA_SDLC_IMPROVEMENT_AUTO_DEPLOY` on, it starts a **release** like the chat agents' policies — a canary share of
users first (`NOVA_RELEASE_CANARY_PERCENT`), a verdict on the SDLC runs it served against the others
(`NOVA_RELEASE_CANARY_MIN_RUNS`, `NOVA_RELEASE_MAX_FAILURE_INCREASE`), then an administrator's approval
(`NOVA_RELEASE_APPROVAL`). Each run records the release it was served under (`context.policy.release_id`) and FORGE
receives it with the observed run, so the live release stays under FORGE's health watch and can be rolled back
automatically. The existing guard (FORGE score clearly below the parent's) and the admin endpoints still work and now
leave a release trail; `/releases` lists and decides SDLC releases like the others. With auto-deploy off the candidate
still waits for an administrator, whose manual activation is recorded as a release.

## Progress

`GET /api/v1/training/progress` (shown at the top of **Team → Agent training**) answers "is the system getting better?" with
what NOVA already stores — nothing is extrapolated:

* **Score curve per agent** — the first measured FORGE baseline, then the score of every version that reached users
  (active or retired). A version that was rejected or rolled back is not on the curve; an agent FORGE never measured has
  no curve at all.
* **Changes stopped before users** — cycles FORGE did not validate plus releases that were rejected or rolled back.
* **Lessons applied** — standards and Skill lessons of the active policy.
* **Failure-rate trend** — production executions (interactive, scheduled, goal, routine) of the last 30 days against the
  30 before. It is shown only when both periods hold at least 5 executions.

The rules are pure (`nova/domain/improvement.py`); `nova/services/improvement.py` reads policies, cycles, releases and tasks.

## From a click to a regression test

An "unhelpful" rating on a NOVA answer already reaches FORGE (a captured run and a human evaluation). The 🧪 button that
appears next to it goes one step further: **Add to the regression tests** turns that run into a regression scenario in
FORGE (`POST /api/v1/feedback/{id}/regression` → FORGE `promote-to-scenario`), so a later NOVA version is checked against
the very case the user complained about. It is idempotent (the same run gives the same case).

It is an explicit action, and it is **refused** when:

* the organization does not send requests to FORGE (`NOVA_FORGE_CAPTURE_MODE=observed` without
  `NOVA_FORGE_CAPTURE_INTENT=true`): FORGE has no input to turn into a test;
* the run served confidential (C2) or secret (C3) context: such a case never becomes a shared test;
* FORGE has not evaluated the run yet, or considers it not failed ("only failed or unsuccessful runs can become regression
  cases"): the reason is shown to the user, nothing is hidden.

The action is audited (`feedback.regression`) and recorded on the feedback (`forwarded.regression`).

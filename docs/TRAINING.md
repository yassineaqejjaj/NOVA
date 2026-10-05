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
* NOVA's citation labels are rewritten for FORGE: `[S1]` → `[source: <FORGE document id>]`, the form FORGE's
  citation rules recognise (NOVA's own Artifacts are unchanged).

## Operating it

Settings (all `NOVA_*`, see `.env.example`):

| Setting | Default | |
|---|---|---|
| `FORGE_API_KEY` | — | FORGE key with role **editor** (creates agents, scenarios, runs, experiments) |
| `FORGE_CREDENTIAL_ID` | — | id of FORGE's `nova` credential (secret = `NOVA_FORGE_INBOUND_TOKEN`) |
| `FORGE_NOVA_ENDPOINT` | derived | NOVA API URL as reachable from FORGE's runner |
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

# NOVA | Engineering case study

> **Project status:** public beta / technical demonstration. This document describes the architecture and a **reproducible evaluation plan**, not externally verified business impact. Metrics below are proposed measurements, **not achieved results**.

## The problem

Teams need to turn vague intents or GitHub issues into reproducible product and engineering work without losing context, approvals or auditability.

## The solution

An AI product agent with versioned Skills, planning and specialist agents, artifact versioning, governed ORBIT retrieval, and FORGE capture/evaluation hooks.

## System flow

```text
Intent or GitHub issue → plan → specialist agent/Skill → artifact or code change → validation/approval → trace and evaluation.
```

## What is available to inspect

[Current capabilities and deployment caveats](STATUS.md) · [Engineering workflow](ENGINEERING.md) · [Architecture](ARCHITECTURE.md) · [CI](https://github.com/yassineaqejjaj/NOVA/actions/workflows/ci.yml).

## A concrete, reproducible demo

Use the locally seeded demo and document a single product-management request, the plan, context selected by ORBIT, the structured artifact, the approval gate, and the trace outcome. For engineering, use the already documented GitHub issue → draft pull request flow; do not auto-merge or publish external code without review.

## Evidence protocol

Record completion against human-reviewed acceptance criteria, number of approval steps, time to artifact, LLM tokens/cost when available, citation accuracy and failed-run count. Use the same input and a declared baseline (manual workflow or a basic single-agent workflow).

To make a claim credible, record the repository commit, environment, dataset version, exact prompts/inputs, configuration, baseline, number of runs, test results, raw observations, and reviewer decision. Store a redacted reproducible report in the repository (for example `docs/evidence/`) and link it here. If the measurements have not been performed, write **Not measured**.

| Measure | Baseline | Candidate | Method | Verified result |
|---|---|---|---|---|
| Quality / task success | To define | To define | Fixed evaluation set and human-reviewed criteria | Not measured |
| Safety / critical failures | To define | To define | Severity-weighted fixed scenarios | Not measured |
| Resource use | To define | To define | Token and runtime logs, same workload | Not measured |
| End-to-end latency | To define | To define | Repeated runs, median and p95 | Not measured |

## Limitations and honest disclosure

The integration status matrix was written on 13 October 2026 and distinguishes implemented, tested, merged and deployed. Verify the latest release before asserting feature availability. CI green establishes only the checks in that workflow, not overall product correctness.

## Five-minute recorded walkthrough

1. **0:00–0:30 — Context.** Explain the user problem and intended scope.
2. **0:30–1:15 — Architecture.** Walk through the principal services and what each owns.
3. **1:15–3:15 — Workflow.** Run the concrete synthetic demo above, showing actual UI and results.
4. **3:15–4:15 — Evidence.** Show relevant trace, test, or comparison; distinguish mock and real providers.
5. **4:15–5:00 — Limits.** Name known constraints and the next experiment.

**Recording checklist:** no live secrets, tokens, proprietary client data, personal health data or real student data; visually label synthetic content; keep a link to the exact code commit and test run used.

---

[Back to repository](../README.md)

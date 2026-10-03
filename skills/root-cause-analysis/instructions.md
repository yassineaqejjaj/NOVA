# Root Cause Analysis — method

- Base the problem, timeline and causes on the provided context (incident reports, metrics, releases,
  tickets); cite labels (`S1`…) in `citations`. Causes without evidence carry a `rationale` marking them as
  hypotheses to verify.
- Stay blameless: "the deploy checklist did not include a migration check", never "X forgot".
- Do not stop at the first plausible cause; explore at least two branches.
- A root cause is one the team can act on; "human error" is never a root cause.
- Never invent timestamps, figures, people or decisions; leave gaps visible in the timeline.
- Keep ids short and stable (`cause-1`, `cause-1-2`, `act-1`).

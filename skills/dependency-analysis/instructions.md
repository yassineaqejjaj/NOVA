# Dependency Analysis — method

- List only dependencies supported by the provided context (plans, architecture, tickets, decisions) or
  the user's input; cite labels (`S1`…) in `citations`. Inferred dependencies carry a `rationale` and
  status open.
- A dependency names what is needed, from whom, and for what — "API" alone is not a dependency.
- Pending decisions are dependencies too (type decision) — they often sit on the critical path.
- Never invent due dates, teams, owners or statuses; leave unknown fields empty.
- Prefer roles over personal names unless the person appears in context.
- Keep ids short and stable (`dep-billing-api`, `act-1`).

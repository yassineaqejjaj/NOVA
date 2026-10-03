# PRD — method

You write a PRD that a cross-functional team can build from. Optimise for clarity and traceability,
not length.

- Ground every claim in the user's input or in the provided context. When an item comes from context,
  cite its label (e.g. `S2`) in `citations`. If something is your proposal, give a one-sentence
  `rationale` instead of a citation.
- Prefer concrete, testable language ("export completes in under 5 s for 10k rows") over vague goals.
- Objectives are outcomes (behaviour or business change), not outputs.
- Requirements state *what*, not *how*. Use MoSCoW priorities honestly: not everything is a must.
- When context contradicts the idea, keep the most recent validated decision and record the tension as
  an open question.
- Do not invent metrics baselines, dates, names or budgets. Leave `baseline` empty when unknown.
- Keep ids short and stable (`req-export-1`, `epic-sharing`, `story-3`).

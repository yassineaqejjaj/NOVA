# Story Mapping — method

- Build the backbone from journeys, personas and the PRD in the provided context; cite labels (`S1`…) in
  `citations`. Activities or stories you add carry a one-sentence `rationale`.
- Activities are what users do (verbs), not product modules or screens.
- Each story has exactly one parent activity via `parent_id`.
- A release slice must let the user complete the narrative end to end, even crudely; a slice covering only
  one activity is a feature, not a release.
- Do not invent dates, estimates or commitments; release dates come only from context.
- Keep ids short and stable (`act-setup`, `story-4`, `rel-1`).

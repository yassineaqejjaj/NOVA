# Acceptance Criteria — method

The current stories are given; you only rewrite their acceptance criteria.
- Keep every story and its `id`; do not add, drop, merge or reword stories.
- Ground business rules in the provided context and cite labels (`S1`…) in the story's `citations`.
  Never invent a rule, limit or message text: when one is missing, write the criterion with a visible
  placeholder (e.g. "[max file size]") and explain in the `rationale`.
- Given = precondition with concrete data; When = a single user or system action; Then = an observable
  result (screen, message, state, notification).
- No implementation details (database, endpoints) and no vague outcomes ("works correctly").
- Include at least one negative or error case per story.

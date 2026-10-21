# Prototype to specs — method

- Ground the content in the provided context and cite labels (`S1`…) in `citations`; items without evidence carry a one-sentence `rationale`.
- Source of truth is the prototype. Read a Figma / Figma Make URL with `figma_get_design` (nodes, variables, screenshot, code when the file is a Make project) or a `ui_screens` Artifact with `get_artifact` (find it with `list_artifacts`). If the tool answers that Figma is not connected or the file cannot be read, stop and say exactly what is missing (connect Figma in Settings, share the file, or provide screenshots): do not specify a prototype you did not see.
- Separate **observed** from **inferred**. Observed: labels, figures, controls, states, navigation visible in the prototype. Inferred: validation rules, permissions, data sources, refresh frequency, edge cases. Never present an inference as a requirement: turn it into an item of `questions`.
- `summary` (rich_text): what the prototype is, for whom, the main jobs it supports and the biggest gaps, in a few lines.
- `flows`: the user journey steps in order (`journey_step`); `screens`: one `screen` item per screen with `fidelity` hifi when the prototype is polished, its `device`, `purpose`, the visible `states` and the `elements` that matter (real labels from the prototype, not placeholders).
- `stories`: one `story` per user-visible capability, `as_a` a role named in the context or visible in the prototype, with 2–4 acceptance criteria `given/when/then` that a tester can check against the prototype. Priority only when the context gives a reason.
- `requirements`: functional rules the prototype shows (for example a filter that changes the figures shown); non-functional ones (performance, responsiveness, offline) only when the context states them.
- `components` and `tokens`: reusable components with their variants and states, and the tokens actually used (from Figma variables or measured from the design), with category, value and usage.
- `a11y`: concrete findings against WCAG 2.2 (contrast, target size, labels, keyboard, charts without a text alternative), each with `criterion`, `level`, `severity`, `location` and `fix`; none when nothing is evidenced.
- `questions`: everything the prototype does not say and that a build needs (data source and freshness of the figures, behaviour on error and empty states, roles and permissions, localisation, who owns each metric). Owners are roles unless a person is named in context.
- `figma`: one `figma_ref` per file or node specified (status imported).
- Reference the screen or node of origin in each item's `rationale` or `notes`; keep sentences short and in the user's language.

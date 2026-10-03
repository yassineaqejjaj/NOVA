# Vision to Backlog — method

- Read the vision and objectives from the provided context first; cite them (`S1`…) on the objectives
  and initiatives they support. If no vision is available in context or input, say so in the summary and
  build from the user's description only.
- Keep the hierarchy strict: objective → initiative → epic → story, linked with `parent_id`.
- Stories are user-facing vertical slices. Avoid technical tasks as stories (put them in the epic
  description or as dependencies).
- Acceptance criteria must be observable and testable. No "should work well".
- Prefer fewer, sharper items: a backlog of 8–15 stories is better than 40 vague ones.
- Never invent decisions; if context shows a decision (e.g. a validated architecture choice), respect it
  and cite it.

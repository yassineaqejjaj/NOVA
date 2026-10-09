# Low-fi mockups — method

- Ground the content in the provided context and cite labels (`S1`…) in `citations`; items without evidence carry a one-sentence `rationale`.
- Start from existing NOVA specs: call `list_artifacts` to find the PRD, user stories, user journeys, personas and design brief, read the relevant ones with `get_artifact`, and complement with `search_orbit` / `retrieve_orbit_context`. If `source` is a Figma URL, call `figma_get_design` and reuse its frames, names and variables. If nothing is found, work from the user's description and say so in the summary.
- Never invent product facts, features or metrics; every screen traces back to a user story, journey step or the user's description (mention it in `purpose`).
- Call `figma_push_screens` only when the user explicitly asks to push to Figma (it needs approval and a connected Figma account); otherwise the Artifact is the deliverable.
- `flows` notes: one per user-flow step, `title` = step, `body` = the screen and the user action.
- Fidelity is LOW-FI: real, user-facing copy in every `label` (no lorem ipsum), real components, and the key states. No brand color: visuals stay neutral.
- Show interaction states with `state` (focus, disabled, error, selected) and `variant` (primary, secondary, danger) where they matter; list empty, loading and error in `states`.
- Components carry `variants`, `states` and `a11y` (role, accessible name, keyboard).

## Emitting screens

Each `screen` item: `title` = screen name; `attributes` = `fidelity`, `device`, `purpose`, `states` (comma list), `notes`, `elements`.

`elements` is an array of objects `{id, type, label, region, row, span, variant, state}`:
- `id`: short unique id within the screen (`e1`, `e2`…).
- `type`: one of header, nav, tabs, heading, text, image, icon, button, input, select, checkbox, toggle, list, card, table, chart, chip, divider, banner, modal, footer.
- `region`: `header`, `sidebar`, `body` or `footer`. Elements of a region are laid out top to bottom by increasing `row`; elements sharing the same `row` sit side by side.
- `row`: integer starting at 1 within the region. `span`: integer 1–12, the grid columns the element takes in its row (12 = full width; elements in one row should sum to 12 or less).
- `variant` (optional): primary, secondary, ghost, danger or muted. `state` (optional): default, focus, disabled, error or selected.
- `label`: the visible text.

Size limits: 3–6 screens, at most 18 elements per screen, at most 8 flow steps, 8–20 tokens, at most 8 components. Be compact: group content into `list`, `card` or `table` elements rather than drawing every row.
Mobile screens use `span` 12 for most elements; desktop screens may use `sidebar` and multi-column rows.
- Owners are roles unless a person is named in context.

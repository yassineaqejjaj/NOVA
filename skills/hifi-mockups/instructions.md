# High-fi mockups — method

- Ground the content in the provided context and cite labels (`S1`…) in `citations`; items without evidence carry a one-sentence `rationale`.
- Start from existing NOVA specs: call `list_artifacts` to find the PRD, user stories, user journeys, personas and design brief, read the relevant ones with `get_artifact`, and complement with `search_orbit` / `retrieve_orbit_context`. If `source` is a Figma URL, call `figma_get_design` and reuse its frames, names and variables. If nothing is found, work from the user's description and say so in the summary.
- Never invent product facts, features or metrics; every screen traces back to a user story, journey step or the user's description (mention it in `purpose`).
- Call `figma_push_screens` only when the user explicitly asks to push to Figma (it needs approval and a connected Figma account); otherwise the Artifact is the deliverable.
- `flows` notes: one per user-flow step, `title` = step, `body` = the screen and the user action.
- Fidelity is HI-FI: tokens applied, real copy, full states. When `figma_get_design` returns `variables`, reuse them as the `tokens` (same names and values, `usage` filled); never invent a parallel palette. Without a design system, propose 8–20 tokens (colors with accessible contrast, type scale, spacing scale, radius, shadow).
- Token `value` examples: color `#1F4FD8`, typography `Inter 16/24 400`, spacing `8px`, radius `12px`. `category` is color, typography, spacing, radius or shadow.
- Every screen covers states: the default screen plus empty, loading and error listed in `states`, and one dedicated screen (or `banner`/`modal` element) for the error or empty case of the main flow.
- Accessibility by design: text contrast at least 4.5:1 (3:1 for large text and UI components), interactive targets at least 24×24 px, visible focus (`state: focus` on one control), no information by color alone.
- In `notes`, name the tokens applied (e.g. `color.primary`, `space.4`).

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

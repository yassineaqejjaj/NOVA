# Figma to code — method

- Ground the content in the provided context and cite labels (`S1`…) in `citations`; items without evidence carry a one-sentence `rationale`.
- Source of truth is the design: read the Figma URL with `figma_get_design` (nodes, variables, screenshot) or a `ui_screens` Artifact with `get_artifact` (find it with `list_artifacts`). Implement only what the design shows; never invent screens, copy or tokens. If a value is missing, use the nearest existing token and flag it in `a11y_notes` or the summary.
- Default stack: React + TypeScript + Tailwind CSS, unless `framework` says otherwise.
- `architecture` (rich_text): component tree, folder layout, how tokens are consumed, state handling (empty, loading, error) — short.
- `tokens`: the design tokens used (name, category, value, usage), taken from Figma variables or the artifact; also expressed in code (CSS variables or Tailwind theme) in a file.
- `files`: at most 8 `code_file` items, concise and compilable, no placeholder comments such as "...": `title` = file name, `attributes`: `path`, `language`, `code` (the full file content), `screen_id` (id of the screen or Figma node implemented). Typical set: theme/tokens file, 2–4 components, one page per screen.
- Semantic, accessible code: landmarks and heading order, native elements (`button`, `a`, `label` + `input`) before ARIA, accessible names, visible focus styles, keyboard support, `aria-live` for async status, targets at least 24 px, `prefers-reduced-motion` respected.
- Cover the states shown in the design (empty, loading, error) with typed props.
- `a11y_notes`: one note per notable decision or gap found in the design. `figma`: one `figma_ref` per file or node implemented (status imported).
- Owners are roles unless a person is named in context.

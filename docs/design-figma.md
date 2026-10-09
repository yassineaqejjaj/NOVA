# Design · Figma MCP · Design-to-code — shared contract

Feature: designers get UX / UI / Research Skills in NOVA. NOVA connects to **Figma through MCP**, turns specs already
generated in NOVA (PRD, user stories, journeys, personas, design brief) or plain language into **wireframes, low-fi and
high-fi mockups**, audits **accessibility**, and the **Engineering agent generates code from the Figma files**.

## 0. Figma access (decision, 2026-10-09)

* The hosted Figma MCP server (`https://mcp.figma.com/mcp`) is the only one with write tools (`use_figma`,
  `generate_figma_design`, `create_new_file`…) but **only clients of the Figma MCP Catalog can connect**: custom OAuth
  apps, dynamic client registration and personal access tokens are rejected. NOVA therefore ships a **generic MCP client**
  (Streamable HTTP, OAuth 2.1 + PKCE per user, tokens encrypted like ORBIT's) and NOVA must be submitted to Figma's
  catalog waitlist. The OAuth client id is configuration (`NOVA_FIGMA_OAUTH_CLIENT_ID`), nothing is hard-coded.
* **Degraded mode** (no catalog access yet, always available): READ via Figma's REST API with the user's personal access
  token (`/v1/files/:key`, `/v1/files/:key/nodes`, `/v1/files/:key/variables/local`, `/v1/images/:key`). No canvas write.
* Mockups are **always produced inside NOVA first** as a structured `ui_screens` Artifact (rendered as wireframe / lo-fi /
  hi-fi preview). It is the single source of truth; pushing it to Figma (`figma_push_screens`) is an approval-gated
  external write that only runs when the MCP write path is connected.

## 1. Artifact types (artifacts/types/*.yaml, + i18n/fr.yaml)

| type | produced by Skill | sections |
|---|---|---|
| `ui_screens` | `wireframes`, `lowfi-mockups`, `hifi-mockups` | `summary` rich_text · `flows` items:`note` (user flow steps) · `tokens` items:`design_token` · `screens` items:`screen` · `components` items:`ui_component` · `figma` items:`figma_ref` |
| `a11y_audit` | `accessibility-audit` | `summary` rich_text · `findings` items:`a11y_finding` · `passed` items:`checklist_item` · `recommendations` items:`action` |
| `ui_code` | `figma-to-code` | `summary` rich_text · `architecture` rich_text · `files` items:`code_file` · `tokens` items:`design_token` · `a11y_notes` items:`note` · `figma` items:`figma_ref` |

## 2. New item kinds (packages/schemas/items/*.json, `additionalProperties: false`, `required: []`)

* `screen`: `fidelity` enum wireframe|lowfi|hifi · `device` enum mobile|tablet|desktop · `purpose` string · `states`
  string (comma list: empty, loading, error…) · `notes` string · `elements` array of element objects:
  `{ id, type, label, region, row, span, variant, state }` where
  `type` ∈ header, nav, tabs, heading, text, image, icon, button, input, select, checkbox, toggle, list, card, table,
  chart, chip, divider, banner, modal, footer · `region` ∈ header|sidebar|body|footer (elements of a region are laid out
  by increasing `row`; elements sharing a `row` sit side by side) · `span` integer 1–12 (grid columns of the row, 12 =
  full width) · `variant` ∈ primary|secondary|ghost|danger|muted (optional) · `state` ∈ default|focus|disabled|error|
  selected (optional) · `label` = visible text (hi-fi: real copy; wireframe: short placeholder).
* `design_token`: `category` enum color|typography|spacing|radius|shadow · `value` string · `usage` string.
* `ui_component`: `kind` string · `variants` string · `states` string · `a11y` string (role, name, keyboard).
* `figma_ref`: `url` string · `file_key` string · `node_id` string · `status` enum linked|pushed|imported.
* `a11y_finding`: `criterion` string (e.g. "1.4.3 Contrast (Minimum)") · `level` enum A|AA|AAA · `principle` enum
  perceivable|operable|understandable|robust · `severity` enum low|medium|high|critical · `location` string ·
  `evidence` string · `fix` string.
* `code_file`: `path` string · `language` string · `code` string · `screen_id` string (the `screen` / Figma node it implements).

## 3. Skills (skills/<id>/, agent in parentheses; fr translations in skills/i18n/fr.yaml; run `uv run python -m nova.skills.build`)

`wireframes` (design), `lowfi-mockups` (design), `hifi-mockups` (design), `accessibility-audit` (design),
`figma-to-code` (engineering). Existing research Skills (`user-research-plan`, `interview-guide`,
`usability-test-plan`, `persona`, `user-journey`, `feedback-synthesis`, `design-review`) stay and are composed with them
(`composes_with`). Specs are read from earlier Artifacts with the `list_artifacts` / `get_artifact` tools and from ORBIT.

## 4. Tools (nova/agent/tools/, registered in `register_builtin_tools`)

| tool | permission | write? | purpose |
|---|---|---|---|
| `figma_get_design` | `context.read` | no | input `{ url?: str, file_key?: str, node_id?: str }` → normalized `{ file_name, nodes: [{id,name,type,children…}], variables: [{name,type,value}], screenshot_url?, source: "mcp"\|"rest" }` |
| `figma_push_screens` | `context.write_external` | **yes** (approval) | input `{ artifact_id: str, file_key?: str }` → `{ external_id, status, url }` ; uses MCP `use_figma`/`create_new_file`; clear `ToolDenied` message when only REST is available |

`ctx.deps.design` is a `DesignProvider` port (nova/domain/design.py): `status(user_id)`, `get_design(user_id, ref)`,
`push_screens(user_id, title, screens, tokens)`. Raises `DesignError(code, message)` with codes `not_connected`,
`forbidden`, `not_found`, `unavailable`, `write_unavailable`.

## 5. HTTP API (apps/api/nova_api/routers/figma.py, all under `/api/v1`)

* `GET /me/figma` → `{ linked: bool, mode: "oauth"|"token"|null, mcp: bool, can_write: bool, figma_handle: str|null, oauth_available: bool }`
* `POST /me/figma/connect` → `{ authorize_url }` (OAuth 2.1 + PKCE, state stored server side) — 409 `figma_oauth_unavailable` when no client id is configured
* `GET /me/figma/callback?code&state` → exchanges the code, stores encrypted tokens, redirects to `/settings?figma=connected`
* `POST /me/figma/token` `{ token }` → validates against `GET https://api.figma.com/v1/me`, stores encrypted (degraded read-only mode)
* `DELETE /me/figma` → unlink (204)

Table `figma_accounts` (alembic `0009_figma.py`): `user_id` pk/fk, `mode`, `figma_user_id`, `handle`, `token_ciphertext`,
`refresh_ciphertext`, `expires_at`, `scope`, `linked_at`. Settings: `figma_mcp_url` (default `https://mcp.figma.com/mcp`),
`figma_api_url` (default `https://api.figma.com`), `figma_oauth_client_id`, `figma_oauth_client_secret`, `figma_oauth_redirect_uri`.

## 6. Web

* `ui_screens` `screens` section renders a **visual preview** per `screen` (device frame; wireframe = grey boxes, lo-fi =
  neutral UI with real labels, hi-fi = tokens applied) with a fidelity switch and the states list.
* Settings → "Figma" card (OAuth connect, or personal access token fallback, status, disconnect).
* Design agent suggestions on Home; Team page specialties; FR/EN strings via `defineMessages`.

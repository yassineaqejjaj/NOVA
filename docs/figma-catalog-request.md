# Figma MCP Catalog — access request for NOVA (draft, not sent)

How to apply (Figma, October 2026): (1) fill the MCP client request form linked from the
[remote server installation page](https://developers.figma.com/docs/figma-mcp-server/remote-server-installation)
(waitlist form), then (2) e-mail **mcpserver@figma.com** with the details below. Figma says new clients are currently
paused, but a request still counts for prioritization. Fields in `[brackets]` need your input.

## Form answers

| Field | Answer |
|---|---|
| Client name | NOVA |
| Client type | Web application (server-side MCP client, Streamable HTTP) |
| Organization | Devoteam |
| Contact | yassine.aqejjaj@devoteam.com |
| App URL | https://nova-six-orcin-96.vercel.app |
| OAuth redirect URI | `https://nova-six-orcin-96.vercel.app/api/v1/me/figma/callback` [adjust if you use a custom domain] |
| Auth flow | OAuth 2.1 Authorization Code + PKCE (S256), per-user; tokens encrypted at rest, revocable from NOVA settings |
| Server | https://mcp.figma.com/mcp |

## E-mail

**To:** mcpserver@figma.com
**Subject:** MCP Catalog request — NOVA (Devoteam): design-to-code and wireframe generation client

Hello Figma MCP team,

I am requesting that NOVA be added to the Figma MCP Catalog.

**What NOVA is.** NOVA is Devoteam's multi-agent product assistant: an orchestrator delegating to specialist agents
(Product, Project, Design, Engineering) with a validation layer. It is used by [number] product, design and
engineering practitioners [internal pilot / customers: to complete].

**Use cases.**
1. *Design to code.* The Engineering agent reads a Figma frame (structure, variables, screenshot) and generates
   component code, mapping design tokens, with accessibility notes.
2. *Accessibility audit.* The Design agent audits a Figma design against WCAG 2.2 AA.
3. *Mockups from specs.* From specs already produced in NOVA (PRD, user stories, journeys), the Design agent
   generates wireframes and low/high-fidelity mockups and, with explicit user approval, pushes them to the user's
   Figma file.

**Tool calls we need.**
- Read: `get_design_context`, `get_metadata`, `get_variable_defs`, `get_screenshot`.
- Write (user-approved only): `use_figma`, `create_new_file`.
We do not need Code Connect writes, image generation or generative-plugin tools.

**Security and governance.** Per-user OAuth 2.1 + PKCE; tokens encrypted at rest; no token shared between users;
every external write requires an explicit approval in the NOVA UI and is audited; the user can disconnect at any
time. NOVA is already integrated and ready: the client is implemented and only blocked by the catalog allowlist.

**Customer requests.** [Add concrete requests from Devoteam teams or clients asking for Figma in NOVA.]

Could you let us know what else you need to evaluate the integration (demo, security questionnaire)?

Best regards,
Yassine Aqejjaj — Devoteam

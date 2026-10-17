# Operations

## Production checklist

* `NOVA_ENV=production` — the API refuses to start with development secrets or `NOVA_AUTH_MODE=dev`.
* Secrets (≥ 32 chars): `NOVA_SESSION_SECRET`, `NOVA_SECRETS_KEY` (encrypts ORBIT session tokens),
  `NOVA_FORGE_INBOUND_TOKEN`, `NOVA_OIDC_CLIENT_SECRET`, `NOVA_FORGE_API_KEY`. Provide them through your secret store.
* `NOVA_COOKIE_SECURE=true` behind HTTPS; Keycloak realm `nova` with client `nova-web` (confidential, PKCE S256,
  redirect `https://<host>/api/v1/auth/callback`, audience mapper) — see `infrastructure/keycloak/nova-realm.json`.
* Organization policy: `NOVA_POLICY_ALLOW_AUTO_EXTERNAL_WRITES` (default `false`: writes to ORBIT always need
  approval), `NOVA_POLICY_MAX_CLASSIFICATION` (cap on the classification NOVA requests from ORBIT),
  `NOVA_LLM_MAX_CLASSIFICATION` (default `1`), `NOVA_LLM_LOCAL`, `NOVA_LLM_LOCAL_HOSTS`, `NOVA_LLM_REDACT_PII`
  (outbound guardrail: what may be sent to an external model, see ARCHITECTURE §11), `NOVA_DEFAULT_CLEARANCE` (default `1`: clearance of a user with no linked ORBIT account, see ARCHITECTURE §11).
* Retention: `NOVA_CONTEXT_REFERENCE_RETENTION_DAYS`, `NOVA_EXECUTION_EVENT_RETENTION_DAYS`, `NOVA_CHECKPOINT_RETENTION_DAYS` (daily
  job); forgetting a source, project or user and the other copies: `docs/DATA_INVENTORY.md`, `NOVA_FORGET_ARTIFACTS`.

## Shared identity provider: realm `orion` (NOV-103, ADR 001)

A second Keycloak realm, `orion`, is the future identity provider of NOVA, ORBIT and FORGE (`infrastructure/keycloak/orion-realm.json`).
It is **off by default**: nothing imports it and no service points at it. The realm `nova` (`nova-realm.json`, never modified:
a test pins its hash) and NOVA's current sign-in are unchanged. Tokens follow the claims contract of `docs/CONTRACTS.md`
(`contracts/claims/`).

**What the realm contains.** Clients, all confidential, no password grant, no implicit flow:

| Client | Use | Notes |
|---|---|---|
| `nova-web` | NOVA (Authorization Code + PKCE S256) | redirect `${ORION_NOVA_PUBLIC_URL}/api/v1/auth/callback`; the only client allowed to do token exchange (RFC 8693), towards the audiences `orbit` and `forge` only |
| `orbit`, `forge` | ORBIT / FORGE (Authorization Code + PKCE S256) | redirect `${ORION_ORBIT_PUBLIC_URL}` / `${ORION_FORGE_PUBLIC_URL}` + `/api/v1/auth/oidc/callback` (a convention for the two follow-up tickets; adjust there) |
| `nova-service` | service account (client credentials) | no audience by default: ask `scope=orion-audience-orbit` or `orion-audience-forge` (+ `orion:run.execute`, `orion:context.read`), one token per audience; no realm role and no workspace until an administrator sets them |

Claims minted: `sub`, `email`, `email_verified`, `orion_workspace_id` (UUID), `orion_project_id` (optional UUID),
`orion_clearance` (**integer** 0-3), `realm_access.roles`, `amr`, `scope`, and the audience of the client. Realm roles: `nova-admin`,
`orbit-admin`, `forge-admin`, `forge-maintainer`, `forge-editor`, `forge-evaluator`, `forge-viewer`; each client only receives the roles of
its own prefix (`fullScopeAllowed` is off). The three `orion_*` attributes and the e-mail are editable by realm administrators only
(declarative user profile): a user cannot raise their own clearance or change workspace. Access tokens live 5 minutes (ADR §6).
Not emitted by Keycloak 26.8 and expected by later tickets: `act` (delegation, preview feature `TOKEN_EXCHANGE_DELEGATION`: the
exchanged token has `sub` = the user but no `act` yet, and carries the roles of the requesting client, so ORBIT / FORGE see local roles only),
`nbf` (the validation module checks it when present), a per-exchange `orion_project_id`.

**Variables** (Keycloak service; secrets of at least 32 characters, from the secret store, never in the repository):
`ORION_REALM_IMPORT=true`, `ORION_NOVA_PUBLIC_URL`, `ORION_ORBIT_PUBLIC_URL`, `ORION_FORGE_PUBLIC_URL`, `ORION_NOVA_CLIENT_SECRET`,
`ORION_ORBIT_CLIENT_SECRET`, `ORION_FORGE_CLIENT_SECRET`, `ORION_NOVA_SERVICE_SECRET`. The image entrypoint
(`infrastructure/keycloak/docker-entrypoint.sh`) copies the realm into the import directory **only** when
`ORION_REALM_IMPORT=true` and refuses to start if a variable is missing or a secret is short (an unresolved `${...}` would be imported
literally). Without the flag the container is `exec kc.sh` exactly as before.

**Create the realm in pre-production** (operator, never production without an explicit decision):

1. On the pre-production `keycloak` service set the variables above (generate each secret, e.g. `openssl rand -base64 36`), then deploy
   that service as usual (`railway up -s keycloak -e preprod` with a reduced context). The import runs **only if the realm does not exist
   yet**: a later start never overwrites it, and changing a variable afterwards changes nothing (edit the client in the admin console).
   Set `ORION_REALM_IMPORT` back to `false` once the realm exists.
2. Finish the realm (idempotent): `KC_URL=https://<keycloak> KC_ADMIN=<admin> KC_ADMIN_PASSWORD=<…> ORION_ENVIRONMENT=preprod uv run python infrastructure/keycloak/configure_orion.py --mfa off --test-user`.
   It sets the `amr` references (`pwd` on the password form, `mfa` on the OTP form), the MFA policy and creates the single synthetic test
   user `orion-test` (role `forge-viewer`, clearance 1, a fake workspace id): the password is generated and printed once, or taken
   from `ORION_TEST_USER_PASSWORD`; it is refused unless `ORION_ENVIRONMENT=preprod`. No production user is ever imported.
3. Check `<keycloak>/realms/orion/.well-known/openid-configuration` and sign in at the `nova-web` client; confirm that `/realms/nova` still works.

**MFA (OTP)** is off by default in pre-production. `configure_orion.py --mfa on` makes "Configure OTP" a default required action and
requires it at next sign-in from every existing user without OTP (service accounts excepted); `--mfa off` removes the default action
(pending required actions stay). With OTP configured the token carries `amr` = `["pwd", "mfa"]`, which the sensitive operations of ADR §4 require.

**Rotate a client secret.** In the admin console (realm `orion`, client, Credentials) regenerate the secret, store it in the secret
store, and redeploy the service that uses it. Rotate `nova-service` the same way for every caller. After the realm exists the
`ORION_*_SECRET` variables are not read again: they only matter for a re-created realm. Rotate after any suspected leak, when a person with
access leaves, and at least once a year.

**Break-glass.** Keycloak's administrator (`KC_BOOTSTRAP_ADMIN_*`, realm `master`) is independent of the realm `orion`: keep it offline in the
vault with a second holder, use it to disable a compromised user or client, to reset MFA of a locked-out administrator
(Users, Credentials, delete OTP) and to restore access; never share it. Each service keeps its own local break-glass administrator outside SSO
(ADR §8) until the migration ends. If the IdP is down the services keep their existing local sign-in (the realm is not wired yet). Roll back
the whole realm by deleting realm `orion` in the admin console (realm `nova` is not touched) and unsetting `ORION_REALM_IMPORT`; restore
from the Keycloak database backup if realm settings were changed by mistake.

## Delegation by token exchange (`NOVA_DELEGATION_MODE`, NOV-111, ADR 001 §6)

`linked_session` (default) is today's behaviour, unchanged: NOVA acts on ORBIT with the ORBIT session each user linked, and
falls back to the project agent key (signalled on the links screen). `token_exchange` replaces it:

* at OIDC sign-in NOVA keeps the user's own tokens, **encrypted** (`NOVA_SECRETS_KEY`) in `delegation_sessions` (migration 0021,
  additive; empty in the default mode); sign-out and a refusal of the IdP delete them;
* for each ORBIT call NOVA exchanges the user's token (RFC 8693) at the IdP token endpoint (`NOVA_DELEGATION_TOKEN_URL`, default
  the OIDC back-channel) for a token to the audience `orbit`, scope `orion:context.read` only, with the target `orion_project_id`
  (known once ORBIT reported it, else the exchange names no project). The token lives 5 minutes at most (a longer one from the IdP
  is cached 5 minutes anyway), is **held in memory only** (per process: never stored, never logged, never served for another user,
  project, audience or scope) and is refused unless it is for the one audience, for the same user, and readable under the claims contract;
* ORBIT validates the token and applies **its own** authorizations; NOVA decides no right. A disabled user, a user who signed out or
  whose session the IdP no longer honours, a refused audience or scope are refusals (`unauthorized` / `forbidden`): there is **no
  fallback** to the linked session or the project agent key. A removed member (ORBIT webhook `member.removed`, NOV-81) loses the
  cached tokens of that project at once in the process that receives it; other processes' tokens expire within 5 minutes;
* with no user (routines, FORGE protocol) the explicit service account `nova-service` acts as itself
  (`NOVA_DELEGATION_SERVICE_CLIENT_SECRET`, client credentials, one token per audience): never a user's identity.

Needs the realm `orion` (NOV-103: `nova-web` allowed to exchange towards `orbit` / `forge`), ORBIT accepting the IdP's tokens
(its OIDC ticket) and `NOVA_AUTH_MODE=oidc` pointed at that realm. Roll back by setting the variable back to `linked_session`
(the stored sessions stay encrypted and unused; delete them with `DELETE FROM delegation_sessions`).
Known limits: the exchanged token has no `act` claim until Keycloak's delegation preview feature is enabled (the IdP
side of the "Delegation" follow-up), and carries the roles of `nova-web`, so ORBIT sees local roles only.

## ORBIT revocation events (webhook)

After a change of rights in ORBIT, NOVA must stop using what it kept (extracts, derived Artifacts, replays, sessions).
ORBIT announces it with its signed webhooks (ORBIT NOV-80); NOVA receives them at `POST /api/v1/webhooks/orbit`.

**Configure ORBIT**: in the ORBIT project, add a webhook to `https://<nova-host>/api/v1/webhooks/orbit`, subscribed to
`document.forgotten`, `memory.forgotten`, `document.acl_changed`, `memory.acl_changed`,
`document.classification_changed`, `member.removed` and `agent.revoked` (an empty selection also works: other types are
acknowledged and ignored). Put the webhook's signing secret in `NOVA_ORBIT_WEBHOOK_SECRET` on `api` (also `worker`,
`beat` for consistency). Without it the endpoint answers 503 and nothing is accepted. Create one webhook per ORBIT
project (the payload names the project slug).

**Contract** (ORBIT's `webhook_payload`, JSON): `id`, `type`, `project {id, slug}`, `target_type`
(`document | memory | user | agent`), `target_id`, `created_at`, `effective_at`, `restricted`, `old_classification`,
`new_classification`; headers `X-Orbit-Event`, `X-Orbit-Delivery` (idempotence key) and
`X-Orbit-Signature: sha256=<HMAC-SHA256(secret, raw body)>`. NOVA answers 401 on a bad or missing signature, 400 on a
malformed or stale event (`NOVA_ORBIT_WEBHOOK_MAX_AGE_SECONDS`, default 24 h), `200 {"status": "duplicate"}` for a
delivery already received. `member.removed` carries the ORBIT user id in `target_id`; `agent.revoked` the key id.

**Effects** (all audited, idempotent): the retrieval references holding the source are marked revoked (never served
again: pinned context, replay with the original context, citations); the Artifacts citing them are flagged "to review"
(banner, no export or publication until an editor reviews them, `POST /artifacts/{id}/review`); `member.removed` drops
that user's ORBIT session, resets their clearance to `NOVA_DEFAULT_CLEARANCE` and revokes what they were served in that
project (status "revoked" on the links screen until they link ORBIT again); `agent.revoked` stops NOVA using the
project's configured agent key (ORBIT's key id cannot be matched to NOVA's configuration, so the check on the links
screen restores it when ORBIT still accepts the key; rotating the key also lifts it). Administrators list the received
events (`GET /admin/orbit-events`) and replay one (`POST /admin/orbit-events/{id}/replay`).

## Workspaces (`orion_workspace_id`, NOV-107)

Every table that holds tenant data carries `workspace_id` (NOT NULL; migration 0020, additive and reversible), `workspaces`
registers the ids, and a project carries an immutable `orion_project_id` (ADR 001 §5). Existing rows belong to the default
workspace, `ORION_DEFAULT_WORKSPACE_ID` (else the fixed `00000000-0000-4000-8000-000000000001`): **set it before the
migration runs and never change it afterwards.**

`NOVA_WORKSPACE_ENFORCEMENT` (default `off`):

* `off`: nothing is filtered, counted or read from a token; rows still get the workspace of their owner (default workspace);
  no API response changes.
* `shadow`: the workspace of a request is the one of its account (copied from the validated token's `orion_workspace_id`
  when the account was created); nothing is refused, but every row read from another workspace, every write across
  workspaces and every token of another workspace than its account's is counted (`nova_workspace_shadow_total{kind,table}`
  and one warning per kind and table). Turn it on first and watch the counter stay at zero.
* `enforce`: every ORM statement on a workspace table is filtered (administrators included: a platform administrator does not
  read another workspace); a foreign object answers 404 like an unknown one; a write or a reference across workspaces, or a
  token of another workspace than its account's (401), is refused; retention runs workspace by workspace; an ORBIT event is
  applied under the workspace of its signed payload, else of the projects that reference its ORBIT project (all of them when
  several), else the default one; checkpoint threads, outbox keys and the composition cache carry the workspace (the default
  workspace keeps the historical keys, the `external_id` FORGE sees is unchanged).

**ORION project id.** ORBIT (NOV-106) reports `orion_project_id` on `GET /projects`, in the context package and in snapshots.
NOVA records it on the ORBIT `ProjectReference` and on the linked NOVA `Project` when it syncs ORBIT projects, when a
retrieval is recorded and when a snapshot is read. The id NOVA minted before ORBIT said anything is a placeholder and gives
way once; after that an id never changes: a different one from ORBIT, or one another project already holds, is not applied,
is logged and audited (`project.orion_id_conflict`, once per report). Several NOVA projects linked to the same ORBIT project
cannot all hold its id: the first one does, the others are reported as conflicts. The id is never part of an API response.

`NOVA_WORKSPACE_STRICT_CLAIM` (default `false`, NOV-104 wiring): reads Keycloak access tokens and the SSO id token through
the ORION claims contract (`nova/domain/orion_claims.py`; the signature is still checked by the existing JWKS validation).
When `true`: a token without `orion_workspace_id` opens nothing (403 `workspace_required`, no account is created); a
malformed ORION claim (`orion_clearance` outside 0-3, bad UUID, bad `act`) is a 401; the claim decides the workspace of the
account it creates and a token of another workspace than its account's is a 401 (whatever `NOVA_WORKSPACE_ENFORCEMENT`
says); the clearance is `min(local clearance, orion_clearance)`, and a session opened by an SSO login keeps that cap
(`occ` in the session cookie). Sessions of NOVA's own password screens carry no token: they stay in the account's workspace.
Turn it on once the IdP's mapper emits the claim, after `shadow` has shown it present on real tokens.

Roll back by setting `off` (no data change). Downgrading the migration is refused while rows belong to another workspace than
the default one (`NOVA_ALLOW_WORKSPACE_MERGE=1` overrides it: the workspaces then merge). Platform records stay in the default
workspace and are read by every workspace: the Skill catalog, the learning loop (policies, releases, training cycles), the FORGE
agent versions cache, revoked agent keys, the FORGE link health. Isolation cases of the three repositories: `docs/ISOLATION.md`. Tests: `tests/integration/test_workspace_isolation.py`, `tests/integration/test_workspace_matrix.py`,
`tests/unit/test_workspace_inventory.py` (a table or route without a declared filter fails), `tests/migration/`.

### Links screen with federated delegation (NOV-114, ADR 001 §11)

With `NOVA_DELEGATION_MODE=token_exchange`, `GET /api/v1/me/links` adds `federated` (Settings → Links then shows it instead of the ORBIT
session view); in `linked_session` (default) the answer has no such key and the screen is unchanged. Per service (ORBIT, FORGE):
state (`ok`, `expiring` (< `NOVA_LINKS_EXPIRY_WARNING_SECONDS`, default 60, of the 5 minute token), `expired` (the user's IdP session is over),
`revoked` (by the user, or removed by ORBIT, NOV-81), `degraded`, `unlinked`, `not_configured`), identity (abbreviated `sub`, e-mail, `iss`, `amr`, `act`),
target project (`orion_project_id`, alias, workspace), expiry and remaining time, scope (scopes, role, effective clearance = `min`, and why it is lower),
last exchange and last round trip (operation, outcome, latency, consecutive errors). Everything is read from what NOVA already recorded
(`delegation_sessions.links`): opening the screen calls neither the IdP nor ORBIT; no token or secret is ever returned. Actions:
reconnect (a new sign-in), `DELETE /me/links/{service}` (revoke: no new token until the user reconnects, audited as `delegation.revoke`),
`POST /me/links/orbit/test` (one `GET /auth/me`, no data). `GET /admin/links` (administrators): statuses of the workspace's members, masked
e-mail, no identity detail, no content.

## FORGE -> NOVA authentication (`NOVA_FORGE_INBOUND_AUTH`, NOV-112, ADR 001 §7)

FORGE calls `POST /v1/agents/{id}/runs` with a credential. Three modes:

* `token` (**default, unchanged**): the shared bearer `NOVA_FORGE_INBOUND_TOKEN`, compared in constant time;
* `both`: that bearer **or** a service-account token of the IdP (the switch-over window: move FORGE, then remove the bearer);
* `oidc`: only the IdP token; the shared bearer is refused (and no longer required in production).

The IdP token must be a client-credentials token (the service account `service-account-<client>`, never a person, no `act`),
audience `nova-web`, scope `orion:run.execute`, `azp` in `NOVA_FORGE_INBOUND_CLIENTS` (default `forge-service`), signed RS256 by
the issuer's JWKS (`NOVA_FORGE_INBOUND_ISSUER`, default `NOVA_OIDC_ISSUER`; keys fetched from `<issuer>/protocol/openid-connect/certs`)
and well-formed under the claims contract (`docs/CONTRACTS.md`). Any other token, for any reason, is the same 401 `UNAUTHORIZED`.
Switch over: create FORGE's service client in the IdP (the realm `orion` ships `nova-service` only: a `forge-service` client with
client credentials, an audience mapper for `nova-web` and the scope `orion:run.execute` is to be added there), set `both`, give FORGE
the token flow, check, then `oidc`. Roll back by setting `token` again (the bearer is unchanged and was never removed).

## Account migration tool (NOV-113, ADR 001 §8)

`uv run python -m nova.migration.accounts <command>` (in the API container: `python -m nova.migration.accounts`) moves accounts to the
shared identity provider **without ever changing a local id** (migration 0022 adds the empty table `account_migrations`; an
account without a row signs in exactly as before; nothing here runs by itself). **Running it in production is the owner's separate
decision**: any write command refuses in production unless `ORION_MIGRATION_ALLOW_PRODUCTION=owner-decision` is set.

| Phase (ADR §8) | Command | Writes? |
|---|---|---|
| 0. Inventory | `inventory [--emails hash\|masked\|clear] [--format json\|csv] [--out FILE]` | **never** |
| 2. Reconciliation | `reconcile --idp-export FILE [--domains d1,d2] [--emit-approval FILE]` | **never** (dry run) |
| 2. Approve | review the template (delete the pairs that must not be linked), then `sign-approval FILE --approved-by NAME` | the file only |
| 2. Link | `apply --idp-export FILE --approval FILE --confirm-backup ID` | links the approved pairs, all or nothing |
| 3. SSO by default | `break-glass --user U --confirm-backup ID`, then `flags --user U --disable-password\|--sso-required --confirm-backup ID` | one account |
| back | `flags --user U --enable-password` (one command, nothing required), `rollback --batch B --confirm-backup ID`, `break-glass --user U --unset` | yes |

* **Inventory**: per account the e-mail (**hashed** with `ORION_INVENTORY_SALT`, the same salt in the three services so the tables can be
  joined; `masked`; or `clear` only with `--confirm-sensitive`), domain, role, effective clearance and its source, workspace, last seen,
  link and flags, problems (`duplicate_email`, `email_not_verifiable`), and a summary; service accounts, and the *existence* (never the value) of the keys.
  Files written with `--out` are mode 0600.
* **Reconciliation** proposes a pair only when nothing is in doubt; conflicts it reports for a person to decide: `duplicate_local_email`
  (merged by an administrator, never automatically), `email_missing`, `unexpected_domain`, `idp_email_unverified` (the address alone proves
  nothing), `duplicate_idp_email`, `sub_already_linked`, `workspace_mismatch` (the workspace comes from the inventory, not the domain),
  `linked_sub_missing_in_idp`. The IdP export is JSON (list or `{"users": [...]}`) or CSV: `sub,email,email_verified[,workspace_id]`.
  Sign-in time confirmation by the user (ADR §8 phase 2) stays the rule in the application: this tool links only pairs a person approved.
* **Approval file**: signed with an HMAC (`ORION_APPROVAL_KEY`, ≥ 32 characters, held by the approver, not by the operator running `apply`)
  over the batch, the proposal hash, the pairs, the approver and the time. `apply` refuses an unsigned or edited file, another key, a data set that
  moved since the approval, a pair that is not in the *current* proposal (nothing is applied then), and a missing or malformed backup id.
* **Flags**: a closed password (`password_login_disabled` / `sso_required`) is refused for an unlinked account, for a break-glass account, and
  while no break-glass administrator exists; the NOVA password sign-in answers a closed account like a wrong password (audited as
  `auth.password_refused`). The break-glass administrator is a person with the administrator role, outside SSO, with a strong password held offline.
* Everything is audited: `account.link`, `account.password_closed`, `account.password_reopened`, `account.break_glass_set|unset`, `account.rollback`.

**Restore procedure.** Before `apply`, `flags` or `break-glass`: take a database backup (`pg_dump`) and note its identifier (the tool records it
in the audit trail). To undo one batch: `rollback --batch <batch>` (removes its links, re-opens the passwords it closed; no account is deleted).
To re-open one password: `flags --user U --enable-password`. To go back further: restore the backup (the only table touched is
`account_migrations`, so `TRUNCATE account_migrations` also returns every account to "untouched"). Rehearse on pre-production data first.

## FORGE capture outbox

A finished run's capture into FORGE is recorded first in the `forge_outbox` table (before the run completes, key
`nova-task:<task id>`), then sent right away. If FORGE is down the row stays `pending` and the worker task
`nova.process_forge_outbox` (every minute, queue `maintenance`) retries it with an exponential backoff (30 s, 1 min … 1 h)
up to `NOVA_FORGE_OUTBOX_MAX_ATTEMPTS` (default 10), then marks it `failed` (the failure queue; a refusal by FORGE other
than 408/425/429 fails at once). `skipped` = nothing was sent (classification guard, FORGE not configured). A run already
linked to a FORGE run is never sent twice; the answer is never stored in the outbox, and a row is emptied once settled.
Unhelpful feedback that cannot reach FORGE waits the same way and is delivered after the capture, with no user action.
State: `GET /api/v1/admin/forge-outbox` (counts per status, age of the oldest waiting row) and
`GET /api/v1/admin/forge-outbox/metrics` (Prometheus text format: `nova_forge_outbox_rows{status}` and
`nova_forge_outbox_oldest_waiting_seconds`; administrator credentials required, no `prometheus_client` dependency).
Alert on `failed > 0` or an oldest waiting age above a few minutes.

## Scaling

| Component | Scaling |
|---|---|
| api | stateless; SSE follows Valkey pub/sub, so any replica can stream any execution |
| worker | horizontal; `acks_late` + LangGraph Postgres checkpoints: a lost pod's execution resumes from its last checkpoint; stale queued work is re-dispatched every 2 minutes |
| beat | exactly one replica |
| inference | vLLM replicas behind a service; guided JSON decoding for structured outputs |

## Observability

* OpenTelemetry (OTLP/HTTP) via `NOVA_OTEL_EXPORTER_OTLP_ENDPOINT`: root span `invoke_agent nova` per execution,
  one span per graph node, `chat <model>` spans with GenAI attributes (`gen_ai.request.model`,
  `gen_ai.usage.input_tokens`…). Free text is redacted; prompts/completions are never put on spans.
* Every execution has a `trace_id` (shown in Work and on each reply). FORGE-initiated runs continue FORGE's
  `traceparent`.
* Logs pass through a redaction filter (keys, JWTs, emails, phone numbers, IBAN/cards + `NOVA_REDACT_PATTERNS`).
* `/health` (liveness) and `/ready` (Postgres + Valkey).

## Data

NOVA's Postgres holds conversations, executions, Artifacts and **references** (ORBIT retrieval ids and the
excerpts actually served, FORGE run ids). It never stores ORBIT's knowledge base or FORGE's traces.
Back it up like any OLTP database; LangGraph checkpoint tables (`checkpoints*`) live in the same database.

## Demo LLM from a laptop (LM Studio or Ollama, authenticated tunnel)

For demos without a GPU server, the laptop's LM Studio (server on port 1234) or Ollama (11434) can serve the
deployed NOVA. Neither requires authentication, so `infrastructure/llm-tunnel/proxy.py` sits in front of it: it requires
`Authorization: Bearer <key>`, forwards only `/v1/chat/completions` and `/v1/models`, and keeps slow
non-streamed completions alive past the tunnel's time-to-first-byte limit.

```bash
python -c "import secrets; print(secrets.token_urlsafe(40))" > ~/.nova-llm-key && chmod 600 ~/.nova-llm-key
LLM_UPSTREAM_URL=http://127.0.0.1:1234 PROXY_KEY_FILE=~/.nova-llm-key uv run --with httpx --with starlette --with uvicorn \
  uvicorn proxy:app --app-dir infrastructure/llm-tunnel --host 127.0.0.1 --port 11500
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:11500      # prints https://<random>.trycloudflare.com
```

Then set on `api`, `worker` and `beat`: `NOVA_LLM_PROVIDER=openai_compatible`,
`NOVA_LLM_BASE_URL=https://<random>.trycloudflare.com/v1`, `NOVA_LLM_MODEL=<model id from GET /v1/models>`,
`NOVA_LLM_API_KEY=<key>`, `NOVA_LLM_TIMEOUT_SECONDS=900`. The quick-tunnel URL changes on every restart and
the laptop must stay awake: use a GPU vLLM server for real production. A tunnel URL is an *external* host to NOVA:
set `NOVA_LLM_LOCAL=true` only if the model really runs inside your perimeter, otherwise C2/C3 work is refused.

### Permanent install on the Mac (launchd)

```bash
infrastructure/llm-tunnel/install-macos.sh <railway-project-id> /path/to/cloudflared http://127.0.0.1:1234
```

Installs two user services that start at login and restart on failure: `com.nova.llm-proxy` (authenticated proxy)
and `com.nova.llm-tunnel` (`supervisor.py`: Cloudflare quick tunnel; every new URL is pushed to
`NOVA_LLM_BASE_URL` on `api`, `worker`, `beat`; a tunnel deleted by Cloudflare is recreated). State and logs live in
`~/.nova-llm-tunnel/` (key `0600`). LM Studio must keep its server running (Developer → Start server, or "start on
login"). The Mac must stay awake for NOVA to answer.

---

## Model fallback and circuit breaker

`NOVA_LLM_FALLBACK_MODELS` (JSON list, default empty) names models tried in order when the main one fails
*transiently* (overload, timeout, connection error); same provider and base URL, another model name. A model that
fails `NOVA_LLM_CIRCUIT_FAILURES` times in a row (default 3) is skipped for `NOVA_LLM_CIRCUIT_COOLDOWN_SECONDS`
(default 60), then probed once. Non-retryable errors (bad request, refused content) are never retried elsewhere,
streams only fall back before the first chunk, and a user's own key (bring your own model) never falls back to the
organization's models. Every attempt, failed ones included, is a row of `llm_calls`.

---

## Spending limits and per-Skill models

* `NOVA_RUN_COST_BUDGET_USD`, `NOVA_RUN_TOKEN_BUDGET`, `NOVA_USER_DAILY_COST_BUDGET_USD` (default 0 = unlimited). They
  are checked **before** each model call, so a runaway run stops with a clear message ("This task reached its cost
  limit…") instead of a surprise bill; completed steps are kept and nothing is retried or sent to a fallback model.
  Cost needs the prices (`NOVA_LLM_PRICE_*`, see *Model fallback*); tokens always work. The daily user limit sums the
  user's calls since midnight UTC.
* `NOVA_LLM_SKILL_MODELS` (JSON, skill id → model) makes another model write a Skill's generation and revision
  steps, e.g. a cheaper one for summaries. Only models NOVA is already allowed to use count (the main model,
  `NOVA_LLM_FALLBACK_MODELS`, `NOVA_REPLAY_MODELS`); any other is ignored with a warning. A user's own key is never
  rerouted. FORGE's `GET /analytics/efficiency` suggests where a cheaper model is as good.

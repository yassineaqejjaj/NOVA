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
* Retention: `NOVA_CONTEXT_REFERENCE_RETENTION_DAYS`, `NOVA_EXECUTION_EVENT_RETENTION_DAYS` (daily job).

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

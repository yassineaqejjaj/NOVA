# Operations

## Production checklist

* `NOVA_ENV=production` — the API refuses to start with development secrets or `NOVA_AUTH_MODE=dev`.
* Secrets (≥ 32 chars): `NOVA_SESSION_SECRET`, `NOVA_SECRETS_KEY` (encrypts ORBIT session tokens),
  `NOVA_FORGE_INBOUND_TOKEN`, `NOVA_OIDC_CLIENT_SECRET`, `NOVA_FORGE_API_KEY`. Provide them through your secret store.
* `NOVA_COOKIE_SECURE=true` behind HTTPS; Keycloak realm `nova` with client `nova-web` (confidential, PKCE S256,
  redirect `https://<host>/api/v1/auth/callback`, audience mapper) — see `infrastructure/keycloak/nova-realm.json`.
* Organization policy: `NOVA_POLICY_ALLOW_AUTO_EXTERNAL_WRITES` (default `false`: writes to ORBIT always need
  approval), `NOVA_POLICY_MAX_CLASSIFICATION` (cap on the classification NOVA requests from ORBIT).
* Retention: `NOVA_CONTEXT_REFERENCE_RETENTION_DAYS`, `NOVA_EXECUTION_EVENT_RETENTION_DAYS` (daily job).

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

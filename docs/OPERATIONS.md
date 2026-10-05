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
the laptop must stay awake: use a GPU vLLM server for real production.

### Permanent install on the Mac (launchd)

```bash
infrastructure/llm-tunnel/install-macos.sh <railway-project-id> /path/to/cloudflared http://127.0.0.1:1234
```

Installs two user services that start at login and restart on failure: `com.nova.llm-proxy` (authenticated proxy)
and `com.nova.llm-tunnel` (`supervisor.py`: Cloudflare quick tunnel; every new URL is pushed to
`NOVA_LLM_BASE_URL` on `api`, `worker`, `beat`; a tunnel deleted by Cloudflare is recreated). State and logs live in
`~/.nova-llm-tunnel/` (key `0600`). LM Studio must keep its server running (Developer → Start server, or "start on
login"). The Mac must stay awake for NOVA to answer.

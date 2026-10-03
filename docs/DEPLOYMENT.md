# Deployment (production)

NOVA runs on **Railway** (backend, identity, data) and **Vercel** (web). ORBIT and FORGE are separate
deployments of their own repositories; NOVA only needs their URLs.

| Component | Platform | URL |
|---|---|---|
| Web (Next.js) | Vercel project `nova` | https://nova-six-orcin-96.vercel.app |
| API (`nova_api`) | Railway project `nova`, service `api` | https://api-production-dfe1.up.railway.app |
| Keycloak (OIDC) | Railway, service `keycloak` | https://keycloak-production-e609.up.railway.app |
| Worker / Beat (Celery) | Railway, services `worker`, `beat` | private |
| Valkey (broker, live events) | Railway, service `valkey` | private (`valkey.railway.internal`) |
| PostgreSQL (NOVA) | Railway, `Postgres` | private |
| PostgreSQL (Keycloak) | Railway, `Postgres-tDoj` | private |
| ORBIT | Railway `orbit` + Vercel `orbit` | https://api-production-deffe.up.railway.app · https://orbit-virid-psi-70.vercel.app |
| FORGE | Railway `forge` + Vercel `forge` | https://api-production-b165a.up.railway.app · https://forge-pied-rho.vercel.app |

```
Browser ──► Vercel (web + same-origin /api proxy, cookies first-party) ──► Railway api ──► Postgres
   │                                                                       │  ├─► Valkey ◄── worker / beat
   └──► Keycloak (login) ◄──────────── OIDC back-channel ──────────────────┘  ├─► ORBIT API (as the user)
                                                                              ├─► FORGE API (fgk_ key)
                                                                              └─► LLM (OpenAI-compatible, self-hosted)
```

## How the pieces are configured

* **One backend image** (`infrastructure/docker/backend.Dockerfile`) for `api`, `worker` and `beat`; the process
  comes from `NOVA_PROCESS`. Every service sets `RAILWAY_DOCKERFILE_PATH`. The API runs migrations on start
  (`alembic upgrade head`), listens on `$PORT` on IPv4 + IPv6, and seeds the demo data when `NOVA_SEED_DEMO=true`
  (idempotent).
* **Keycloak** (`infrastructure/railway/keycloak.Dockerfile`) runs `start --optimized` behind the Railway proxy
  (`KC_PROXY_HEADERS=xforwarded`) and imports the `nova` realm on first start. The realm's redirect URI, client
  secret and demo password come from `NOVA_PUBLIC_URL`, `NOVA_OIDC_CLIENT_SECRET`, `NOVA_DEMO_PASSWORD`.
  The import runs **only if the realm does not exist yet**: change those values in the Keycloak admin console
  afterwards.
* **Valkey** (`infrastructure/railway/valkey.Dockerfile`) requires `VALKEY_PASSWORD`, has no public domain.
* **Web on Vercel**: root directory `apps/web`, Node 22, Fluid compute. The only variable is `NOVA_API_URL`
  (read at runtime by `src/app/api/[...path]/route.ts`, no rebuild needed to change it). Live execution streams
  (SSE) run up to 300 s per request and reconnect with replay.
* Production refuses unsafe settings at startup (`nova/config.py`): dev secrets, `NOVA_AUTH_MODE=dev`,
  non-https `NOVA_PUBLIC_URL`, `NOVA_COOKIE_SECURE=false`, missing `NOVA_OIDC_CLIENT_SECRET`.

### Variables (Railway)

Backend (`api`, `worker`, `beat` share the same secrets):

| Variable | Value |
|---|---|
| `NOVA_ENV` | `production` |
| `NOVA_DATABASE_URL` | `${{Postgres.DATABASE_URL}}` (converted to asyncpg automatically) |
| `NOVA_VALKEY_URL` | `redis://default:${{valkey.VALKEY_PASSWORD}}@${{valkey.RAILWAY_PRIVATE_DOMAIN}}:6379/0` |
| `NOVA_PUBLIC_URL` | the Vercel URL |
| `NOVA_OIDC_ISSUER` | `<keycloak URL>/realms/nova` |
| `NOVA_OIDC_CLIENT_SECRET` | same value as on `keycloak` |
| `NOVA_SESSION_SECRET`, `NOVA_SECRETS_KEY`, `NOVA_FORGE_INBOUND_TOKEN` | random, ≥ 32 chars |
| `NOVA_COOKIE_SECURE` | `true` |
| `NOVA_LLM_PROVIDER` / `_BASE_URL` / `_MODEL` / `_API_KEY` | OpenAI-compatible self-hosted server (vLLM, Ollama) |
| `NOVA_ORBIT_BASE_URL` / `NOVA_ORBIT_PUBLIC_URL` | ORBIT API / web |
| `NOVA_FORGE_BASE_URL` / `NOVA_FORGE_PUBLIC_URL` / `NOVA_FORGE_API_KEY` | FORGE API / web / `fgk_` key |
| `NOVA_PROCESS` | `api` · `worker` · `beat` |

Secrets are only stored in Railway (`railway variable list -s api`). Never commit them.

## Deploying a new version

```bash
git push                                        # CI: lint, tests (SQLite + Postgres), typecheck, build, E2E, images
railway up -s api --detach                      # same for worker, beat (and keycloak / valkey when they change)
npx vercel deploy --prod                        # from the repository root
```

To deploy automatically on every push, connect the GitHub repository to each Railway service
(Service → Settings → Source) and to the Vercel project (`npx vercel git connect`).

## Connecting FORGE

FORGE has no command to create an API key: an admin creates it once.

1. FORGE → Settings → API keys: create `nova` with role **evaluator** (or **editor** to let NOVA capture
   production executions). Set it as `NOVA_FORGE_API_KEY` on `api`, `worker` and `beat`.
2. FORGE → Settings → Credentials: create a credential of kind **nova**, base URL
   `https://api-production-dfe1.up.railway.app`, secret = `NOVA_FORGE_INBOUND_TOKEN`
   (`railway variable list -s api --kv | grep FORGE_INBOUND`).
3. NOVA registers itself as agent `nova` on its first capture (`NOVA_FORGE_CAPTURE_POLICY`).

## Connecting ORBIT

Each user links their own ORBIT account in NOVA (**Settings → ORBIT**). NOVA retrieves context as that user,
so ORBIT's permissions and C0–C3 classification apply unchanged. No CORS or ORBIT-side configuration is needed.

## LLM

Railway has no GPU. NOVA needs an OpenAI-compatible server reachable over HTTPS with an API key, for example
vLLM on a GPU host (`--api-key`). For demos, `docs/OPERATIONS.md` (“Demo LLM from a laptop”) describes exposing a laptop's Ollama
through an authenticated tunnel; its URL changes when the tunnel restarts, so update `NOVA_LLM_BASE_URL`
on `api`, `worker` and `beat` accordingly.

## Operations

* Health: `GET /health` (API). Logs: `railway logs -s api` (also `worker`, `beat`, `keycloak`).
* Keycloak admin: `<keycloak URL>/admin` with `KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD` (Railway variables).
  Create real users there (or federate your IdP) and disable the demo user for a real rollout.
* Backups: enable Railway PostgreSQL backups on both databases.
* Rollback: Railway → service → Deployments → Redeploy a previous one; Vercel → Deployments → Promote.

# Open-source components

NOVA's runtime is **exclusively open source and self-hostable**. It runs inside private infrastructure,
without external network access and without any proprietary SaaS (no OpenAI/Anthropic/Gemini/Azure/Bedrock/
Vertex APIs, no LangSmith, Auth0, Clerk, Pinecone or Datadog). Licenses below were read from the installed
package metadata (`importlib.metadata`, `package.json`) on 2026-10-03.

## Platform services

| Component | Version | License | Role |
|---|---|---|---|
| PostgreSQL | 17 | PostgreSQL License | NOVA database, LangGraph checkpoints, Keycloak database (local) |
| Valkey | 8 | BSD-3-Clause | Celery broker, execution event pub/sub, short-lived state |
| Keycloak | 26.8 | Apache-2.0 | OIDC / SSO / realm roles (RBAC) |
| vLLM | configurable | Apache-2.0 | Inference server (OpenAI-compatible API, guided JSON decoding) |
| Ollama | optional | MIT | Laptop inference alternative (`--profile cpu-llm`) |
| Jaeger | optional | Apache-2.0 | Local OTLP trace backend (`--profile observability`) |
| ORBIT | sibling repo | ORION | Context, memory, knowledge (not duplicated) |
| FORGE | sibling repo | ORION | Traces, evaluation, improvement (not duplicated) |

Models are configuration, not code. Suggested open-weight defaults: Qwen2.5-7B/32B-Instruct (Apache-2.0),
Qwen3-8B (Apache-2.0). Check the license of any model you deploy.

## Backend (Python 3.12)

| Package | Version | License | Why |
|---|---|---|---|
| fastapi | 0.142 | MIT | HTTP API |
| uvicorn | 0.54 | BSD-3-Clause | ASGI server |
| pydantic / pydantic-settings | 2.13 / 2.15 | MIT | Typed state, structured outputs, settings |
| sqlalchemy | 2.1 | MIT | ORM (async) |
| asyncpg | 0.31 | Apache-2.0 | PostgreSQL driver (application) |
| psycopg | 3.3 | LGPL-3.0-only | PostgreSQL driver (LangGraph checkpointer; used unmodified as a library) |
| alembic | 1.20 | MIT | Migrations |
| langgraph | 1.2 | MIT | Agent execution graph, interrupts, checkpoints |
| langgraph-checkpoint-postgres | 3.1 | MIT | Durable, resumable executions |
| langchain-core | 1.6 | MIT | Transitive dependency of LangGraph only (NOVA's domain does not use LangChain abstractions) |
| celery (+ kombu, billiard) | 5.6 | BSD-3-Clause / BSD | Background execution, retries, scheduling |
| redis (client) | 8.1 | MIT | Valkey client |
| httpx | 0.28 | BSD-3-Clause | ORBIT, FORGE, inference clients |
| sse-starlette | 3.5 | BSD-3-Clause | Server-Sent Events |
| pyjwt | 2.15 | MIT | OIDC token validation (JWKS), NOVA sessions |
| cryptography | 50 | Apache-2.0 OR BSD-3-Clause | Fernet encryption of ORBIT session tokens |
| pyyaml | 6.0 | MIT | Skill and Artifact type specs |
| jsonschema | 4.26 | MIT | Skill/item schema validation |
| opentelemetry-sdk, -exporter-otlp-proto-http, -instrumentation-fastapi | 1.45 / 0.66b0 | Apache-2.0 | Tracing (GenAI semantic conventions) |
| email-validator | 2.3 | Unlicense | Pydantic dependency |

Development only: pytest (MIT), pytest-asyncio (Apache-2.0), respx (BSD-3-Clause), ruff (MIT), aiosqlite (MIT).

## Frontend (Node 22)

| Package | Version | License | Why |
|---|---|---|---|
| next | 15.5 | MIT | App framework (standalone server) |
| react / react-dom | 19.3 | MIT | UI |
| tailwindcss | 4.3 | MIT | Styling |
| shadcn/ui pattern on @radix-ui/* | 1.x–2.x | MIT | Accessible primitives (`packages/ui`) |
| class-variance-authority | 0.7 | Apache-2.0 | Component variants |
| clsx / tailwind-merge | 2.1 / 3.7 | MIT | Class composition |
| lucide-react | 1.51 | ISC | Icons |
| @tanstack/react-query | 5.104 | MIT | Server state |
| zustand | 5.0 | MIT | Client state |
| lexical (+ @lexical/*) | 0.52 | MIT | Artifact rich-text editing |
| framer-motion | 14.0 | MIT | Motion |
| cmdk | 1.1 | MIT | Command palette |
| react-markdown / remark-gfm | 10.1 / 4.0 | MIT | Rendering NOVA text blocks |
| sonner | 2.0 | MIT | Toasts |
| geist (fonts, self-hosted) | 1.7 | SIL OFL 1.1 | Typography, no font CDN |

Development only: TypeScript (Apache-2.0), ESLint (MIT), @playwright/test (Apache-2.0).

## Not used (by design)

CrewAI, AutoGen, PydanticAI, additional workflow engines, vector databases, RAG stacks or memory frameworks:
LangGraph covers orchestration and ORBIT owns retrieval and memory (docs/ARCHITECTURE.md).

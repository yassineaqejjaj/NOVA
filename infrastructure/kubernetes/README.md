# NOVA on Kubernetes

Plain manifests (kustomize-ready). They assume PostgreSQL, Valkey, Keycloak, an inference server (vLLM),
ORBIT and FORGE are reachable inside the cluster; managed or in-cluster operators are both fine.

```bash
kubectl create namespace nova
kubectl -n nova create secret generic nova-secrets \
  --from-literal=NOVA_DATABASE_URL='postgresql+asyncpg://nova:***@postgres:5432/nova' \
  --from-literal=NOVA_SESSION_SECRET="$(openssl rand -hex 32)" \
  --from-literal=NOVA_SECRETS_KEY="$(openssl rand -hex 32)" \
  --from-literal=NOVA_OIDC_CLIENT_SECRET='***' \
  --from-literal=NOVA_FORGE_API_KEY='fgk_***' \
  --from-literal=NOVA_FORGE_INBOUND_TOKEN="$(openssl rand -hex 32)"
kubectl apply -k infrastructure/kubernetes
```

* `api` runs migrations (`alembic upgrade head`) on start; run one replica during upgrades or use the `migrate` Job.
* `worker` scales horizontally (Celery `acks_late` + LangGraph checkpoints make executions resumable on pod loss).
* `beat` must run as a single replica.
* Executions stream through Valkey pub/sub, so the API can scale out behind any ingress (SSE needs
  `proxy-buffering off` — set on the ingress below).

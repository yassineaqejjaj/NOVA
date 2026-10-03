# Valkey (Celery broker + live event pub/sub) for Railway: private network only, password required.
FROM valkey/valkey:8-alpine
EXPOSE 6379
CMD ["sh", "-c", "exec valkey-server --bind '* -::*' --port 6379 --protected-mode no --requirepass \"$VALKEY_PASSWORD\" --maxmemory-policy noeviction"]

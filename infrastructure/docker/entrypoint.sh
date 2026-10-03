#!/bin/sh
# NOVA backend entrypoint. The process comes from the first argument or NOVA_PROCESS (Railway: one image,
# several services). Listens on $PORT when the platform provides one, on IPv4 and IPv6 (private networking).
set -e
PROCESS="${1:-${NOVA_PROCESS:-api}}"
[ $# -gt 0 ] && shift
case "$PROCESS" in
  api)
    alembic upgrade head
    if [ "${NOVA_SEED_DEMO:-false}" = "true" ]; then python -m nova.seed; fi
    exec uvicorn nova_api.main:app --host "${NOVA_BIND_HOST:-::}" --port "${PORT:-8200}" \
      --workers "${NOVA_API_WORKERS:-1}" --proxy-headers --forwarded-allow-ips="${NOVA_FORWARDED_ALLOW_IPS:-*}" \
      --timeout-graceful-shutdown 20
    ;;
  worker)
    exec celery -A nova_worker.app worker -Q executions,maintenance --concurrency "${NOVA_WORKER_CONCURRENCY:-2}" --loglevel INFO
    ;;
  beat)
    exec celery -A nova_worker.app beat --loglevel INFO --schedule /tmp/celerybeat-schedule
    ;;
  migrate)
    exec alembic upgrade head
    ;;
  seed)
    exec python -m nova.seed "$@"
    ;;
  *)
    exec "$PROCESS" "$@"
    ;;
esac

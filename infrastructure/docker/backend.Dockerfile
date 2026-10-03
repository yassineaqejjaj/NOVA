# NOVA backend image (api, worker, beat). Python 3.12 + uv, non-root, no build tools at runtime.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    PYTHONPATH=/app:/app/apps/api:/app/services/worker
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"

COPY alembic.ini ./
COPY alembic ./alembic
COPY nova ./nova
COPY apps/api ./apps/api
COPY services/worker ./services/worker
COPY skills ./skills
COPY artifacts ./artifacts
COPY packages/schemas ./packages/schemas
COPY infrastructure/docker/entrypoint.sh /entrypoint.sh

RUN useradd --create-home --uid 10001 nova && chmod +x /entrypoint.sh \
    && python -m nova.skills.build --check
USER nova
EXPOSE 8200
ENTRYPOINT ["/entrypoint.sh"]
CMD []

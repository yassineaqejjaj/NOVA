"""NOVA settings (environment variables prefixed ``NOVA_``; see ``.env.example``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

DEV_SESSION_SECRET = "nova-dev-session-secret-change-me-0123456789abcdef"
DEV_SECRETS_KEY = "nova-dev-secrets-key-change-me-0123456789abcdef"
DEV_FORGE_INBOUND_TOKEN = "nova-dev-forge-inbound-token"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_", env_file=".env", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    version: str = "0.1.0"
    public_url: str = "http://localhost:3200"

    # --- Infrastructure -------------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://nova:nova@localhost:5435/nova"
    valkey_url: str = "redis://localhost:6382/0"
    celery_broker_url: str | None = None  # defaults to valkey_url
    celery_task_always_eager: bool = False
    # With eager execution: "await" runs inside the request (unit/integration tests); "background" schedules it on
    # the API's event loop so the SSE stream is exercised (E2E without a worker).
    inline_execution: Literal["await", "background"] = "await"

    # --- Authentication (Keycloak / OIDC) --------------------------------------------------------
    auth_mode: Literal["oidc", "dev"] = "oidc"
    oidc_issuer: str = "http://localhost:8280/realms/nova"  # expected `iss`, browser-facing
    oidc_internal_url: str | None = None  # back-channel base (container network), defaults to issuer
    oidc_client_id: str = "nova-web"
    oidc_client_secret: str = ""
    oidc_audience: str = "nova-web"
    oidc_admin_role: str = "nova-admin"
    session_secret: str = DEV_SESSION_SECRET
    session_ttl_minutes: int = 720
    cookie_secure: bool = False

    # --- Secrets ----------------------------------------------------------------------------------
    secrets_key: str = DEV_SECRETS_KEY  # Fernet key material for ORBIT session tokens

    # --- LLM (open-weight, self-hosted) -----------------------------------------------------------
    llm_provider: Literal["vllm", "openai_compatible"] = "vllm"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = ""
    llm_api_key: str = ""  # optional (vLLM --api-key)
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.2

    # --- ORBIT --------------------------------------------------------------------------------
    orbit_base_url: str = "http://localhost:8000"
    orbit_public_url: str = "http://localhost:3000"
    orbit_agent_keys: str = ""  # "slug:orb_key,slug2:orb_key2" (service mode, see integration-analysis G-O2)
    orbit_timeout_seconds: float = 45.0  # ORBIT cold-starts its embedding model on the first request
    orbit_default_token_budget: int = 4000

    # --- FORGE --------------------------------------------------------------------------------
    forge_base_url: str = "http://localhost:8100"
    forge_public_url: str = "http://localhost:3100"
    forge_api_key: str = ""  # fgk_… with role evaluator/editor
    forge_inbound_token: str = DEV_FORGE_INBOUND_TOKEN  # bearer FORGE sends to the NOVA Agent Protocol
    forge_capture_policy: Literal["off", "on_feedback", "sampled", "all"] = "on_feedback"
    forge_capture_sample_rate: float = 0.1
    forge_timeout_seconds: float = 20.0

    # --- Observability --------------------------------------------------------------------------
    otel_exporter_otlp_endpoint: str = ""
    otel_exporter_otlp_headers: str = ""
    otel_service_name: str = "nova"
    redact_patterns: str = ""  # extra regexes (comma separated) redacted from logs/telemetry

    # --- Policy -------------------------------------------------------------------------------
    policy_allow_auto_external_writes: bool = False
    policy_max_classification: int = Field(default=3, ge=0, le=3)
    context_reference_retention_days: int = 180
    execution_event_retention_days: int = 90
    max_workflow_steps: int = 8
    max_tool_iterations: int = 2

    # --- Paths ----------------------------------------------------------------------------------
    skills_dir: Path = REPO_ROOT / "skills"
    artifact_types_dir: Path = REPO_ROOT / "artifacts" / "types"
    item_schemas_dir: Path = REPO_ROOT / "packages" / "schemas" / "items"

    @field_validator("database_url")
    @classmethod
    def _asyncpg_url(cls, value: str) -> str:
        """Accept platform URLs (``postgres://…?sslmode=require``, Railway/Heroku style) and use asyncpg."""
        parts = urlsplit(value)
        if parts.scheme not in ("postgres", "postgresql"):
            return value
        query = dict(parse_qsl(parts.query))
        sslmode = query.pop("sslmode", None)
        if sslmode and sslmode != "disable":
            query["ssl"] = sslmode
        return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, urlencode(query), parts.fragment))

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.valkey_url

    @property
    def oidc_backchannel(self) -> str:
        return (self.oidc_internal_url or self.oidc_issuer).rstrip("/")

    def orbit_agent_key_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for pair in self.orbit_agent_keys.split(","):
            slug, sep, key = pair.strip().partition(":")
            if sep and slug and key:
                result[slug.strip()] = key.strip()
        return result

    @model_validator(mode="after")
    def _refuse_dev_secrets_in_production(self) -> Settings:
        if self.is_production:
            problems = []
            if self.session_secret == DEV_SESSION_SECRET or len(self.session_secret) < 32:
                problems.append("NOVA_SESSION_SECRET")
            if self.secrets_key == DEV_SECRETS_KEY or len(self.secrets_key) < 32:
                problems.append("NOVA_SECRETS_KEY")
            if self.forge_inbound_token == DEV_FORGE_INBOUND_TOKEN:
                problems.append("NOVA_FORGE_INBOUND_TOKEN")
            if self.auth_mode == "dev":
                problems.append("NOVA_AUTH_MODE=dev")
            if not self.cookie_secure:
                problems.append("NOVA_COOKIE_SECURE must be true")
            if not self.public_url.startswith("https://"):
                problems.append("NOVA_PUBLIC_URL must be https")
            if self.auth_mode == "oidc" and len(self.oidc_client_secret) < 16:
                problems.append("NOVA_OIDC_CLIENT_SECRET")
            if problems:
                raise ValueError("Development values are not allowed in production: " + ", ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

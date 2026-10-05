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
    remember_me_days: int = 30  # "Keep me signed in"
    cookie_secure: bool = False

    # --- Accounts: sign-up with a company address, verified by an e-mailed code -------------------
    signup_domains: str = "devoteam.com"  # comma-separated; "*" = any address; empty disables sign-up
    # "auto": confirm the address by an e-mailed code when NOVA can send e-mail, else activate the account at once
    signup_email_verification: Literal["auto", "required", "off"] = "auto"
    # Shared demo account, created / kept in sync at API start-up when both are set (password via secret variable)
    demo_account_email: str = ""
    demo_account_password: str = ""
    demo_account_name: str = "Compte démo"
    email_code_ttl_minutes: int = 15
    email_code_max_attempts: int = 5
    email_code_resend_seconds: int = 60
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # e.g. "NOVA <nova@devoteam.com>"
    smtp_starttls: bool = True  # STARTTLS on smtp_port; port 465 uses implicit TLS

    # --- Secrets ----------------------------------------------------------------------------------
    secrets_key: str = DEV_SECRETS_KEY  # Fernet key material for ORBIT session tokens

    # --- LLM (open-weight, self-hosted) -----------------------------------------------------------
    llm_provider: Literal["vllm", "openai_compatible", "anthropic"] = "vllm"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = ""
    llm_api_key: str = ""  # optional (vLLM --api-key)
    llm_timeout_seconds: float = 120.0
    llm_max_tokens: int = 4096
    # Extra completion budget for reasoning models (Gemma 4, Qwen 3…): their hidden reasoning counts against max_tokens.
    llm_reasoning_tokens: int = Field(default=0, ge=0, le=32768)
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

    # --- Voice (self-hosted speech-to-text / text-to-speech service) ---------------------------------
    voice_url: str = ""  # self-hosted voice service (empty: not deployed)
    voice_token: str = ""
    voice_timeout_seconds: float = 60.0
    # Providers: "selfhosted" (services/voice) or "elevenlabs"; the self-hosted service is the fallback when configured.
    voice_tts_provider: Literal["selfhosted", "elevenlabs"] = "selfhosted"
    voice_stt_provider: Literal["selfhosted", "elevenlabs"] = "selfhosted"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "EXAVITQu4vr4xnSDxMaL"  # premade "Sarah" (multilingual)
    elevenlabs_tts_model: str = "eleven_multilingual_v2"
    elevenlabs_stt_model: str = "scribe_v1"

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
    max_tool_iterations: int = 1  # tool rounds per Skill step (the project context is retrieved beforehand)
    validation_review: bool = True  # the Validation agent grades each deliverable with the model (else checks only)
    max_revisions: int = 1  # revisions NOVA may ask a specialist agent for after validation

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
    def signup_domain_list(self) -> list[str]:
        return [d.strip().lower().lstrip("@") for d in self.signup_domains.split(",") if d.strip()]

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @property
    def email_outbox(self) -> bool:
        """Outside production, codes go to a local outbox (logs + dev endpoint) when no SMTP server is set."""
        return not self.is_production and not self.smtp_configured

    @property
    def signup_any_domain(self) -> bool:
        return "*" in self.signup_domain_list

    @property
    def signup_verifies_email(self) -> bool:
        if self.signup_email_verification == "auto":
            return self.smtp_configured or self.email_outbox
        return self.signup_email_verification == "required"

    @property
    def signup_enabled(self) -> bool:
        can_verify = self.smtp_configured or self.email_outbox
        return bool(self.signup_domain_list) and (can_verify or not self.signup_verifies_email)

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
            if "elevenlabs" in (self.voice_tts_provider, self.voice_stt_provider) and not self.elevenlabs_api_key:
                problems.append("NOVA_ELEVENLABS_API_KEY (required by the ElevenLabs voice provider)")
            if self.voice_url and len(self.voice_token) < 24:
                problems.append("NOVA_VOICE_TOKEN (required with NOVA_VOICE_URL)")
            if self.llm_provider == "anthropic" and not self.llm_api_key:
                problems.append("NOVA_LLM_API_KEY (required by NOVA_LLM_PROVIDER=anthropic)")
            if problems:
                raise ValueError("Development values are not allowed in production: " + ", ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

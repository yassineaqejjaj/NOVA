"""NOVA settings (environment variables prefixed ``NOVA_``; see ``.env.example``)."""

from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

DEV_SESSION_SECRET = "nova-dev-session-secret-change-me-0123456789abcdef"
DEV_SECRETS_KEY = "nova-dev-secrets-key-change-me-0123456789abcdef"
DEV_FORGE_INBOUND_TOKEN = "nova-dev-forge-inbound-token"
#: The workspace every row belongs to until an identity provider says otherwise (NOV-107). Fixed before the migration
#: runs and never changed afterwards: ``ORION_DEFAULT_WORKSPACE_ID`` overrides it for an installation.
DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NOVA_", env_file=".env", extra="ignore", populate_by_name=True)

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    version: str = "0.1.0"
    build_commit: str = ""  # commit of the running build (NOVA_BUILD_COMMIT; else the platform's, reported to FORGE)
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

    # --- Workspaces (docs/adr/001-identite-federee.md §5 and §9, NOV-107) -----------------------------------------
    # "off": nothing changes (rows carry a workspace, no request is filtered); "shadow": the filter is computed and what it
    # would have hidden is counted (nova_workspace_shadow_total, log), nothing is refused; "enforce": every query is
    # filtered by the workspace of the request and a foreign object answers 404 like an unknown one.
    workspace_enforcement: Literal["off", "shadow", "enforce"] = "off"
    # Strict claims (ADR 001 §3-§4, NOV-104): a validated token without ``orion_workspace_id`` opens no workspace resource, a
    # malformed ORION claim refuses the token, ``orion_workspace_id`` decides the workspace of the account it creates and
    # the effective clearance is ``min(local clearance, orion_clearance)``. Off: tokens are read as before.
    workspace_strict_claim: bool = False
    # The workspace of every row created before an IdP gives one, and of every request while OIDC claims are not read.
    default_workspace_id: uuid.UUID = Field(
        default=DEFAULT_WORKSPACE_ID, validation_alias=AliasChoices("ORION_DEFAULT_WORKSPACE_ID", "NOVA_DEFAULT_WORKSPACE_ID")
    )

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
    # Self-healing: models tried, in order, when the main one fails transiently; a circuit breaker skips a model that keeps failing.
    llm_fallback_models: list[str] = Field(default_factory=list)
    llm_circuit_failures: int = Field(default=3, ge=1, le=100)
    llm_circuit_cooldown_seconds: float = Field(default=60.0, ge=1, le=3600)
    # Spending limits (0 = unlimited). Cost needs the prices below; tokens always work. Checked before every model call.
    run_cost_budget_usd: float = Field(default=0.0, ge=0)
    run_token_budget: int = Field(default=0, ge=0)
    user_daily_cost_budget_usd: float = Field(default=0.0, ge=0)
    # Model per Skill for the generation steps (skill id -> model), restricted to the models NOVA is already
    # allowed to use (the main one, the fallbacks, the replay allow-list). Others are ignored.
    llm_skill_models: dict[str, str] = Field(default_factory=dict)
    # Models a replay may switch to (empty: replays keep the configured model). Guards cost: a replay is a real run.
    replay_models: list[str] = Field(default_factory=list)
    # Cost model (USD per million tokens). 0 = self-hosted: calls are recorded with a cost of 0.
    llm_price_input_per_mtok: float = Field(default=0.0, ge=0)
    llm_price_output_per_mtok: float = Field(default=0.0, ge=0)
    llm_price_table: dict[str, tuple[float, float]] = Field(default_factory=dict)  # model -> (input, output)

    # Outbound guardrail (domain/llm_guardrail.py): content above this level is never sent to an external model.
    # A destination declared local (the whole organization endpoint, or hosts on the list) is not capped.
    llm_max_classification: int = Field(default=1, ge=0, le=3)
    llm_local: bool = False  # the organization's own model runs inside the perimeter (vLLM, Ollama…)
    llm_local_hosts: str = ""  # comma-separated hosts treated as internal (also for users' own endpoints)
    llm_redact_pii: bool = True  # mask secrets, e-mails, IBANs and phone numbers in prompts sent to an external model
    llm_allow_classified_external: bool = False  # production: explicit override to allow a ceiling above C1 on an external model

    # --- ORBIT --------------------------------------------------------------------------------
    # Revocation events (POST /api/v1/webhooks/orbit): HMAC secret of the ORBIT webhook; empty = endpoint disabled (503)
    orbit_webhook_secret: str = ""
    orbit_webhook_max_age_seconds: int = Field(default=86400, ge=0)  # older events are refused (0 = no limit)
    orbit_base_url: str = "http://localhost:8000"
    orbit_public_url: str = "http://localhost:3000"
    orbit_agent_keys: str = ""  # "slug:orb_key,slug2:orb_key2" (service mode, see integration-analysis G-O2)
    orbit_timeout_seconds: float = 45.0  # ORBIT cold-starts its embedding model on the first request
    orbit_default_token_budget: int = 4000

    # --- Figma (docs/design-figma.md §0): MCP + OAuth 2.1 (catalog clients only), REST token fallback ---------
    figma_mcp_url: str = "https://mcp.figma.com/mcp"
    figma_api_url: str = "https://api.figma.com"
    figma_oauth_client_id: str = ""
    figma_oauth_client_secret: str = ""
    figma_oauth_redirect_uri: str = ""  # empty: <NOVA_PUBLIC_URL>/api/v1/me/figma/callback
    figma_timeout_seconds: float = 30.0

    # --- FORGE --------------------------------------------------------------------------------
    forge_base_url: str = "http://localhost:8100"
    forge_public_url: str = "http://localhost:3100"
    forge_api_key: str = ""  # fgk_… with role evaluator/editor
    forge_inbound_token: str = DEV_FORGE_INBOUND_TOKEN  # bearer FORGE sends to the NOVA Agent Protocol
    forge_capture_policy: Literal["off", "on_feedback", "sampled", "all"] = "on_feedback"
    forge_capture_sample_rate: float = 0.1
    # "reexecute": FORGE replays the request under the version active at that moment (comparable across versions);
    # "observed": FORGE receives what really happened, with the run manifest (release monitoring, failures included).
    forge_capture_mode: Literal["reexecute", "observed"] = "reexecute"
    # Observed capture reports outcomes, never text. The user's request (redacted of personal data) is only sent when
    # this is on: it may hold confidential (C2) or secret (C3) material, so it is off unless the organization opts in.
    forge_capture_intent: bool = False
    # Highest classification (0-3) of the context of a run that may be captured: above it, capture by re-execution is
    # skipped (its state says so) and observed capture withholds the request text. C2 and C3 never leave by default.
    # Capture outbox (services/forge_outbox.py): attempts (exponential backoff, 30 s … 1 h) before a capture is marked failed
    forge_outbox_max_attempts: int = Field(default=10, ge=1, le=100)
    forge_max_capture_classification: int = Field(default=1, ge=0, le=3)
    forge_timeout_seconds: float = 20.0
    # FORGE `nova` credential (Settings → Credentials) whose secret is NOVA_FORGE_INBOUND_TOKEN: FORGE uses it to
    # authenticate when it calls NOVA back. Agent versions registered by NOVA reference it.
    # SDLC Autopilot runs are ingested by FORGE as observed runs (metrics and stage summaries, never code or diffs)
    forge_sdlc_ingest: bool = True
    # Auto-merge of an SDLC run needs a green CI: a repository without CI (or a run that was never checked) is not "clean".
    # false restores the old behaviour (no CI accepted), a run can still opt in with allow_merge_without_ci.
    sdlc_require_ci: bool = True
    # Self-improvement of the SDLC agent: runs FORGE scores below the threshold produce lessons, deployed as a new policy
    sdlc_improvement: bool = True
    sdlc_improvement_auto_deploy: bool = True  # false: the candidate waits for an administrator
    sdlc_improvement_threshold: float = Field(default=70.0, ge=0, le=100)  # used when FORGE gives no pass/fail verdict
    sdlc_improvement_rollback_min_runs: int = Field(default=3, ge=2, le=50)
    sdlc_improvement_rollback_drop: float = Field(default=10.0, ge=1, le=100)  # points below the previous version
    forge_credential_id: str = ""
    # NOVA API as reachable *from FORGE* (agent version endpoint). Empty: derived from NOVA_PUBLIC_URL.
    forge_nova_endpoint: str = ""

    # --- Training loop (docs/TRAINING.md): FORGE evaluates each agent on all its Skills, NOVA learns ----------
    training_enabled: bool = True  # needs NOVA_FORGE_API_KEY (role editor) and NOVA_FORGE_CREDENTIAL_ID
    training_interval_days: int = Field(default=0, ge=0, le=90)  # 0 = cycles started by an admin; N = every N days
    training_repetitions: int = Field(default=1, ge=1, le=5)  # runs per Skill and per arm
    training_max_skills: int = Field(default=0, ge=0, le=100)  # 0 = every Skill of the agent
    training_cycle_timeout_hours: int = Field(default=24, ge=1, le=168)
    # Time FORGE gives one training run (a multi-step Skill on a small model needs more than FORGE's 120 s default)
    training_run_timeout_seconds: int = Field(default=600, ge=60, le=3600)
    training_auto_promote: bool = True  # promote a candidate policy when FORGE validates it
    # Proof FORGE must give, outside production, before a learned policy meets users (docs/TRAINING.md): "enforce" holds
    # a candidate without proof (also when FORGE is unreachable), "warn" records it and goes on, "off" skips the check.
    policy_gate_mode: Literal["enforce", "warn", "off"] = "warn"
    policy_gate_min_gain: float = Field(default=0.02, ge=0, le=1)  # composite score (0-1) the candidate must gain
    policy_gate_min_evaluations: int = Field(default=3, ge=1, le=1000)  # independent scored runs per arm
    # Releases (docs/TRAINING.md): a validated candidate goes through a canary before reaching everyone.
    release_canary_percent: int = Field(default=10, ge=0, le=100)  # share of users; 0 = no canary
    release_canary_min_runs: int = Field(default=20, ge=1, le=10000)  # canary executions before a verdict
    release_max_failure_increase: float = Field(default=0.10, ge=0, le=1)  # rollback above this failure-rate gap
    release_approval: Literal["none", "full"] = "full"  # "full": a healthy canary waits for an administrator
    # After it goes live, FORGE keeps comparing the release with the one it replaced (observed runs).
    release_watch_days: int = Field(default=7, ge=1, le=90)  # how long an active release stays under watch
    release_health_rollback: bool = True  # roll back on a significant drop in success or rise in failures

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
    # Clearance of a user with no linked ORBIT account (or none known): what they may read of derived content.
    default_clearance: int = Field(default=1, ge=0, le=3)
    context_reference_retention_days: int = 180
    checkpoint_retention_days: int = Field(default=90, ge=0)  # LangGraph checkpoints of finished runs (0 = keep)
    # What happens to Artifacts derived from a forgotten source: "mark" (flagged, readable) or "purge" (deleted)
    forget_artifacts: Literal["mark", "purge"] = "mark"
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
    def figma_redirect_uri(self) -> str:
        return self.figma_oauth_redirect_uri or f"{self.public_url.rstrip('/')}/api/v1/me/figma/callback"

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

    def local_hosts(self) -> frozenset[str]:
        """Hosts inside the perimeter: the loopback addresses and ``NOVA_LLM_LOCAL_HOSTS``."""
        return frozenset(
            {"localhost", "127.0.0.1", "::1"} | {h.strip().lower() for h in self.llm_local_hosts.split(",") if h.strip()}
        )

    def is_local_host(self, base_url: str) -> bool:
        return (urlsplit(base_url).hostname or "").lower() in self.local_hosts()

    @property
    def llm_is_local(self) -> bool:
        """Is the organization's model inside the perimeter (declared, or a self-hosted endpoint on an internal host)?"""
        if self.llm_local:
            return True
        return self.llm_provider != "anthropic" and self.is_local_host(self.llm_base_url)

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
            if self.llm_max_classification > 1 and not self.llm_is_local and not self.llm_allow_classified_external:
                problems.append(
                    "NOVA_LLM_MAX_CLASSIFICATION above 1 with an external model "
                    "(declare it local with NOVA_LLM_LOCAL, or set NOVA_LLM_ALLOW_CLASSIFIED_EXTERNAL=true)"
                )
            if problems:
                raise ValueError("Development values are not allowed in production: " + ", ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

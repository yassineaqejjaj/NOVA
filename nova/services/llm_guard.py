"""Classification guard wiring: which destination a model is, and the audit trail of a refused call."""

from __future__ import annotations

from nova.agent.providers.guard import GuardedProvider
from nova.config import Settings, get_settings
from nova.domain.llm import LLMProvider
from nova.domain.llm_guardrail import CallScope, ClassificationBlocked, Destination
from nova.infra.db import session_scope
from nova.services.audit import audit


def org_destination(settings: Settings) -> Destination:
    """The organization's model: inside the perimeter when declared (``NOVA_LLM_LOCAL``) or on an internal host."""
    return Destination(f"{settings.llm_provider}/{settings.llm_model}", settings.llm_is_local)


def user_destination(settings: Settings, provider: str, model: str, base_url: str) -> Destination:
    """A user's own model (bring your own key): external, unless its endpoint host is on ``NOVA_LLM_LOCAL_HOSTS``."""
    return Destination(f"{provider}/{model}", bool(base_url) and settings.is_local_host(base_url))


def guard(
    provider: LLMProvider,
    scope: CallScope,
    destination: Destination,
    *,
    settings: Settings | None = None,
    task_id: str | None = None,
    user_id: str | None = None,
) -> GuardedProvider:
    settings = settings or get_settings()

    async def on_block(error: ClassificationBlocked, model: str) -> None:
        async with session_scope() as session:
            await audit(
                session,
                actor_id=user_id,
                action="llm.blocked",
                target_type="task" if task_id else "user",
                target_id=task_id or user_id,
                summary=f"Model call refused: C{error.level} content, external model limited to C{error.ceiling}",
                details={
                    "reason": "classification",
                    "level": error.level,
                    "ceiling": error.ceiling,
                    "destination": error.destination,
                    "model": model,
                },
            )

    return GuardedProvider(
        provider,
        scope,
        destination,
        max_classification=settings.llm_max_classification,
        redact_pii=settings.llm_redact_pii,
        on_block=on_block,
    )

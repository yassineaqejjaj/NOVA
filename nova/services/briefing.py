"""Spoken morning briefing: the Today page's own facts, as sentences NOVA can say aloud (domain/briefing.py)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.briefing import BriefItem, Lang, script
from nova.domain.permissions import Principal
from nova.infra.models import Artifact
from nova.services import today as today_service


async def build(session: AsyncSession, principal: Principal, accept_language: str | None) -> dict[str, Any]:
    data = await today_service.today(session, principal, accept_language)
    lang: Lang = "fr" if data.get("lang") == "fr" else "en"
    recommended = data.get("recommended") or []
    artifact_ids = [uuid.UUID(i["artifact_id"]) for i in recommended if i.get("artifact_id")]
    levels: dict[str, int] = {}
    if artifact_ids:
        rows = await session.execute(select(Artifact.id, Artifact.classification).where(Artifact.id.in_(artifact_ids)))
        levels = {str(aid): int(level) for aid, level in rows.all()}
    items = [BriefItem(i.get("title") or "", levels.get(str(i.get("artifact_id")), 1)) for i in recommended]
    brief = data["brief"]
    sentences, withheld = script(
        data["user"]["first_name"],
        lang,
        actions_required=int(brief["actions_required"]),
        running=int(brief["running"]),
        results_ready=int(brief["results_ready"]),
        items=items,
    )
    return {"lang": lang, "sentences": sentences, "text": " ".join(sentences), "withheld": withheld}

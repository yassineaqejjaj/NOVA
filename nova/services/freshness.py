"""Living Artifacts: check an Artifact's cited sources against ORBIT's changes, and propose an update.

ORBIT is asked as the user, so it only ever reports changes the user may see. The update itself reuses the
section-level regeneration (a *proposed* version waiting for approval): nothing is rewritten silently.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.domain.artifacts import ArtifactContent
from nova.domain.context import ContextChange, ContextError, ContextItem
from nova.domain.freshness import CitedSource, SourceChange, assess
from nova.domain.permissions import Principal
from nova.infra.db import aware
from nova.infra.models import ArtifactVersion, ContextRetrievalReference
from nova.services import providers
from nova.services.access import require_artifact

PAGE = 20  # the ORBIT adapter reads one page of changes; a full page may hide older ones


def _section_citations(content: ArtifactContent) -> dict[tuple[str, str], set[str]]:
    """``{(ref, label): {section keys}}`` for every citation in the Artifact."""
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, section in content.sections.items():
        for block in section.blocks:
            for c in block.citations:
                if c.ref:
                    found[(c.ref, c.label)].add(key)
        for item in section.items:
            for c in item.citations:
                if c.ref:
                    found[(c.ref, c.label)].add(key)
    return found


async def cited_sources(session: AsyncSession, principal: Principal, content: ArtifactContent) -> list[CitedSource]:
    cites = _section_citations(content)
    if not cites:
        return []
    refs = (
        await session.scalars(
            select(ContextRetrievalReference).where(
                ContextRetrievalReference.id.in_([uuid.UUID(ref) for ref, _ in cites]),
                ContextRetrievalReference.user_id == uuid.UUID(principal.user_id) if not principal.is_admin else True,
            )
        )
    ).all()
    sources: dict[tuple[str, str], CitedSource] = {}
    for ref in refs:
        for raw in ref.items:
            item = ContextItem.model_validate(raw)
            sections = cites.get((str(ref.id), item.citation))
            slug = item.project_slug or ref.project_slug
            if not sections or not slug:
                continue
            ids = frozenset(i for i in (item.document_id, item.memory_item_id, item.ref_id) if i)
            key = (slug, min(ids) if ids else item.title)
            known = sources.get(key)
            sources[key] = CitedSource(
                ids=(known.ids | ids) if known else ids,
                title=item.title,
                project_slug=slug,
                sections=(known.sections | sections) if known else frozenset(sections),
            )
    return list(sources.values())


def _change(c: ContextChange) -> SourceChange:
    return SourceChange(c.id, c.project_slug, c.type, c.type_label, c.title, c.target_id, aware(c.created_at))


async def _changes(user_id: str, slugs: set[str], since: datetime) -> tuple[list[SourceChange], bool]:
    """Changes ORBIT reports for the projects since ``since``; ``False`` when it could not be asked."""
    found: list[SourceChange] = []
    for slug in sorted(slugs):
        try:
            found += [_change(c) for c in await providers.context().recent_changes(user_id, slug, since)]
        except ContextError:
            return [], False
    return found, True


async def check(session: AsyncSession, principal: Principal, artifact_id: str) -> dict[str, Any]:
    artifact, _ = await require_artifact(session, artifact_id, principal)
    version = await session.scalar(
        select(ArtifactVersion).where(
            ArtifactVersion.artifact_id == artifact.id, ArtifactVersion.version == artifact.current_version
        )
    )
    if version is None:
        return {"status": "unverified", "reason": "no_citations", "impacts": [], "stale_sections": [], "as_of": None}
    as_of = aware(version.created_at)
    sources = await cited_sources(session, principal, ArtifactContent.model_validate(version.content))
    changes, checked = await _changes(principal.user_id, {s.project_slug for s in sources}, as_of) if sources else ([], True)
    return {
        **assess(sources, changes, as_of, checked=checked),
        "as_of": as_of.isoformat(),
        "sources": len(sources),
        "may_be_incomplete": len(changes) >= PAGE,
    }

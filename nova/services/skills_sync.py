"""Sync the Skill registry (files) into ``skills`` / ``skill_versions`` (immutable, content-hashed)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import get_settings
from nova.infra.models import Skill, SkillVersion
from nova.skills.registry import SkillRegistry

log = logging.getLogger(__name__)


class SkillVersionError(Exception):
    pass


async def sync_skills(session: AsyncSession, registry: SkillRegistry) -> dict[str, int]:
    created = updated = 0
    problems = []
    for spec in registry.all():
        version = await session.scalar(
            select(SkillVersion).where(SkillVersion.skill_id == spec.id, SkillVersion.version == spec.version)
        )
        skill = await session.get(Skill, spec.id)
        if skill is None:
            skill = Skill(
                id=spec.id,
                name=spec.name,
                category=spec.category.value,
                summary=spec.summary,
                current_version=spec.version,
                system=spec.system,
            )
            session.add(skill)
            await session.flush()
        else:
            skill.name, skill.category, skill.summary, skill.current_version = (
                spec.name,
                spec.category.value,
                spec.summary,
                spec.version,
            )
        if version is None:
            session.add(
                SkillVersion(
                    skill_id=spec.id,
                    version=spec.version,
                    content_hash=spec.content_hash,
                    spec=spec.model_dump(mode="json", exclude={"output_schema"}),
                )
            )
            created += 1
        elif version.content_hash != spec.content_hash:
            problems.append(f"{spec.id}@{spec.version} changed without a version bump")
            version.content_hash, version.spec = spec.content_hash, spec.model_dump(mode="json", exclude={"output_schema"})
            updated += 1
    if problems:
        message = "; ".join(problems)
        if get_settings().is_production:
            raise SkillVersionError(message + " — bump the Skill version (versions are immutable)")
        log.warning("Skill versions must be bumped when content changes: %s", message)
    await session.flush()
    return {"created": created, "updated": updated}

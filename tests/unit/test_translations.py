"""Every displayed piece of the catalog exists in French (UI labels; prompts keep the English definitions)."""

from __future__ import annotations

from nova.artifacts.registry import get_artifact_registry
from nova.domain.skills import SkillTranslation
from nova.skills.registry import get_skill_registry


def test_every_skill_is_fully_translated_in_french():
    gaps = {}
    for skill in get_skill_registry().all():
        fr = skill.translations.get("fr")
        if fr is None:
            gaps[skill.id] = ["all"]
            continue
        if missing := SkillTranslation.model_validate(fr).missing(skill):
            gaps[skill.id] = missing
    assert not gaps, gaps


def test_every_artifact_type_is_fully_translated_in_french():
    gaps = {}
    for artifact_type in get_artifact_registry().types.values():
        fr = artifact_type.translations.get("fr") or {}
        missing = [f for f in ("name", "description") if not fr.get(f)]
        sections = fr.get("sections") or {}
        for section in artifact_type.sections:
            tr = sections.get(section.key) or {}
            if not tr.get("title"):
                missing.append(f"{section.key}.title")
            if section.description and not tr.get("description"):
                missing.append(f"{section.key}.description")
        if missing:
            gaps[artifact_type.type] = missing
    assert not gaps, gaps

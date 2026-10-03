"""Skill library: parsing, validation, schemas, routing."""

from __future__ import annotations

import pytest
import yaml

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.skills import SkillSpec
from nova.skills import build
from nova.skills.registry import SkillRegistry, SkillValidationError, get_skill_registry, load_skill
from nova.skills.router import SkillRouter

PARTIAL_CREATE = {"functional-requirements", "definition-of-ready"}  # documented partial fills


def test_library_loads_and_schemas_are_up_to_date():
    registry = get_skill_registry()
    assert len(registry.all()) == 48
    assert build.main(check=True) == 0


def test_every_create_skill_fills_its_artifact_type():
    artifacts = get_artifact_registry()
    for skill in get_skill_registry().all(include_system=False):
        if skill.outputs.mode != "create" or skill.id in PARTIAL_CREATE:
            continue
        expected = set(artifacts.get(skill.outputs.artifact_type).section_keys)
        assert set(skill.filled_sections) == expected, skill.id


def test_every_step_fills_each_section_once():
    for skill in get_skill_registry().all():
        keys = [k for step in skill.steps for k in step.fills]
        assert len(keys) == len(set(keys)), skill.id


def test_invalid_skill_is_rejected(tmp_path):
    src = get_settings().skills_dir / "prd"
    target = tmp_path / "prd"
    target.mkdir()
    for f in src.iterdir():
        (target / f.name).write_text(f.read_text())
    spec = yaml.safe_load((target / "skill.yaml").read_text())
    spec["steps"][0]["fills"] = ["not_a_section"]
    (target / "skill.yaml").write_text(yaml.safe_dump(spec))
    with pytest.raises(SkillValidationError, match="unknown sections"):
        load_skill(target, get_artifact_registry())


def test_unregistered_tool_is_rejected(tmp_path):
    src = get_settings().skills_dir / "prd"
    target = tmp_path / "prd"
    target.mkdir()
    for f in src.iterdir():
        (target / f.name).write_text(f.read_text())
    with pytest.raises(SkillValidationError, match="unregistered tools"):
        load_skill(target, get_artifact_registry(), known_tools={"get_artifact"})


def test_semver_is_required():
    raw = yaml.safe_load((get_settings().skills_dir / "prd" / "skill.yaml").read_text())
    raw["version"] = "1.0"
    with pytest.raises(ValueError):
        SkillSpec.model_validate(raw)


def test_catalog_digest_is_stable():
    registry = get_skill_registry()
    other = SkillRegistry(get_settings().skills_dir, get_artifact_registry())
    assert registry.catalog_digest() == other.catalog_digest()


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("Create a PRD for this idea", "prd"),
        ("Help me turn the FORGE vision into a backlog.", "vision-to-backlog"),
        ("Prepare Sprint 19.", "sprint-planning"),
        ("Help me prioritize these initiatives with RICE", "rice-prioritization"),
        ("Create the user stories for this epic", "user-story-generation"),
        ("Write the release notes for 2.3", "release-notes"),
    ],
)
def test_router_ranks_the_expected_skill_first(intent, expected):
    candidates = SkillRouter(get_skill_registry()).candidates(intent)
    assert candidates and candidates[0].skill.id == expected


def test_router_explicit_reference_wins_and_follow_ups_are_offered():
    router = SkillRouter(get_skill_registry())
    candidates = router.candidates("something unrelated", explicit=["kano-analysis"])
    assert candidates[0].skill.id == "kano-analysis"
    ids = [c.skill.id for c in router.candidates("Create a PRD for this idea")]
    assert set(get_skill_registry().get("prd").composes_with) <= set(ids)


def test_system_skills_are_never_routed():
    ids = [c.skill.id for c in SkillRouter(get_skill_registry()).candidates("edit artifact section update")]
    assert "artifact-edit" not in ids

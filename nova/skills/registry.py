"""Skill registry: loads ``/skills/<id>/`` directories, validates them and computes content hashes.

Skills are data (versioned product workflows), not code: LangGraph orchestrates them, the registry
guarantees they are consistent with the Artifact types and the Tool Registry.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from nova.artifacts.registry import ArtifactRegistry, get_artifact_registry
from nova.config import get_settings
from nova.domain.skills import SkillEvaluation, SkillSpec

SKILL_FILES = ("skill.yaml", "instructions.md", "input.schema.json", "output.schema.json", "evaluation.yaml")


class SkillValidationError(ValueError):
    pass


def compute_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for name in SKILL_FILES:
        path = directory / name
        digest.update(name.encode())
        digest.update(path.read_bytes() if path.exists() else b"")
    return digest.hexdigest()


def expected_output_schema(spec: SkillSpec, artifacts: ArtifactRegistry) -> dict:
    artifact_type = artifacts.get(spec.outputs.artifact_type)
    return artifacts.output_schema(artifact_type, spec.filled_sections)


def load_skill(directory: Path, artifacts: ArtifactRegistry, known_tools: set[str] | None = None) -> SkillSpec:
    missing = [name for name in SKILL_FILES if not (directory / name).exists()]
    if missing:
        raise SkillValidationError(f"{directory.name}: missing {', '.join(missing)}")
    try:
        raw = yaml.safe_load((directory / "skill.yaml").read_text())
        spec = SkillSpec.model_validate(raw)
    except Exception as exc:
        raise SkillValidationError(f"{directory.name}/skill.yaml: {exc}") from exc
    if spec.id != directory.name:
        raise SkillValidationError(f"{directory.name}: id '{spec.id}' must match the directory name")
    if spec.outputs.artifact_type not in artifacts.types:
        raise SkillValidationError(f"{spec.id}: unknown artifact type '{spec.outputs.artifact_type}'")
    artifact_type = artifacts.get(spec.outputs.artifact_type)
    for step in spec.steps:
        unknown = [k for k in step.fills if artifact_type.section(k) is None]
        if unknown:
            raise SkillValidationError(f"{spec.id}.{step.id}: unknown sections {unknown}")
    if known_tools is not None:
        unknown_tools = sorted(set(spec.tools) - known_tools)
        if unknown_tools:
            raise SkillValidationError(f"{spec.id}: unregistered tools {unknown_tools}")

    input_schema = json.loads((directory / "input.schema.json").read_text())
    output_schema = json.loads((directory / "output.schema.json").read_text())
    for schema in (input_schema, output_schema):
        Draft202012Validator.check_schema(schema)
    declared = {i.name for i in spec.inputs}
    if set(input_schema.get("properties", {})) != declared:
        raise SkillValidationError(f"{spec.id}: input.schema.json properties must match skill.yaml inputs")
    if output_schema != expected_output_schema(spec, artifacts):
        raise SkillValidationError(f"{spec.id}: output.schema.json is out of date (run `uv run python -m nova.skills.build`)")
    evaluation = SkillEvaluation.model_validate(yaml.safe_load((directory / "evaluation.yaml").read_text()) or {})
    return spec.model_copy(
        update={
            "instructions": (directory / "instructions.md").read_text().strip(),
            "input_schema": input_schema,
            "output_schema": output_schema,
            "evaluation": evaluation,
            "content_hash": compute_hash(directory),
        }
    )


class SkillRegistry:
    def __init__(self, skills_dir: Path, artifacts: ArtifactRegistry, known_tools: set[str] | None = None) -> None:
        self.artifacts = artifacts
        self._skills: dict[str, SkillSpec] = {}
        errors: list[str] = []
        for directory in sorted(
            p for p in skills_dir.iterdir() if p.is_dir() and p.name != "i18n" and not p.name.startswith(("_", "."))
        ):
            try:
                spec = load_skill(directory, artifacts, known_tools)
            except SkillValidationError as exc:
                errors.append(str(exc))
                continue
            self._skills[spec.id] = spec
        for path in sorted((skills_dir / "i18n").glob("*.yaml")) if (skills_dir / "i18n").is_dir() else []:
            lang = path.stem
            for skill_id, translation in (yaml.safe_load(path.read_text()) or {}).items():
                if skill_id not in self._skills:
                    errors.append(f"i18n/{path.name}: unknown skill '{skill_id}'")
                    continue
                spec = self._skills[skill_id]
                self._skills[skill_id] = spec.model_copy(update={"translations": {**spec.translations, lang: translation}})
        for spec in self._skills.values():
            unknown = [s for s in spec.composes_with if s not in self._skills]
            if unknown:
                errors.append(f"{spec.id}: composes_with unknown skills {unknown}")
        if errors:
            raise SkillValidationError("Invalid skills:\n  " + "\n  ".join(errors))

    def get(self, skill_id: str) -> SkillSpec:
        try:
            return self._skills[skill_id]
        except KeyError as exc:
            raise KeyError(f"Unknown skill '{skill_id}'") from exc

    def has(self, skill_id: str) -> bool:
        return skill_id in self._skills

    def all(self, *, include_system: bool = True) -> list[SkillSpec]:
        return [s for s in self._skills.values() if include_system or not s.system]

    def catalog_digest(self) -> str:
        """Stable hash of the whole catalog (part of the agent version registered in FORGE)."""
        joined = "|".join(f"{s.id}@{s.version}:{s.content_hash}" for s in sorted(self._skills.values(), key=lambda s: s.id))
        return hashlib.sha256(joined.encode()).hexdigest()[:16]


@lru_cache
def get_skill_registry() -> SkillRegistry:
    from nova.agent.tools.registry import get_tool_registry

    return SkillRegistry(get_settings().skills_dir, get_artifact_registry(), set(get_tool_registry().names()))

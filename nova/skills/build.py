"""Regenerate ``input.schema.json`` / ``output.schema.json`` of every Skill from its ``skill.yaml``.

uv run python -m nova.skills.build           # write
uv run python -m nova.skills.build --check   # fail if a file is out of date (CI)

Also maintains ``skills/versions.lock.json`` (``id@version`` → content hash, never pruned): Skill versions are immutable
— deployed databases refuse a known version whose content changed — so a content change without a version bump fails
here, before it reaches production.
"""

from __future__ import annotations

import json
import sys

import yaml

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.skills import SkillSpec
from nova.skills.registry import compute_hash, expected_output_schema

LOCK = "versions.lock.json"


def input_schema(spec: SkillSpec) -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": f"{spec.name} — inputs",
        "type": "object",
        "properties": {i.name: {"type": "string", "description": i.description} for i in spec.inputs},
        "required": [i.name for i in spec.inputs if i.required],
        "additionalProperties": False,
    }


def main(check: bool = False) -> int:
    artifacts = get_artifact_registry()
    skills_dir = get_settings().skills_dir
    lock_path = skills_dir / LOCK
    lock: dict[str, str] = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    locked = dict(lock)
    stale: list[str] = []
    unbumped: list[str] = []
    directories = sorted(p for p in skills_dir.iterdir() if p.is_dir() and p.name != "i18n" and not p.name.startswith(("_", ".")))
    for directory in directories:
        spec = SkillSpec.model_validate(yaml.safe_load((directory / "skill.yaml").read_text()))
        for name, schema in (
            ("input.schema.json", input_schema(spec)),
            ("output.schema.json", expected_output_schema(spec, artifacts)),
        ):
            path = directory / name
            text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
            if not path.exists() or path.read_text() != text:
                stale.append(f"{directory.name}/{name}")
                if not check:
                    path.write_text(text)
    for directory in directories:  # hashes cover the generated schemas: computed once they are up to date
        spec = SkillSpec.model_validate(yaml.safe_load((directory / "skill.yaml").read_text()))
        key, digest = f"{spec.id}@{spec.version}", compute_hash(directory)
        if key in locked and locked[key] != digest:
            unbumped.append(key)
        elif key not in locked:
            lock[key] = digest
            stale.append(f"{LOCK} ({key})")
    if unbumped:
        print("Changed without a version bump (versions are immutable): " + ", ".join(unbumped))
        return 1
    if lock != locked and not check:
        lock_path.write_text(json.dumps(dict(sorted(lock.items())), indent=2) + "\n")
    if stale:
        print(("Out of date: " if check else "Updated: ") + ", ".join(stale))
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))

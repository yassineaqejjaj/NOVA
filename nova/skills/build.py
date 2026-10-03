"""Regenerate ``input.schema.json`` / ``output.schema.json`` of every Skill from its ``skill.yaml``.

uv run python -m nova.skills.build           # write
uv run python -m nova.skills.build --check   # fail if a file is out of date (CI)
"""

from __future__ import annotations

import json
import sys

import yaml

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.skills import SkillSpec
from nova.skills.registry import expected_output_schema


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
    stale: list[str] = []
    for directory in sorted(p for p in get_settings().skills_dir.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
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
    if stale:
        print(("Out of date: " if check else "Updated: ") + ", ".join(stale))
    return 1 if (check and stale) else 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv))

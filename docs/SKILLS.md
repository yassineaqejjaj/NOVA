# Skills

A Skill is a **versioned product workflow**, not a prompt. LangGraph orchestrates Skills; Skills define product
methods; FORGE evaluates executions.

## Anatomy (`skills/<id>/`)

| File | Purpose |
|---|---|
| `skill.yaml` | Identity, purpose, version, category, triggers, inputs, expected ORBIT context, methodology, **steps** (each fills Artifact sections), tools, outputs, `composes_with` |
| `instructions.md` | Method guidance (trust level: Skill instructions — above user and context) |
| `input.schema.json` | Generated from `inputs` |
| `output.schema.json` | Generated from the Artifact type sections the steps fill |
| `evaluation.yaml` | Criteria + deterministic checks using FORGE rule types (`sections_present`, `citation_required`, `no_pii`, `min_length`/`max_length`) |

Each **step** is one model call constrained by a JSON Schema built from the sections it `fills`, so progress
is real ("Writing user stories"), outputs stay small enough for open-weight models, and every sub-step is a
LangGraph checkpoint (a failure resumes at the failed sub-step).

## Rules enforced by the registry (`nova/skills/registry.py`)

* `id` = directory name; semantic `version`; content hash over all five files.
* Output Artifact type exists; every `fills` key is a section of that type.
* Tools must be registered in the Tool Registry; the Skill can only call tools it declares.
* `input.schema.json` matches `inputs`; `output.schema.json` is up to date (`uv run python -m nova.skills.build`).
* `composes_with` references existing Skills.
* Changing a Skill's content without bumping `version` is refused in production (versions are immutable and
  recorded in `skill_versions`; every execution stores the Skill id + version; FORGE agent versions carry the
  catalog digest).

## Routing and composition

1. The **router** scores Skills deterministically (triggers, names, summaries, category, requested Artifact type,
   preferred methods, explicit `/skill` references) and returns candidates plus their natural follow-ups.
2. The **planner** (model) builds a short workflow **from candidates only**; unknown ids are dropped. The Skill
   producing an explicitly requested deliverable is always included.
3. In *Assist* mode, multi-Skill workflows are shown for confirmation and can be edited (reorder, remove, add).

## Adding a Skill

```bash
mkdir skills/my-skill && $EDITOR skills/my-skill/skill.yaml skills/my-skill/instructions.md skills/my-skill/evaluation.yaml
uv run python -m nova.skills.build      # generates the JSON Schemas
uv run pytest tests/unit/test_skills.py # validates the whole library
```

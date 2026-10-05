"""Skill specification — a Skill is a versioned product workflow, not a prompt (ARCHITECTURE §6)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from nova.domain.enums import SkillCategory

SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class SkillInput(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    description: str
    required: bool = False
    ask: bool = False  # NOVA may ask the user for it when missing (only required + ask inputs are asked)
    question: str | None = None  # wording used when asking


class ExpectedContext(BaseModel):
    orbit_intent: Literal["general", "specification", "design", "engineering", "research", "analysis", "validation"] = "general"
    query_hint: str = ""  # appended to the user's intent when querying ORBIT
    source_kinds: list[str] | None = None
    token_budget: int = Field(default=4000, ge=500, le=32000)
    required: bool = False  # the Skill cannot produce sound output without project context


class Methodology(BaseModel):
    name: str
    principles: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)


class SkillStep(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str  # operational label shown to the user ("Creating epics")
    instruction: str
    fills: list[str] = Field(min_length=1)  # artifact section keys produced by this step


class SkillOutputs(BaseModel):
    artifact_type: str
    mode: Literal["create", "update"] = "create"


class EvaluationCheck(BaseModel):
    """Deterministic check, expressed with FORGE rule types so it can be exported as-is."""

    type: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class SkillEvaluation(BaseModel):
    criteria: list[dict[str, Any]] = Field(default_factory=list)  # {key, question, weight}
    checks: list[EvaluationCheck] = Field(default_factory=list)


class SkillSpec(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    name: str
    version: str
    category: SkillCategory
    summary: str
    purpose: str
    triggers: list[str] = Field(default_factory=list)
    inputs: list[SkillInput] = Field(default_factory=list)
    expected_context: ExpectedContext = Field(default_factory=ExpectedContext)
    methodology: Methodology
    steps: list[SkillStep] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    outputs: SkillOutputs
    composes_with: list[str] = Field(default_factory=list)
    system: bool = False  # internal Skill (not proposed by routing, e.g. artifact-edit)
    # Display translations from skills/i18n/<lang>.yaml: {"fr": {"name": …, "summary": …}}
    translations: dict[str, dict[str, str]] = Field(default_factory=dict)

    # Loaded from sibling files (not in skill.yaml)
    instructions: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    evaluation: SkillEvaluation = Field(default_factory=SkillEvaluation)
    content_hash: str = ""

    @field_validator("version")
    @classmethod
    def _semver(cls, value: str) -> str:
        if not SEMVER.match(value):
            raise ValueError("version must be semantic (MAJOR.MINOR.PATCH)")
        return value

    @model_validator(mode="after")
    def _unique_steps(self) -> SkillSpec:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        return self

    @property
    def required_inputs(self) -> list[SkillInput]:
        return [i for i in self.inputs if i.required]

    @property
    def filled_sections(self) -> list[str]:
        return list(dict.fromkeys(key for step in self.steps for key in step.fills))

    def catalog_line(self) -> str:
        return f"- {self.id} ({self.category}): {self.summary} → {self.outputs.artifact_type}"


class SelectedSkill(BaseModel):
    skill_id: str
    version: str
    step_id: str  # plan step that runs it
    reason: str = ""

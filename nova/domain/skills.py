"""Skill specification — a Skill is a versioned product workflow, not a prompt (ARCHITECTURE §6)."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nova.domain.agents import AgentProfile
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


class InputTranslation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str | None = None
    question: str | None = None


class SkillTranslation(BaseModel):
    """Display translation of a Skill (skills/i18n/<lang>.yaml). Keys must match the Skill exactly."""

    model_config = ConfigDict(extra="forbid")
    name: str
    summary: str
    purpose: str | None = None
    method: str | None = None  # methodology name
    principles: list[str] | None = None  # same order and length as methodology.principles
    steps: dict[str, str] = Field(default_factory=dict)  # step id → title
    criteria: dict[str, str] = Field(default_factory=dict)  # criterion key → question
    checks: list[str] | None = None  # same order and length as evaluation.checks (descriptions)
    inputs: dict[str, InputTranslation] = Field(default_factory=dict)

    def problems(self, spec: SkillSpec) -> list[str]:
        found = []
        if unknown := set(self.steps) - {s.id for s in spec.steps}:
            found.append(f"unknown steps {sorted(unknown)}")
        if unknown := set(self.criteria) - {str(c.get("key")) for c in spec.evaluation.criteria}:
            found.append(f"unknown criteria {sorted(unknown)}")
        if unknown := set(self.inputs) - {i.name for i in spec.inputs}:
            found.append(f"unknown inputs {sorted(unknown)}")
        if self.principles is not None and len(self.principles) != len(spec.methodology.principles):
            found.append("principles must match methodology.principles one to one")
        if self.checks is not None and len(self.checks) != len(spec.evaluation.checks):
            found.append("checks must match evaluation.checks one to one")
        return found

    def missing(self, spec: SkillSpec) -> list[str]:
        """What a complete translation still lacks (shown by the completeness test)."""
        gaps = [f for f in ("purpose", "method", "principles") if getattr(self, f) is None]
        gaps += [f"steps.{s.id}" for s in spec.steps if s.id not in self.steps]
        gaps += [f"criteria.{c.get('key')}" for c in spec.evaluation.criteria if c.get("key") not in self.criteria]
        gaps += [f"inputs.{i.name}" for i in spec.inputs if i.name not in self.inputs]
        if spec.evaluation.checks and self.checks is None:
            gaps.append("checks")
        return gaps


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
    agent: AgentProfile = AgentProfile.product  # the specialist agent that carries out this Skill
    # Display translations from skills/i18n/<lang>.yaml (see SkillTranslation); prompts keep the English definition.
    translations: dict[str, dict[str, Any]] = Field(default_factory=dict)

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

"""NOVA's Validation agent: verifies each deliverable before it is saved.

Deterministic checks come from the Skill's ``evaluation.yaml`` (the FORGE rule types, run locally) plus generic
structure checks; the review grades the Skill's criteria with the model. When something fails, NOVA (the
orchestrator) sends the step back to its specialist agent for a revision, then checks again.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nova.artifacts.render import render_section
from nova.domain.artifacts import ArtifactType, SectionContent
from nova.domain.skills import SkillSpec
from nova.infra.redaction import redact


class CheckResult(BaseModel):
    key: str  # check type (sections_present, citation_required, max_length, no_pii, filled)
    index: int | None = None  # position in evaluation.checks (translations), None for generic checks
    label: str  # English description; the UI translates by index
    passed: bool
    detail: str = ""
    sections: list[str] = Field(default_factory=list)  # sections to fix when it fails


class CriterionVerdict(BaseModel):
    key: str = Field(description="Criterion key, exactly as listed")
    passed: bool
    comment: str = Field(default="", description="One short sentence, in the user's language")


class ReviewIssue(BaseModel):
    section: str = Field(description="Section key, exactly as listed")
    problem: str = Field(description="What is wrong, one sentence in the user's language")
    fix: str = Field(description="What the specialist must change, one sentence in the user's language")


class ValidationReview(BaseModel):
    """What the Validation agent returns."""

    verdict: Literal["pass", "revise"] = Field(description="revise only for a problem that matters to the user")
    criteria: list[CriterionVerdict] = Field(default_factory=list, max_length=8)
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=4)
    summary: str = Field(default="", description="One sentence for the user, in the user's language")


class StepValidation(BaseModel):
    status: Literal["passed", "revised", "warning"]
    checks: list[CheckResult] = Field(default_factory=list)
    criteria: list[CriterionVerdict] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: str = ""
    reviewed: bool = False
    revisions: int = 0

    @property
    def passed_checks(self) -> int:
        return sum(1 for c in self.checks if c.passed)


def _text(sections: dict[str, SectionContent]) -> str:
    return "\n".join(line for s in sections.values() for line in render_section(s))


def _citations(sections: dict[str, SectionContent]) -> int:
    return sum(len(b.citations) for s in sections.values() for b in s.blocks) + sum(
        len(i.citations) for s in sections.values() for i in s.items
    )


def run_checks(
    skill: SkillSpec,
    artifact_type: ArtifactType,
    produced: dict[str, SectionContent],
    *,
    fills: list[str],
    existing: dict[str, SectionContent] | None = None,
    context_count: int = 0,
) -> list[CheckResult]:
    merged = {**(existing or {}), **produced}
    by_title = {s.title.lower(): s.key for s in artifact_type.sections}
    results = []
    empty = [k for k in fills if k not in merged or merged[k].is_empty()]
    results.append(
        CheckResult(
            key="filled",
            label="Every section of the step is filled",
            passed=not empty,
            detail=", ".join(empty),
            sections=empty,
        )
    )
    for index, check in enumerate(skill.evaluation.checks):
        label = check.description or check.type
        if check.type == "sections_present":
            keys = [by_title.get(str(t).lower(), str(t)) for t in check.params.get("sections", [])]
            missing = [k for k in keys if k not in merged or merged[k].is_empty()]
            results.append(
                CheckResult(
                    key=check.type, index=index, label=label, passed=not missing, detail=", ".join(missing), sections=missing
                )
            )
        elif check.type == "citation_required":
            minimum = int(check.params.get("min", 1))
            found = _citations(produced)
            passed = context_count == 0 or found >= minimum
            detail = "no context provided" if context_count == 0 else f"{found} citation(s)"
            results.append(
                CheckResult(
                    key=check.type, index=index, label=label, passed=passed, detail=detail, sections=[] if passed else fills
                )
            )
        elif check.type == "max_length":
            words = len(_text(merged).split())
            limit = int(check.params.get("words", 10_000))
            results.append(
                CheckResult(
                    key=check.type,
                    index=index,
                    label=label,
                    passed=words <= limit,
                    detail=f"{words}/{limit} words",
                    sections=[] if words <= limit else fills,
                )
            )
        elif check.type == "no_pii":
            leaking = [k for k, s in produced.items() if (text := _text({k: s})) and redact(text) != text]
            results.append(
                CheckResult(
                    key=check.type, index=index, label=label, passed=not leaking, detail=", ".join(leaking), sections=leaking
                )
            )
    return results


def sections_to_revise(checks: list[CheckResult], review: ValidationReview | None, fills: list[str]) -> list[str]:
    keys = [k for c in checks if not c.passed for k in c.sections]
    if review and review.verdict == "revise":
        keys += [i.section for i in review.issues] or fills
    return [k for k in dict.fromkeys(keys) if k in fills]


def revision_feedback(checks: list[CheckResult], review: ValidationReview | None) -> str:
    lines = [f"- Check failed: {c.label} ({c.detail})" for c in checks if not c.passed]
    if review and review.verdict == "revise":
        lines += [f"- {i.section}: {i.problem} → {i.fix}" for i in review.issues]
    return "REVISION REQUESTED BY NOVA'S VALIDATION AGENT. Fix exactly these points, keep everything else:\n" + "\n".join(lines)

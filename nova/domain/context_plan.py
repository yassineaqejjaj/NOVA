"""Adaptive context: what ORBIT is asked for, derived from the Skills the request is likely to use.

Every Skill declares an ``expected_context`` (purpose, query hint, source kinds, token budget). The context
is retrieved once per run, before planning, so the plan is the union of the candidate Skills' needs:

* budget  - the largest budget a candidate asks for (never below the global default: it is a floor, so
            adapting can only give an agent more room, not silently starve one that works today);
* purpose - the candidates' own purpose when they all agree, otherwise the intent category's purpose;
* hints   - the candidates' query hints, appended to the user's intent (deduplicated, bounded);
* kinds   - restricted to a union of source kinds only when every candidate names some.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nova.domain.skills import ExpectedContext

MAX_HINT_CHARS = 400
MAX_TOKEN_BUDGET = 32000


@dataclass(frozen=True)
class ContextPlan:
    token_budget: int
    purpose: str
    query_hints: list[str] = field(default_factory=list)
    source_kinds: list[str] | None = None
    required: bool = False  # at least one candidate cannot work without project context

    def augment(self, query: str, limit: int = 7000) -> str:
        """The user's query followed by the Skills' hints (kept within ``limit`` characters)."""
        hint = " ".join(self.query_hints)[:MAX_HINT_CHARS].strip()
        return f"{query}\n\nRelevant context: {hint}"[:limit] if hint else query[:limit]


def plan_context(candidates: list[ExpectedContext], *, default_budget: int, default_purpose: str) -> ContextPlan:
    """Merge the candidate Skills' expectations (no candidates: the defaults, i.e. today's behaviour)."""
    if not candidates:
        return ContextPlan(token_budget=default_budget, purpose=default_purpose)
    purposes = {c.orbit_intent for c in candidates}
    purpose = purposes.pop() if len(purposes) == 1 and "general" not in purposes else default_purpose
    hints = list(dict.fromkeys(c.query_hint.strip() for c in candidates if c.query_hint.strip()))
    kinds: list[str] | None = None
    if all(c.source_kinds for c in candidates):
        kinds = list(dict.fromkeys(k for c in candidates for k in (c.source_kinds or [])))
    budget = min(MAX_TOKEN_BUDGET, max(default_budget, *(c.token_budget for c in candidates)))
    return ContextPlan(
        token_budget=budget,
        purpose=purpose,
        query_hints=hints,
        source_kinds=kinds,
        required=any(c.required for c in candidates),
    )

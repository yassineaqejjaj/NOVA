"""OpenAI-compatible fake inference server for E2E tests (test double — never used in production).

Deterministic: answers each structured-output request from its JSON Schema, with light intent rules so
the E2E scenarios exercise real routing (PRD, vision → backlog, sprint planning, edits, provenance).

    uv run uvicorn tests.support.fake_llm_server:app --port 8391
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from fastapi import FastAPI, Request

from tests.support.schema_faker import fake

app = FastAPI()

SECTION_WORDS = {"metric": "metrics", "risk": "risks", "summary": "summary", "requirement": "functional_requirements"}


def _between(text: str, start: str, end: str | None = None) -> str:
    if start not in text:
        return ""
    tail = text.split(start, 1)[1]
    return tail.split(end, 1)[0] if end and end in tail else tail


def intent(user: str) -> dict[str, Any]:
    request = _between(user, "USER REQUEST:\n", "\n").strip().lower()
    viewing = re.search(r"currently viewing artifact id=([0-9a-f-]+)", user)
    artifacts = re.findall(r"- id=([0-9a-f-]+) type=(\w+).*?(?: items=(.*))?$", user, re.MULTILINE)
    catalog = re.findall(r"^- ([a-z0-9-]+) \(", _between(user, "SKILL CATALOG:\n"), re.MULTILINE)
    if request.startswith("why") and viewing:
        target = viewing.group(1)
        items = next((i for a, _, i in artifacts if a == target), "") or ""
        first_item = items.split(";")[0].split(":")[0].strip() if items else None
        return {
            "kind": "explain_provenance",
            "goal": "Explain provenance",
            "target_artifact_id": target,
            "target_item_id": first_item,
        }
    if viewing and any(w in request for w in ("rewrite", "change", "update", "improve")):
        sections = [key for word, key in SECTION_WORDS.items() if word in request] or ["summary"]
        return {"kind": "edit_artifact", "goal": request, "target_artifact_id": viewing.group(1), "target_sections": sections}
    if request.endswith("?") and not any(w in request for w in ("create", "prepare", "turn", "write")):
        return {"kind": "question", "goal": request, "context_query": request}
    hints = [s for s in catalog if any(part in request for part in s.split("-") if len(part) > 3)]
    return {"kind": "run_workflow", "goal": request, "context_query": request, "candidate_skill_ids": hints[:4]}


def plan(user: str) -> dict[str, Any]:
    candidates = re.findall(r"^- ([a-z0-9-]+): ", _between(user, "CANDIDATE SKILLS:\n"), re.MULTILINE)
    first = candidates[0] if candidates else "prd"
    return {
        "objective": _between(user, "GOAL: ", "\n").strip() or "Work",
        "steps": [{"id": "step-1", "title": first.replace("-", " ").title(), "skill_id": first}],
    }


def answer(user: str) -> dict[str, Any]:
    labels = re.findall(r'label="(S\d+)"', user)
    if labels:
        return {
            "answer": f"Based on the recorded context [{labels[0]}], this was decided to serve the objective.",
            "citations": labels[:1],
        }
    return {"answer": "No recorded source supports this element; it was proposed from your request.", "citations": []}


def _revise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (f"{v} (revised)" if k in ("title", "text") and isinstance(v, str) else _revise(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_revise(v) for v in value]
    return value


@app.post("/v1/chat/completions")
async def completions(request: Request) -> dict[str, Any]:
    body = await request.json()
    messages = body.get("messages", [])
    user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    response_format = body.get("response_format") or {}
    spec = response_format.get("json_schema") or {}
    name, schema = spec.get("name"), spec.get("schema") or {}
    if name == "IntentClassification":
        value: Any = intent(user)
    elif name == "PlanOutput":
        value = plan(user)
    elif name == "AnswerOutput":
        value = answer(user)
    elif schema:
        labels = re.findall(r'label="(S\d+)"', user)
        value = fake(schema, citations=labels[:1])
        if "EDIT INSTRUCTION:" in user:  # an edit returns revised content, like a real model would
            value = _revise(value)
    else:
        value = "OK"
    content = value if isinstance(value, str) else json.dumps(value)
    return {
        "id": f"fake-{time.time_ns()}",
        "object": "chat.completion",
        "model": body.get("model", "fake-model"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": len(json.dumps(messages)) // 4, "completion_tokens": len(content) // 4},
    }

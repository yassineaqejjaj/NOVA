"""Minimal ORBIT API double for E2E tests (shapes follow ORBIT docs/API.md; test fixture data only).

uv run uvicorn tests.support.fake_orbit_server:app --port 8392
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response

app = FastAPI()
USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "email": "pm@orbit.test",
    "full_name": "Test PM",
    "is_admin": False,
    "clearance": 2,
}
PASSWORD = "orbit-e2e"
PROJECT = {"id": "22222222-2222-2222-2222-222222222222", "slug": "forge", "name": "FORGE", "description": "AI Evaluation Platform", "role": "owner",
           "stats": {"sources": 3, "documents": 3, "memory_items": 2, "context_requests_7d": 0}}  # fmt: skip
ITEMS = [
    ("FORGE Vision v2", "memory", None, "decision", "Every agent release is measurably better before it ships.", 1),
    (
        "Q4 Objectives",
        "chunk",
        "document",
        None,
        "Objective: no release with an undetected regression. Objective: gate releases in CI.",
        1,
    ),
    (
        "Sprint 19 Backlog",
        "chunk",
        "ticket",
        None,
        "FORGE-212 CLI gate (5 pts, carried over). FORGE-230 score provenance (8 pts).",
        2,
    ),
]


def _token() -> str:
    claims = (
        base64.urlsafe_b64encode(json.dumps({"sub": USER["id"], "exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
    )
    return f"eyJhbGciOiJIUzI1NiJ9.{claims}.signature"


def _auth(request: Request) -> None:
    if not request.headers.get("authorization", "").startswith("Bearer eyJ") and not request.headers.get("x-orbit-key"):
        raise HTTPException(401, {"detail": "Authentification requise", "code": "unauthorized"})


def _project(slug: str) -> None:
    if slug != "forge":
        raise HTTPException(404, {"detail": "Projet introuvable", "code": "not_found"})


@app.post("/api/v1/auth/login")
async def login(body: dict[str, Any], response: Response) -> dict[str, Any]:
    if body.get("email") != USER["email"] or body.get("password") != PASSWORD:
        raise HTTPException(401, {"detail": "E-mail ou mot de passe incorrect", "code": "unauthorized"})
    response.set_cookie("orbit_session", _token(), httponly=True)
    return USER


@app.get("/api/v1/auth/me")
async def me(request: Request) -> dict[str, Any]:
    _auth(request)
    return USER


@app.get("/api/v1/projects")
async def projects(request: Request) -> list[dict[str, Any]]:
    _auth(request)
    return [PROJECT]


@app.post("/api/v1/projects/{slug}/context")
async def context(slug: str, request: Request) -> dict[str, Any]:
    _auth(request)
    _project(slug)
    body = await request.json()
    allowed = {"task", "intent", "agent_id", "on_behalf_of", "token_budget", "scopes", "source_kinds", "include_sources", "freshness_days",
               "max_classification", "min_relevance", "session_id", "base_snapshot", "save_snapshot", "explain"}  # fmt: skip
    extra = set(body) - allowed
    if extra:  # ORBIT input models forbid unknown fields
        raise HTTPException(422, {"detail": f"Champs inconnus : {sorted(extra)}", "code": "validation_error"})
    items = []
    for i, (title, ctype, source_kind, memory_kind, excerpt, classification) in enumerate(ITEMS, 1):
        items.append({
            "citation": f"S{i}", "candidate_type": ctype, "id": str(uuid.uuid5(uuid.NAMESPACE_URL, title)),
            "document_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, title)) if ctype == "chunk" else None,
            "memory_item_id": str(uuid.uuid5(uuid.NAMESPACE_OID, title)) if ctype == "memory" else None,
            "title": title, "source_kind": source_kind, "memory_kind": memory_kind, "excerpt": excerpt, "tokens": 40,
            "scores": {"final": 0.9 - i * 0.1}, "classification": classification,
            "date": (datetime.now(UTC) - timedelta(days=i)).isoformat(), "pii_redacted": False, "reason_code": "INCLUDED_RELEVANT",
        })  # fmt: skip
    return {"request_id": str(uuid.uuid4()), "trace_id": uuid.uuid4().hex, "task": body["task"], "intent": body.get("intent", "general"),
            "created_at": datetime.now(UTC).isoformat(), "context": "", "items": items, "excluded": [], "exclusion_summary": {"EXCLUDED_ACL": 1},
            "tokens_used": 120, "token_budget": body.get("token_budget", 4000), "candidates_count": 4, "timings": {"total": 42.0},
            "snapshot": None, "config": {"reranker": "heuristic", "embedding_model": "hash"},
            "warnings": ["Le contexte contient des informations classifiées C2 (Confidentiel)."]}  # fmt: skip


@app.get("/api/v1/projects/{slug}/changes")
async def changes(slug: str, request: Request) -> dict[str, Any]:
    _auth(request)
    _project(slug)
    item = {"id": str(uuid.uuid4()), "project_id": PROJECT["id"], "type": "document.new_version", "type_label": "Nouvelle version de document",
            "title": "Nouvelle version : FORGE PRD", "summary": "« FORGE PRD » mis à jour (v4)", "target_type": "document", "target_id": None,
            "classification": 1, "actor_label": "Test PM", "created_at": datetime.now(UTC).isoformat(), "data": {"version": 4}}  # fmt: skip
    return {"items": [item], "total": 1, "page": 1, "page_size": 20}


@app.get("/api/v1/projects/{slug}/overview")
async def overview(slug: str, request: Request) -> dict[str, Any]:
    _auth(request)
    _project(slug)
    return {
        "stats": {"sources": 2, "documents": 14, "memory_items": 9, "validated_decisions": 4, "snapshots": 1},
        "memory_by_scope": {},
    }


@app.get("/api/v1/projects/{slug}/search")
async def search(slug: str, request: Request, q: str = "", limit: int = 10) -> list[dict[str, Any]]:
    _auth(request)
    _project(slug)
    return [{"chunk_id": str(uuid.uuid4()), "document_id": str(uuid.uuid4()), "document_title": "Q4 Objectives", "source_kind": "document",
             "text": f"Result for {q}", "score": 0.8, "bm25": 1.0, "dense": 0.5, "section": None, "source_updated_at": None}]  # fmt: skip


@app.post("/api/v1/projects/{slug}/context/requests/{request_id}/feedback")
async def feedback(slug: str, request_id: str, request: Request) -> dict[str, str]:
    _auth(request)
    return {"id": str(uuid.uuid4())}


@app.post("/api/v1/projects/{slug}/memory")
async def memory(slug: str, request: Request) -> dict[str, Any]:
    _auth(request)
    return {"id": str(uuid.uuid4()), "title": (await request.json())["title"], "status": "proposed"}


@app.post("/api/v1/projects/{slug}/documents/text")
async def document(slug: str, request: Request) -> dict[str, Any]:
    _auth(request)
    return {"id": str(uuid.uuid4()), "status": "pending"}

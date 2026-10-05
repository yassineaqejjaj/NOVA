"""HTTP-level flows through the FastAPI app (dev auth, eager execution, fake LLM/ORBIT/FORGE)."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
import pytest_asyncio

from nova.config import get_settings
from nova.domain.outputs import AnswerOutput, IntentClassification, PlanOutput
from nova_api.main import create_app


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app, email: str | None = None, name: str = "Yassine") -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    response = await client.post(
        "/api/v1/auth/dev-login",
        json={"email": email or f"{uuid.uuid4().hex[:8]}@example.com", "name": name, "title": "Head of AI"},
    )
    assert response.status_code == 200, response.text
    return client


async def _project(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/projects", json={"name": f"FORGE {uuid.uuid4().hex[:4]}", "description": "AI Evaluation Platform"}
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _ask(client: httpx.AsyncClient, text: str, **composer) -> dict:
    conversation = (await client.post("/api/v1/conversations", json={})).json()
    response = await client.post(f"/api/v1/conversations/{conversation['id']}/messages", json={"text": text, **composer})
    assert response.status_code == 202, response.text
    detail = (await client.get(f"/api/v1/conversations/{conversation['id']}")).json()
    return {"conversation": detail, "reply": detail["messages"][-1], "task_id": response.json()["task"]["id"]}


async def test_auth_required_and_me(app):
    anonymous = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    response = await anonymous.get("/api/v1/me")
    assert response.status_code == 401 and response.json()["code"] == "unauthorized"
    client = await _client(app)
    me = (await client.get("/api/v1/me")).json()
    assert me["display_name"] == "Yassine" and me["preferences"]["nova_name"] == "NOVA"
    today = (await client.get("/api/v1/today")).json()
    assert today["user"]["first_name"] == "Yassine"


async def test_home_command_center_is_computed_from_real_work(app, llm):
    client = await _client(app)
    empty = (await client.get("/api/v1/today")).json()
    assert empty["nova"]["state"] == "idle" and empty["brief"]["results_ready"] == 0 and empty["continue"] == []
    assert empty["context"]["system"] == "ORBIT" and empty["quality"]["last_evaluation"] is None

    await _ask(client, "Create a PRD for scheduled CSV exports")
    home = (await client.get("/api/v1/today")).json()
    assert home["nova"]["state"] == "completed" and home["brief"]["results_ready"] == 1
    assert home["continue"][0]["title"]
    for rec in home["recommendations"]:
        assert rec["actions"] and rec["context"] and rec["suggestion"]
    if home["recommendations"]:
        target = home["recommendations"][0]["id"]
        assert (await client.post("/api/v1/today/dismiss", json={"id": target})).status_code == 204
        after = (await client.get("/api/v1/today")).json()
        assert target not in {r["id"] for r in after["recommendations"]}


async def test_prd_flow_edit_conflict_versions_compare_export(app, llm):
    client = await _client(app)
    result = await _ask(client, "Create a PRD for scheduled CSV exports")
    reply = result["reply"]
    assert reply["task"]["status"] == "completed"
    artifact_block = next(b for b in reply["blocks"] if b["type"] == "artifact")
    artifact_id = artifact_block["data"]["artifact_id"]

    artifact = (await client.get(f"/api/v1/artifacts/{artifact_id}")).json()
    assert artifact["type"] == "prd" and artifact["version"] == 1 and artifact["can_edit"]
    summary = {"kind": "rich_text", "blocks": [{"type": "paragraph", "text": "Edited by the user"}]}
    saved = await client.patch(f"/api/v1/artifacts/{artifact_id}", json={"base_version": 1, "sections": {"summary": summary}})
    assert saved.json() == {"version": 2, "changed_sections": ["summary"]}
    stale = await client.patch(f"/api/v1/artifacts/{artifact_id}", json={"base_version": 1, "sections": {"summary": summary}})
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"

    versions = (await client.get(f"/api/v1/artifacts/{artifact_id}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1] and versions[1]["skill_id"] == "prd"
    diff = (await client.get(f"/api/v1/artifacts/{artifact_id}/compare", params={"from": 1, "to": 2})).json()
    assert {d["key"]: d["status"] for d in diff["sections"]}["summary"] == "changed"
    md = await client.get(f"/api/v1/artifacts/{artifact_id}/export", params={"format": "md"})
    assert md.status_code == 200 and "## Summary" in md.text and "Edited by the user" in md.text

    final = await client.patch(f"/api/v1/artifacts/{artifact_id}", json={"base_version": 2, "status": "final"})
    assert final.status_code == 200
    events = (await client.get("/api/v1/activity")).json()
    assert {"work", "artifact", "decision"} <= {e["category"] for e in events}
    decision = next(e for e in events if e["category"] == "decision")
    assert decision["artifact_id"] == artifact_id and decision["text"].endswith("as final")


async def test_other_users_cannot_see_an_artifact(app):
    owner = await _client(app)
    result = await _ask(owner, "Create a PRD for audit logs")
    artifact_id = next(b for b in result["reply"]["blocks"] if b["type"] == "artifact")["data"]["artifact_id"]
    stranger = await _client(app)
    assert (await stranger.get(f"/api/v1/artifacts/{artifact_id}")).status_code == 404
    assert (await stranger.get(f"/api/v1/tasks/{result['task_id']}")).status_code == 404


async def test_provenance_question_uses_only_recorded_sources(app, llm, orbit):
    client = await _client(app)
    project_id = await _project(client)
    # Link the NOVA project to an ORBIT slug so context is retrieved.
    from nova.infra import db
    from nova.infra.models import ProjectReference

    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    first = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    artifact_id = next(b for b in first["reply"]["blocks"] if b["type"] == "artifact")["data"]["artifact_id"]
    artifact = (await client.get(f"/api/v1/artifacts/{artifact_id}")).json()
    requirement = artifact["content"]["sections"]["functional_requirements"]["items"][0]

    llm.intent = lambda m: IntentClassification(
        kind="explain_provenance", goal="Explain requirement", target_artifact_id=artifact_id, target_item_id=requirement["id"]
    )
    llm.answer = lambda m: AnswerOutput(answer="It comes from the vision [S1] and the budget [S7].", citations=["S1", "S7"])
    second = await _ask(client, "Why did you include this requirement?", project_id=project_id, active_artifact_id=artifact_id)
    blocks = {b["key"]: b for b in second["reply"]["blocks"]}
    sources = blocks["citations"]["data"]["sources"]
    assert [s["label"] for s in sources] == ["S1"] and sources[0]["title"] == "FORGE Vision v2"
    assert "[S7]" not in blocks["text"]["data"]["markdown"]  # unrecorded label removed — no fabricated provenance

    provenance = (await client.get(f"/api/v1/artifacts/{artifact_id}/provenance", params={"item": requirement["id"]})).json()
    assert provenance["sources"][0]["label"] == "S1" and provenance["origin"]["skill_id"] == "prd"


async def test_section_regeneration_changes_only_that_section(app, llm):
    client = await _client(app)
    first = await _ask(client, "Create a PRD for scheduled CSV exports")
    artifact_id = next(b for b in first["reply"]["blocks"] if b["type"] == "artifact")["data"]["artifact_id"]
    before = (await client.get(f"/api/v1/artifacts/{artifact_id}")).json()["content"]["sections"]

    def rewrite_metrics(raw, messages):
        return {"summary": "Metrics rewritten", "sections": {"metrics": {"items": [
            {"id": "metric-adoption", "title": "Weekly exporters", "attributes": {"definition": "Users exporting weekly", "target": "40%"}}
        ]}}}  # fmt: skip

    llm.step_override = rewrite_metrics
    response = await client.post(
        f"/api/v1/artifacts/{artifact_id}/sections/metrics/regenerate", json={"instruction": "Rewrite the success metrics"}
    )
    assert response.status_code == 202
    after = (await client.get(f"/api/v1/artifacts/{artifact_id}")).json()
    assert after["version"] == 2
    assert after["content"]["sections"]["metrics"]["items"][0]["title"] == "Weekly exporters"
    for key, section in before.items():
        if key != "metrics":
            assert after["content"]["sections"][key] == section
    versions = (await client.get(f"/api/v1/artifacts/{artifact_id}/versions")).json()
    assert versions[0]["changed_sections"] == ["metrics"] and versions[0]["skill_id"] == "artifact-edit"


async def test_forge_agent_protocol_runs_without_orbit(app, orbit):
    settings = get_settings()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as forge:
        body = {
            "protocol": "forge-agent-protocol/v1",
            "run_id": "run-123",
            "input": {"prompt": "Rédige un PRD pour l'export CSV planifié."},
            "context": {
                "documents": [
                    {"id": "interviews-2026", "title": "Entretiens clients", "content": "Les clients exportent chaque lundi."}
                ]
            },
            "constraints": ["Inclure des critères d'acceptation"],
            "budget": {"timeout_seconds": 60, "max_steps": 8},
            "nova_agent_id": "nova-orchestrator",
        }
        denied = await forge.post("/v1/agents/nova-orchestrator/runs", json=body)
        assert denied.status_code == 401
        response = await forge.post(
            "/v1/agents/nova-orchestrator/runs",
            json=body,
            headers={
                "Authorization": f"Bearer {settings.forge_inbound_token}",
                "traceparent": "00-5b8efff798038103d269b633813fc60c-eee19b7ec3c1b174-01",
            },
        )
    data = response.json()
    assert response.status_code == 200 and data["protocol"] == "forge-agent-protocol/v1" and data.get("error") is None
    assert "# " in data["output"] and "prd" in data["output_json"]
    assert data["usage"]["input_tokens"] > 0 and data["metadata"]["skills"][0]["id"] == "prd"
    assert {e["type"] for e in data["events"]} >= {"retrieval", "llm_call"}
    assert data["metadata"]["trace_id"] == "5b8efff798038103d269b633813fc60c"  # FORGE trace continued
    assert orbit.queries == []  # reproducible: FORGE context only


async def test_not_useful_feedback_is_routed_to_orbit_and_forge(app, orbit, forge):
    client = await _client(app)
    project_id = await _project(client)
    from nova.infra import db
    from nova.infra.models import ProjectReference

    async with db.session_scope() as session:
        session.add(ProjectReference(project_id=uuid.UUID(project_id), system="orbit", external_id="forge", label="FORGE"))
    result = await _ask(client, "Create a PRD for scheduled CSV exports", project_id=project_id)
    response = await client.post(
        "/api/v1/feedback", json={"rating": "not_useful", "comment": "Metrics are vague", "message_id": result["reply"]["id"]}
    )
    assert response.status_code == 201
    assert response.json()["forwarded"] == {"orbit": True, "forge": "pending"}
    assert orbit.feedback and orbit.feedback[0][1] is False
    assert forge.captured and forge.captured[0].user_intent.startswith("Create a PRD")
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["evaluation"]["run_id"] == "run-1"


async def test_sse_replays_events_of_a_finished_execution(app):
    client = await _client(app)
    result = await _ask(client, "Create a PRD for audit logs")
    async with client.stream("GET", f"/api/v1/executions/{result['task_id']}/events") as response:
        lines = [line async for line in response.aiter_lines()]
    events = [json.loads(line[5:]) for line in lines if line.startswith("data:")]
    types = [e.get("type") for e in events]
    assert "block" in types and "done" in types and events[-1] == {"status": "completed"}
    seqs = [e["seq"] for e in events if "seq" in e]
    assert seqs == sorted(seqs)


@pytest.mark.parametrize("autonomy", ["suggest"])
async def test_suggest_mode_always_confirms(app, llm, autonomy):
    llm.plan = lambda m: PlanOutput(objective="PRD", steps=[{"id": "a", "title": "PRD", "skill_id": "prd"}])
    client = await _client(app)
    result = await _ask(client, "Create a PRD for SSO", autonomy=autonomy)
    assert result["reply"]["task"]["status"] == "waiting_user"
    resume = await client.post(f"/api/v1/executions/{result['task_id']}/resume", json={"value": {"action": "cancel"}})
    assert resume.status_code == 202
    task = (await client.get(f"/api/v1/tasks/{result['task_id']}")).json()
    assert task["status"] == "cancelled"


async def test_language_and_orb_color_preferences_localize_server_text(app, llm):
    client = await _client(app)
    me = (await client.patch("/api/v1/me/preferences", json={"language": "fr", "orb_color": "violet"})).json()
    assert me["preferences"]["language"] == "fr" and me["preferences"]["orb_color"] == "violet"
    assert (await client.patch("/api/v1/me/preferences", json={"orb_color": "neon"})).status_code == 422

    await _ask(client, "Create a PRD for scheduled CSV exports")
    events = (await client.get("/api/v1/activity")).json()
    texts = " ".join(e["text"] for e in events)
    assert "NOVA a" in texts and "Terminé" in texts
    skills = (await client.get("/api/v1/skills")).json()
    prd = next(s for s in skills if s["id"] == "prd")
    assert prd["translations"]["fr"]["name"] and prd["translations"]["fr"]["artifact_type_name"]
    types = (await client.get("/api/v1/artifacts/types")).json()
    assert all(t["translations"]["fr"]["name"] for t in types)

    english = await _client(app)  # no preference: follows Accept-Language
    events_fr = (await english.get("/api/v1/activity", headers={"Accept-Language": "fr-FR,fr;q=0.9"})).json()
    assert isinstance(events_fr, list)


async def test_voice_relays_audio_to_the_voice_service_and_never_without_auth(app, monkeypatch):
    import httpx as _httpx

    from nova.config import get_settings
    from nova_api.routers import voice
    from tests.support import fake_voice_server

    monkeypatch.setattr(get_settings(), "voice_url", "http://voice.test")
    monkeypatch.setattr(get_settings(), "voice_token", fake_voice_server.TOKEN)
    monkeypatch.setattr(voice, "TRANSPORT", _httpx.ASGITransport(app=fake_voice_server.app))

    anonymous = _httpx.AsyncClient(transport=_httpx.ASGITransport(app=app), base_url="http://test")
    assert (await anonymous.post("/api/v1/voice/speak", json={"text": "Bonjour"})).status_code == 401

    client = await _client(app)
    assert (await client.get("/api/v1/voice/status")).json() == {"enabled": True}
    heard = await client.post("/api/v1/voice/transcribe", files={"audio": ("speech.webm", b"\x1aE\xdf\xa3fake", "audio/webm")})
    assert heard.status_code == 200 and heard.json()["text"] == fake_voice_server.TRANSCRIPT
    spoken = await client.post("/api/v1/voice/speak", json={"text": "Bonjour, je suis NOVA.", "language": "fr"})
    assert spoken.status_code == 200 and spoken.headers["content-type"] == "audio/wav" and spoken.content[:4] == b"RIFF"
    assert (await client.post("/api/v1/voice/transcribe", files={"audio": ("s.webm", b"", "audio/webm")})).status_code == 422

    monkeypatch.setattr(get_settings(), "voice_url", "")
    assert (await client.post("/api/v1/voice/speak", json={"text": "x"})).json()["code"] == "voice_unavailable"

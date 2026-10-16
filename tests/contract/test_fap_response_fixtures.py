"""What NOVA answers to FORGE (NOV-74): ``contracts/fap_response/*.json``, the source of FORGE's copy.

The real route answers the contract request bodies (scripted LLM, SQLite, no external service); the answers are
normalised (volatile values replaced, long text cut, see ``NORMALIZATION``) and compared with the committed files.
A change of the response shape fails here until the fixtures are regenerated and FORGE's copy is refreshed::

    NOVA_REGENERATE_CONTRACTS=1 uv run pytest tests/contract/test_fap_response_fixtures.py

Each file is ``{"status_code": <HTTP status>, "body": <FAP response>}``.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

import httpx
import pytest
import pytest_asyncio

from nova.config import get_settings
from nova_api.main import create_app
from tests.contract.support import FAP_REQUEST_DIR, FAP_RESPONSE_DIR, load, load_script
from tests.contract.test_orbit_forge_nova_traversal import current_label, request_body

sync = load_script("sync_contract_fixtures")
MANIFEST = "manifest.json"
TIMESTAMP = "2026-10-01T12:00:00+00:00"
UUID = "00000000-0000-4000-8000-000000000000"
NORMALIZATION = [
    "output cut to its first 160 characters; output_json artifacts reduced to their type with an empty object",
    "events: first event of each type, ids and timestamps replaced, token counts fixed, free-text detail cut",
    "usage fixed (100 in / 20 out); task id, trace id, runtime commit, skill catalog digest, release labels and Skill versions replaced",
]


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def normalize(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    body = json.loads(json.dumps(body))
    body["output"] = body["output"][:160]
    if body["error"]:
        body["error"]["message"] = body["error"]["message"].replace(current_label(), "<current release label>")
    if body["output_json"]:
        body["output_json"] = {kind: {} for kind in body["output_json"]}
    first: dict[str, dict[str, Any]] = {}
    for event in body["events"]:
        first.setdefault(event["type"], event)
    body["events"] = [
        {
            **e,
            "id": f"evt-{kind}",
            "ended_at": TIMESTAMP if e["ended_at"] else None,
            "output": None if e["output"] is None else "<detail>",
            "attributes": {k: (v if k not in ("input_tokens", "output_tokens") else 100 if k == "input_tokens" else 20)
                           for k, v in e["attributes"].items()},
        }
        for kind, e in first.items()
    ]  # fmt: skip
    for e in body["events"]:  # Skill versions move with the catalog: the shape matters, not the number
        if "nova.skill_version" in e["attributes"]:
            e["attributes"]["nova.skill_version"] = "<version>"
            e["name"] = f"Skill {e['attributes']['nova.skill']}@<version>"
    body["usage"] = (
        {**body["usage"], "input_tokens": 100, "output_tokens": 20, "model_calls": 1, "tool_calls": 0}
        if body["events"]
        else body["usage"]
    )
    meta = body["metadata"]
    if meta:
        executed = meta["executed"]
        digest = "<digest>"
        meta["skills"] = [{**skill, "version": "<version>"} for skill in meta["skills"]]
        meta.update(
            nova_task_id=UUID, trace_id=None, skill_catalog=digest, requested_version="<current release label>",
            executed_version=f"{executed['nova_version']}+{digest}",
            executed={**executed, "runtime_commit": "", "skill_catalog": digest, "version": f"{executed['nova_version']}+{digest}"},
        )  # fmt: skip
    return {"status_code": status_code, "body": body}


async def answers(app: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    async def post(body: dict[str, Any], token: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or get_settings().forge_inbound_token}".encode()}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post(f"/v1/agents/{body['nova_agent_id']}/runs", json=body, headers=headers)

    live = request_body("live")
    current = {**live, "agent": {**live["agent"], "version": current_label()}}
    out: dict[str, dict[str, Any]] = {}
    ok = await post(current)
    out["response_ok.json"] = normalize(ok.status_code, ok.json())
    stale = await post(live)  # the label FORGE registered earlier is not the current runtime
    out["response_unsupported_override.json"] = normalize(stale.status_code, stale.json())
    wrong = await post(current, token="fgk_wrong_credential")
    out["response_unauthorized.json"] = normalize(wrong.status_code, wrong.json())
    monkeypatch.setattr(get_settings(), "policy_max_classification", 2)
    refused = await post(current)
    out["response_classification_refused.json"] = normalize(refused.status_code, refused.json())
    return out


def render(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def build_manifest(files: dict[str, str]) -> str:
    manifest = {
        "contract": "fap-response",
        "protocol": "forge-agent-protocol/v1",
        "source": "NOVA tests/contract/test_fap_response_fixtures.py (real route, scripted LLM, synthetic data)",
        "normalization": NORMALIZATION,
        "derived_from": {"fap_request_manifest_sha256": hashlib.sha256((FAP_REQUEST_DIR / MANIFEST).read_bytes()).hexdigest()},
        "files": {name: {"sha256": hashlib.sha256(text.encode()).hexdigest()} for name, text in sorted(files.items())},
    }
    return json.dumps(manifest, indent=1, ensure_ascii=False) + "\n"


async def test_the_response_fixtures_are_what_the_real_route_answers(app, monkeypatch) -> None:
    files = {name: render(data) for name, data in (await answers(app, monkeypatch)).items()}
    files[MANIFEST] = build_manifest({n: t for n, t in files.items()})
    if os.environ.get("NOVA_REGENERATE_CONTRACTS"):
        FAP_RESPONSE_DIR.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            (FAP_RESPONSE_DIR / name).write_text(text, encoding="utf-8")
    assert {p.name for p in FAP_RESPONSE_DIR.glob("*.json")} == set(files)
    for name, text in files.items():
        assert (FAP_RESPONSE_DIR / name).read_text(encoding="utf-8") == text, (
            f"contracts/fap_response/{name} is stale: NOVA_REGENERATE_CONTRACTS=1 uv run pytest "
            "tests/contract/test_fap_response_fixtures.py, then refresh the copy in FORGE (docs/CONTRACTS.md)"
        )


def test_the_response_fixtures_match_their_manifest_and_the_request_copy() -> None:
    assert sync.verify_copy(FAP_RESPONSE_DIR) == []
    manifest = load(FAP_RESPONSE_DIR, MANIFEST)
    assert manifest["derived_from"]["fap_request_manifest_sha256"] == sync.digest(FAP_REQUEST_DIR / MANIFEST)


def test_the_mandatory_scenarios_are_answered_as_the_protocol_says() -> None:
    ok, stale, wrong, refused = (
        load(FAP_RESPONSE_DIR, f"response_{n}.json")
        for n in ("ok", "unsupported_override", "unauthorized", "classification_refused")
    )
    assert (
        ok["status_code"] == 200
        and ok["body"]["error"] is None
        and ok["body"]["output"]
        and ok["body"]["metadata"]["executed_version"]
    )
    assert (stale["status_code"], stale["body"]["error"]["type"], stale["body"]["error"]["fields"]) == (
        422,
        "unsupported_override",
        ["agent.version"],
    )
    assert stale["body"]["metadata"] == {}  # nothing was executed
    assert (wrong["status_code"], wrong["body"]["error"]["type"]) == (401, "UNAUTHORIZED")
    assert (refused["status_code"], refused["body"]["error"]["type"]) == (403, "CLASSIFICATION_REFUSED")

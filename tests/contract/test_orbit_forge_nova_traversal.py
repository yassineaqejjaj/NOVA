"""ORBIT -> FORGE -> NOVA traversal (NOV-74): real ORBIT fixtures, the body FORGE really produced, NOVA's mapper and endpoint.

Chain of fixtures, each hop verified against its manifest:

* ORBIT ``ContextPackage`` / ``Snapshot`` (``tests/fixtures/orbit``, copy of ORBIT ``contracts/orbit``);
* the request FORGE sends (``tests/fixtures/fap_request``, copy of FORGE ``contracts/fap_request``, generated from FORGE's
  real code out of the very same ORBIT contract: the manifests must agree);
* NOVA: ``NovaRunRequest`` / ``mapper.provided_context`` and the real ``POST /v1/agents/{id}/runs`` endpoint.

No service: the app runs in-process on SQLite with the scripted LLM. Synthetic data only.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import Artifact, ContextRetrievalReference, Task
from nova.integrations.forge import mapper
from nova.integrations.forge.schemas import NovaRunRequest
from nova.services import providers
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app
from tests.contract.support import FAP_REQUEST_DIR, ORBIT_DIR, load, load_script

sync = load_script("sync_contract_fixtures")

REQUESTS = {
    "live": "request_orbit_live.json",
    "limited": "request_orbit_live_limited_rights.json",
    "snapshot": "request_orbit_snapshot.json",
}


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


def request_body(key: str) -> dict[str, Any]:
    return load(FAP_REQUEST_DIR, REQUESTS[key])


def current_label() -> str:
    """The FORGE agent version label of the NOVA runtime running now (what a registered FORGE version carries)."""
    settings = get_settings()
    return mapper.release_label(
        settings.version, providers.llm().model_name, get_skill_registry().catalog_digest(), settings.llm_provider
    )


def items_of(key: str) -> list:
    return mapper.provided_context(NovaRunRequest.model_validate(request_body(key)))


# --- The chain of fixtures ----------------------------------------------------------------------------------------------


def test_the_copies_are_exactly_what_their_manifests_pin() -> None:
    assert sync.verify_copy(ORBIT_DIR) == [] and sync.verify_copy(FAP_REQUEST_DIR) == []


def test_forge_produced_its_bodies_from_the_orbit_contract_this_repository_holds() -> None:
    """Two copies of the same ORBIT contract (here and in FORGE) cannot silently diverge: the hash is the link."""
    forge_manifest = load(FAP_REQUEST_DIR, "manifest.json")
    assert forge_manifest["derived_from"]["orbit_manifest_sha256"] == sync.digest(ORBIT_DIR / "manifest.json"), (
        "FORGE generated its bodies from another ORBIT contract version: refresh both copies (docs/CONTRACTS.md)"
    )
    assert forge_manifest["derived_from"]["orbit_schema_version"] == load(ORBIT_DIR, "manifest.json")["schema_version"]
    assert forge_manifest["protocol"] == "forge-agent-protocol/v1"


@pytest.mark.skipif(not os.environ.get("CONTRACT_SOURCE_ORBIT"), reason="set CONTRACT_SOURCE_ORBIT=<ORBIT>/contracts/orbit")
def test_the_orbit_copy_is_identical_to_the_orbit_source() -> None:
    assert sync.differences(Path(os.environ["CONTRACT_SOURCE_ORBIT"]), ORBIT_DIR) == []


@pytest.mark.skipif(not os.environ.get("CONTRACT_SOURCE_FORGE"), reason="set CONTRACT_SOURCE_FORGE=<FORGE>/contracts/fap_request")
def test_the_forge_copy_is_identical_to_the_forge_source() -> None:
    assert sync.differences(Path(os.environ["CONTRACT_SOURCE_FORGE"]), FAP_REQUEST_DIR) == []


# --- Mapper: what NOVA reads out of FORGE's body --------------------------------------------------------------------------


def test_the_excerpt_reaches_nova_identical_and_not_empty() -> None:
    package = load(ORBIT_DIR, "context_package.json")
    items = items_of("live")
    documents = items[: len(package["items"])]
    assert [i.excerpt for i in documents] == [o["excerpt"] for o in package["items"]]
    assert all(i.excerpt.strip() for i in items)


def test_every_source_stays_identifiable_back_to_orbit() -> None:
    package = load(ORBIT_DIR, "context_package.json")
    items = items_of("live")
    for item, orbit in zip(items, package["items"], strict=False):
        assert (item.ref_id, item.title, item.version, item.document_id) == (
            orbit["id"], orbit["title"], orbit["version"], orbit["document_id"],
        )  # fmt: skip
        assert item.citation == orbit["citation"]  # NOVA cites by position, which is ORBIT's order here
    assert items[-1].ref_id == mapper.ORBIT_CONTEXT_REF and items[-1].source_system == "orbit"
    assert items[-1].excerpt == package["context"]


def test_a_secret_document_stays_secret_and_nothing_is_lowered() -> None:
    package = load(ORBIT_DIR, "context_package.json")
    items = items_of("live")
    by_id = {i.ref_id: i for i in items}
    assert all(by_id[o["id"]].classification >= o["classification"] for o in package["items"])
    secret = next(o for o in package["items"] if o["classification"] == 3)
    assert by_id[secret["id"]].classification == 3
    assert items[-1].classification == 3  # the assembled ORBIT text carries the declared maximum


def test_limited_rights_stay_limited() -> None:
    limited = load(ORBIT_DIR, "context_package_limited_rights.json")
    items = items_of("limited")
    assert [i.classification for i in items] == [1, 1]  # the C1 passage + ORBIT's own text; no C3 is invented
    assert limited["max_classification"] == 1
    assert "120 EUR" not in json.dumps([i.model_dump(mode="json") for i in items], ensure_ascii=False)


def test_a_forgotten_snapshot_item_does_not_exist_for_nova() -> None:
    snapshot = load(ORBIT_DIR, "snapshot.json")
    forgotten = [i for i in snapshot["items"] if i["forgotten"]]
    assert forgotten
    items = items_of("snapshot")
    assert not {i["id"] for i in forgotten} & {i.ref_id for i in items}
    assert "contenu oublié" not in json.dumps([i.model_dump(mode="json") for i in items], ensure_ascii=False)
    served = [i for i in snapshot["items"] if not i["forgotten"]]
    assert [i.excerpt for i in items[: len(served)]] == [s["excerpt"] for s in served]
    assert [i.ref_id for i in items[: len(served)]] == [s["id"] for s in served]
    assert items[-1].excerpt == snapshot["content"]


def test_without_a_declared_maximum_the_levels_are_the_orbit_ones_or_secret() -> None:
    """If FORGE sent no maximum, a document keeps its own level and one without level is C3 (fail closed)."""
    body = request_body("live")
    del body["context"]["max_classification"]
    levels = [i.classification for i in mapper.provided_context(NovaRunRequest.model_validate(body))]
    assert levels[:3] == [1, 2, 3]
    unlabelled = copy.deepcopy(body)
    del unlabelled["context"]["documents"][0]["classification"]
    assert mapper.provided_context(NovaRunRequest.model_validate(unlabelled))[0].classification == mapper.UNCLASSIFIED_LEVEL


# --- Endpoint: the same bodies against the real route ---------------------------------------------------------------------


async def post(app: Any, body: dict[str, Any], *, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token or get_settings().forge_inbound_token}".encode()}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as forge:
        return await forge.post(f"/v1/agents/{body['nova_agent_id']}/runs", json=body, headers=headers)


async def forge_tasks() -> int:
    async with db.session_scope() as session:
        return await session.scalar(select(func.count()).select_from(Task).where(Task.origin == "forge_protocol"))


async def records(task_id: str) -> tuple[list[dict], list[int], list[int]]:
    async with db.session_scope() as session:
        task = await session.get(Task, uuid.UUID(task_id))
        artifacts = (await session.scalars(select(Artifact).where(Artifact.task_id == task.id))).all()
        refs = (
            await session.scalars(select(ContextRetrievalReference).where(ContextRetrievalReference.task_id == task.id))
        ).all()
        return task.input["provided_context"], [a.classification for a in artifacts], [r.max_classification for r in refs]


async def test_the_real_context_runs_secret_and_cites_the_orbit_documents(app) -> None:
    body = request_body("live")
    body["agent"]["version"] = current_label()  # the one part FORGE gets from NOVA's registration, not from ORBIT
    response = await post(app, body)
    data = response.json()
    assert response.status_code == 200 and data.get("error") is None and data["output"].strip()
    provided, artifact_levels, record_levels = await records(data["metadata"]["nova_task_id"])
    assert [p["excerpt"] for p in provided[:3]] == [d["content"] for d in body["context"]["documents"]]
    assert [p["ref_id"] for p in provided[:3]] == [d["id"] for d in body["context"]["documents"]]
    assert artifact_levels and set(artifact_levels) == {3} and record_levels == [3]  # the C3 passage makes the run C3
    assert "[source: 3bc8be0b-0000-4000-8000-000000000001]" in data["output"]  # source identifiable in what FORGE evaluates
    assert data["metadata"]["requested_version"] == current_label() and data["metadata"]["executed_version"]


async def test_limited_rights_run_with_the_limited_level(app) -> None:
    body = request_body("limited")
    body["agent"]["version"] = current_label()
    data = (await post(app, body)).json()
    assert data.get("error") is None
    provided, artifact_levels, record_levels = await records(data["metadata"]["nova_task_id"])
    assert len(provided) == 2 and set(artifact_levels) == {1} and record_levels == [1]


async def test_a_snapshot_context_runs_without_the_forgotten_item(app) -> None:
    body = request_body("snapshot")
    body["agent"]["version"] = current_label()
    data = (await post(app, body)).json()
    assert data.get("error") is None
    provided, _, _ = await records(data["metadata"]["nova_task_id"])
    assert "c2" not in {p["ref_id"] for p in provided} and "contenu oublié" not in json.dumps(provided, ensure_ascii=False)


async def test_a_wrong_credential_is_a_401_and_nothing_runs(app) -> None:
    body = request_body("live")
    body["agent"]["version"] = current_label()
    before = await forge_tasks()
    for token in ("fgk_wrong_credential", "", "orb_not_a_nova_token"):
        response = await post(app, body, token=token or "x")
        assert response.status_code == 401 and response.json()["error"]["type"] == "UNAUTHORIZED", token
    assert await forge_tasks() == before


async def test_a_version_change_is_refused_with_unsupported_override_and_nothing_runs(app) -> None:
    body = request_body("live")  # the label FORGE registered at another time: not NOVA's current runtime
    assert body["agent"]["version"] != current_label()
    before = await forge_tasks()
    response = await post(app, body)
    error = response.json()["error"]
    assert response.status_code == 422 and error["type"] == "unsupported_override" and error["retryable"] is False
    assert error["fields"] == ["agent.version"] and body["agent"]["version"] in error["message"]
    assert response.json()["metadata"] == {} and await forge_tasks() == before

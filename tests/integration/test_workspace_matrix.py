"""The mandatory isolation cases of NOV-110 for NOVA, over the two-space fixture of ``tests/support/workspace_spaces.py``.

Every case runs in ``enforce`` with tokens signed by a test key (no IdP). ``docs/ISOLATION.md`` maps each case of the ticket to
the tests of the three repositories; the cases already covered by ``test_workspace_isolation.py`` are not repeated here.
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from nova.config import get_settings
from nova.infra import db, scope
from nova.infra.models import (
    Artifact,
    ContextRetrievalReference,
    ForgeOutbox,
    ForgetRequest,
    OrbitEvent,
    Project,
    Task,
)
from nova_api.main import create_app
from tests.support.workspace_spaces import Member, Space, build_space, call, install_test_idp, sign


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest_asyncio.fixture
async def spaces(app, monkeypatch) -> tuple[Space, Space]:
    monkeypatch.setattr(get_settings(), "workspace_enforcement", "enforce")
    install_test_idp(monkeypatch)
    return await build_space(app, "A"), await build_space(app, "B")


def same_as_unknown(foreign, unknown, where: str = "") -> None:
    """ADR §9 invariant 3: a resource of another space answers exactly like an identifier nobody ever had."""
    assert foreign.status_code == unknown.status_code == 404, (where, foreign.status_code, foreign.text)
    assert foreign.json() == unknown.json(), where


ARTIFACT_READS = ("", "/versions", "/comments", "/provenance", "/freshness", "/export?format=md", "/export?format=json")


# --- read, list, search, export ---------------------------------------------------------------------------------------------


async def test_read_list_search_and_export_never_cross_spaces_for_any_role(app, spaces):
    a, b = spaces
    for member in b.members.values():
        for artifact in a.artifacts.values():
            for suffix in ARTIFACT_READS:
                foreign = await call(app, member, "GET", f"/api/v1/artifacts/{artifact}{suffix}")
                unknown = await call(app, member, "GET", f"/api/v1/artifacts/{uuid.uuid4()}{suffix}")
                same_as_unknown(foreign, unknown, f"{member.role} {suffix}")
        for path, params in (
            ("/api/v1/artifacts", {}),
            ("/api/v1/artifacts", {"q": "SECRET"}),
            ("/api/v1/search", {"q": f"SECRET-{a.name}"}),
            ("/api/v1/projects", {}),
            ("/api/v1/activity", {}),
        ):
            listed = await call(app, member, "GET", path, params=params)
            assert listed.status_code == 200 and f"-{a.name}-" not in listed.text and a.slugs[0] not in listed.text, (
                member.role,
                path,
            )


async def test_inside_a_space_every_role_sees_what_its_clearance_allows(app, spaces):
    a, _ = spaces
    for project in (0, 1):
        for classification in (1, 2, 3):
            artifact = a.artifacts[(project, classification)]
            owner = await call(app, a["owner"], "GET", f"/api/v1/artifacts/{artifact}")
            assert owner.status_code == 200 and owner.json()["title"] == a.title(project, classification)  # C3 clearance
            for role in ("editor", "viewer"):  # default clearance C1: above it the Artifact does not exist for them
                seen = await call(app, a[role], "GET", f"/api/v1/artifacts/{artifact}")
                if classification == 1:
                    assert seen.status_code == 200
                else:
                    same_as_unknown(seen, await call(app, a[role], "GET", f"/api/v1/artifacts/{uuid.uuid4()}"), role)
    listed = (await call(app, a["viewer"], "GET", "/api/v1/artifacts")).json()
    assert {x["title"] for x in listed} == {a.title(0, 1), a.title(1, 1)}


# --- writes and deletes ---------------------------------------------------------------------------------------------------------


async def test_writes_and_deletes_across_spaces_change_nothing(app, spaces):
    a, b = spaces
    routine = (
        await call(
            app,
            a["owner"],
            "POST",
            "/api/v1/routines",
            json={"name": "Revue A", "instructions": "x", "schedule": {"kind": "manual"}},
        )
    ).json()["id"]
    skill = (
        await call(
            app, a["owner"], "POST", "/api/v1/learned-skills", json={"name": "Savoir-faire A", "steps": [{"title": "one"}]}
        )
    ).json()["id"]
    unknown = str(uuid.uuid4())
    artifact = a.artifacts[(0, 1)]
    for member in b.members.values():
        attempts = [
            ("PATCH", "/api/v1/artifacts/{}", {"json": {"base_version": 1, "title": "hijacked"}}),
            ("POST", "/api/v1/artifacts/{}/comments", {"json": {"section_key": "summary", "body": "x"}}),
            ("POST", "/api/v1/artifacts/{}/review", {}),
            ("POST", "/api/v1/artifacts/{}/sections/summary/regenerate", {"json": {"instruction": "x"}}),
            ("POST", "/api/v1/artifacts/{}/refresh", {}),
            ("PATCH", "/api/v1/routines/{}", {"json": {"name": "pirate"}}),
            ("POST", "/api/v1/routines/{}/run", {}),
            ("DELETE", "/api/v1/routines/{}", {}),
            ("DELETE", "/api/v1/learned-skills/{}", {}),
            ("POST", "/api/v1/learned-skills/{}/run", {"json": {}}),
        ]
        for method, template, kwargs in attempts:
            target = {"/artifacts/": artifact, "/routines/": routine, "/learned-skills/": skill}
            real = next(v for k, v in target.items() if k in template)
            foreign = await call(app, member, method, template.format(real), **kwargs)
            same_as_unknown(
                foreign, await call(app, member, method, template.format(unknown), **kwargs), f"{member.role} {method} {template}"
            )
    async with db.session_scope() as session:  # nothing moved
        assert (await session.get(Artifact, artifact)).title == a.title(0, 1)
    assert routine in {r["id"] for r in (await call(app, a["owner"], "GET", "/api/v1/routines")).json()}
    assert skill in {s["id"] for s in (await call(app, a["owner"], "GET", "/api/v1/learned-skills")).json()}
    assert (
        await call(app, a["owner"], "DELETE", f"/api/v1/routines/{routine}")
    ).status_code == 204  # the owner's own delete works


# --- a token of one space aimed at a project of another ----------------------------------------------------------------------


async def test_a_token_of_a_space_aimed_at_a_project_of_another_opens_nothing(app, spaces):
    a, b = spaces
    async with db.session_scope() as session:
        orion_ids = [(await session.get(Project, p)).orion_project_id for p in b.projects]
    unknown = str(uuid.uuid4())
    for project, orion in zip(b.projects, orion_ids, strict=True):
        # even a token that claims B's project: it is the workspace and the local membership that open a project
        owner = Member("owner", a["owner"].subject, sign(a["owner"].subject, a.id, orion_project_id=str(orion)))

        async def probe(target: str, owner: Member = owner) -> list:
            conversation = (await call(app, owner, "POST", "/api/v1/conversations", json={})).json()["id"]
            return [
                await call(app, owner, "GET", f"/api/v1/projects/{target}"),
                await call(app, owner, "POST", "/api/v1/artifacts", json={"type": "prd", "title": "x", "project_id": target}),
                await call(app, owner, "GET", "/api/v1/context/snapshots", params={"project_id": target}),
                await call(app, owner, "GET", f"/api/v1/context/projects/{target}"),
                await call(
                    app,
                    owner,
                    "POST",
                    f"/api/v1/conversations/{conversation}/messages",
                    json={"text": "hi", "project_id": target},
                ),
            ]

        for foreign, reference in zip(await probe(str(project)), await probe(unknown), strict=True):
            assert foreign.status_code == reference.status_code >= 400
            assert foreign.json() == reference.json()  # no sign that the project exists elsewhere
        filtered = await call(app, owner, "GET", "/api/v1/artifacts", params={"project_id": str(project)})
        assert filtered.status_code == 200 and filtered.json() == []  # a list filtered by a project of another space is empty
        tasks = await call(app, owner, "GET", "/api/v1/tasks", params={"project_id": str(project)})
        assert tasks.status_code == 200 and tasks.json() == []
    assert (await call(app, a["owner"], "GET", f"/api/v1/projects/{a.projects[0]}")).status_code == 200  # its own: fine


# --- keys and service accounts ------------------------------------------------------------------------------------------------------


async def test_the_forge_inbound_key_runs_in_the_default_space_and_no_space_sees_it(app, spaces, llm, orbit):
    _, b = spaces
    body = {
        "protocol": "forge-agent-protocol/v1",
        "run_id": f"run-{uuid.uuid4().hex[:6]}",
        "input": {"prompt": "Rédige un PRD pour l'export CSV planifié."},
        "context": {"documents": [{"id": "d1", "title": "Entretiens", "content": "Les clients exportent chaque lundi."}]},
        "budget": {"timeout_seconds": 60, "max_steps": 8},
        "nova_agent_id": "nova-orchestrator",
    }
    headers = {"Authorization": f"Bearer {get_settings().forge_inbound_token}"}
    response = await call(app, None, "POST", "/v1/agents/nova-orchestrator/runs", json=body, headers=headers)
    assert response.status_code == 200, response.text
    task_id = response.json()["metadata"]["nova_task_id"]
    async with db.session_scope() as session:
        assert (await session.get(Task, uuid.UUID(task_id))).workspace_id == get_settings().default_workspace_id
    for member in b.members.values():  # the key does not act for a user, nor does a user of another space reach its run
        same_as_unknown(
            await call(app, member, "GET", f"/api/v1/executions/{task_id}"),
            await call(app, member, "GET", f"/api/v1/executions/{uuid.uuid4()}"),
        )


# --- an administrator of a space on another ----------------------------------------------------------------------------------------


async def test_an_administrator_of_a_space_administers_nothing_of_another(app, spaces):
    a, b = spaces
    slug, delivery = f"orbit-{uuid.uuid4().hex[:6]}", f"delivery-{uuid.uuid4().hex}"
    async with db.session_scope() as session:
        owner = b["owner"].user_id
        event_row = OrbitEvent(
            delivery_id=delivery,
            type="document.forgotten",
            project_slug=slug,
            target_type="document",
            target_id="d",
            workspace_id=b.id,
        )
        reference = ContextRetrievalReference(user_id=owner, project_slug=slug, max_classification=1, items=[], workspace_id=b.id)
        session.add_all(
            [
                event_row,
                reference,
                ForgetRequest(scope="project", target=slug, workspace_id=b.id),
                ForgeOutbox(
                    task_id=str(uuid.uuid4()), idempotency_key=f"nova-task:{uuid.uuid4()}", status="pending", workspace_id=b.id
                ),
            ]
        )
        await session.flush()
        event_id, reference_id = event_row.id, reference.id
    admin = a["admin"]
    listing = await call(app, admin, "GET", "/api/v1/admin/orbit-events")
    assert listing.status_code == 200 and delivery not in listing.text
    same_as_unknown(
        await call(app, admin, "POST", f"/api/v1/admin/orbit-events/{event_id}/replay"),
        await call(app, admin, "POST", f"/api/v1/admin/orbit-events/{uuid.uuid4()}/replay"),
    )
    assert slug not in (await call(app, admin, "GET", "/api/v1/admin/forget")).text
    erased = await call(app, admin, "POST", "/api/v1/admin/forget", json={"scope": "project", "project_slug": slug})
    assert erased.status_code == 200 and erased.json()["effects"]["references"] == 0  # B's references are not A's to erase
    outbox = (await call(app, admin, "GET", "/api/v1/admin/forge-outbox")).json()
    assert outbox["pending"] == 0 and outbox["failed"] == 0  # B's waiting capture is not counted for A
    async with db.session_scope() as session:
        assert await session.get(ContextRetrievalReference, reference_id) is not None
    for path in ("/api/v1/admin/orbit-events", "/api/v1/admin/forge-outbox"):  # B's own administrator does see them
        seen = await call(app, b["admin"], "GET", path)
        assert seen.status_code == 200
    assert delivery in (await call(app, b["admin"], "GET", "/api/v1/admin/orbit-events")).text


# --- background work -----------------------------------------------------------------------------------------------------------------


async def test_a_run_started_with_a_token_and_its_background_work_stay_in_the_space(app, spaces, llm, orbit, forge):
    from nova.domain.outputs import IntentClassification

    a, b = spaces
    llm.intent = lambda m: IntentClassification(
        kind="run_workflow", goal="PRD", candidate_skill_ids=["prd"], context_query="exports"
    )
    conversation = (await call(app, b["editor"], "POST", "/api/v1/conversations", json={})).json()["id"]
    sent = await call(
        app,
        b["editor"],
        "POST",
        f"/api/v1/conversations/{conversation}/messages",
        json={"text": "Create a PRD", "project_id": str(b.projects[0])},
    )
    assert sent.status_code == 202, sent.text
    task_id = uuid.UUID(sent.json()["task"]["id"])
    async with db.session_scope() as session:
        task = await session.get(Task, task_id)
        assert task.status == "completed" and task.workspace_id == b.id and task.project_id == b.projects[0]
        produced = (await session.scalars(select(Artifact).where(Artifact.task_id == task_id))).all()
        assert produced and {x.workspace_id for x in produced} == {b.id}
    for member in a.members.values():
        same_as_unknown(
            await call(app, member, "GET", f"/api/v1/executions/{task_id}"),
            await call(app, member, "GET", f"/api/v1/executions/{uuid.uuid4()}"),
        )
        same_as_unknown(
            await call(app, member, "GET", f"/api/v1/executions/{task_id}/events"),
            await call(app, member, "GET", f"/api/v1/executions/{uuid.uuid4()}/events"),
        )


# --- the matrix would notice a missing filter ----------------------------------------------------------------------------------------


async def test_the_matrix_fails_when_the_filter_is_removed(app, spaces):
    """Acceptance criterion of NOV-110: without the workspace filter a foreign read succeeds, so the cases above fail."""
    a, b = spaces
    artifact = a.artifacts[(0, 1)]
    assert (await call(app, b["admin"], "GET", f"/api/v1/artifacts/{artifact}")).status_code == 404
    event.remove(Session, "do_orm_execute", scope._filter_by_workspace)
    try:
        leaked = await call(app, b["admin"], "GET", f"/api/v1/artifacts/{artifact}")
        assert leaked.status_code == 200 and leaked.json()["title"] == a.title(0, 1)  # what the matrix exists to catch
    finally:
        event.listen(Session, "do_orm_execute", scope._filter_by_workspace)
    assert (await call(app, b["admin"], "GET", f"/api/v1/artifacts/{artifact}")).status_code == 404

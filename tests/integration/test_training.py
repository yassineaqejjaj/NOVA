"""FORGE training loop end to end with an in-memory FORGE (no network): cycle, promotion, rollback, API, protocol."""

from __future__ import annotations

import itertools
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from nova.config import get_settings
from nova.domain.agents import AgentProfile
from nova.infra import db
from nova.infra.models import AgentPolicy, TrainingCycle, User
from nova.integrations.forge.client import ForgeError
from nova.services import learning, providers, training
from nova.skills.registry import get_skill_registry
from nova_api.main import create_app


class FakeForge:
    """The FORGE endpoints the training loop uses, with scripted run results and experiment outcome."""

    def __init__(self) -> None:
        self.ids = itertools.count(1)
        self.agents: dict[str, dict[str, Any]] = {}
        self.versions: dict[str, list[dict[str, Any]]] = {}
        self.scenarios: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.experiments: dict[str, dict[str, Any]] = {}
        self.run_status = "pending"
        self.recommendations: dict[str, list[dict[str, Any]]] = {
            "prd": [
                {"category": "output_format", "priority": "p0", "title": "Quantify every goal", "description": ""},
                {"category": "retrieval", "priority": "p1", "title": "Retrieve customer interviews", "description": ""},
            ]
        }
        self.experiment_status = "running"
        self.recommendation = "ship"
        self.cancelled: list[str] = []

    def _id(self) -> str:
        return str(uuid.UUID(int=next(self.ids)))

    async def find_agent(self, slug: str) -> dict[str, Any] | None:
        return self.agents.get(slug)

    async def create_agent(self, body: dict[str, Any]) -> dict[str, Any]:
        agent = {"id": self._id(), **body}
        self.agents[body["slug"]] = agent
        return agent

    async def list_agent_versions(self, agent_id: str) -> list[dict[str, Any]]:
        return self.versions.get(agent_id, [])

    async def create_agent_version(self, agent_id: str, body: dict[str, Any]) -> dict[str, Any]:
        hashed = ("adapter_config", "budget", "model", "endpoint", "system_prompt")  # like FORGE's content hash
        if any(all(v.get(k) == body.get(k) for k in hashed) for v in self.versions.get(agent_id, [])):
            raise ForgeError(409, "identical version")
        version = {"id": self._id(), **body}
        self.versions.setdefault(agent_id, []).append(version)
        return version

    async def find_scenario(self, slug: str) -> dict[str, Any] | None:
        return self.scenarios.get(slug)

    async def create_scenario(self, body: dict[str, Any]) -> dict[str, Any]:
        scenario = {"id": self._id(), **body}
        self.scenarios[body["slug"]] = scenario
        return scenario

    def skill_of(self, scenario_id: str) -> str:
        return next(s["content"]["input"]["nova_skill"] for s in self.scenarios.values() if s["id"] == scenario_id)

    async def create_runs(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        created = []
        for scenario_id in body["scenario_ids"]:
            run = {
                "id": self._id(),
                "scenario_id": scenario_id,
                "agent_version_id": body["agent_version_id"],
                "tags": body["tags"],
            }
            self.runs[run["id"]] = run
            created.append(run)
        return created

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return {**self.runs[run_id], "status": self.run_status, "composite_score": 0.72}

    async def run_feedback(self, run_id: str) -> dict[str, Any] | None:
        skill = self.skill_of(self.runs[run_id]["scenario_id"])
        return {"id": f"report-{run_id}", "weaknesses": ["Vague goals"], "recommendations": self.recommendations.get(skill, [])}

    async def create_experiment(self, body: dict[str, Any]) -> dict[str, Any]:
        experiment = {"id": self._id(), **body}
        self.experiments[experiment["id"]] = experiment
        return experiment

    async def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        return {**self.experiments[experiment_id], "status": self.experiment_status}

    async def experiment_comparison(self, experiment_id: str) -> dict[str, Any]:
        scenario_id = self.experiments[experiment_id]["scenario_ids"][0]
        return {
            "recommendation": {"recommendation": self.recommendation, "summary": "Candidate is better."},
            "composite": {"baseline_mean": 0.72, "candidate_mean": 0.78, "delta": 0.06},
            "regressions": [],
            "improvements": [{"scenario_id": scenario_id, "slug": "x"}],
        }

    async def cancel_experiment(self, experiment_id: str) -> None:
        self.cancelled.append(experiment_id)


@pytest.fixture
def fake_forge(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "forge_api_key", "fgk_test")
    monkeypatch.setattr(settings, "forge_credential_id", str(uuid.uuid4()))
    monkeypatch.setattr(settings, "forge_nova_endpoint", "http://nova-api.test")
    forge = FakeForge()
    providers.override("forge_client", forge)
    return forge


@pytest_asyncio.fixture(autouse=True)
async def clean_training():
    async def wipe() -> None:
        async with db.session_scope() as session:
            await session.execute(delete(TrainingCycle))
            await session.execute(delete(AgentPolicy))
        learning.invalidate()

    await wipe()
    yield
    await wipe()


async def _cycle(cycle_id: uuid.UUID) -> TrainingCycle:
    async with db.session_scope() as session:
        cycle = await session.get(TrainingCycle, cycle_id)
        assert cycle is not None
        return cycle


async def _start(profile: AgentProfile = AgentProfile.product) -> uuid.UUID:
    async with db.session_scope() as session:
        return (await training.start_cycle(session, profile)).id


async def test_cycle_learns_on_every_skill_and_promotes_when_forge_validates(fake_forge):
    cycle_id = await _start()
    product_skills = training.agent_skills(get_skill_registry(), AgentProfile.product)

    assert await training.advance(cycle_id)  # queued → evaluating
    cycle = await _cycle(cycle_id)
    assert cycle.status == "evaluating"
    assert {s["id"] for s in cycle.skills} == {s.id for s in product_skills}  # every service of the agent
    assert len(fake_forge.runs) == len(product_skills)
    agent = fake_forge.agents["nova-product"]
    baseline = fake_forge.versions[agent["id"]][0]
    assert baseline["adapter_config"]["nova_agent_id"] == "nova-product" and baseline["credential_id"]
    assert baseline["endpoint"] == "http://nova-api.test"

    assert not await training.advance(cycle_id)  # FORGE still running: nothing happens

    fake_forge.run_status = "completed"
    assert await training.advance(cycle_id)  # evaluating → experimenting
    cycle = await _cycle(cycle_id)
    assert cycle.status == "experimenting" and cycle.result["changed_skills"] == ["prd"]
    async with db.session_scope() as session:
        candidate = await session.get(AgentPolicy, cycle.candidate_policy_id)
        assert candidate.status == "candidate" and candidate.version == 1
        assert candidate.skills == {"prd": ["Quantify every goal"]}
        assert candidate.recommendations[0]["category"] == "retrieval"  # kept for the team, not applied
    experiment = fake_forge.experiments[cycle.forge_experiment_id]
    assert experiment["baseline_version_id"] == baseline["id"]
    assert experiment["candidate_version_id"] != baseline["id"]
    assert len(experiment["scenario_ids"]) == len(product_skills)  # no regression allowed on the other Skills

    assert not await training.advance(cycle_id)  # experiment running
    fake_forge.experiment_status = "completed"
    assert await training.advance(cycle_id)
    cycle = await _cycle(cycle_id)
    assert cycle.status == "promoted" and cycle.result["decision"]["promote"]
    async with db.session_scope() as session:
        snapshot = await learning.snapshot(session)
    assert snapshot["product"]["version"] == 1 and snapshot["product"]["skills"]["prd"] == ["Quantify every goal"]

    async with db.session_scope() as session:
        previous = await training.rollback(session, AgentProfile.product, None)
    assert previous.version == 0
    async with db.session_scope() as session:
        assert (await learning.snapshot(session))["product"]["skills"] == {}


async def test_rejected_candidate_keeps_the_active_policy(fake_forge):
    fake_forge.run_status, fake_forge.experiment_status, fake_forge.recommendation = "completed", "completed", "do_not_ship"
    cycle_id = await _start()
    for _ in range(3):
        await training.advance(cycle_id)
    cycle = await _cycle(cycle_id)
    assert cycle.status == "rejected" and not cycle.result["decision"]["promote"]
    async with db.session_scope() as session:
        policies = {p.version: p.status for p in (await session.scalars(select(AgentPolicy))).all()}
    assert policies == {0: "active", 1: "rejected"}


async def test_nothing_to_learn_ends_without_experiment(fake_forge):
    fake_forge.run_status, fake_forge.recommendations = "completed", {}
    cycle_id = await _start(AgentProfile.design)
    await training.advance(cycle_id)
    assert await training.advance(cycle_id)
    cycle = await _cycle(cycle_id)
    assert cycle.status == "no_change" and cycle.forge_experiment_id is None and not fake_forge.experiments


async def test_one_open_cycle_per_agent_and_configuration_required(fake_forge, monkeypatch):
    await _start()
    async with db.session_scope() as session:
        with pytest.raises(training.TrainingError) as conflict:
            await training.start_cycle(session, AgentProfile.product)
    assert conflict.value.code == "conflict"
    monkeypatch.setattr(get_settings(), "forge_credential_id", "")
    assert "NOVA_FORGE_CREDENTIAL_ID" in training.missing_configuration()


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def _client(app, *, admin: bool) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    assert (await client.post("/api/v1/auth/dev-login", json={"email": email, "name": "Yassine"})).status_code == 200
    if admin:
        async with db.session_scope() as session:
            user = await session.scalar(select(User).where(User.email == email))
            user.is_admin = True
    return client


async def test_training_api_is_readable_by_all_and_managed_by_admins(app, fake_forge):
    member = await _client(app, admin=False)
    overview = (await member.get("/api/v1/training")).json()
    assert {a["agent"] for a in overview["agents"]} == {p.value for p in AgentProfile}
    assert overview["can_manage"] is False and overview["missing"] == []
    assert (await member.post("/api/v1/training/agents/product/cycles")).status_code == 403

    admin = await _client(app, admin=True)
    started = await admin.post("/api/v1/training/agents/product/cycles")
    assert started.status_code == 201 and started.json()["status"] == "queued"
    assert (await admin.post("/api/v1/training/agents/product/cycles")).status_code == 409
    everyone = (await admin.post("/api/v1/training/cycles")).json()["started"]
    assert {c["agent"] for c in everyone} == {"project", "design", "engineering"}
    detail = (await member.get("/api/v1/training/agents/product")).json()
    assert len(detail["skills"]) == len(training.agent_skills(get_skill_registry(), AgentProfile.product))
    cancelled = await admin.post(f"/api/v1/training/cycles/{started.json()['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert (await member.get("/api/v1/training/agents/unknown")).status_code == 404


async def test_protocol_runs_one_specialist_on_one_skill_with_a_candidate_policy(app, llm):
    async with db.session_scope() as session:
        policy = AgentPolicy(
            agent="product",
            version=3,
            status="candidate",
            standards=["Name the target segment."],
            skills={"prd": ["Quantify every goal"]},
        )
        session.add(policy)
        await session.flush()
        policy_id = str(policy.id)
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.forge_inbound_token}"}
    body = {
        "input": {"prompt": "Write the PRD for offline closing.", "nova_skill": "prd"},
        "context": {"documents": [{"id": "brief", "title": "Brief", "content": "Technicians work offline."}]},
        "budget": {"timeout_seconds": 60},
        "options": {"policy_id": policy_id},
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as forge:
        response = await forge.post("/v1/agents/nova-product/runs", json=body, headers=headers)
        wrong_agent = await forge.post("/v1/agents/nova-design/runs", json={**body, "options": {}}, headers=headers)
        unknown = await forge.post("/v1/agents/nova-sales/runs", json=body, headers=headers)
    data = response.json()
    assert response.status_code == 200 and data.get("error") is None, data
    assert data["metadata"]["nova_agent_id"] == "nova-product"
    assert data["metadata"]["policies"]["product"]["version"] == 3
    assert [s["id"] for s in data["metadata"]["skills"]] == ["prd"]
    step_prompts = [m[0].content for name, m in llm.calls if m and "SKILL INSTRUCTIONS" in m[0].content]
    assert step_prompts and all("Quantify every goal" in p and "Name the target segment." in p for p in step_prompts)
    assert wrong_agent.status_code == 400  # prd belongs to the Product agent
    assert unknown.status_code == 404


async def test_a_changed_configuration_registers_a_new_forge_version(fake_forge, monkeypatch):
    registry = get_skill_registry()
    settings = get_settings()
    async with db.session_scope() as session:
        policy = await learning.ensure_base_policy(session, AgentProfile.engineering)
        first = await training.forge_version_id(fake_forge, policy, settings, registry)
        assert await training.forge_version_id(fake_forge, policy, settings, registry) == first  # cached
        monkeypatch.setattr(settings, "training_run_timeout_seconds", 900)
        second = await training.forge_version_id(fake_forge, policy, settings, registry)
    assert second != first  # baseline and candidate must always share the same budget, model and catalog
    versions = fake_forge.versions[fake_forge.agents["nova-engineering"]["id"]]
    assert [v["budget"]["timeout_seconds"] for v in versions] == [600, 900]


async def test_cycles_are_manual_by_default(fake_forge, monkeypatch):
    assert get_settings().training_interval_days == 0
    assert await training.start_due_cycles() == 0  # nothing starts on its own
    monkeypatch.setattr(get_settings(), "training_interval_days", 7)
    assert await training.start_due_cycles() == len(AgentProfile)  # opt-in schedule: one cycle per agent

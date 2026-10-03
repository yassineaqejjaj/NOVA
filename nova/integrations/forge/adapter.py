"""``EvaluationSink`` implemented on FORGE (integration-analysis §2.7).

* registers NOVA as a FORGE agent with one immutable version per NOVA release × model × Skill catalog;
* captures production executions as scenario + replay run (FORGE calls NOVA back through the NOVA
  Agent Protocol and evaluates) — gap G-F1 documents the observed-run extension;
* forwards user feedback as a human evaluation on ``ux.perceived_usefulness``.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from nova.config import Settings
from nova.domain.evaluation import ExecutionRecord, FeedbackRecord
from nova.domain.outputs import EvaluationReference
from nova.infra.db import session_scope
from nova.infra.models import IntegrationReference
from nova.integrations.forge import mapper
from nova.integrations.forge.client import ForgeClient, ForgeError
from nova.skills.registry import SkillRegistry

log = logging.getLogger(__name__)


class ForgeEvaluationSink:
    def __init__(
        self,
        settings: Settings,
        skills: SkillRegistry,
        model: str,
        client: ForgeClient | None = None,
        *,
        nova_inbound_url: str | None = None,
        credential_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.skills = skills
        self.model = model
        self.client = client or ForgeClient(
            settings.forge_base_url, settings.forge_api_key, timeout=settings.forge_timeout_seconds
        )
        self.nova_inbound_url = nova_inbound_url or settings.public_url.replace(":3200", ":8200")
        self.credential_id = credential_id

    @property
    def enabled(self) -> bool:
        return bool(self.settings.forge_api_key)

    async def agent_version_id(self) -> str:
        """Find or register the FORGE agent version of this NOVA release (cached in integration_references)."""
        digest = self.skills.catalog_digest()
        release = mapper.release_label(self.settings.version, self.model, digest)
        async with session_scope() as session:
            cached = await session.scalar(
                select(IntegrationReference).where(
                    IntegrationReference.system == "forge",
                    IntegrationReference.kind == "agent_version",
                    IntegrationReference.nova_type == "release",
                    IntegrationReference.nova_id == f"{release}|{self.model}",
                )
            )
            if cached:
                return cached.external_id
        agent = await self.client.find_agent(mapper.AGENT_SLUG) or await self.client.create_agent(mapper.agent_body())
        body = mapper.agent_version_body(
            nova_version=self.settings.version,
            model=self.model,
            catalog_digest=digest,
            skills=self.skills.all(),
            nova_base_url=self.nova_inbound_url,
            credential_id=self.credential_id,
        )
        try:
            version = await self.client.create_agent_version(str(agent["id"]), body)
        except ForgeError as exc:
            if exc.status != 409:
                raise
            versions = await self.client.list_agent_versions(str(agent["id"]))
            version = next((v for v in versions if v.get("version") == body["version"]), None)
            if version is None:
                raise
        async with session_scope() as session:
            session.add(
                IntegrationReference(
                    system="forge",
                    kind="agent_version",
                    nova_type="release",
                    nova_id=f"{release}|{self.model}",
                    external_id=str(version["id"]),
                    data={"agent_id": str(agent["id"]), "release": release},
                )
            )
        return str(version["id"])

    async def capture(self, record: ExecutionRecord) -> EvaluationReference | None:
        if not self.enabled:
            return None
        version_id = await self.agent_version_id()
        scenario = await self.client.create_scenario(mapper.scenario_body(record))
        runs = await self.client.create_runs(mapper.run_body(version_id, str(scenario["id"]), record))
        run = runs[0] if runs else {}
        return EvaluationReference(
            scenario_id=str(scenario["id"]),
            run_id=str(run.get("id")) if run else None,
            status=run.get("status"),
            url=f"{self.settings.forge_public_url.rstrip('/')}/runs/{run.get('id')}" if run else None,
        )

    async def refresh(self, reference: EvaluationReference) -> EvaluationReference:
        if not self.enabled or not reference.run_id:
            return reference
        run = await self.client.get_run(reference.run_id)
        return reference.model_copy(
            update={"status": run.get("status"), "composite_score": run.get("composite_score"), "passed": run.get("passed")}
        )

    async def feedback(self, reference: EvaluationReference, feedback: FeedbackRecord) -> None:
        if not self.enabled or not reference.run_id:
            return
        await self.client.human_evaluation(
            reference.run_id, mapper.usefulness_evaluation(feedback.rating == "useful", feedback.comment)
        )

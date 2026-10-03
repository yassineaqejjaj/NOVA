"""NOVA demo data (NOVA-side objects only — ORBIT context is never faked).

    python -m nova.seed            # idempotent
    python -m nova.seed --reset    # remove the demo user's NOVA data first

Creates Yassine (Head of AI), the NOVA / ORBIT / FORGE projects (linked to ORBIT slugs of the same
name: context appears only if those projects exist in ORBIT), example conversations, tasks, Skill
executions and Artifacts. Seeded Artifacts carry no citations because no ORBIT retrieval happened.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import timedelta

from sqlalchemy import delete, select

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.artifacts import ArtifactContent, ArtifactItem, SectionContent, TextBlock, empty_content
from nova.domain.enums import SectionKind
from nova.infra import db
from nova.infra.db import utcnow
from nova.infra.models import (
    Artifact,
    ArtifactVersion,
    Conversation,
    Message,
    MessageBlock,
    Project,
    ProjectMember,
    ProjectReference,
    SkillExecution,
    Task,
    TaskStep,
    User,
    UserPreferences,
)
from nova.skills.registry import get_skill_registry

DEMO_EMAIL = "yassine@orion.local"
PROJECTS = [
    ("nova", "NOVA", "Personal AI Product Agent"),
    ("orbit", "ORBIT", "Governed context and memory for AI agents"),
    ("forge", "FORGE", "AI Evaluation Platform"),
]


def text(*paragraphs: str) -> SectionContent:
    return SectionContent(kind=SectionKind.rich_text, blocks=[TextBlock(text=p) for p in paragraphs])


def items(kind: str, *rows: dict) -> SectionContent:
    return SectionContent(kind=SectionKind.items, items=[ArtifactItem(kind=kind, **row) for row in rows])


def story(
    id_: str,
    parent: str,
    title: str,
    as_a: str,
    i_want: str,
    so_that: str,
    ac: list[tuple[str, str, str]] | None,
    priority: str = "should",
) -> dict:
    attributes: dict = {"as_a": as_a, "i_want": i_want, "so_that": so_that, "priority": priority, "status": "draft"}
    if ac:
        attributes["acceptance_criteria"] = [{"given": g, "when": w, "then": t} for g, w, t in ac]
    return {"id": id_, "parent_id": parent, "title": title, "attributes": attributes}


def forge_backlog() -> ArtifactContent:
    content = empty_content(get_artifact_registry().get("backlog"), "Backlog · FORGE Beta")
    content.sections.update(
        summary=text(
            "Backlog derived from the FORGE vision: make every agent release measurably better before it ships.",
            "Scope: the Beta, focused on regression detection and explainable scores for product agents.",
        ),
        objectives=items(
            "objective",
            {
                "id": "obj-regressions",
                "title": "No agent release ships with an undetected regression",
                "attributes": {"timeframe": "Beta"},
            },
            {
                "id": "obj-trust",
                "title": "Product teams trust FORGE scores enough to gate releases on them",
                "attributes": {"timeframe": "Beta"},
            },
        ),
        initiatives=items(
            "initiative",
            {
                "id": "ini-ci-gate",
                "parent_id": "obj-regressions",
                "title": "CI release gate",
                "attributes": {
                    "expected_impact": "Regressions blocked before deployment",
                    "confidence": "high",
                    "status": "planned",
                },
            },
            {
                "id": "ini-explain",
                "parent_id": "obj-trust",
                "title": "Explainable scores",
                "attributes": {
                    "expected_impact": "Scores traceable to criteria, judges and trace steps",
                    "confidence": "medium",
                    "status": "planned",
                },
            },
        ),
        epics=items(
            "epic",
            {
                "id": "epic-gate",
                "parent_id": "ini-ci-gate",
                "title": "Experiment gate in CI",
                "attributes": {"value": "Teams block a deployment when the candidate regresses", "priority": "must"},
            },
            {
                "id": "epic-provenance",
                "parent_id": "ini-explain",
                "title": "Score provenance",
                "attributes": {"value": "Every score links to its criterion, judge and evidence", "priority": "must"},
            },
        ),
        stories=items(
            "story",
            story(
                "story-gate-cli",
                "epic-gate",
                "Fail the pipeline on regression",
                "release engineer",
                "the CLI to exit non-zero when an experiment recommends do_not_ship",
                "regressions never reach production",
                [
                    (
                        "an experiment with a critical regression",
                        "the CI runs the gate command",
                        "the job fails with the regressions listed",
                    )
                ],
                "must",
            ),
            story(
                "story-gate-report",
                "epic-gate",
                "Readable gate report",
                "product manager",
                "a summary of gains and regressions per scenario",
                "I can decide quickly whether to ship",
                None,
            ),
            story(
                "story-prov-criterion",
                "epic-provenance",
                "Trace a score to its criterion",
                "evaluator",
                "to open the criterion, judge and evidence behind a score",
                "I can challenge a judgement",
                None,
            ),
            story(
                "story-prov-human",
                "epic-provenance",
                "Compare AI and human scores",
                "evaluator",
                "to see where judges disagree with human reviewers",
                "I know which judges to calibrate",
                None,
            ),
        ),
        risks=items(
            "risk",
            {
                "id": "risk-flaky",
                "title": "Judge variance creates flaky gates",
                "attributes": {
                    "likelihood": "medium",
                    "impact": "high",
                    "mitigation": "Repetitions and noise-aware regression thresholds",
                },
            },
        ),
        questions=items(
            "question",
            {
                "id": "q-threshold",
                "title": "Which regression threshold should block a release by default?",
                "attributes": {"owner": "Head of AI", "status": "open"},
            },
        ),
    )
    return content


def evaluation_prd() -> ArtifactContent:
    content = empty_content(get_artifact_registry().get("prd"), "PRD · Scheduled evaluation exports")
    content.sections.update(
        summary=text("Let teams schedule exports of FORGE evaluation results to share them with stakeholders."),
        problem=text(
            "Product managers rebuild evaluation summaries by hand every week; results are shared late and inconsistently."
        ),
        objectives=items(
            "objective", {"id": "obj-share", "title": "Weekly evaluation results reach stakeholders without manual work"}
        ),
        functional_requirements=items(
            "requirement",
            {
                "id": "req-schedule",
                "title": "Schedule an export",
                "description": "Daily or weekly, per benchmark",
                "rationale": "Proposed from the user's request",
                "attributes": {"type": "functional", "priority": "must"},
            },
            {"id": "req-format", "title": "CSV and Markdown formats", "attributes": {"type": "functional", "priority": "should"}},
        ),
        metrics=items(
            "metric",
            {
                "id": "metric-adoption",
                "title": "Teams with a scheduled export",
                "attributes": {"definition": "Share of active teams with ≥1 schedule", "type": "success"},
            },
        ),
        open_questions=items(
            "question",
            {"id": "q-dest", "title": "Which destinations are allowed (email, storage)?", "attributes": {"status": "open"}},
        ),
    )
    return content


async def reset(session) -> None:
    user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
    if user:
        await session.execute(delete(Artifact).where(Artifact.owner_id == user.id))
        await session.execute(delete(Task).where(Task.user_id == user.id))
        await session.execute(delete(Conversation).where(Conversation.user_id == user.id))


async def seed() -> None:
    db.configure()
    registry = get_skill_registry()
    async with db.session_scope() as session:
        if "--reset" in sys.argv:
            await reset(session)
        user = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                subject=f"seed:{DEMO_EMAIL}",
                email=DEMO_EMAIL,
                display_name="Yassine",
                title="Head of AI",
                realm_roles=["nova-user", "nova-admin"],
                is_admin=True,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserPreferences(
                    user_id=user.id,
                    role="Head of AI",
                    teams=["AI Platform", "Product"],
                    preferred_methods=["RICE", "Jobs To Be Done", "Story Mapping"],
                    default_autonomy="assist",
                    onboarding_completed_at=utcnow(),
                )
            )
        projects: dict[str, Project] = {}
        for slug, name, description in PROJECTS:
            project = await session.scalar(select(Project).where(Project.slug == slug))
            if project is None:
                project = Project(slug=slug, name=name, description=description, created_by=user.id)
                session.add(project)
                await session.flush()
                session.add(
                    ProjectReference(
                        project_id=project.id,
                        system="orbit",
                        external_id=slug,
                        label=name,
                        url=f"{get_settings().orbit_public_url}/projects/{slug}",
                    )
                )
            if await session.get(ProjectMember, (project.id, user.id)) is None:
                session.add(ProjectMember(project_id=project.id, user_id=user.id, role="owner", source="nova"))
            projects[slug] = project
        await session.flush()

        if await session.scalar(select(Artifact.id).where(Artifact.owner_id == user.id)):
            print("Demo data already present (use --reset to recreate).")
            return

        forge = projects["forge"]
        now = utcnow()
        # 1. Vision → Backlog (completed, with Skill execution and Artifact)
        conversation = Conversation(user_id=user.id, project_id=forge.id, title="Turn the FORGE vision into a backlog")
        session.add(conversation)
        await session.flush()
        ask = Message(
            conversation_id=conversation.id,
            role="user",
            meta={"text": "Help me turn the FORGE vision into a backlog.", "seed": True},
        )
        reply = Message(conversation_id=conversation.id, role="nova", meta={"seed": True})
        session.add_all([ask, reply])
        await session.flush()
        skill = registry.get("vision-to-backlog")
        task = Task(
            user_id=user.id,
            project_id=forge.id,
            conversation_id=conversation.id,
            message_id=reply.id,
            objective="Help me turn the FORGE vision into a backlog.",
            status="completed",
            phase="completed",
            phase_label="Completed",
            progress_done=1,
            progress_total=1,
            input={"seed": True},
            created_at=now - timedelta(days=1, hours=2),
            started_at=now - timedelta(days=1, hours=2),
            finished_at=now - timedelta(days=1, hours=1, minutes=58),
            model="seed",
        )
        session.add(task)
        await session.flush()
        reply.task_id = task.id
        execution = SkillExecution(
            task_id=task.id,
            step_key="1-backlog",
            skill_id=skill.id,
            skill_version=skill.version,
            status="completed",
            input={"intent": ask.meta["text"]},
            model="seed",
            duration_ms=0,
        )
        session.add(execution)
        await session.flush()
        backlog = forge_backlog()
        artifact = Artifact(
            type="backlog",
            title=backlog.title,
            project_id=forge.id,
            owner_id=user.id,
            conversation_id=conversation.id,
            task_id=task.id,
            current_version=1,
            classification=1,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            ArtifactVersion(
                artifact_id=artifact.id,
                version=1,
                content=backlog.model_dump(mode="json"),
                changed_sections=list(backlog.sections),
                author_type="nova",
                skill_execution_id=execution.id,
                task_id=task.id,
                summary="Demo backlog (seed data)",
                state="current",
            )
        )
        session.add(
            TaskStep(
                task_id=task.id,
                position=0,
                step_key="1-backlog",
                title="Turn the vision into a backlog",
                skill_id=skill.id,
                skill_version=skill.version,
                status="completed",
                artifact_id=artifact.id,
                detail="Saved v1",
            )
        )
        session.add_all(
            [
                MessageBlock(
                    message_id=reply.id,
                    key="text",
                    position=0,
                    type="text",
                    payload={"markdown": f"Created **{backlog.title}** (v1). Demo data: no ORBIT context was used."},
                ),
                MessageBlock(
                    message_id=reply.id,
                    key=f"artifact-{artifact.id}",
                    position=1,
                    type="artifact",
                    payload={
                        "artifact_id": str(artifact.id),
                        "type": "backlog",
                        "type_name": "Backlog",
                        "icon": "kanban",
                        "title": backlog.title,
                        "version": 1,
                        "created": True,
                        "status": "current",
                        "changed_titles": [],
                        "summary": "Demo backlog",
                        "classification": 1,
                    },
                ),
            ]
        )

        # 2. A PRD with a user edit (version history)
        prd = evaluation_prd()
        prd_artifact = Artifact(type="prd", title=prd.title, project_id=forge.id, owner_id=user.id, current_version=2)
        session.add(prd_artifact)
        await session.flush()
        session.add(
            ArtifactVersion(
                artifact_id=prd_artifact.id,
                version=1,
                content=prd.model_dump(mode="json"),
                changed_sections=list(prd.sections),
                author_type="nova",
                summary="Demo PRD (seed data)",
                state="superseded",
            )
        )
        edited = prd.model_copy(deep=True)
        edited.sections["summary"] = text(
            "Let teams schedule exports of FORGE evaluation results (CSV, Markdown) for stakeholders."
        )
        session.add(
            ArtifactVersion(
                artifact_id=prd_artifact.id,
                version=2,
                content=edited.model_dump(mode="json"),
                changed_sections=["summary"],
                author_type="user",
                author_id=user.id,
                summary="Edited summary",
                state="current",
            )
        )

        # 3. Scheduled work: real execution tomorrow morning (picked up by the scheduler)
        sprint_conv = Conversation(user_id=user.id, project_id=forge.id, title="Prepare FORGE Sprint 19")
        session.add(sprint_conv)
        await session.flush()
        sprint_reply = Message(conversation_id=sprint_conv.id, role="nova", meta={"seed": True})
        session.add_all(
            [
                Message(conversation_id=sprint_conv.id, role="user", meta={"text": "Prepare Sprint 19.", "seed": True}),
                sprint_reply,
            ]
        )
        await session.flush()
        tomorrow = (now + timedelta(days=1)).replace(hour=7, minute=30, second=0, microsecond=0)
        session.add(
            Task(
                user_id=user.id,
                project_id=forge.id,
                conversation_id=sprint_conv.id,
                message_id=sprint_reply.id,
                objective="Prepare Sprint 19.",
                status="scheduled",
                scheduled_for=tomorrow,
                origin="scheduled",
                input={
                    "conversation_id": str(sprint_conv.id),
                    "message_id": str(sprint_reply.id),
                    "project_id": str(forge.id),
                    "project_slug": "forge",
                    "origin": "scheduled",
                    "autonomy": "assist",
                    "intent": "Prepare Sprint 19.",
                    "skill_refs": ["sprint-planning"],
                    "context_mode": "auto",
                    "preferences": {"nova_name": "NOVA", "role": "Head of AI"},
                },
            )
        )
    print(f"Seeded NOVA demo data for {DEMO_EMAIL} (projects: {', '.join(p[1] for p in PROJECTS)}).")
    await db.engine().dispose()


if __name__ == "__main__":
    asyncio.run(seed())

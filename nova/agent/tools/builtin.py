"""Built-in tools available to Skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nova.agent.tools.registry import RetryPolicy, ToolContext, ToolDefinition, ToolDenied, ToolRegistry
from nova.artifacts.render import render_markdown
from nova.domain.context import ContextItem, ContextQuery
from nova.domain.permissions import Permission


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=8, ge=1, le=20)


class SearchHitOut(BaseModel):
    title: str
    snippet: str
    source_kind: str | None = None
    ref_id: str


class SearchOut(BaseModel):
    results: list[SearchHitOut]


class RetrieveIn(BaseModel):
    query: str = Field(min_length=2, max_length=2000)
    token_budget: int = Field(default=2500, ge=500, le=8000)


class RetrieveOut(BaseModel):
    """The execute_tools node merges ``items`` into the state (relabelled) and records the reference."""

    retrieval_id: str | None
    items: list[ContextItem]
    warnings: list[str] = Field(default_factory=list)


class ArtifactIn(BaseModel):
    artifact_id: str


class ArtifactOut(BaseModel):
    artifact_id: str
    type: str
    title: str
    version: int
    markdown: str


class ListArtifactsIn(BaseModel):
    limit: int = Field(default=10, ge=1, le=25)


class ArtifactLine(BaseModel):
    artifact_id: str
    type: str
    title: str
    version: int


class ListArtifactsOut(BaseModel):
    artifacts: list[ArtifactLine]


class ProposeDecisionIn(BaseModel):
    kind: Literal["decision", "requirement", "constraint", "risk", "fact"] = "decision"
    title: str = Field(min_length=3, max_length=300)
    content: str = Field(min_length=3, max_length=4000)


class ExternalWriteOut(BaseModel):
    external_id: str
    status: str


class PublishArtifactIn(BaseModel):
    artifact_id: str


def _require_project(ctx: ToolContext) -> str:
    if not ctx.state.project_slug:
        raise ToolDenied("No project context: choose a project first")
    return ctx.state.project_slug


async def search_orbit(ctx: ToolContext, args: SearchIn) -> SearchOut:
    slug = _require_project(ctx)
    hits = await ctx.deps.context.search(ctx.state.user_id, slug, args.query, args.limit)
    return SearchOut(
        results=[SearchHitOut(title=h.title, snippet=h.snippet[:400], source_kind=h.source_kind, ref_id=h.ref_id) for h in hits]
    )


async def retrieve_orbit_context(ctx: ToolContext, args: RetrieveIn) -> RetrieveOut:
    """Targeted retrieval; the nodes merge the new items into the state with fresh labels."""
    slug = _require_project(ctx)
    bundle = await ctx.deps.context.retrieve(
        ContextQuery(
            user_id=ctx.state.user_id,
            project_slug=slug,
            task=args.query,
            token_budget=args.token_budget,
            session_id=ctx.state.conversation_id,
        )
    )
    return RetrieveOut(retrieval_id=bundle.retrieval_id, items=bundle.items, warnings=bundle.warnings)


async def get_artifact(ctx: ToolContext, args: ArtifactIn) -> ArtifactOut:
    snapshot = await ctx.deps.store.get_artifact(args.artifact_id, ctx.state.user_id)
    if snapshot is None:
        raise ToolDenied("Artifact not found or not accessible")
    markdown = render_markdown(snapshot.content, ctx.deps.artifacts.get(snapshot.type))
    return ArtifactOut(
        artifact_id=snapshot.artifact_id,
        type=snapshot.type,
        title=snapshot.title,
        version=snapshot.version,
        markdown=markdown[:12000],
    )


async def list_artifacts(ctx: ToolContext, args: ListArtifactsIn) -> ListArtifactsOut:
    outlines = await ctx.deps.store.list_artifact_outlines(ctx.state.user_id, project_id=ctx.state.project_id, limit=args.limit)
    return ListArtifactsOut(
        artifacts=[ArtifactLine(artifact_id=o.artifact_id, type=o.type, title=o.title, version=o.version) for o in outlines]
    )


async def propose_orbit_decision(ctx: ToolContext, args: ProposeDecisionIn) -> ExternalWriteOut:
    slug = _require_project(ctx)
    external_id = await ctx.deps.context.propose_memory(
        ctx.state.user_id,
        slug,
        kind=args.kind,
        title=args.title,
        content=args.content,
        source_label=f"NOVA task {ctx.state.task_id}",
    )
    return ExternalWriteOut(external_id=external_id, status="proposed")


async def publish_artifact_to_orbit(ctx: ToolContext, args: PublishArtifactIn) -> ExternalWriteOut:
    slug = _require_project(ctx)
    snapshot = await ctx.deps.store.get_artifact(args.artifact_id, ctx.state.user_id)
    if snapshot is None:
        raise ToolDenied("Artifact not found or not accessible")
    markdown = render_markdown(snapshot.content, ctx.deps.artifacts.get(snapshot.type))
    external_id = await ctx.deps.context.publish_document(
        ctx.state.user_id,
        slug,
        title=snapshot.title,
        content=markdown,
        external_id=f"nova-artifact-{snapshot.artifact_id}",
        classification=max(1, snapshot.classification),
    )
    return ExternalWriteOut(external_id=external_id, status="published")


def register_builtin_tools(registry: ToolRegistry) -> None:
    network_retry = RetryPolicy(max_attempts=2, backoff_seconds=0.5)
    registry.register(
        ToolDefinition(
            name="search_orbit",
            description="Search the project's ORBIT knowledge (documents, tickets, decisions).",
            input_model=SearchIn,
            output_model=SearchOut,
            permission=Permission.context_read,
            handler=search_orbit,
            timeout_seconds=15,
            retry=network_retry,
            audit=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="retrieve_orbit_context",
            description="Ask ORBIT for additional governed context on a specific topic (adds citable items).",
            input_model=RetrieveIn,
            output_model=RetrieveOut,
            permission=Permission.context_read,
            handler=retrieve_orbit_context,
            timeout_seconds=20,
            retry=network_retry,
            audit=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_artifact",
            description="Read one of the user's NOVA Artifacts.",
            input_model=ArtifactIn,
            output_model=ArtifactOut,
            permission=Permission.artifact_read,
            handler=get_artifact,
            timeout_seconds=5,
            audit=False,
        )
    )
    registry.register(
        ToolDefinition(
            name="list_artifacts",
            description="List recent Artifacts of the current project.",
            input_model=ListArtifactsIn,
            output_model=ListArtifactsOut,
            permission=Permission.artifact_read,
            handler=list_artifacts,
            timeout_seconds=5,
            audit=False,
        )
    )
    registry.register(
        ToolDefinition(
            name="propose_orbit_decision",
            description="Propose a decision/requirement to ORBIT project memory (status 'proposed', human validation).",
            input_model=ProposeDecisionIn,
            output_model=ExternalWriteOut,
            permission=Permission.context_write_external,
            handler=propose_orbit_decision,
            timeout_seconds=15,
            audit=True,
            external_write=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="publish_artifact_to_orbit",
            description="Publish an Artifact to ORBIT as a project document so other agents can use it.",
            input_model=PublishArtifactIn,
            output_model=ExternalWriteOut,
            permission=Permission.context_write_external,
            handler=publish_artifact_to_orbit,
            timeout_seconds=20,
            audit=True,
            external_write=True,
        )
    )

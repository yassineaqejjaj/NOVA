"""Built-in tools available to Skills."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from nova.agent.snapshots import retrieve_with_reference
from nova.agent.tools.registry import RetryPolicy, ToolContext, ToolDefinition, ToolDenied, ToolRegistry
from nova.artifacts.render import render_markdown
from nova.domain.context import ContextError, ContextItem, ContextQuery, SnapshotRef
from nova.domain.design import (
    DesignError,
    DesignNode,
    DesignRef,
    ElementSpec,
    ScreenSpec,
    TokenSpec,
    parse_figma_url,
)
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
    snapshot: SnapshotRef | None = None


class ListSnapshotsIn(BaseModel):
    pass


class SnapshotLine(BaseModel):
    name: str
    latest_version: int
    versions: int
    last_task: str = ""


class ListSnapshotsOut(BaseModel):
    snapshots: list[SnapshotLine]


class GetSnapshotIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    version: int | None = Field(default=None, ge=1)


class SnapshotItemLine(BaseModel):
    citation: str
    title: str
    forgotten: bool = False


class GetSnapshotOut(BaseModel):
    name: str
    version: int
    task: str = ""
    token_count: int = 0
    content: str
    items: list[SnapshotItemLine]
    truncated: bool = False


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
    bundle = await retrieve_with_reference(
        ctx.deps,
        ContextQuery(
            user_id=ctx.state.user_id,
            project_slug=slug,
            task=args.query,
            token_budget=args.token_budget,
            session_id=ctx.state.conversation_id,
        ),
    )
    return RetrieveOut(retrieval_id=bundle.retrieval_id, items=bundle.items, warnings=bundle.warnings, snapshot=bundle.snapshot)


def _snapshot_denied(exc: ContextError) -> ToolDenied:
    return ToolDenied(f"ORBIT snapshots unavailable ({exc.code}): {exc.message}"[:300])


async def list_orbit_snapshots(ctx: ToolContext, args: ListSnapshotsIn) -> ListSnapshotsOut:
    slug = _require_project(ctx)
    try:
        found = await ctx.deps.context.list_snapshots(ctx.state.user_id, slug)
    except ContextError as exc:
        raise _snapshot_denied(exc) from exc
    return ListSnapshotsOut(
        snapshots=[
            SnapshotLine(name=s.name, latest_version=s.latest_version, versions=s.versions, last_task=s.last_task[:200])
            for s in found[:50]
        ]
    )


async def get_orbit_snapshot(ctx: ToolContext, args: GetSnapshotIn) -> GetSnapshotOut:
    slug = _require_project(ctx)
    try:
        snap = await ctx.deps.context.get_snapshot(ctx.state.user_id, slug, args.name, args.version)
    except ContextError as exc:
        raise _snapshot_denied(exc) from exc
    return GetSnapshotOut(
        name=snap.name,
        version=snap.version,
        task=snap.task[:300],
        token_count=snap.token_count,
        content=snap.content[:12000],
        items=[SnapshotItemLine(citation=i.citation, title=i.title, forgotten=i.forgotten) for i in snap.items[:100]],
        truncated=len(snap.content) > 12000,
    )


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


# --- Figma (docs/design-figma.md §4) ------------------------------------------------------------------


class FigmaGetDesignIn(BaseModel):
    url: str | None = Field(default=None, max_length=1000)
    file_key: str | None = Field(default=None, max_length=100)
    node_id: str | None = Field(default=None, max_length=50)


class FigmaVariableOut(BaseModel):
    name: str
    type: str = ""
    value: str | float | bool | None = None


class FigmaGetDesignOut(BaseModel):
    file_name: str
    nodes: list[DesignNode]
    variables: list[FigmaVariableOut]
    screenshot_url: str | None = None
    source: Literal["mcp", "rest"]
    truncated: bool = False


class FigmaPushIn(BaseModel):
    artifact_id: str
    file_key: str | None = Field(default=None, max_length=100)


class FigmaPushOut(BaseModel):
    external_id: str
    status: str
    url: str | None = None


def _design(ctx: ToolContext):
    if ctx.deps.design is None:
        raise ToolDenied("Connect Figma in Settings")
    return ctx.deps.design


def _design_error(exc: DesignError) -> ToolDenied:
    hints = {
        "not_connected": "Connect Figma in Settings",
        "forbidden": "Figma refused access: check that your Figma account can open this file",
        "not_found": "Figma file or node not found: check the link",
        "write_unavailable": "Pushing to Figma needs the Figma MCP connection (OAuth); only a read-only token is linked. "
        "The mockups stay available in the NOVA Artifact.",
        "unavailable": "Figma is temporarily unavailable",
    }
    return ToolDenied(f"{hints.get(exc.code, 'Figma error')} ({exc.message})"[:300])


def _scalar(value: object) -> str | float | bool | None:
    if value is None or isinstance(value, (str, float, bool)):
        return value
    if isinstance(value, int):
        return float(value)
    return str(value)[:120]


async def figma_get_design(ctx: ToolContext, args: FigmaGetDesignIn) -> FigmaGetDesignOut:
    design = _design(ctx)
    ref = parse_figma_url(args.url) if args.url else None
    if args.url and ref is None:
        raise ToolDenied("This is not a Figma file link")
    file_key = args.file_key or (ref.file_key if ref else None)
    if not file_key:
        raise ToolDenied("Provide a Figma url or file_key")
    node_id = (args.node_id or (ref.node_id if ref else None) or "").replace("-", ":") or None
    try:
        snapshot = await design.get_design(ctx.state.user_id, DesignRef(file_key=file_key, node_id=node_id, url=args.url))
    except DesignError as exc:
        raise _design_error(exc) from exc
    return FigmaGetDesignOut(
        file_name=snapshot.file_name,
        nodes=snapshot.nodes,
        variables=[FigmaVariableOut(name=v.name, type=v.type, value=_scalar(v.value)) for v in snapshot.variables[:100]],
        screenshot_url=snapshot.screenshot_url,
        source=snapshot.source,
        truncated=snapshot.truncated,
    )


def _split(value: object) -> list[str]:
    return [p.strip() for p in str(value or "").split(",") if p.strip()]


def _int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return default


def _screen_spec(item) -> ScreenSpec:
    attrs = item.attributes
    elements = []
    for raw in attrs.get("elements") or []:
        if not isinstance(raw, dict):
            continue
        elements.append(
            ElementSpec(
                id=str(raw.get("id") or ""),
                type=str(raw.get("type") or "text"),
                label=str(raw.get("label") or ""),
                region=raw.get("region") if raw.get("region") in ("header", "sidebar", "body", "footer") else "body",
                row=_int(raw.get("row"), 0),
                span=min(12, max(1, _int(raw.get("span"), 12))),
                variant=raw.get("variant") or None,
                state=raw.get("state") or None,
            )
        )
    return ScreenSpec(
        id=item.id,
        name=item.title,
        fidelity=attrs.get("fidelity") if attrs.get("fidelity") in ("wireframe", "lowfi", "hifi") else "wireframe",
        device=attrs.get("device") if attrs.get("device") in ("mobile", "tablet", "desktop") else "desktop",
        purpose=str(attrs.get("purpose") or item.description or ""),
        states=_split(attrs.get("states")),
        notes=str(attrs.get("notes") or ""),
        elements=elements,
    )


def _token_spec(item) -> TokenSpec:
    attrs = item.attributes
    category = attrs.get("category")
    return TokenSpec(
        name=item.title,
        category=category if category in ("color", "typography", "spacing", "radius", "shadow") else "color",
        value=str(attrs.get("value") or ""),
        usage=str(attrs.get("usage") or ""),
    )


async def figma_push_screens(ctx: ToolContext, args: FigmaPushIn) -> FigmaPushOut:
    design = _design(ctx)
    snapshot = await ctx.deps.store.get_artifact(args.artifact_id, ctx.state.user_id)
    if snapshot is None:
        raise ToolDenied("Artifact not found or not accessible")
    if snapshot.type != "ui_screens":
        raise ToolDenied("Only 'ui_screens' Artifacts can be pushed to Figma")
    sections = snapshot.content.sections
    screens = [_screen_spec(i) for i in (sections["screens"].items if "screens" in sections else []) if i.kind == "screen"]
    tokens = [_token_spec(i) for i in (sections["tokens"].items if "tokens" in sections else []) if i.kind == "design_token"]
    if not screens:
        raise ToolDenied("This Artifact has no screens to push")
    try:
        result = await design.push_screens(ctx.state.user_id, snapshot.title, screens, tokens, file_key=args.file_key)
    except DesignError as exc:
        raise _design_error(exc) from exc
    return FigmaPushOut(external_id=result.external_id, status=result.status, url=result.url)


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
            name="list_orbit_snapshots",
            description="List the project's ORBIT snapshots (versioned shared contexts): name, latest version, last task.",
            input_model=ListSnapshotsIn,
            output_model=ListSnapshotsOut,
            permission=Permission.context_read,
            handler=list_orbit_snapshots,
            timeout_seconds=15,
            retry=network_retry,
            audit=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="get_orbit_snapshot",
            description="Read one ORBIT snapshot version (markdown content with [S1] citations); 'version' omitted = latest.",
            input_model=GetSnapshotIn,
            output_model=GetSnapshotOut,
            permission=Permission.context_read,
            handler=get_orbit_snapshot,
            timeout_seconds=15,
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
    registry.register(
        ToolDefinition(
            name="figma_get_design",
            description="Read a Figma file or node (structure, variables) from a Figma link; MCP when connected, else REST.",
            input_model=FigmaGetDesignIn,
            output_model=FigmaGetDesignOut,
            permission=Permission.context_read,
            handler=figma_get_design,
            timeout_seconds=60,
            retry=network_retry,
            audit=True,
        )
    )
    registry.register(
        ToolDefinition(
            name="figma_push_screens",
            description="Push the screens and tokens of a 'ui_screens' Artifact to Figma (needs the Figma MCP connection).",
            input_model=FigmaPushIn,
            output_model=FigmaPushOut,
            permission=Permission.context_write_external,
            handler=figma_push_screens,
            timeout_seconds=120,
            audit=True,
            external_write=True,
        )
    )

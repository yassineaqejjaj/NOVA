"""Workspace scope: the one place where "this request only sees its own workspace" is implemented (NOV-107).

ADR 001 §9: every resource belongs to exactly one ``orion_workspace_id``; the workspace of a request comes from the
validated token (or the default workspace while OIDC claims are not read), never from a parameter; a resource of another
workspace answers like one that does not exist.

How it works
------------
* ``WorkspaceScoped`` is a mixin that adds the ``workspace_id`` column (NOT NULL). Every table that holds tenant data uses
  it; the tables that do not (the Skill catalog, the learning loop, sign-in bootstrap) are listed, with a reason, in
  ``tests/unit/test_workspace_inventory.py``, which fails when a table or a route is not declared.
* The *scope* of the running code is a context variable. The API binds it after authentication (``current_principal``);
  jobs bind it with ``workspace_scope``; platform-level code (FORGE agent-version cache…) runs under ``platform_scope``.
* ``NOVA_WORKSPACE_ENFORCEMENT``:
  ``off``     nothing is bound, nothing is filtered, nothing is counted (rows still get their workspace);
  ``shadow``  every row loaded from another workspace than the scope's is counted (``nova_workspace_shadow_total``), the
              result is not changed: it tells what ``enforce`` would hide before it is turned on;
  ``enforce`` every ORM statement (SELECT, UPDATE, DELETE) on a scoped table gets ``workspace_id = <scope>``, and a write
              or a reference across workspaces raises ``WorkspaceViolation``.
* New rows get their workspace before the flush: from the object that owns them (a user, a task, a project… through the
  foreign keys), else from the scope, else the default workspace. A workspace never changes once set.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal
from weakref import WeakSet

from opentelemetry import metrics
from sqlalchemy import Uuid, event, inspect
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from nova.config import get_settings

log = logging.getLogger(__name__)

Mode = Literal["off", "shadow", "enforce"]
_SHADOW = metrics.get_meter("nova.workspace").create_counter(
    "nova_workspace_shadow_total",
    description="Reads, writes and references across workspaces that NOVA_WORKSPACE_ENFORCEMENT=enforce would have refused",
)
_shadow_counts: Counter[str] = Counter()
_logged: set[str] = set()
_PARENT_CACHE_MAX = 20_000
_parent_workspace: dict[tuple[str, uuid.UUID], uuid.UUID] = {}  # a workspace never changes: this cache is never stale


class WorkspaceViolation(Exception):
    """A write or a reference across workspaces (``enforce``), or a change of the workspace of a row (always)."""


def mode() -> Mode:
    return get_settings().workspace_enforcement


def default_workspace_id() -> uuid.UUID:
    return get_settings().default_workspace_id


class WorkspaceScoped:
    """Mixin: the row belongs to exactly one workspace (ADR 001 §9, invariant 1)."""

    workspace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, default=default_workspace_id, sort_order=10_000)


# --- The scope of the running code --------------------------------------------------------------------------------------


@dataclass(slots=True)
class Scope:
    """Mutable on purpose: the API creates it before authentication, authentication fills it in."""

    workspace_id: uuid.UUID | None = None


_current: ContextVar[Scope | None] = ContextVar("nova_workspace_scope", default=None)


def current_workspace() -> uuid.UUID | None:
    scope = _current.get()
    return scope.workspace_id if scope else None


def bind(workspace_id: uuid.UUID | None) -> None:
    """Scope the code that runs from here (the request, the job) to ``workspace_id``; ``None`` lifts the scope."""
    scope = _current.get()
    if scope is None:
        _current.set(Scope(workspace_id))
    else:
        scope.workspace_id = workspace_id


@contextmanager
def workspace_scope(workspace_id: uuid.UUID | None) -> Iterator[None]:
    """Run a block scoped to ``workspace_id`` (a job on behalf of a workspace, a webhook resolved to one)."""
    token = _current.set(Scope(workspace_id))
    try:
        yield
    finally:
        _current.reset(token)


def platform_scope():
    """Run a block that is not about one workspace: platform records (FORGE versions cache, revoked agent keys)."""
    return workspace_scope(None)


_platform_records: WeakSet[Any] = WeakSet()


def platform_record[T](record: T) -> T:
    """Mark a new row as a platform record: it lives in the default workspace whatever the scope that creates it."""
    record.workspace_id = default_workspace_id()  # type: ignore[attr-defined]
    _platform_records.add(record)
    return record


class ScopeMiddleware:
    """Pure ASGI: one scope holder per request, reset when the request ends (authentication fills it in)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = _current.set(Scope())
        try:
            await self.app(scope, receive, send)
        finally:
            _current.reset(token)


# --- Shadow counter --------------------------------------------------------------------------------------------------------


def record_shadow(kind: str, table: str) -> None:
    key = f"{kind}:{table}"
    _shadow_counts[key] += 1
    _SHADOW.add(1, {"kind": kind, "table": table})
    if key not in _logged:  # once per kind and table and process: the counter carries the volume
        _logged.add(key)
        log.warning("workspace shadow: %s on %s would be refused by NOVA_WORKSPACE_ENFORCEMENT=enforce", kind, table)


def shadow_counts() -> dict[str, int]:
    return dict(_shadow_counts)


def reset_shadow_counts() -> None:
    _shadow_counts.clear()
    _logged.clear()


# --- Reads: the filter (enforce) and the counter (shadow) -----------------------------------------------------------------


@event.listens_for(Session, "do_orm_execute")
def _filter_by_workspace(state: Any) -> None:
    if mode() != "enforce":
        return
    workspace = current_workspace()
    if workspace is None:
        return
    is_read = state.is_select and not (state.is_column_load or state.is_relationship_load)
    if is_read or state.is_update or state.is_delete:
        state.statement = state.statement.options(
            with_loader_criteria(WorkspaceScoped, lambda cls: cls.workspace_id == workspace, include_aliases=True)
        )


@event.listens_for(WorkspaceScoped, "load", propagate=True)
def _count_foreign_reads(target: Any, _context: Any) -> None:
    if mode() != "shadow":
        return
    workspace = current_workspace()
    found = target.__dict__.get("workspace_id")
    if workspace is not None and found is not None and found != workspace:
        record_shadow("read", target.__table__.name)


# --- Writes: the workspace of new rows, and its immutability ---------------------------------------------------------------


def _scoped_classes() -> dict[str, type]:
    from nova.infra.db import Base

    return {m.local_table.name: m.class_ for m in Base.registry.mappers if issubclass(m.class_, WorkspaceScoped)}


_fk_cache: dict[type, list[tuple[str, type]]] = {}


def _parents_of(cls: type) -> list[tuple[str, type]]:
    """(attribute, class) of the foreign keys of ``cls`` that point to a workspace-scoped table."""
    if cls not in _fk_cache:
        scoped = _scoped_classes()
        mapper = inspect(cls)
        found = []
        for column in mapper.local_table.columns:
            for fk in column.foreign_keys:
                target = scoped.get(fk.column.table.name)
                if target is not None:
                    found.append((mapper.get_property_by_column(column).key, target))
        _fk_cache[cls] = found
    return _fk_cache[cls]


def _workspace_of_parent(session: Session, cls: type, key: Any, *, allow_query: bool) -> uuid.UUID | None:
    table = cls.__table__.name  # type: ignore[attr-defined]
    cached = _parent_workspace.get((table, key))
    if cached is not None:
        return cached
    parent = session.identity_map.get(inspect(cls).identity_key_from_primary_key((key,)))
    if parent is None and allow_query:
        with platform_scope():  # the filter would hide exactly the parent whose workspace we need to compare
            parent = session.get(cls, key)
    found = getattr(parent, "workspace_id", None) if parent is not None else None
    if found is not None:
        if len(_parent_workspace) >= _PARENT_CACHE_MAX:
            _parent_workspace.clear()
        _parent_workspace[(table, key)] = found
    return found


def _soft_parents(session: Session, obj: Any, allow_query: bool) -> set[uuid.UUID]:
    """Workspaces of the objects a row names without a foreign key: ``workspace_soft_parents`` = ((attribute, table), …)
    on the model, and ``workspace_hint()`` = (table, id) for rows that name their parent by type (integration references).
    The first one found wins: these are hints for rows created without a scope, not constraints."""
    scoped = _scoped_classes()
    candidates = [(table, obj.__dict__.get(attribute)) for attribute, table in getattr(type(obj), "workspace_soft_parents", ())]
    hint = getattr(obj, "workspace_hint", None)
    if hint is not None:
        candidates.append(hint())
    for table, raw in candidates:
        cls = scoped.get(table)
        key = raw if isinstance(raw, uuid.UUID) else None
        if key is None and raw:
            try:
                key = uuid.UUID(str(raw))
            except ValueError:
                continue
        if cls is not None and key is not None:
            found = _workspace_of_parent(session, cls, key, allow_query=allow_query)
            if found is not None:
                return {found}
    return set()


def _resolve(session: Session, obj: Any, allow_query: bool, seen: set[int]) -> None:
    """Give ``obj`` its workspace: explicit, else its parents' (they must agree), else the scope's, else the default."""
    if id(obj) in seen:
        return
    seen.add(id(obj))
    current_mode = mode()
    scope = current_workspace() if current_mode != "off" else None
    parents: set[uuid.UUID] = set()
    for attribute, cls in _parents_of(type(obj)):
        value = obj.__dict__.get(attribute)
        if value is not None:
            found = _workspace_of_parent(session, cls, value, allow_query=allow_query)
            if found is not None:
                parents.add(found)
    for relation in inspect(type(obj)).relationships:  # parents attached by object, their key not yet assigned
        related = obj.__dict__.get(relation.key)
        if isinstance(related, WorkspaceScoped) and relation.direction.name == "MANYTOONE":
            if related.workspace_id is None and related in session.new:
                _resolve(session, related, allow_query, seen)
            if related.workspace_id is not None:
                parents.add(related.workspace_id)
    explicit = obj.__dict__.get("workspace_id")
    if not parents and not explicit:  # no foreign key: the ids the row carries without one (audit actor, FORGE run's task…)
        parents |= _soft_parents(session, obj, allow_query)
    if len(parents | ({explicit} if explicit else set())) > 1:
        _refuse_or_count("reference", obj, "it points to objects of different workspaces")
    chosen = explicit or next(iter(sorted(parents)), None) or scope or default_workspace_id()
    if scope is not None and chosen != scope and obj not in _platform_records:
        _refuse_or_count("write", obj, "it is created in a workspace other than the one of the request")
    obj.workspace_id = chosen


def _refuse_or_count(kind: str, obj: Any, why: str) -> None:
    table = obj.__table__.name
    if mode() == "enforce":
        raise WorkspaceViolation(f"{table}: {why}")
    if mode() == "shadow":
        record_shadow(kind, table)


@event.listens_for(Session, "before_flush")
def _assign_workspace(session: Session, _flush_context: Any, _instances: Any) -> None:
    # Off: no query is added to a flush, parents are only looked for in what the session already holds.
    allow_query = mode() != "off"
    seen: set[int] = set()
    for obj in list(session.new):
        if isinstance(obj, WorkspaceScoped):
            _resolve(session, obj, allow_query, seen)
    for obj in session.dirty:
        if isinstance(obj, WorkspaceScoped):
            history = inspect(obj).attrs.workspace_id.history
            if history.added and history.deleted and history.deleted[0] not in (None, history.added[0]):
                raise WorkspaceViolation(f"{obj.__table__.name}: the workspace of a row never changes")

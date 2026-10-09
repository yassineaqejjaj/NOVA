"""Apply the user's reference ORBIT snapshot to a retrieval (reference only: ORBIT keeps the content and the governance)."""

from __future__ import annotations

from nova.agent.deps import AgentDeps
from nova.domain.context import ContextBundle, ContextError, ContextQuery

UNUSABLE_WARNING = (
    "The reference ORBIT snapshot “{name}” is no longer available; NOVA continued without it. "
    "Choose another snapshot in the ORBIT context page."
)


async def retrieve_with_reference(d: AgentDeps, query: ContextQuery) -> ContextBundle:
    """``retrieve`` with the user's enabled reference snapshot of the project as ``base_snapshot``.

    If ORBIT refuses the snapshot (deleted / no longer readable), retry once without it and warn.
    """
    if query.base_snapshot is None:
        ref = await d.store.get_snapshot_reference(query.user_id, query.project_slug)
        if ref is not None:
            query = query.model_copy(update={"base_snapshot": ref})
    if query.base_snapshot is None:
        return await d.context.retrieve(query)
    name = query.base_snapshot.name
    try:
        return await d.context.retrieve(query)
    except ContextError as exc:
        if exc.code not in ("not_found", "invalid", "forbidden"):
            raise
    bundle = await d.context.retrieve(query.model_copy(update={"base_snapshot": None}))
    bundle.warnings = [UNUSABLE_WARNING.format(name=name), *bundle.warnings]
    return bundle

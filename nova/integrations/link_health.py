"""Last exchange with FORGE (success or error), kept in ``integration_references`` for the links screen.

Only a status line is stored (``HTTP 503``, ``unreachable``): never a response body, a URL with credentials or a key.
Recording is best effort and never breaks the call it observes. (ORBIT's equivalent lives on ``orbit_accounts``.)
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select

from nova.infra.db import platform_session_scope, utcnow
from nova.infra.models import IntegrationReference

SUCCESS_WRITE_EVERY = 60.0  # seconds: a busy link does not write on every call
_last_success_write = 0.0


def reset() -> None:
    """Forget the throttle (tests). Not 0.0: ``time.monotonic()`` can be below 60 s on a freshly booted machine (CI)."""
    global _last_success_write
    _last_success_write = float("-inf")


async def _row(session: Any) -> IntegrationReference | None:
    return await session.scalar(
        select(IntegrationReference).where(
            IntegrationReference.system == "forge",
            IntegrationReference.kind == "link",
            IntegrationReference.nova_type == "link",
            IntegrationReference.nova_id == "nova",
        )
    )


async def record_forge(*, error: str | None = None) -> None:
    global _last_success_write
    now = time.monotonic()
    if error is None and now - _last_success_write < SUCCESS_WRITE_EVERY:
        return
    try:
        async with platform_session_scope() as session:
            row = await _row(session)
            if row is None:
                row = IntegrationReference(
                    system="forge", kind="link", nova_type="link", nova_id="nova", external_id="forge", data={}
                )
                session.add(row)
            stamp = utcnow().isoformat()
            row.data = {
                **row.data,
                **({"last_error_at": stamp, "last_error": error[:200]} if error else {"last_success_at": stamp}),
            }
        if error is None:
            _last_success_write = now
    except Exception:  # bookkeeping must never fail the exchange it observes
        return


async def forge_state() -> dict[str, Any]:
    async with platform_session_scope() as session:
        row = await _row(session)
    data = row.data if row else {}
    return {key: data.get(key) for key in ("last_success_at", "last_error_at", "last_error")}

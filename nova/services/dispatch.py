"""Dispatch executions to the Celery worker (or run them inline when ``celery_task_always_eager``)."""

from __future__ import annotations

import asyncio
from typing import Any

from opentelemetry.propagate import inject

from nova.config import get_settings

_background: set[asyncio.Task] = set()


def _carrier() -> dict[str, str]:
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


async def dispatch(task_id: str, mode: str, resume_value: Any = None, *, countdown: float | None = None) -> None:
    settings = get_settings()
    if settings.celery_task_always_eager:
        from nova.services.executions import run_task

        coro = run_task(task_id, mode, resume_value, traceparent=_carrier())  # type: ignore[arg-type]
        if settings.inline_execution == "background":
            task = asyncio.create_task(coro)
            _background.add(task)
            task.add_done_callback(_background.discard)
        else:
            await coro
        return
    from nova_worker.app import celery_app

    celery_app.send_task("nova.execute", args=[task_id, mode, resume_value, _carrier()], countdown=countdown, queue="executions")


async def dispatch_sdlc(run_id: str, *, countdown: float | None = None) -> None:
    """Advance an SDLC run on the worker (or inline when eager)."""
    settings = get_settings()
    if settings.celery_task_always_eager:
        from nova.services.sdlc import run_until_pause

        coro = run_until_pause(run_id)
        if settings.inline_execution == "background":
            task = asyncio.create_task(coro)
            _background.add(task)
            task.add_done_callback(_background.discard)
        else:
            await coro
        return
    from nova_worker.app import celery_app

    celery_app.send_task("nova.sdlc_advance", args=[run_id], countdown=countdown, queue="executions")

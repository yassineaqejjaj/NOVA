"""Celery application (infrastructure-level background execution; agent logic lives in LangGraph).

* queue ``executions``: NOVA executions (start / resume / retry from checkpoint);
* queue ``maintenance``: scheduled work, FORGE evaluation refresh, retention.

Each worker process keeps one asyncio event loop so that HTTP/DB/Valkey clients are reused safely.
"""

from __future__ import annotations

import asyncio
import logging
import sys

import billiard
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown

from nova.config import get_settings
from nova.infra import db
from nova.infra.telemetry import configure_telemetry

settings = get_settings()

# Celery's prefork pool needs `fork`; Python ≥ 3.8 defaults to `spawn` on macOS (Linux images are unaffected).
if sys.platform == "darwin" and billiard.get_start_method(allow_none=True) is None:
    billiard.set_start_method("fork")

celery_app = Celery("nova", broker=settings.broker_url, backend=settings.valkey_url, include=["nova_worker.tasks"])
celery_app.conf.update(
    task_default_queue="executions",
    task_acks_late=True,  # a crashed worker does not lose the execution (it resumes from the checkpoint)
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    timezone="UTC",
    beat_schedule={
        "start-scheduled-work": {"task": "nova.start_scheduled", "schedule": 60.0, "options": {"queue": "maintenance"}},
        "run-missions": {"task": "nova.run_missions", "schedule": 60.0, "options": {"queue": "maintenance"}},
        "requeue-stale-work": {"task": "nova.requeue_stale", "schedule": 120.0, "options": {"queue": "maintenance"}},
        "refresh-evaluations": {"task": "nova.refresh_evaluations", "schedule": 300.0, "options": {"queue": "maintenance"}},
        "retention": {"task": "nova.retention", "schedule": 86400.0, "options": {"queue": "maintenance"}},
        "requeue-stale-sdlc": {"task": "nova.sdlc_requeue_stale", "schedule": 120.0, "options": {"queue": "maintenance"}},
        "sdlc-forge-sync": {"task": "nova.sdlc_forge_sync", "schedule": 300.0, "options": {"queue": "maintenance"}},
        "advance-training": {"task": "nova.advance_training", "schedule": 120.0, "options": {"queue": "maintenance"}},
    },
)

_loop: asyncio.AbstractEventLoop | None = None


@worker_process_init.connect
def _init_process(**_: object) -> None:
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    db.configure(null_pool=True)
    configure_telemetry(service_name=f"{settings.otel_service_name}-worker")
    logging.getLogger(__name__).info("NOVA worker process ready")


@worker_process_shutdown.connect
def _shutdown_process(**_: object) -> None:
    if _loop is not None:
        _loop.close()


def run(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _init_process()
    assert _loop is not None
    return _loop.run_until_complete(coro)

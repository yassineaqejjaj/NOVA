"""Celery tasks."""

from __future__ import annotations

import logging
from typing import Any

from nova.services import maintenance, training
from nova.services.executions import RetryableExecutionError, run_task
from nova_worker.app import celery_app, run

log = logging.getLogger(__name__)
MAX_RETRIES = 3


@celery_app.task(name="nova.execute", bind=True, max_retries=MAX_RETRIES, acks_late=True)
def execute(self, task_id: str, mode: str, resume_value: Any = None, carrier: dict[str, str] | None = None) -> str:
    """Run one execution segment. Infrastructure failures retry from the last LangGraph checkpoint."""
    final = self.request.retries >= MAX_RETRIES
    try:
        status = run(run_task(task_id, mode, resume_value, traceparent=carrier, final_attempt=final))  # type: ignore[arg-type]
    except RetryableExecutionError as exc:
        log.warning("Execution %s will be retried: %s", task_id, exc)
        raise self.retry(args=[task_id, "retry", None, carrier], countdown=5 * 2**self.request.retries) from exc
    return str(status)


@celery_app.task(name="nova.start_scheduled")
def start_scheduled() -> int:
    return run(maintenance.start_due_scheduled_tasks())


@celery_app.task(name="nova.run_missions")
def run_missions() -> int:
    return run(maintenance.run_missions())


@celery_app.task(name="nova.requeue_stale")
def requeue_stale() -> int:
    return run(maintenance.requeue_stale_tasks())


@celery_app.task(name="nova.refresh_evaluations")
def refresh_evaluations() -> int:
    return run(maintenance.refresh_evaluations())


@celery_app.task(name="nova.retention")
def retention() -> dict[str, int]:
    return run(maintenance.apply_retention())


@celery_app.task(name="nova.advance_training")
def advance_training() -> int:
    """FORGE training loop: start due cycles and advance open ones (services/training.py)."""
    return run(training.tick())

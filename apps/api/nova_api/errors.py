"""API errors: ``{"detail", "code", "actions"}`` — understandable messages, never stack traces."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from nova.domain.context import ContextError
from nova.services.access import AccessDenied

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str, actions: list[dict[str, str]] | None = None) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail, self.actions = status, code, detail, actions or []


def _body(code: str, detail: str, actions: list[dict[str, str]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"detail": detail, "code": code, "actions": actions or [], **extra}


CONTEXT_STATUS = {"unauthorized": 409, "not_linked": 409, "forbidden": 403, "not_found": 404, "unavailable": 503, "invalid": 422}
CONTEXT_ACTIONS = {
    "unauthorized": [{"label": "Reconnect ORBIT", "action": "link_orbit"}],
    "not_linked": [{"label": "Connect ORBIT", "action": "link_orbit"}],
    "forbidden": [
        {"label": "Request access", "action": "request_access"},
        {"label": "Choose another source", "action": "choose_source"},
    ],
    "unavailable": [{"label": "Retry", "action": "retry"}],
}


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.detail, exc.actions), status_code=exc.status)

    @app.exception_handler(AccessDenied)
    async def _denied(_: Request, __: AccessDenied) -> JSONResponse:
        return JSONResponse(_body("not_found", "Not found, or you don't have access."), status_code=404)

    @app.exception_handler(ContextError)
    async def _context(_: Request, exc: ContextError) -> JSONResponse:
        return JSONResponse(
            _body(f"orbit_{exc.code}", exc.message, CONTEXT_ACTIONS.get(exc.code)), status_code=CONTEXT_STATUS.get(exc.code, 502)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()[:10]]
        return JSONResponse(_body("validation_error", "Some fields are invalid.", errors=errors), status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(_body("internal_error", "Something went wrong on NOVA's side. Please retry."), status_code=500)

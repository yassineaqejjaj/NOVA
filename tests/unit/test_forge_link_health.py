"""FORGE link health: the last exchange (success or error) is remembered, without ever keeping a secret or a body."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import delete

from nova.infra import db
from nova.infra.models import IntegrationReference
from nova.integrations import link_health
from nova.integrations.forge.client import ForgeClient, ForgeError


@pytest_asyncio.fixture(autouse=True)
async def clean():
    link_health.reset()
    async with db.session_scope() as session:
        await session.execute(delete(IntegrationReference).where(IntegrationReference.kind == "link"))
    yield
    link_health.reset()


def _client(status: int = 200, *, body: str = "{}", boom: bool = False) -> ForgeClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if boom:
            raise httpx.ConnectError("refused")
        return httpx.Response(status, text=body)

    return ForgeClient("http://forge", "fgk_secret_key_0123456789", transport=httpx.MockTransport(handler))


async def test_a_successful_call_is_remembered():
    await _client().run_scores("r1")
    state = await link_health.forge_state()
    assert state["last_success_at"] is not None and state["last_error_at"] is None and state["last_error"] is None


@pytest.mark.parametrize(
    ("kwargs", "expected"), [({"status": 503}, "HTTP 503"), ({"status": 401}, "HTTP 401"), ({"boom": True}, "unreachable")]
)
async def test_an_outage_or_a_refused_credential_is_remembered_without_the_body(kwargs, expected):
    with pytest.raises(ForgeError):
        await _client(**kwargs, body="trace with fgk_secret_key_0123456789").run_scores("r1")
    state = await link_health.forge_state()
    assert state["last_error"] == expected and state["last_error_at"] is not None
    assert "fgk_" not in str(state)


async def test_an_answer_that_is_a_plain_refusal_of_the_request_still_proves_the_link_works():
    with pytest.raises(ForgeError):
        await _client(404).run_scores("missing")  # FORGE answered: the link is alive
    state = await link_health.forge_state()
    assert state["last_success_at"] is not None and state["last_error"] is None

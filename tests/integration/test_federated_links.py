"""The links screen with federated delegation (NOV-114): states, identity, scope, last round trip, actions, administrator view.

Default mode (``linked_session``): the answer of ``GET /me/links`` is what it was and the new routes do not exist. Everything
shown comes from what NOVA already recorded: opening the screen calls neither the IdP nor ORBIT.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from nova.config import get_settings
from nova.infra import db
from nova.infra.db import utcnow
from nova.infra.models import AuditEvent, DelegationSession, OrbitAccount, ProjectReference, User
from nova.integrations import idp
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova.integrations.orbit.client import OrbitClient
from nova.services import delegation, federated_links, providers
from nova_api.main import create_app
from tests.support.fake_idp import FakeIdP

API = "/api/v1"
PROJECT_ID = "0a0b0c0d-0000-4000-8000-000000000106"
NOW = 1_792_152_000.0


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


async def login(app, *, admin: bool = False) -> tuple[httpx.AsyncClient, str]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    email = f"{uuid.uuid4().hex[:8]}@example.com"
    assert (await client.post(f"{API}/auth/dev-login", json={"email": email, "name": "Yassine Example"})).status_code == 200
    async with db.session_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        user.is_admin = admin
        return client, str(user.id)


class World:
    def __init__(self, fake: FakeIdP, clock: dict[str, float]) -> None:
        self.fake, self.clock = fake, clock
        self.orbit_status = 200
        self.orbit_calls: list[httpx.Request] = []

    def orbit(self, request: httpx.Request) -> httpx.Response:
        self.orbit_calls.append(request)
        return httpx.Response(self.orbit_status, json={} if request.url.path.endswith("/auth/me") else [])


@pytest.fixture
def federated(monkeypatch):
    settings = get_settings()
    for name, value in {"delegation_mode": "token_exchange", "oidc_client_secret": "s" * 32, "orbit_agent_keys": ""}.items():
        monkeypatch.setattr(settings, name, value)
    clock = {"now": NOW}
    fake = FakeIdP()
    fake.now = lambda: clock["now"]
    fake.roles = ["orbit-admin", "forge-editor", "nova-admin"]
    idp.use_transport(fake.transport())
    delegation.set_clock(lambda: clock["now"])
    delegation.clear_cache()
    monkeypatch.setattr(federated_links, "utcnow", lambda: datetime.fromtimestamp(clock["now"], UTC))
    world = World(fake, clock)
    providers.override(
        "context", OrbitContextProvider(settings, OrbitClient("http://orbit", transport=httpx.MockTransport(world.orbit)))
    )
    yield world
    idp.use_transport(None)
    delegation.set_clock(None)
    delegation.clear_cache()


async def sign_in(world: World, user_id: str) -> dict:
    tokens = world.fake.sign_in()
    async with db.session_scope() as session:
        await delegation.remember_subject(session, uuid.UUID(user_id), tokens)
    return tokens


async def links(client) -> dict:
    return (await client.get(f"{API}/me/links")).json()


async def use_orbit(user_id: str, slug: str = "atlas") -> None:
    await providers.context().search(user_id, slug, "refund")


async def reference(slug: str, orion_project_id: str) -> None:
    async with db.session_scope() as session:
        from nova.infra.models import Project

        project = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="Atlas", description="")
        session.add(project)
        await session.flush()
        session.add(
            ProjectReference(
                project_id=project.id, system="orbit", external_id=slug, label=slug, orion_project_id=uuid.UUID(orion_project_id)
            )
        )


# --- default mode -----------------------------------------------------------------------------------------------------------


async def test_the_default_mode_leaves_the_screen_as_it_was(app):
    assert get_settings().delegation_mode == "linked_session"
    client, _ = await login(app)
    body = await links(client)
    assert set(body) == {"orbit", "forge"} and "federated" not in body  # not even a new key
    assert {"status", "mode", "linked", "agent_keys", "fallback"} <= set(body["orbit"])  # the screen as it was
    assert (await client.delete(f"{API}/me/links/orbit")).status_code == 404
    assert (await client.post(f"{API}/me/links/orbit/test")).status_code == 404
    admin, _ = await login(app, admin=True)
    assert (await admin.get(f"{API}/admin/links")).json() == {"mode": "linked_session", "members": []}


# --- states -----------------------------------------------------------------------------------------------------------------


async def test_a_member_who_never_signed_in_through_the_idp_is_unlinked(app, federated):
    client, _ = await login(app)
    federated_body = (await links(client))["federated"]
    assert federated_body["mode"] == "token_exchange" and federated_body["expiry_warning_seconds"] == 60
    for service in ("orbit", "forge"):
        entry = federated_body["services"][service]
        assert entry["status"] in ("unlinked", "not_configured") and entry["linked"] is False
    assert federated_body["services"]["orbit"]["status"] == "unlinked"
    assert federated_body["services"]["forge"]["status"] == "not_configured"  # no FORGE key either


async def test_a_healthy_delegation_shows_who_acts_for_which_project_with_which_scope(app, federated, monkeypatch):
    monkeypatch.setattr(get_settings(), "forge_api_key", "fgk_api_key_for_tests_0123456789")
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    await reference("atlas", PROJECT_ID)
    federated.fake.clearance = 0  # the organisation caps this user at C0
    await use_orbit(user_id)
    body = await links(client)
    orbit = body["federated"]["services"]["orbit"]
    assert orbit["status"] == "ok" and orbit["linked"] is True
    ident = orbit["identity"]
    assert ident["issuer"] == "https://idp.orion.test/realms/orion" and ident["amr"] == ["pwd"] and ident["act"] is None
    assert ident["sub"].endswith("…") and len(ident["sub"]) == 9 and ident["email"].endswith("@example.com")
    assert orbit["project"] == {
        "orion_project_id": PROJECT_ID, "alias": "atlas", "workspace_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    }  # fmt: skip
    assert orbit["scope"]["scopes"] == ["orion:context.read"] and orbit["scope"]["roles"] == ["admin"]  # only orbit-* roles
    assert orbit["scope"]["clearance"] == {"local": 1, "cap": 0, "effective": 0, "reason": "capped_by_token"}
    assert orbit["expiry"]["remaining_seconds"] == 300 and orbit["expiry"]["renewal"] == "on_demand"
    assert orbit["last_exchange"]["status"] == "ok" and orbit["last_exchange"]["consecutive_errors"] == 0
    assert orbit["roundtrip"]["operation"] == "search" and orbit["roundtrip"]["status"] == "ok"
    assert orbit["actions"] == ["reconnect", "revoke", "test"]
    assert body["federated"]["services"]["forge"]["status"] == "unlinked"  # key configured, nothing delegated yet
    assert body["federated"]["services"]["forge"]["actions"] == ["reconnect", "revoke"]


async def test_a_clearance_the_token_does_not_lower_is_the_local_one(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    federated.fake.clearance = 3
    await use_orbit(user_id)
    clearance = (await links(client))["federated"]["services"]["orbit"]["scope"]["clearance"]
    assert clearance == {"local": 1, "cap": 3, "effective": 1, "reason": "local"}  # the claim never raises it


async def test_opening_the_screen_calls_neither_the_idp_nor_orbit(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    await use_orbit(user_id)
    idp_before, orbit_before = len(federated.fake.calls), len(federated.orbit_calls)
    for _ in range(3):
        await links(client)
    federated.clock["now"] += 1000  # even much later: the screen only reads what was recorded
    await links(client)
    assert (len(federated.fake.calls), len(federated.orbit_calls)) == (idp_before, orbit_before)


async def test_a_token_about_to_expire_is_flagged_and_an_expired_one_renews_on_demand(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    await use_orbit(user_id)
    federated.clock["now"] += 250  # 50 s left of 300
    expiring = (await links(client))["federated"]["services"]["orbit"]
    assert expiring["status"] == "expiring" and expiring["expiry"]["remaining_seconds"] == 50
    federated.clock["now"] += 100  # the token is over; the session is not: renewed at the next call, not an error
    later = (await links(client))["federated"]["services"]["orbit"]
    assert later["status"] == "ok" and later["expiry"]["remaining_seconds"] == 0


async def test_an_exchange_the_idp_refuses_is_degraded_with_its_error_count_and_no_secret(app, federated):
    client, user_id = await login(app)
    tokens = await sign_in(federated, user_id)
    federated.fake.audiences = set()
    for _ in range(2):
        with pytest.raises(Exception):  # noqa: B017 - ContextError
            await use_orbit(user_id)
    orbit = (await links(client))["federated"]["services"]["orbit"]
    assert orbit["status"] == "degraded" and orbit["last_exchange"]["consecutive_errors"] == 2
    assert orbit["last_exchange"]["last_error"] == "audience_refused" and orbit["last_exchange"]["last_error_at"]
    text = json.dumps(await links(client))
    assert tokens["access_token"] not in text and tokens["refresh_token"] not in text


async def test_an_orbit_error_on_a_call_is_a_degraded_link_with_the_operation_and_latency(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    federated.orbit_status = 503
    with pytest.raises(Exception):  # noqa: B017
        await use_orbit(user_id)
    orbit = (await links(client))["federated"]["services"]["orbit"]
    assert orbit["status"] == "degraded" and orbit["call_errors"] == 1
    assert orbit["roundtrip"]["operation"] == "search" and orbit["roundtrip"]["status"] == "unavailable"
    assert isinstance(orbit["roundtrip"]["latency_ms"], int)
    federated.orbit_status = 200
    await use_orbit(user_id)
    assert (await links(client))["federated"]["services"]["orbit"]["status"] == "ok"  # the next good call heals it


async def test_a_session_the_idp_no_longer_honours_is_expired_then_unlinked(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    async with db.session_scope() as session:  # the refresh token ran out (the IdP session is over)
        (await session.get(DelegationSession, uuid.UUID(user_id))).refresh_expires_at = utcnow() - timedelta(days=400)
    assert (await links(client))["federated"]["services"]["orbit"]["status"] == "expired"
    await delegation.forget_subject(user_id)  # sign-out
    assert (await links(client))["federated"]["services"]["orbit"]["status"] == "unlinked"


async def test_a_member_removed_by_orbit_is_revoked_until_they_sign_in_again(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    async with db.session_scope() as session:
        session.add(
            OrbitAccount(
                user_id=uuid.UUID(user_id),
                orbit_user_id="o1",
                orbit_email="a@example.com",
                revoked_at=utcnow(),
                revoked_reason="member.removed",
            )
        )
    orbit = (await links(client))["federated"]["services"]["orbit"]
    assert orbit["status"] == "revoked" and orbit["revoked_reason"] == "member.removed"


# --- actions ----------------------------------------------------------------------------------------------------------------


async def test_the_user_can_revoke_the_delegation_and_reconnect(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    await use_orbit(user_id)
    assert (await client.delete(f"{API}/me/links/orbit")).status_code == 204
    orbit = (await links(client))["federated"]["services"]["orbit"]
    assert orbit["status"] == "revoked" and orbit["revoked_reason"] == "user"
    exchanges = len([c for c in federated.fake.calls if c["grant_type"].endswith("token-exchange")])
    with pytest.raises(Exception, match="revoked this delegation"):
        await use_orbit(user_id)  # no new token is exchanged
    assert len([c for c in federated.fake.calls if c["grant_type"].endswith("token-exchange")]) == exchanges
    async with db.session_scope() as session:
        audit = (await session.scalars(select(AuditEvent).where(AuditEvent.action == "delegation.revoke"))).all()
        assert len(audit) == 1 and audit[0].details == {"service": "orbit"}
    await sign_in(federated, user_id)  # reconnect = a new sign-in
    await use_orbit(user_id)
    assert (await links(client))["federated"]["services"]["orbit"]["status"] == "ok"
    assert (await client.delete(f"{API}/me/links/unknown")).status_code == 404


async def test_the_test_action_makes_one_call_that_touches_no_data(app, federated):
    client, user_id = await login(app)
    await sign_in(federated, user_id)
    result = (await client.post(f"{API}/me/links/orbit/test")).json()
    assert result["result"] == "ok" and result["link"]["status"] == "ok"
    assert [c.url.path for c in federated.orbit_calls] == ["/api/v1/auth/me"]  # a profile call: no project, no document
    federated.orbit_status = 403
    result = (await client.post(f"{API}/me/links/orbit/test")).json()
    assert result["result"] == "forbidden" and result["link"]["status"] == "degraded"
    assert (await client.post(f"{API}/me/links/forge/test")).status_code == 400  # nothing to test per user there


# --- administrators ---------------------------------------------------------------------------------------------------------


async def test_an_administrator_sees_the_links_of_the_workspace_without_identity_or_content(app, federated):
    member, member_id = await login(app)
    await sign_in(federated, member_id)
    await use_orbit(member_id)
    admin, _ = await login(app, admin=True)
    assert (await member.get(f"{API}/admin/links")).status_code == 403
    body = (await admin.get(f"{API}/admin/links")).json()
    assert body["mode"] == "token_exchange"
    mine = next(m for m in body["members"] if m["user_id"] == member_id)
    assert mine["services"]["orbit"]["status"] == "ok" and mine["services"]["orbit"]["roundtrip"]["operation"] == "search"
    assert mine["email"].count("*") == 3 and "@example.com" in mine["email"]
    text = json.dumps(mine)
    assert "issuer" not in text and "scopes" not in text and "refund" not in text  # statuses only, no identity detail, no content
    full_sub = federated.fake.sign_in()  # (sub of the synthetic user)
    assert full_sub["access_token"] not in json.dumps(body)


def test_helpers_never_expose_a_full_identifier():
    assert federated_links.abbreviate("5b1d0000-0000-4000-8000-000000000001") == "5b1d0000…"
    assert federated_links.abbreviate("short") == "short" and federated_links.abbreviate(None) is None
    assert federated_links.mask_email("alice@example.test") == "a***@example.test" and federated_links.mask_email(None) is None


async def test_an_orbit_error_whose_body_is_a_list_is_still_a_context_error():
    """Found while writing this screen: ORBIT answering an error with a JSON list crashed the client (AttributeError)."""
    from nova.domain.context import ContextError

    client = OrbitClient("http://orbit", transport=httpx.MockTransport(lambda r: httpx.Response(503, json=["x"])))
    with pytest.raises(ContextError) as exc:
        await client.projects(None)  # type: ignore[arg-type]
    assert exc.value.code == "unavailable" and exc.value.retryable

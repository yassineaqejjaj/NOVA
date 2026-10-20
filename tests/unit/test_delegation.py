"""Delegation by token exchange (NOV-111): against a fake identity provider, with the default mode left untouched."""

from __future__ import annotations

import base64
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from nova.config import get_settings
from nova.domain.context import ContextError
from nova.infra import db
from nova.infra.crypto import decrypt
from nova.infra.db import utcnow
from nova.infra.models import AuditEvent, DelegationSession, ProjectReference
from nova.integrations import idp
from nova.integrations.idp import DelegationError
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova.integrations.orbit.client import OrbitClient
from nova.services import delegation, revocation
from tests.support.fake_idp import ISSUER, OTHER_WORKSPACE, FakeIdP

PROJECT_ID = "0a0b0c0d-0000-4000-8000-000000000106"


@pytest.fixture
def clock():
    state = {"now": 1_792_152_000.0}
    return state


@pytest.fixture
def provider_env(monkeypatch, clock):
    """token_exchange mode, a fake IdP, an ORBIT that records what it receives. Everything restored afterwards."""
    settings = get_settings()
    for name, value in {
        "delegation_mode": "token_exchange",
        "oidc_client_secret": "s" * 32,
        "orbit_agent_keys": "",
        "delegation_service_client_secret": "n" * 32,
    }.items():
        monkeypatch.setattr(settings, name, value)
    fake = FakeIdP()
    fake.now = lambda: clock["now"]
    idp.use_transport(fake.transport())
    delegation.set_clock(lambda: clock["now"])
    delegation.clear_cache()
    seen: list[httpx.Request] = []

    def orbit(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[])

    provider = OrbitContextProvider(settings, OrbitClient("http://orbit", transport=httpx.MockTransport(orbit)))
    yield fake, provider, seen
    idp.use_transport(None)
    delegation.set_clock(None)
    delegation.clear_cache()


async def _sign_in(user, fake: FakeIdP, **kw) -> dict:
    tokens = fake.sign_in(**kw)
    async with db.session_scope() as session:
        await delegation.remember_subject(session, uuid.UUID(user.user_id), tokens)
    return tokens


def exchanges(fake: FakeIdP) -> list[dict[str, str]]:
    return [c for c in fake.calls if c["grant_type"].endswith("token-exchange")]


def bearer(request: httpx.Request) -> str:
    return request.headers["authorization"].removeprefix("Bearer ")


def payload(token: str) -> dict:
    body = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))


async def _reference(slug: str, orion_project_id: str | None) -> None:
    async with db.session_scope() as session:
        ref = await session.scalar(select(ProjectReference).where(ProjectReference.external_id == slug))
        if ref is None:
            from nova.infra.models import Project

            project = Project(slug=f"p-{uuid.uuid4().hex[:6]}", name="P", description="")
            session.add(project)
            await session.flush()
            ref = ProjectReference(project_id=project.id, system="orbit", external_id=slug, label=slug)
            session.add(ref)
        ref.orion_project_id = uuid.UUID(orion_project_id) if orion_project_id else None


# --- default mode ---------------------------------------------------------------------------------------------------


async def test_the_default_mode_is_linked_session_and_never_touches_the_idp(user, monkeypatch):
    assert get_settings().delegation_mode == "linked_session"
    called = []
    idp.use_transport(httpx.MockTransport(lambda r: called.append(r) or httpx.Response(500)))
    try:
        provider = OrbitContextProvider(
            get_settings(), OrbitClient("http://orbit", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
        )
        with pytest.raises(ContextError) as exc:
            await provider.list_projects(user.user_id)
        assert exc.value.code == "not_linked"  # the linked-session behaviour, as before
        identity = await provider.identity(user.user_id)
        assert identity.mode == "none" and not identity.linked
    finally:
        idp.use_transport(None)
    assert called == []


# --- exchange ---------------------------------------------------------------------------------------------------------


async def test_a_call_carries_a_short_delegated_token_for_one_project(user, provider_env):
    fake, provider, seen = provider_env
    await _sign_in(user, fake)
    await _reference("atlas", PROJECT_ID)
    await provider.search(user.user_id, "atlas", "refund")
    (exchange,) = exchanges(fake)
    assert exchange["audience"] == "orbit" and exchange["orion_project_id"] == PROJECT_ID
    assert exchange["scope"] == "orion-audience-orbit orion:context.read"  # the smallest scope that serves the call
    assert exchange["subject_token"] and exchange["client_id"] == get_settings().oidc_client_id
    claims = payload(bearer(seen[-1]))
    assert claims["aud"] == "orbit" and claims["sub"] == payload(exchange["subject_token"])["sub"]  # the user, for ORBIT
    assert claims["exp"] - claims["iat"] <= 300 and claims["orion_project_id"] == PROJECT_ID
    assert bearer(seen[-1]) != exchange["subject_token"]  # never the user's own token


async def test_the_delegated_token_is_never_stored_or_logged(user, provider_env, caplog):
    fake, provider, seen = provider_env
    tokens = await _sign_in(user, fake)
    await provider.list_projects(user.user_id)
    delegated = bearer(seen[-1])
    async with db.session_scope() as session:
        row = await session.get(DelegationSession, uuid.UUID(user.user_id))
        stored = " ".join(str(v) for v in (row.access_ciphertext, row.refresh_ciphertext, json.dumps(row.links)))
        audits = " ".join(str(a.details) + str(a.summary) for a in (await session.scalars(select(AuditEvent))).all())
    assert delegated not in stored and delegated not in audits and delegated not in caplog.text
    assert tokens["access_token"] not in stored and tokens["refresh_token"] not in stored  # the user's own: encrypted
    assert decrypt(row.refresh_ciphertext) == tokens["refresh_token"]
    token = next(iter(delegation._cache.values()))
    assert delegated not in repr(token)


async def test_cache_per_user_project_audience_and_scope(user, provider_env, clock):
    fake, provider, seen = provider_env
    await _sign_in(user, fake)
    await _reference("atlas", PROJECT_ID)
    await _reference("borealis", "0a0b0c0d-0000-4000-8000-000000000107")
    await provider.search(user.user_id, "atlas", "a")
    await provider.search(user.user_id, "atlas", "b")
    assert len(exchanges(fake)) == 1  # served from memory for the validity of the token
    await provider.search(user.user_id, "borealis", "c")
    assert len(exchanges(fake)) == 2  # another project: another token, never the first one
    assert bearer(seen[-1]) != bearer(seen[0])
    assert payload(bearer(seen[-1]))["orion_project_id"].endswith("107")
    clock["now"] += 301  # the 5 minutes are over
    await provider.search(user.user_id, "atlas", "d")
    assert len(exchanges(fake)) == 3


async def test_a_long_lived_token_from_the_idp_is_not_kept_beyond_five_minutes(user, provider_env, clock):
    fake, provider, _ = provider_env
    fake.lifespan = 3600
    await _sign_in(user, fake)
    await provider.list_projects(user.user_id)
    (token,) = delegation._cache.values()
    assert token.expires_at - clock["now"] <= 300
    clock["now"] += 301
    await provider.list_projects(user.user_id)
    assert len(exchanges(fake)) == 2


async def test_the_cache_does_not_cross_users(provider_env, user):
    fake, provider, seen = provider_env
    from nova.services.users import principal_for, upsert_user

    async with db.session_scope() as session:
        other = principal_for(await upsert_user(session, subject=f"t-{uuid.uuid4()}", email=f"{uuid.uuid4().hex[:6]}@example.com",
                                                display_name="B", realm_roles=["nova-user"], is_admin=False))  # fmt: skip
    await _sign_in(user, fake)
    await _sign_in(other, fake, sub="5b1d0000-0000-4000-8000-000000000002")
    await provider.list_projects(user.user_id)
    await provider.list_projects(other.user_id)
    assert len(exchanges(fake)) == 2
    assert payload(bearer(seen[0]))["sub"] != payload(bearer(seen[1]))["sub"]


# --- refusals ---------------------------------------------------------------------------------------------------------


async def test_an_audience_the_idp_does_not_allow_is_refused(user, provider_env):
    fake, provider, seen = provider_env
    fake.audiences = {"forge"}
    await _sign_in(user, fake)
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "forbidden" and seen == []  # ORBIT was never called


async def test_a_scope_broader_than_the_allowed_one_never_reaches_the_idp(user, provider_env):
    fake, _, _ = provider_env
    await _sign_in(user, fake)
    with pytest.raises(DelegationError) as exc:
        await delegation.delegated_token(user.user_id, audience="orbit", project_key=None, scope="orion:run.execute")
    assert exc.value.code == "scope_refused" and exchanges(fake) == []
    with pytest.raises(DelegationError) as exc:
        await delegation.delegated_token(user.user_id, audience="nova-web", project_key=None)
    assert exc.value.code == "audience_refused" and exchanges(fake) == []


async def test_a_scope_the_idp_refuses_is_a_refusal(user, provider_env):
    fake, provider, _ = provider_env
    fake.scopes = set()
    await _sign_in(user, fake)
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "forbidden"


async def test_a_disabled_user_gets_nothing(user, provider_env):
    fake, provider, seen = provider_env
    tokens = await _sign_in(user, fake)
    fake.disabled.add(payload(tokens["access_token"])["sub"])
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unauthorized" and seen == []


async def test_a_session_the_idp_no_longer_honours_is_forgotten(user, provider_env, clock):
    fake, provider, _ = provider_env
    await _sign_in(user, fake, lifespan=60)
    clock["now"] += 120  # the user's access token expired: it is refreshed...
    fake.refresh_valid = False  # ...and the IdP refuses (signed out, revoked, user disabled)
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unauthorized"
    assert not await delegation.has_subject(user.user_id)  # nothing is left to try with
    with pytest.raises(ContextError) as again:
        await provider.list_projects(user.user_id)
    assert again.value.code == "unauthorized" and exchanges(fake) == []


async def test_an_expired_subject_token_is_refreshed_and_the_refresh_token_rotated(user, provider_env, clock):
    fake, provider, _ = provider_env
    first = await _sign_in(user, fake, lifespan=60)
    clock["now"] += 120
    await provider.list_projects(user.user_id)
    refreshes = [c for c in fake.calls if c["grant_type"] == "refresh_token"]
    assert [r["refresh_token"] for r in refreshes] == [first["refresh_token"]]
    async with db.session_scope() as session:
        row = await session.get(DelegationSession, uuid.UUID(user.user_id))
    assert decrypt(row.refresh_ciphertext) != first["refresh_token"]  # the new one replaced it
    assert exchanges(fake)[0]["subject_token"] != first["access_token"]  # exchanged with the refreshed token


async def test_an_expired_subject_token_without_refresh_is_not_exchanged(user, provider_env, clock):
    fake, provider, _ = provider_env
    tokens = fake.sign_in(lifespan=60)
    del tokens["refresh_token"]
    async with db.session_scope() as session:
        await delegation.remember_subject(session, uuid.UUID(user.user_id), tokens)
    clock["now"] += 120
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unauthorized" and exchanges(fake) == []


async def test_a_user_who_never_signed_in_through_the_idp_is_refused(user, provider_env):
    _, provider, seen = provider_env
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unauthorized" and seen == []


async def test_an_unavailable_idp_is_retryable(user, provider_env):
    fake, provider, _ = provider_env
    await _sign_in(user, fake)
    fake.unavailable = True
    with pytest.raises(ContextError) as exc:
        await provider.list_projects(user.user_id)
    assert exc.value.code == "unavailable" and exc.value.retryable


async def test_there_is_no_fallback_to_a_key_or_a_linked_session(user, provider_env, monkeypatch):
    fake, provider, seen = provider_env
    monkeypatch.setattr(get_settings(), "orbit_agent_keys", "atlas:orb_agent_key_for_tests_0123456789")
    await _sign_in(user, fake)
    fake.audiences = set()
    with pytest.raises(ContextError):
        await provider.search(user.user_id, "atlas", "x")
    with pytest.raises(ContextError):
        await provider.get_snapshot(user.user_id, "atlas", "plan")  # an agent-key endpoint: still no key
    assert seen == []  # the agent key was never used instead


@pytest.mark.parametrize("flaw", ["wrong_sub", "wrong_audience", "no_token"])
async def test_a_token_that_is_not_for_this_user_and_audience_is_refused(user, provider_env, flaw):
    fake, provider, _ = provider_env
    await _sign_in(user, fake)
    if flaw == "wrong_sub":
        fake.wrong_sub = True
    elif flaw == "wrong_audience":
        original = fake.token
        fake.token = lambda **kw: original(**{**kw, "aud": ["orbit", "forge"]})
    else:
        fake.handler = lambda request: httpx.Response(200, json={"nope": 1})
        idp.use_transport(httpx.MockTransport(fake.handler))
    with pytest.raises(ContextError):
        await provider.list_projects(user.user_id)
    assert delegation._cache == {}


# --- ORBIT revocation (NOV-81) ----------------------------------------------------------------------------------------


async def test_a_member_removal_drops_the_cached_token_at_once(user, provider_env):
    fake, provider, _ = provider_env
    await _sign_in(user, fake)
    await provider.list_projects(user.user_id)
    assert delegation.drop_cached(user.user_id, "-") == 1
    await provider.list_projects(user.user_id)
    assert len(exchanges(fake)) == 2
    assert revocation.delegation is delegation  # the revocation handler calls drop_cached (see test_revocation)


# --- no user ------------------------------------------------------------------------------------------------------------


async def test_without_a_user_the_service_account_acts_as_itself(provider_env):
    fake, _, _ = provider_env
    token = await delegation.service_token("forge")
    claims = payload(token)
    assert claims["preferred_username"] == "service-account-nova-service" and "act" not in claims
    (call,) = fake.calls
    assert call["grant_type"] == "client_credentials" and "subject_token" not in call
    assert call["scope"] == "orion-audience-forge orion:run.execute"


async def test_the_service_account_needs_a_secret_and_never_a_user_token(provider_env, monkeypatch):
    fake, _, _ = provider_env
    fake.actor = "someone"
    with pytest.raises(DelegationError) as exc:
        await delegation.service_token("orbit")
    assert exc.value.code == "idp_invalid"  # a service token that claims to act for someone is refused
    monkeypatch.setattr(get_settings(), "delegation_service_client_secret", "")
    with pytest.raises(DelegationError) as exc:
        await delegation.service_token("orbit")
    assert exc.value.code == "service_not_configured"


# --- the status line for the links screen --------------------------------------------------------------------------------


async def test_the_outcome_of_each_exchange_is_remembered_as_a_status_line(user, provider_env):
    fake, provider, _ = provider_env
    await _sign_in(user, fake)
    await provider.list_projects(user.user_id)
    identity = await provider.identity(user.user_id)
    assert identity.mode == "delegated" and identity.linked and identity.last_success_at and identity.expires_at
    assert identity.clearance == 2
    fake.audiences = set()
    delegation.clear_cache()
    for _ in range(2):
        with pytest.raises(ContextError):
            await provider.list_projects(user.user_id)
    async with db.session_scope() as session:
        entry = (await session.get(DelegationSession, uuid.UUID(user.user_id))).links["orbit"]
    assert entry["status"] == "error" and entry["consecutive_errors"] == 2 and entry["last_error"] == "audience_refused"
    assert entry["issuer"] == ISSUER and entry["workspace_id"] and "token" not in json.dumps(entry).lower()
    identity = await provider.identity(user.user_id)
    assert identity.last_error == "audience_refused"


async def test_sign_out_forgets_everything(user, provider_env):
    fake, provider, _ = provider_env
    await _sign_in(user, fake)
    await provider.list_projects(user.user_id)
    await delegation.forget_subject(user.user_id)
    assert not await delegation.has_subject(user.user_id) and delegation._cache == {}


def test_other_workspace_constant_is_synthetic():
    assert uuid.UUID(OTHER_WORKSPACE) and timedelta(seconds=delegation.MAX_LIFETIME) <= timedelta(minutes=5)
    assert utcnow()

"""``NOVA_WORKSPACE_STRICT_CLAIM``: tokens read through the ORION claims contract (ADR 001 §3-§4, NOV-104 + NOV-107).

The identity provider is replaced by a stand-in for the signature check (``validate_oidc_token``); everything after it,
including the claims contract (``nova/domain/orion_claims.py``), is the real code. Synthetic tokens, no secret.
"""

from __future__ import annotations

import json
import time
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.artifacts import empty_content
from nova.infra import db
from nova.infra.models import Artifact, ArtifactVersion, User
from nova_api.auth import SESSION_COOKIE, issue_session
from nova_api.main import create_app

W1, W2 = str(uuid.uuid4()), str(uuid.uuid4())


@pytest_asyncio.fixture
async def app():
    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
def idp(monkeypatch):
    """OIDC mode with a token validator that returns the payload the test put in the bearer (JSON)."""
    monkeypatch.setattr(get_settings(), "auth_mode", "oidc")

    def validate(token, _settings, **_):
        payload = json.loads(token)
        now = int(time.time())
        return {"iss": "http://idp.test/realms/orion", "aud": "nova-web", "iat": now, "exp": now + 600, **payload}

    monkeypatch.setattr("nova_api.auth.validate_oidc_token", validate)


def _bearer(**claims) -> dict[str, str]:
    return {"Authorization": "Bearer " + json.dumps(claims)}


async def _get(app, path: str, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies) as client:
        return await client.get(path, headers=headers)


async def _account(subject: str) -> User | None:
    async with db.session_scope() as session:
        return await session.scalar(select(User).where(User.subject == subject))


async def _artifact_of(user_id: uuid.UUID, classification: int = 1) -> str:
    async with db.session_scope() as session:
        artifact = Artifact(type="prd", title="C1 document", owner_id=user_id, classification=classification, current_version=1)
        session.add(artifact)
        await session.flush()
        content = empty_content(get_artifact_registry().get("prd"), "C1 document")
        session.add(
            ArtifactVersion(
                artifact_id=artifact.id, version=1, content=content.model_dump(mode="json"), author_type="nova", state="current"
            )
        )
        return str(artifact.id)


def _sub() -> str:
    return f"sub-{uuid.uuid4()}"


# --- default (flag off): nothing changes ------------------------------------------------------------------------------------------


async def test_without_the_flag_tokens_are_read_as_before(app, idp):
    assert get_settings().workspace_strict_claim is False
    sub = _sub()
    ok = await _get(app, "/api/v1/me", _bearer(sub=sub, email="a@example.com"))  # no workspace claim: fine
    assert ok.status_code == 200
    odd = await _get(app, "/api/v1/me", _bearer(sub=sub, email="a@example.com", orion_clearance="nine"))  # not looked at
    assert odd.status_code == 200
    user = await _account(sub)
    assert user.workspace_id == get_settings().default_workspace_id  # the claim decides nothing while it is off
    artifact = await _artifact_of(user.id)
    capped = await _get(app, f"/api/v1/artifacts/{artifact}", _bearer(sub=sub, orion_clearance=0))
    assert capped.status_code == 200  # no cap applied


# --- strict ---------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def strict(monkeypatch, idp):
    monkeypatch.setattr(get_settings(), "workspace_strict_claim", True)


async def test_a_token_without_workspace_opens_no_workspace_resource_and_creates_no_account(app, strict):
    sub = _sub()
    refused = await _get(app, "/api/v1/artifacts", _bearer(sub=sub, email="b@example.com"))
    assert refused.status_code == 403 and refused.json()["code"] == "workspace_required"
    assert await _account(sub) is None  # nothing was created for it
    assert (await _get(app, "/api/v1/me", _bearer(sub=sub, orion_workspace_id=None))).status_code == 403


async def test_a_malformed_orion_claim_refuses_the_token(app, strict):
    for bad in ({"orion_clearance": 9}, {"orion_clearance": "1"}, {"orion_workspace_id": "not-a-uuid"}, {"act": "me"}):
        response = await _get(app, "/api/v1/me", _bearer(sub=_sub(), **{"orion_workspace_id": W1, **bad}))
        assert response.status_code == 401, bad  # never read as "no cap" or "no workspace"


async def test_the_workspace_claim_decides_the_workspace_of_the_account_it_creates_and_only_that(app, strict):
    sub = _sub()
    first = await _get(app, "/api/v1/me", _bearer(sub=sub, email="c@example.com", orion_workspace_id=W1))
    assert first.status_code == 200
    assert str((await _account(sub)).workspace_id) == W1
    again = await _get(app, "/api/v1/me", _bearer(sub=sub, orion_workspace_id=W1.upper()))
    assert again.status_code == 200
    other = await _get(app, "/api/v1/me", _bearer(sub=sub, orion_workspace_id=W2))  # the account never moves
    assert other.status_code == 401
    assert str((await _account(sub)).workspace_id) == W1


async def test_the_clearance_is_the_minimum_of_the_local_one_and_the_claim(app, strict):
    sub = _sub()
    await _get(app, "/api/v1/me", _bearer(sub=sub, orion_workspace_id=W1))
    artifact = await _artifact_of((await _account(sub)).id, classification=1)  # the default local clearance is 1 (C1)
    path = f"/api/v1/artifacts/{artifact}"
    assert (await _get(app, path, _bearer(sub=sub, orion_workspace_id=W1))).status_code == 200  # no claim: the local value
    assert (await _get(app, path, _bearer(sub=sub, orion_workspace_id=W1, orion_clearance=3))).status_code == 200  # never more
    assert (await _get(app, path, _bearer(sub=sub, orion_workspace_id=W1, orion_clearance=1))).status_code == 200
    capped = await _get(app, path, _bearer(sub=sub, orion_workspace_id=W1, orion_clearance=0))
    unknown = await _get(app, f"/api/v1/artifacts/{uuid.uuid4()}", _bearer(sub=sub, orion_workspace_id=W1, orion_clearance=0))
    assert capped.status_code == unknown.status_code == 404 and capped.json() == unknown.json()  # as an unknown id


async def test_a_session_opened_by_a_capped_token_keeps_the_cap(app, strict):
    sub = _sub()
    await _get(app, "/api/v1/me", _bearer(sub=sub, orion_workspace_id=W1))
    user = await _account(sub)
    artifact = await _artifact_of(user.id, classification=1)
    path = f"/api/v1/artifacts/{artifact}"
    settings = get_settings()
    plain = {SESSION_COOKIE: issue_session(str(user.id), settings)}
    capped = {SESSION_COOKIE: issue_session(str(user.id), settings, clearance_cap=0)}
    assert (await _get(app, path, cookies=plain)).status_code == 200
    assert (await _get(app, path, cookies=capped)).status_code == 404
    get_settings().workspace_strict_claim = False
    try:
        assert (await _get(app, path, cookies=capped)).status_code == 200  # flag off: the cap is not read
    finally:
        get_settings().workspace_strict_claim = True

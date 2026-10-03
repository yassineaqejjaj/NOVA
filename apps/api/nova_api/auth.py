"""Authentication: Keycloak OIDC (BFF, Authorization Code + PKCE), NOVA session cookie, bearer tokens.

The browser only holds an httpOnly ``nova_session`` cookie. API clients may present a Keycloak access
token (validated against the realm JWKS, issuer and audience). ``NOVA_AUTH_MODE=dev`` enables a local
login for development and tests (refused in production by settings validation).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from functools import lru_cache
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings, get_settings
from nova.domain.permissions import Principal
from nova.infra.db import get_session
from nova.services.audit import audit
from nova.services.users import get_user, principal_for, upsert_user
from nova_api.errors import ApiError

SESSION_COOKIE = "nova_session"
OIDC_COOKIE = "nova_oidc"
router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Session tokens ----------------------------------------------------------------------------------


def issue_session(user_id: str, settings: Settings) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + settings.session_ttl_minutes * 60, "typ": "nova-session"},
        settings.session_secret,
        algorithm="HS256",
    )


def _set_session(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_minutes * 60,
        path="/",
    )


@lru_cache
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=600)


def validate_oidc_token(token: str, settings: Settings, *, audience: str, nonce: str | None = None) -> dict[str, Any]:
    signing_key = _jwks_client(f"{settings.oidc_backchannel}/protocol/openid-connect/certs").get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=audience,
        issuer=settings.oidc_issuer,
        options={"require": ["exp", "iss", "sub"]},
    )
    if nonce is not None and claims.get("nonce") != nonce:
        raise jwt.InvalidTokenError("nonce mismatch")
    return claims


def _roles(claims: dict[str, Any]) -> list[str]:
    roles = list((claims.get("realm_access") or {}).get("roles") or [])
    return [r for r in roles if r.startswith("nova")]


async def current_principal(request: Request, session: SessionDep) -> Principal:
    settings = get_settings()
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        try:
            claims = jwt.decode(token, settings.session_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        except jwt.PyJWTError as exc:
            raise ApiError(401, "unauthorized", "Your session has expired. Sign in again.") from exc
        user = await get_user(session, claims["sub"])
        if user is None or user.is_service:
            raise ApiError(401, "unauthorized", "Sign in again.")
        return principal_for(user)
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer ") and settings.auth_mode == "oidc":
        try:
            claims = validate_oidc_token(header[7:].strip(), settings, audience=settings.oidc_audience)
        except (jwt.PyJWTError, httpx.HTTPError) as exc:
            raise ApiError(401, "unauthorized", "Invalid access token.") from exc
        roles = _roles(claims)
        user = await upsert_user(
            session,
            subject=claims["sub"],
            email=claims.get("email", ""),
            display_name=claims.get("name", ""),
            realm_roles=roles,
            is_admin=settings.oidc_admin_role in roles,
        )
        await session.commit()
        return principal_for(user)
    raise ApiError(401, "unauthorized", "Sign in to use NOVA.")


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


# --- OIDC (BFF) ----------------------------------------------------------------------------------------


def _redirect_uri(settings: Settings) -> str:
    return f"{settings.public_url.rstrip('/')}/api/v1/auth/callback"


def _safe_next(target: str | None) -> str:
    return target if target and target.startswith("/") and not target.startswith("//") else "/"


@router.get("/config")
async def auth_config() -> dict[str, Any]:
    settings = get_settings()
    return {"mode": settings.auth_mode, "issuer": settings.oidc_issuer if settings.auth_mode == "oidc" else None}


@router.get("/login")
async def login(next: str | None = Query(default=None)) -> RedirectResponse:
    settings = get_settings()
    if settings.auth_mode != "oidc":
        return RedirectResponse(f"/login?next={_safe_next(next)}")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    params = {
        "client_id": settings.oidc_client_id,
        "response_type": "code",
        "scope": "openid profile email",
        "redirect_uri": _redirect_uri(settings),
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    response = RedirectResponse(f"{settings.oidc_issuer}/protocol/openid-connect/auth?{urlencode(params)}")
    flow = jwt.encode(
        {"state": state, "nonce": nonce, "verifier": verifier, "next": _safe_next(next), "exp": int(time.time()) + 600},
        settings.session_secret,
        algorithm="HS256",
    )
    response.set_cookie(OIDC_COOKIE, flow, httponly=True, secure=settings.cookie_secure, samesite="lax", max_age=600, path="/")
    return response


@router.get("/callback")
async def callback(request: Request, session: SessionDep, code: str = Query(), state: str = Query()) -> RedirectResponse:
    settings = get_settings()
    try:
        flow = jwt.decode(request.cookies.get(OIDC_COOKIE, ""), settings.session_secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise ApiError(400, "invalid_login", "The sign-in attempt expired. Try again.") from exc
    if not secrets.compare_digest(flow["state"], state):
        raise ApiError(400, "invalid_login", "The sign-in attempt is invalid. Try again.")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(settings),
        "client_id": settings.oidc_client_id,
        "code_verifier": flow["verifier"],
    }
    if settings.oidc_client_secret:
        data["client_secret"] = settings.oidc_client_secret
    async with httpx.AsyncClient(timeout=10) as client:
        token_response = await client.post(f"{settings.oidc_backchannel}/protocol/openid-connect/token", data=data)
    if token_response.status_code != 200:
        raise ApiError(401, "invalid_login", "Keycloak refused the sign-in.")
    tokens = token_response.json()
    try:
        claims = validate_oidc_token(tokens["id_token"], settings, audience=settings.oidc_client_id, nonce=flow["nonce"])
    except jwt.PyJWTError as exc:
        raise ApiError(401, "invalid_login", "The identity token is invalid.") from exc
    roles = _roles(claims)
    user = await upsert_user(
        session,
        subject=claims["sub"],
        email=claims.get("email", ""),
        display_name=claims.get("name") or claims.get("preferred_username", ""),
        realm_roles=roles,
        is_admin=settings.oidc_admin_role in roles,
        email_verified=claims.get("email_verified") is True,
    )
    await audit(
        session, actor_id=user.id, action="auth.login", target_type="user", target_id=str(user.id), summary="Signed in (SSO)"
    )
    await session.commit()
    response = RedirectResponse(flow["next"])
    _set_session(response, issue_session(str(user.id), settings), settings)
    response.delete_cookie(OIDC_COOKIE, path="/")
    return response


# Lenient address: internal/dev domains such as `.local` (ORBIT's own admin uses one) must be accepted.
LooseEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
]


class DevLoginIn(BaseModel):
    email: LooseEmail
    name: str = Field(default="", max_length=200)
    title: str = Field(default="", max_length=200)


@router.post("/dev-login")
async def dev_login(body: DevLoginIn, session: SessionDep, response: Response) -> dict[str, str]:
    settings = get_settings()
    if settings.auth_mode != "dev" or settings.is_production:
        raise ApiError(404, "not_found", "Not available.")
    user = await upsert_user(
        session,
        subject=f"dev:{body.email.lower()}",
        email=body.email.lower(),
        display_name=body.name or body.email.split("@")[0],
        realm_roles=["nova-user"],
        is_admin=False,
    )
    if body.title:
        user.title = body.title
    await audit(
        session, actor_id=user.id, action="auth.login", target_type="user", target_id=str(user.id), summary="Signed in (dev)"
    )
    await session.commit()
    _set_session(response, issue_session(str(user.id), settings), settings)
    return {"user_id": str(user.id)}


@router.post("/logout")
async def logout(response: Response) -> dict[str, str | None]:
    settings = get_settings()
    response.delete_cookie(SESSION_COOKIE, path="/")
    end_session = None
    if settings.auth_mode == "oidc":
        params = urlencode({"client_id": settings.oidc_client_id, "post_logout_redirect_uri": settings.public_url})
        end_session = f"{settings.oidc_issuer}/protocol/openid-connect/logout?{params}"
    return {"redirect": end_session}


async def require_user(principal: CurrentPrincipal) -> Principal:
    return principal


__all__ = ["CurrentPrincipal", "current_principal", "router"]

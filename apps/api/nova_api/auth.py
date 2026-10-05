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
from nova.services import accounts
from nova.services.audit import audit
from nova.services.identity import IdentityError, validate_oidc_token
from nova.services.mailer import last_code
from nova.services.users import get_user, principal_for, upsert_user
from nova_api.errors import ApiError

SESSION_COOKIE = "nova_session"
OIDC_COOKIE = "nova_oidc"
router = APIRouter(prefix="/auth", tags=["auth"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Session tokens ----------------------------------------------------------------------------------


def issue_session(user_id: str, settings: Settings, *, ttl_seconds: int | None = None, method: str = "sso") -> str:
    """``method``: how the user signed in (``sso`` through Keycloak's pages, ``pwd`` on NOVA's screens, ``dev``)."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": user_id,
            "iat": now,
            "exp": now + (ttl_seconds or settings.session_ttl_minutes * 60),
            "typ": "nova-session",
            "amr": method,
        },
        settings.session_secret,
        algorithm="HS256",
    )


def _set_session(response: Response, token: str, settings: Settings, *, max_age: int | None = -1) -> None:
    """``max_age=None`` makes a browser-session cookie ("Keep me signed in" unchecked)."""
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_ttl_minutes * 60 if max_age == -1 else max_age,
        path="/",
    )


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
    return {
        "mode": settings.auth_mode,
        "issuer": settings.oidc_issuer if settings.auth_mode == "oidc" else None,
        "password_login": True,
        "signup": {
            "enabled": settings.signup_enabled,
            "domains": [] if settings.signup_any_domain else settings.signup_domain_list,  # [] = any address
            "verification": settings.signup_verifies_email,
        },
        "password_reset": settings.smtp_configured or settings.email_outbox,
        "dev_outbox": settings.email_outbox,
        # Identity providers shown on the sign-in screen; "available" once configured in Keycloak.
        "providers": [{"id": "google", "name": "Google", "available": False}],
    }


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
    _set_session(response, issue_session(str(user.id), settings, method="dev"), settings)
    return {"user_id": str(user.id)}


# --- Password accounts (NOVA's own sign-in / sign-up screens) -------------------------------------------

LANG = Annotated[str, StringConstraints(pattern=r"^(en|fr)$")]


class PasswordLoginIn(BaseModel):
    email: LooseEmail
    password: str = Field(min_length=1, max_length=256)
    remember: bool = False


class SignupIn(BaseModel):
    email: LooseEmail
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=256)
    accept_terms: bool
    lang: LANG = "en"


class EmailIn(BaseModel):
    email: LooseEmail
    lang: LANG = "en"


class CodeIn(BaseModel):
    email: LooseEmail
    code: str = Field(pattern=r"^\s*\d{6}\s*$")


class ResetIn(CodeIn):
    password: str = Field(min_length=1, max_length=256)


IDENTITY_STATUS = {
    "invalid_credentials": 401,
    "email_not_verified": 403,
    "account_disabled": 403,
    "account_exists": 409,
    "domain_not_allowed": 422,
    "weak_password": 422,
    "name_required": 422,
    "invalid_code": 422,
    "code_expired": 410,
    "too_many_requests": 429,
    "signup_disabled": 403,
    "email_unavailable": 503,
    "identity_unavailable": 503,
}


def _identity_error(exc: IdentityError) -> ApiError:
    return ApiError(IDENTITY_STATUS.get(exc.code, 400), exc.code, str(exc))


def _sign_in(response: Response, user_id: str, settings: Settings, *, remember: bool) -> None:
    if remember:
        ttl = settings.remember_me_days * 86400
        _set_session(response, issue_session(user_id, settings, ttl_seconds=ttl, method="pwd"), settings, max_age=ttl)
    else:
        _set_session(response, issue_session(user_id, settings, method="pwd"), settings, max_age=None)


@router.post("/password-login")
async def password_login(body: PasswordLoginIn, session: SessionDep, response: Response) -> dict[str, str]:
    try:
        user = await accounts.password_login(session, email=body.email, password=body.password)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    _sign_in(response, str(user.id), get_settings(), remember=body.remember)
    return {"user_id": str(user.id)}


@router.post("/signup", status_code=202)
async def signup(body: SignupIn, session: SessionDep, response: Response) -> dict[str, Any]:
    if not body.accept_terms:
        raise ApiError(422, "terms_required", "Accept the terms of service and the privacy policy.")
    try:
        user = await accounts.start_signup(session, email=body.email, name=body.name, password=body.password, lang=body.lang)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    if user is not None:  # no e-mail verification configured: the account is active and signed in
        _sign_in(response, str(user.id), get_settings(), remember=False)
        return {"email": body.email, "verification": False, "user_id": str(user.id)}
    return {"email": body.email, "verification": True, "expires_in_minutes": get_settings().email_code_ttl_minutes}


@router.post("/signup/resend", status_code=202)
async def signup_resend(body: EmailIn, session: SessionDep) -> dict[str, str]:
    try:
        await accounts.resend_signup_code(session, email=body.email, lang=body.lang)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    return {"status": "sent"}


@router.post("/signup/verify")
async def signup_verify(body: CodeIn, session: SessionDep, response: Response) -> dict[str, str]:
    try:
        user = await accounts.verify_signup(session, email=body.email, code=body.code)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    _sign_in(response, str(user.id), get_settings(), remember=False)
    return {"user_id": str(user.id)}


@router.post("/password/forgot", status_code=202)
async def password_forgot(body: EmailIn, session: SessionDep) -> dict[str, str]:
    try:
        await accounts.forgot_password(session, email=body.email, lang=body.lang)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    return {"status": "sent"}  # same answer whether or not the address has an account


@router.post("/password/reset")
async def password_reset(body: ResetIn, session: SessionDep) -> dict[str, str]:
    try:
        await accounts.reset_password(session, email=body.email, code=body.code, password=body.password)
    except IdentityError as exc:
        raise _identity_error(exc) from exc
    return {"status": "reset"}


@router.get("/dev/outbox")
async def dev_outbox(email: str = Query()) -> dict[str, str | None]:
    """Development only: the last code e-mailed to an address (no SMTP server outside production)."""
    if not get_settings().email_outbox:
        raise ApiError(404, "not_found", "Not available.")
    return {"code": last_code(email.strip().lower())}


@router.post("/logout")
async def logout(request: Request, response: Response) -> dict[str, str | None]:
    settings = get_settings()
    try:
        method = jwt.decode(request.cookies.get(SESSION_COOKIE, ""), settings.session_secret, algorithms=["HS256"]).get("amr")
    except jwt.PyJWTError:
        method = None
    response.delete_cookie(SESSION_COOKIE, path="/")
    end_session = None
    # NOVA's own sign-in leaves no Keycloak session behind; sessions from before the "amr" claim came through SSO.
    if settings.auth_mode == "oidc" and method in ("sso", None):
        params = urlencode({"client_id": settings.oidc_client_id, "post_logout_redirect_uri": settings.public_url})
        end_session = f"{settings.oidc_issuer}/protocol/openid-connect/logout?{params}"
    return {"redirect": end_session}


async def require_user(principal: CurrentPrincipal) -> Principal:
    return principal


__all__ = ["CurrentPrincipal", "current_principal", "router"]

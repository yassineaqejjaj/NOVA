"""Delegation by token exchange (ADR 001 §6, NOV-111): NOVA acts for a user with a short token the IdP issues for ORBIT.

Only active with ``NOVA_DELEGATION_MODE=token_exchange``; the default (``linked_session``) never reaches this module.

* the user's own tokens are kept encrypted in ``delegation_sessions`` (access + refresh, refreshed on demand): they
  prove who the user is, nothing more;
* a delegated token is exchanged per (user, project, audience, scope), lives 5 minutes at most, is held **in memory only**
  until it expires (the cache of a process: another process exchanges its own), is never written anywhere, never reused
  for another project, never logged;
* the target service validates it and applies its own authorizations (ADR §4); NOVA never decides a right here;
* no fallback: a failure is a refusal, never the project agent key or another identity (ADR §7).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import delete

from nova.config import Settings, get_settings
from nova.domain.orion_claims import AUDIENCES, ClaimsError, parse_claims
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import DelegationSession
from nova.integrations import idp
from nova.integrations.idp import DelegationError

MAX_LIFETIME = 300  # seconds: ADR §6, a delegated token lives 5 minutes at most
SKEW = 30  # seconds: a cached token is not served in its last half minute
#: What each target may be asked for: the smallest scope that serves the call, nothing broader (ADR §6).
ALLOWED_SCOPES: dict[str, frozenset[str]] = {
    "orbit": frozenset({"orion:context.read"}),
    "forge": frozenset({"orion:run.execute"}),
}
TARGETS = ("orbit", "forge")


@dataclass(frozen=True)
class DelegatedToken:
    """A delegated token and what is known of it without trusting it (the target validates the signature)."""

    access_token: str
    expires_at: float  # epoch seconds, never more than MAX_LIFETIME after it was obtained
    audience: str
    scope: str
    project_key: str
    subject: str
    actor: str | None
    issuer: str
    amr: tuple[str, ...]
    scopes: tuple[str, ...]
    workspace_id: str | None
    project_id: str | None
    clearance: int | None

    def __repr__(self) -> str:  # a token must never reach a log through repr
        return f"DelegatedToken(audience={self.audience!r}, project={self.project_key!r}, expires_at={self.expires_at})"


_cache: dict[tuple[str, str, str, str], DelegatedToken] = {}
_clock = time.time


def set_clock(clock: Any) -> None:
    """Tests only."""
    global _clock
    _clock = clock if clock is not None else time.time


def clear_cache() -> None:
    _cache.clear()


def drop_cached(user_id: str | uuid.UUID, project_key: str | None = None) -> int:
    """Forget the delegated tokens of a user (all projects, or one): ORBIT told NOVA the access was removed (NOV-81)."""
    uid = str(user_id)
    doomed = [k for k in _cache if k[0] == uid and (project_key is None or k[1] == project_key)]
    for key in doomed:
        del _cache[key]
    return len(doomed)


def enabled(settings: Settings | None = None) -> bool:
    return (settings or get_settings()).delegation_mode == "token_exchange"


# --- the user's own session ------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.fromtimestamp(_clock(), UTC)


def _expiry(seconds: Any) -> datetime | None:
    return _now() + timedelta(seconds=int(seconds)) if isinstance(seconds, (int, float)) and seconds > 0 else None


async def remember_subject(session: Any, user_id: uuid.UUID, tokens: dict[str, Any]) -> None:
    """Keep the user's tokens from the sign-in (encrypted). Called at the OIDC callback, in ``token_exchange`` mode only."""
    access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
    if not isinstance(access, str):
        return
    row = await session.get(DelegationSession, user_id)
    if row is None:
        row = DelegationSession(user_id=user_id, links={})
        session.add(row)
    row.access_ciphertext = encrypt(access)
    row.access_expires_at = _expiry(tokens.get("expires_in"))
    row.refresh_ciphertext = encrypt(refresh) if isinstance(refresh, str) else None
    row.refresh_expires_at = _expiry(tokens.get("refresh_expires_in"))
    row.updated_at = utcnow()


async def forget_subject(user_id: str | uuid.UUID) -> None:
    """Sign-out or a refused refresh: the stored tokens and every delegated token of the user are gone."""
    uid = uuid.UUID(str(user_id))
    async with session_scope() as session:
        await session.execute(delete(DelegationSession).where(DelegationSession.user_id == uid))
    drop_cached(uid)


async def has_subject(user_id: str | uuid.UUID) -> bool:
    async with session_scope() as session:
        row = await session.get(DelegationSession, uuid.UUID(str(user_id)))
    return bool(row and (row.access_ciphertext or row.refresh_ciphertext))


async def subject_token(user_id: str, settings: Settings | None = None) -> str:
    """The user's own access token, refreshed when it is about to expire. Refusal: ``subject_missing`` / ``subject_expired``."""
    settings = settings or get_settings()
    uid = uuid.UUID(user_id)
    async with session_scope() as session:
        row = await session.get(DelegationSession, uid)
        if row is None or not (row.access_ciphertext or row.refresh_ciphertext):
            raise DelegationError("subject_missing", "Sign in again to let NOVA act for you")
        access = decrypt(row.access_ciphertext) if row.access_ciphertext else None
        valid = access and row.access_expires_at is not None and aware(row.access_expires_at) > _now() + timedelta(seconds=SKEW)
        refresh_token = decrypt(row.refresh_ciphertext) if row.refresh_ciphertext else None
    if valid:
        return access  # type: ignore[return-value]
    if not refresh_token:
        await forget_subject(uid)
        raise DelegationError("subject_expired", "Your sign-in expired: sign in again")
    try:
        body = await idp.refresh(settings, refresh_token)
    except DelegationError as exc:
        if exc.code in ("subject_expired", "user_disabled"):  # the IdP no longer honours this session
            await forget_subject(uid)
        raise
    async with session_scope() as session:
        row = await session.get(DelegationSession, uid)
        if row is not None:
            await remember_subject(session, uid, {**body, "refresh_token": body.get("refresh_token", refresh_token)})
    return body["access_token"]


# --- exchange ----------------------------------------------------------------------------------------------------------


def _unverified(token: str) -> dict[str, Any]:
    """Claims of a token the IdP just handed over TLS: read for caching and checks only; the target verifies the signature."""
    try:
        return jwt.decode(token, options={"verify_signature": False, "verify_exp": False, "verify_aud": False})
    except jwt.PyJWTError as exc:
        raise DelegationError("idp_invalid", "The identity provider answered a token NOVA cannot read") from exc


def _checked(
    token: str, *, audience: str, subject_token_value: str | None, scope: str, project_key: str, now: float
) -> DelegatedToken:
    payload = _unverified(token)
    try:
        claims = parse_claims(payload)
    except ClaimsError as exc:
        raise DelegationError("idp_invalid", f"The delegated token breaks the claims contract ({exc.code})") from exc
    if AUDIENCES[audience] not in claims.audience or len(claims.audience) != 1:
        raise DelegationError("audience_refused", "The delegated token is not for this audience alone")
    if subject_token_value is not None and claims.subject != _unverified(subject_token_value).get("sub"):
        raise DelegationError("idp_invalid", "The delegated token is for another user")
    expires_at = min(float(claims.expires_at), now + MAX_LIFETIME)
    return DelegatedToken(
        access_token=token,
        expires_at=expires_at,
        audience=audience,
        scope=scope,
        project_key=project_key,
        subject=claims.subject,
        actor=claims.actor.subject if claims.actor else None,
        issuer=claims.issuer,
        amr=claims.amr,
        scopes=claims.scopes,
        workspace_id=claims.workspace_id,
        project_id=claims.project_id,
        clearance=claims.clearance,
    )


async def delegated_token(
    user_id: str,
    *,
    audience: str,
    project_key: str | None,
    orion_project_id: str | None = None,
    scope: str | None = None,
    settings: Settings | None = None,
) -> DelegatedToken:
    """The token NOVA presents to ``audience`` on behalf of ``user_id`` for one project.

    ``project_key`` is the ORION project id when known, else the project's slug (``None``: a call that names no project).
    The cache is keyed by (user, project, audience, scope): a token is never served for another one.
    """
    settings = settings or get_settings()
    if audience not in TARGETS:
        raise DelegationError("audience_refused", "NOVA delegates to ORBIT and FORGE only")
    wanted = scope or (settings.delegation_scope_orbit if audience == "orbit" else sorted(ALLOWED_SCOPES[audience])[0])
    if wanted not in ALLOWED_SCOPES[audience]:  # refused here, before the IdP is even asked
        raise DelegationError("scope_refused", "This scope is broader than what NOVA may ask for this audience")
    key = (user_id, project_key or "-", audience, wanted)
    now = _clock()
    cached = _cache.get(key)
    if cached is not None and cached.expires_at - SKEW > now:
        return cached
    _cache.pop(key, None)
    subject = await subject_token(user_id, settings)
    started = time.monotonic()
    try:
        body = await idp.exchange(settings, subject, audience=audience, scope=wanted, orion_project_id=orion_project_id)
        token = _checked(
            body["access_token"], audience=audience, subject_token_value=subject, scope=wanted, project_key=key[1], now=now
        )
    except DelegationError as exc:
        await record(user_id, audience, error=exc.code, project_key=key[1], latency_ms=int((time.monotonic() - started) * 1000))
        raise
    _cache[key] = token
    await record(user_id, audience, token=token, latency_ms=int((time.monotonic() - started) * 1000))
    return token


async def service_token(audience: str, *, scope: str | None = None, settings: Settings | None = None) -> str:
    """No user (routine, protocol): the explicit service account's own token, never a user's identity (ADR §6.5, §7)."""
    settings = settings or get_settings()
    if audience not in TARGETS:
        raise DelegationError("audience_refused", "NOVA delegates to ORBIT and FORGE only")
    wanted = scope or sorted(ALLOWED_SCOPES[audience])[0]
    if wanted not in ALLOWED_SCOPES[audience]:
        raise DelegationError("scope_refused", "This scope is broader than what NOVA may ask for this audience")
    body = await idp.client_credentials(settings, audience=audience, scope=wanted)
    token = _checked(
        body["access_token"], audience=audience, subject_token_value=None, scope=wanted, project_key="-", now=_clock()
    )
    if token.actor is not None:
        raise DelegationError("idp_invalid", "A service token does not act for a user")
    return token.access_token


# --- what the links screen shows (no token, no secret) -----------------------------------------------------------------


async def record(
    user_id: str,
    audience: str,
    *,
    token: DelegatedToken | None = None,
    error: str | None = None,
    project_key: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Remember the outcome of an exchange as a status line (best effort: never breaks the call it observes)."""
    try:
        async with session_scope() as session:
            row = await session.get(DelegationSession, uuid.UUID(user_id))
            if row is None:
                return
            links = dict(row.links or {})
            previous = dict(links.get(audience) or {})
            now = datetime.now(UTC).isoformat()
            if token is not None:
                entry = {
                    **previous,
                    "status": "ok",
                    "last_success_at": now,
                    "consecutive_errors": 0,
                    "last_error": None,
                    "last_error_at": previous.get("last_error_at"),
                    "issuer": token.issuer,
                    "subject": token.subject,
                    "actor": token.actor,
                    "amr": list(token.amr),
                    "scopes": list(token.scopes),
                    "workspace_id": token.workspace_id,
                    "project_id": token.project_id,
                    "project_key": token.project_key,
                    "clearance_cap": token.clearance,
                    "expires_at": datetime.fromtimestamp(token.expires_at, UTC).isoformat(),
                    "exchange_ms": latency_ms,
                }
            else:
                entry = {
                    **previous,
                    "status": "error",
                    "last_error": error,
                    "last_error_at": now,
                    "consecutive_errors": int(previous.get("consecutive_errors", 0)) + 1,
                    "project_key": project_key or previous.get("project_key"),
                    "exchange_ms": latency_ms,
                }
            links[audience] = entry
            row.links = links
            row.updated_at = utcnow()
    except Exception:  # bookkeeping never fails the exchange it observes
        return

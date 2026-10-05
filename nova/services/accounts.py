"""Sign-up with a company address, e-mailed verification codes, password sign-in and reset.

Codes: 6 digits, stored as an HMAC (keyed by the session secret), valid ``email_code_ttl_minutes``, at most
``email_code_max_attempts`` tries, one new code per ``email_code_resend_seconds``. Requests about unknown addresses
answer like known ones (no account enumeration through reset).
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings, get_settings
from nova.infra.db import utcnow
from nova.infra.models import EmailCode, User
from nova.services.audit import audit
from nova.services.identity import IdentityError, IdentityUser, check_password_strength, identity_backend
from nova.services.mailer import MailerError, code_email, send_email
from nova.services.users import upsert_user


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _hash(code: str, email: str, purpose: str, settings: Settings) -> str:
    return hmac.new(settings.session_secret.encode(), f"{purpose}:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def company_domain(email: str, settings: Settings | None = None) -> str | None:
    """The allowed company domain of ``email`` (exact domain, not a look-alike sub-domain)."""
    settings = settings or get_settings()
    domain = email.rsplit("@", 1)[-1] if "@" in email else ""
    return domain if domain in settings.signup_domain_list else None


async def _send_code(session: AsyncSession, email: str, purpose: str, lang: str) -> None:
    settings = get_settings()
    last = await session.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )
    now = utcnow()
    if last is not None and (now - _aware(last.created_at)).total_seconds() < settings.email_code_resend_seconds:
        raise IdentityError("too_many_requests", "A code was just sent. Wait a minute before asking for a new one.")
    await session.execute(
        update(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        EmailCode(
            email=email,
            purpose=purpose,
            code_hash=_hash(code, email, purpose, settings),
            expires_at=now + timedelta(minutes=settings.email_code_ttl_minutes),
        )
    )
    await session.flush()
    subject, text, html = code_email(purpose, lang, code, settings.email_code_ttl_minutes)
    try:
        await send_email(email, subject, text, html, code=code)
    except MailerError as exc:
        raise IdentityError("email_unavailable", "The e-mail could not be sent. Try again later.") from exc


async def _consume_code(session: AsyncSession, email: str, purpose: str, code: str) -> None:
    settings = get_settings()
    row = await session.scalar(
        select(EmailCode)
        .where(EmailCode.email == email, EmailCode.purpose == purpose, EmailCode.consumed_at.is_(None))
        .order_by(EmailCode.created_at.desc())
        .limit(1)
    )
    if row is None or _aware(row.expires_at) < utcnow():
        raise IdentityError("code_expired", "This code has expired. Ask for a new one.")
    if row.attempts >= settings.email_code_max_attempts:
        raise IdentityError("code_expired", "Too many attempts. Ask for a new code.")
    row.attempts += 1
    if not hmac.compare_digest(row.code_hash, _hash(code.strip(), email, purpose, settings)):
        await session.commit()  # keep the attempt even though the request fails
        raise IdentityError("invalid_code", "This code is not valid.")
    row.consumed_at = utcnow()


async def start_signup(session: AsyncSession, *, email: str, name: str, password: str, lang: str) -> None:
    settings = get_settings()
    email = normalize_email(email)
    if not settings.signup_enabled:
        raise IdentityError("signup_disabled", "Sign-up is not available yet.")
    if company_domain(email, settings) is None:
        domains = ", ".join(f"@{d}" for d in settings.signup_domain_list)
        raise IdentityError("domain_not_allowed", f"Use your company address ({domains}).")
    if not name.strip():
        raise IdentityError("name_required", "Enter your full name.")
    check_password_strength(password)
    backend = identity_backend(session, settings)
    existing = await backend.find(email)
    if existing is not None and existing.enabled:
        raise IdentityError("account_exists", "An account already exists for this address. Sign in instead.")
    if existing is None:
        await backend.create(email, name.strip(), password)
    else:  # an unconfirmed sign-up: the latest details win
        await backend.update_pending(existing, name.strip(), password)
    await _send_code(session, email, "signup", lang)
    await session.commit()


async def resend_signup_code(session: AsyncSession, *, email: str, lang: str) -> None:
    email = normalize_email(email)
    existing = await identity_backend(session).find(email)
    if existing is None or existing.enabled:
        return  # nothing pending: same answer as for a real resend
    await _send_code(session, email, "signup", lang)
    await session.commit()


async def _nova_user(session: AsyncSession, identity: IdentityUser) -> User:
    settings = get_settings()
    return await upsert_user(
        session,
        subject=identity.subject,
        email=identity.email,
        display_name=identity.name,
        realm_roles=identity.roles or ["nova-user"],
        is_admin=settings.oidc_admin_role in identity.roles,
        email_verified=True,
    )


async def verify_signup(session: AsyncSession, *, email: str, code: str) -> User:
    email = normalize_email(email)
    backend = identity_backend(session)
    pending = await backend.find(email)
    if pending is None:
        raise IdentityError("code_expired", "This code has expired. Ask for a new one.")
    await _consume_code(session, email, "signup", code)
    if not pending.enabled:
        await backend.activate(pending)
    pending.roles = pending.roles or ["nova-user"]
    user = await _nova_user(session, pending)
    await audit(
        session, actor_id=user.id, action="auth.signup", target_type="user", target_id=str(user.id), summary="Account created"
    )
    await session.commit()
    return user


async def password_login(session: AsyncSession, *, email: str, password: str) -> User:
    identity = await identity_backend(session).authenticate(normalize_email(email), password)
    user = await _nova_user(session, identity)
    await audit(session, actor_id=user.id, action="auth.login", target_type="user", target_id=str(user.id), summary="Signed in")
    await session.commit()
    return user


async def forgot_password(session: AsyncSession, *, email: str, lang: str) -> None:
    email = normalize_email(email)
    if not (get_settings().smtp_configured or get_settings().email_outbox):
        raise IdentityError("email_unavailable", "Password reset by e-mail is not available yet.")
    existing = await identity_backend(session).find(email)
    if existing is None or not existing.enabled:
        return  # no enumeration: unknown and known addresses get the same answer
    try:
        await _send_code(session, email, "reset", lang)
    except IdentityError as exc:
        if exc.code != "too_many_requests":
            raise
    await session.commit()


async def reset_password(session: AsyncSession, *, email: str, code: str, password: str) -> None:
    """Sets the new password; the user then signs in with it (roles come from the identity provider's token)."""
    email = normalize_email(email)
    check_password_strength(password)
    backend = identity_backend(session)
    existing = await backend.find(email)
    if existing is None or not existing.enabled:
        raise IdentityError("invalid_code", "This code is not valid.")
    await _consume_code(session, email, "reset", code)
    await backend.set_password(existing, password)
    user = await session.scalar(select(User).where(User.subject == existing.subject))
    if user is not None:
        await audit(session, actor_id=user.id, action="auth.password_reset", target_type="user", target_id=str(user.id))
    await session.commit()

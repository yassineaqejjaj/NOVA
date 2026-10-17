"""Account migration tool (ADR 001 §8, NOV-113): inventory, reconciliation (dry-run), approved links, sign-in flags, break-glass.

    uv run python -m nova.migration.accounts inventory [--emails hash|masked|clear] [--format json|csv] [--out FILE]
    uv run python -m nova.migration.accounts reconcile --idp-export FILE [--domains devoteam.com] [--emit-approval FILE]
    uv run python -m nova.migration.accounts sign-approval FILE --approved-by NAME
    uv run python -m nova.migration.accounts apply --idp-export FILE --approval FILE --confirm-backup ID
    uv run python -m nova.migration.accounts rollback --batch BATCH
    uv run python -m nova.migration.accounts flags --user ID_OR_EMAIL (--disable-password | --sso-required | --enable-password)
    uv run python -m nova.migration.accounts break-glass --user ID_OR_EMAIL [--unset]

Rules (they are what makes the tool safe to leave in the repository):

* ``inventory`` and ``reconcile`` **never write**: the session is rolled back, a test compares the database before and after;
* an e-mail leaves the tool hashed (HMAC with ``ORION_INVENTORY_SALT``, shared by the three services so the tables can be
  joined), masked, or in clear only with ``--confirm-sensitive``; no token, key or password is ever printed;
* ``apply`` needs ``--confirm-backup <id>``, an approval file **signed** (HMAC, ``ORION_APPROVAL_KEY``) for the *current*
  proposal, and links only the pairs the file lists; all or nothing; in production it also needs
  ``ORION_MIGRATION_ALLOW_PRODUCTION=owner-decision``: executing it in production is the owner's separate decision;
* the flags that close the password sign-in refuse to apply to an unlinked account, and while no break-glass administrator
  exists; re-opening a password is one command and needs nothing;
* every link, flag and rollback is audited (``account.*`` events).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings, get_settings
from nova.infra import db, scope
from nova.infra.models import AccountMigration, DelegationSession, OrbitAccount, User
from nova.services.audit import audit

SCHEMA = 1
MIN_SECRET = 32
BACKUP_ID = re.compile(r"^[A-Za-z0-9._:/-]{6,80}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PRODUCTION_DECISION = "owner-decision"


class ToolError(Exception):
    """A refusal the operator must read: the message says what to do, never what the secret is."""


# --- small helpers --------------------------------------------------------------------------------------------------------


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _secret(env: str, *, name: str) -> str:
    value = os.environ.get(env, "")
    if len(value) < MIN_SECRET:
        raise ToolError(f"{env} ({name}) must be set, at least {MIN_SECRET} characters")
    return value


def email_ref(email: str, salt: str) -> str:
    """A stable reference of an address that cannot be guessed without the salt (same value in every service)."""
    return hmac.new(salt.encode(), normalize_email(email).encode(), hashlib.sha256).hexdigest()[:32]


def mask_email(email: str) -> str:
    local, _, domain = normalize_email(email).partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def show_email(email: str, mode: str, salt: str | None) -> str:
    if mode == "clear":
        return normalize_email(email)
    if mode == "masked":
        return mask_email(email)
    return email_ref(email, salt or "")


def _stamp(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(data: Any) -> str:
    return hashlib.sha256(canonical(data).encode()).hexdigest()


# --- 0. inventory (read only) ---------------------------------------------------------------------------------------------


async def inventory(session: AsyncSession, settings: Settings, *, salt: str, emails: str = "hash") -> dict[str, Any]:
    """Every account with what the reconciliation board needs. Personal data is hashed or masked unless asked for."""
    users = (await session.scalars(select(User).order_by(User.created_at, User.id))).all()
    clearances = {r.user_id: r.clearance for r in (await session.scalars(select(OrbitAccount))).all()}
    states = {m.user_id: m for m in (await session.scalars(select(AccountMigration))).all()}
    by_email: dict[str, list[uuid.UUID]] = {}
    for user in users:
        if normalize_email(user.email) and not user.is_service:
            by_email.setdefault(normalize_email(user.email), []).append(user.id)
    accounts = []
    for user in users:
        email = normalize_email(user.email)
        state = states.get(user.id)
        problems = []
        if not user.is_service:
            if not email or not EMAIL.match(email):
                problems.append("email_not_verifiable")
            if email and len(by_email.get(email, [])) > 1:
                problems.append("duplicate_email")
        accounts.append(
            {
                "user_id": str(user.id),
                "kind": "service" if user.is_service else "person",
                "email": show_email(user.email, emails, salt) if email else None,
                "email_domain": email.partition("@")[2] or None,
                "subject_ref": hashlib.sha256(f"{salt}:{user.subject}".encode()).hexdigest()[:32],
                "role": "admin" if user.is_admin else "member",
                "realm_roles": sorted(user.realm_roles or []),
                "clearance": clearances.get(user.id, settings.default_clearance),
                "clearance_source": "orbit" if user.id in clearances else "default",
                "workspace_id": str(user.__dict__.get("workspace_id") or settings.default_workspace_id),
                "created_at": _stamp(user.created_at),
                "last_seen_at": _stamp(user.last_seen_at),
                "orion_sub": state.orion_sub if state else None,
                "password_login_disabled": bool(state and state.password_login_disabled),
                "sso_required": bool(state and state.sso_required),
                "break_glass": bool(state and state.break_glass),
                "problems": problems,
            }
        )
    delegations = await session.scalar(select(func.count()).select_from(DelegationSession))
    return {
        "schema": SCHEMA,
        "service": "nova",
        "generated_at": datetime.now(UTC).isoformat(),
        "emails": emails,
        "summary": {
            "accounts": len(accounts),
            "people": sum(a["kind"] == "person" for a in accounts),
            "service_accounts": sum(a["kind"] == "service" for a in accounts),
            "admins": sum(a["role"] == "admin" for a in accounts),
            "linked": sum(a["orion_sub"] is not None for a in accounts),
            "never_seen": sum(a["last_seen_at"] is None for a in accounts),
            "duplicate_emails": sum("duplicate_email" in a["problems"] for a in accounts),
            "email_not_verifiable": sum("email_not_verifiable" in a["problems"] for a in accounts),
            "break_glass": sum(a["break_glass"] for a in accounts),
        },
        # Keys and credentials: what exists, never a value
        "keys": {
            "orbit_agent_keys": sorted(settings.orbit_agent_key_map()),  # project slugs only
            "forge_api_key_set": bool(settings.forge_api_key),
            "forge_inbound_token_set": bool(settings.forge_inbound_token),
            "forge_inbound_auth": settings.forge_inbound_auth if hasattr(settings, "forge_inbound_auth") else "token",
            "delegation_sessions": int(delegations or 0),
        },
        "accounts": accounts,
    }


def render(report: dict[str, Any], fmt: str) -> str:
    if fmt == "json":
        return json.dumps(report, indent=1, ensure_ascii=False) + "\n"
    columns = [
        "user_id", "kind", "email", "email_domain", "role", "clearance", "clearance_source", "workspace_id",
        "last_seen_at", "orion_sub", "password_login_disabled", "sso_required", "break_glass", "problems",
    ]  # fmt: skip
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns)
    for account in report["accounts"]:
        writer.writerow([";".join(account[c]) if c == "problems" else account[c] for c in columns])
    return out.getvalue()


# --- 1. reconciliation (dry run) ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class IdpAccount:
    sub: str
    email: str
    email_verified: bool
    workspace_id: str | None = None


def load_idp_export(path: Path) -> list[IdpAccount]:
    """The IdP's list of accounts: JSON (a list, or ``{"users": [...]}``) or CSV with ``sub,email,email_verified[,workspace_id]``."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        rows: list[dict[str, Any]] = list(csv.DictReader(io.StringIO(text)))
    else:
        data = json.loads(text)
        rows = data["users"] if isinstance(data, dict) else data
    accounts = []
    for i, row in enumerate(rows):
        sub = str(row.get("sub") or row.get("id") or "").strip()
        if not sub:
            raise ToolError(f"{path.name}: row {i + 1} has no sub")
        verified = row.get("email_verified", row.get("emailVerified", False))
        accounts.append(
            IdpAccount(
                sub=sub,
                email=normalize_email(row.get("email")),
                email_verified=verified is True or str(verified).strip().lower() in ("true", "1", "yes"),
                workspace_id=(str(row.get("workspace_id") or row.get("orion_workspace_id") or "").lower() or None),
            )
        )
    return accounts


@dataclass
class Proposal:
    links: list[dict[str, Any]] = field(default_factory=list)  # what could be linked
    conflicts: list[dict[str, Any]] = field(default_factory=list)  # what must be decided by a person
    already_linked: int = 0
    unmatched_local: list[str] = field(default_factory=list)  # user ids with no IdP account (stay local, "to reconcile")
    unmatched_idp: list[str] = field(default_factory=list)  # subs with no local account

    @property
    def sha256(self) -> str:
        return sha256(
            sorted(({"user_id": link["user_id"], "sub": link["sub"]} for link in self.links), key=lambda x: x["user_id"])
        )

    def as_dict(self, salt: str, emails: str = "hash") -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "proposal_sha256": self.sha256,
            "summary": {
                "proposed": len(self.links),
                "conflicts": len(self.conflicts),
                "already_linked": self.already_linked,
                "unmatched_local": len(self.unmatched_local),
                "unmatched_idp": len(self.unmatched_idp),
            },
            "links": [{**link, "email": show_email(link["email"], emails, salt)} for link in self.links],
            "conflicts": [
                {**c, "email": show_email(c["email"], emails, salt) if c.get("email") else None} for c in self.conflicts
            ],
            "unmatched_local": self.unmatched_local,
            "unmatched_idp": self.unmatched_idp,
        }


def _domain_ok(email: str, domains: list[str]) -> bool:
    return "*" in domains or email.partition("@")[2] in domains


async def propose(session: AsyncSession, idp: list[IdpAccount], *, domains: list[str]) -> Proposal:
    """The local account <-> IdP ``sub`` table the data supports. A pair is proposed only when nothing is in doubt."""
    users = [u for u in (await session.scalars(select(User))).all() if not u.is_service]
    states = {m.user_id: m for m in (await session.scalars(select(AccountMigration))).all()}
    linked_subs = {m.orion_sub: m.user_id for m in states.values() if m.orion_sub}
    result = Proposal()
    local_by_email: dict[str, list[User]] = {}
    for user in users:
        local_by_email.setdefault(normalize_email(user.email), []).append(user)
    idp_by_email: dict[str, list[IdpAccount]] = {}
    for account in idp:
        idp_by_email.setdefault(account.email, []).append(account)
    seen_subs = {a.sub for a in idp}

    def conflict(kind: str, user: User | None, sub: str | None, email: str) -> None:
        result.conflicts.append({"kind": kind, "user_id": str(user.id) if user else None, "sub": sub, "email": email})

    for user in users:
        email = normalize_email(user.email)
        state = states.get(user.id)
        if state and state.orion_sub:
            if state.orion_sub in seen_subs:
                result.already_linked += 1
                continue
            conflict("linked_sub_missing_in_idp", user, state.orion_sub, email)
            continue
        if not email or not EMAIL.match(email):
            conflict("email_missing", user, None, email)
            continue
        if len(local_by_email[email]) > 1:
            conflict("duplicate_local_email", user, None, email)  # merged by an administrator, never automatically (§8)
            continue
        if not _domain_ok(email, domains):
            conflict("unexpected_domain", user, None, email)
            continue
        candidates = idp_by_email.get(email, [])
        if not candidates:
            result.unmatched_local.append(str(user.id))
            continue
        if len(candidates) > 1:
            conflict("duplicate_idp_email", user, None, email)
            continue
        (account,) = candidates
        if not account.email_verified:
            conflict("idp_email_unverified", user, account.sub, email)  # the address alone proves nothing
            continue
        if account.sub in linked_subs and linked_subs[account.sub] != user.id:
            conflict("sub_already_linked", user, account.sub, email)
            continue
        local_workspace = str(user.__dict__.get("workspace_id") or get_settings().default_workspace_id).lower()
        if account.workspace_id and account.workspace_id != local_workspace:
            conflict("workspace_mismatch", user, account.sub, email)  # the workspace comes from the inventory, not the domain
            continue
        result.links.append({"user_id": str(user.id), "sub": account.sub, "email": email, "workspace_id": local_workspace})
    # an IdP account is unmatched when no local account carries its address (a conflict is not "unmatched")
    result.unmatched_idp = sorted(a.sub for a in idp if a.email not in local_by_email and a.sub not in linked_subs)
    result.links.sort(key=lambda link: link["user_id"])
    return result


# --- 2. approval (signed) and apply ---------------------------------------------------------------------------------------


def approval_template(proposal: Proposal, *, batch: str | None = None) -> dict[str, Any]:
    """To be reviewed: delete the pairs that must NOT be linked, then sign. Nothing is approved until signed."""
    return {
        "schema": SCHEMA,
        "batch": batch or f"mig-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(3)}",
        "proposal_sha256": proposal.sha256,
        "approved": [{"user_id": link["user_id"], "sub": link["sub"]} for link in proposal.links],
        "approved_by": None,
        "approved_at": None,
        "signature": None,
    }


def _signed_part(doc: dict[str, Any]) -> bytes:
    body = {k: doc.get(k) for k in ("schema", "batch", "proposal_sha256", "approved", "approved_by", "approved_at")}
    body["approved"] = sorted(body["approved"] or [], key=lambda x: (x["user_id"], x["sub"]))
    return canonical(body).encode()


def sign_approval(doc: dict[str, Any], key: str, approved_by: str) -> dict[str, Any]:
    if not approved_by.strip():
        raise ToolError("--approved-by is required")
    signed = {**doc, "approved_by": approved_by.strip(), "approved_at": datetime.now(UTC).isoformat()}
    signed["signature"] = hmac.new(key.encode(), _signed_part(signed), hashlib.sha256).hexdigest()
    return signed


def verify_approval(doc: dict[str, Any], key: str) -> None:
    signature = doc.get("signature")
    if not signature or not doc.get("approved_by") or not isinstance(doc.get("approved"), list):
        raise ToolError("the approval file is not signed")
    expected = hmac.new(key.encode(), _signed_part(doc), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(signature), expected):
        raise ToolError("the approval signature does not match its content (edited after signing, or another key)")


def _guard_write(settings: Settings) -> None:
    if settings.is_production and os.environ.get("ORION_MIGRATION_ALLOW_PRODUCTION") != PRODUCTION_DECISION:
        raise ToolError(
            "refused in production: executing the migration there is the owner's separate decision "
            f"(ORION_MIGRATION_ALLOW_PRODUCTION={PRODUCTION_DECISION})"
        )


def _backup(backup_id: str | None) -> str:
    if not backup_id or not BACKUP_ID.match(backup_id):
        raise ToolError("--confirm-backup <id> is required: take a backup of the database and give its identifier")
    return backup_id


async def apply_links(
    session: AsyncSession,
    settings: Settings,
    idp: list[IdpAccount],
    approval: dict[str, Any],
    *,
    key: str,
    backup_id: str | None,
    domains: list[str],
) -> dict[str, Any]:
    """Link the approved pairs, all or nothing. Anything that changed since the dry run aborts it."""
    _guard_write(settings)
    backup = _backup(backup_id)
    verify_approval(approval, key)
    proposal = await propose(session, idp, domains=domains)
    if approval["proposal_sha256"] != proposal.sha256:
        raise ToolError("the data moved since the approval (new proposal differs): run reconcile again and re-approve")
    current = {(link["user_id"], link["sub"]) for link in proposal.links}
    approved = {(a["user_id"], a["sub"]) for a in approval["approved"]}
    unknown = approved - current
    if unknown:
        raise ToolError(f"{len(unknown)} approved pair(s) are not in the current proposal: nothing was changed")
    if not approved:
        raise ToolError("the approval lists no pair")
    batch, now = str(approval["batch"]), datetime.now(UTC)
    for user_id, sub in sorted(approved):
        uid = uuid.UUID(user_id)
        row = await session.get(AccountMigration, uid)
        if row is None:
            row = AccountMigration(user_id=uid)
            session.add(row)
        row.orion_sub, row.linked_at, row.linked_batch = sub, now, batch
        await audit(
            session,
            actor_id=None,
            action="account.link",
            target_type="user",
            target_id=user_id,
            summary="Account linked to its IdP identity (migration tool)",
            details={"batch": batch, "backup": backup, "approved_by": approval["approved_by"], "sub": sub},
        )
    await session.flush()
    return {"batch": batch, "linked": len(approved), "backup": backup, "approved_by": approval["approved_by"]}


async def rollback_batch(session: AsyncSession, settings: Settings, batch: str, *, backup_id: str | None) -> dict[str, Any]:
    """Undo one batch: its links are removed, and the passwords its flags closed are re-opened. Accounts are never deleted."""
    _guard_write(settings)
    backup = _backup(backup_id)
    rows = (
        await session.scalars(
            select(AccountMigration).where((AccountMigration.linked_batch == batch) | (AccountMigration.flags_batch == batch))
        )
    ).all()
    if not rows:
        raise ToolError(f"no account belongs to batch {batch}")
    for row in rows:
        if row.linked_batch == batch:
            row.orion_sub, row.linked_at, row.linked_batch = None, None, None
        if row.flags_batch == batch:
            row.password_login_disabled = row.sso_required = False
            row.flags_batch = None
        await audit(
            session,
            actor_id=None,
            action="account.rollback",
            target_type="user",
            target_id=str(row.user_id),
            summary="Migration batch rolled back",
            details={"batch": batch, "backup": backup},
        )
    return {"batch": batch, "accounts": len(rows)}


# --- 3. flags and break-glass ------------------------------------------------------------------------------------------------


async def find_user(session: AsyncSession, ref: str) -> User:
    try:
        user = await session.get(User, uuid.UUID(ref))
    except ValueError:
        matches = (await session.scalars(select(User).where(func.lower(User.email) == normalize_email(ref)))).all()
        if len(matches) > 1:
            raise ToolError("several accounts share this address: use the user id") from None
        user = matches[0] if matches else None
    if user is None:
        raise ToolError("no such account")
    return user


async def _state(session: AsyncSession, user: User) -> AccountMigration:
    row = await session.get(AccountMigration, user.id)
    if row is None:
        row = AccountMigration(user_id=user.id)
        session.add(row)
        await session.flush()
    return row


async def _break_glass_admins(session: AsyncSession, *, besides: uuid.UUID | None = None) -> int:
    query = select(func.count()).select_from(AccountMigration).where(AccountMigration.break_glass.is_(True))
    if besides:
        query = query.where(AccountMigration.user_id != besides)
    return int(await session.scalar(query) or 0)


async def close_password(
    session: AsyncSession, settings: Settings, ref: str, *, sso_required: bool, backup_id: str | None, batch: str | None = None
) -> dict[str, Any]:
    """Phase 3: the password sign-in of a linked account is closed. Refused without a break-glass administrator."""
    _guard_write(settings)
    backup = _backup(backup_id)
    user = await find_user(session, ref)
    row = await _state(session, user)
    if user.is_service:
        raise ToolError("a service account has no password sign-in to close")
    if row.break_glass:
        raise ToolError("a break-glass account keeps its password: unset break-glass first")
    if not row.orion_sub:
        raise ToolError("this account is not linked to an IdP identity: its password is its only way in")
    if await _break_glass_admins(session) == 0:
        raise ToolError("no break-glass administrator exists: create one before closing any password (ADR §8)")
    row.sso_required, row.password_login_disabled = sso_required, not sso_required
    row.flags_batch = batch or f"flags-{datetime.now(UTC):%Y%m%d}-{secrets.token_hex(3)}"
    await audit(
        session,
        actor_id=None,
        action="account.password_closed",
        target_type="user",
        target_id=str(user.id),
        summary="Password sign-in closed (migration tool)",
        details={
            "flag": "sso_required" if sso_required else "password_login_disabled",
            "backup": backup,
            "batch": row.flags_batch,
        },
    )
    return {
        "user_id": str(user.id),
        "flag": "sso_required" if sso_required else "password_login_disabled",
        "batch": row.flags_batch,
    }


async def enable_password(session: AsyncSession, ref: str) -> dict[str, Any]:
    """The way back, in one command: no backup, no approval (an emergency must not wait for a ceremony)."""
    user = await find_user(session, ref)
    row = await session.get(AccountMigration, user.id)
    if row is not None:
        row.password_login_disabled = row.sso_required = False
    await audit(
        session, actor_id=None, action="account.password_reopened", target_type="user", target_id=str(user.id),
        summary="Password sign-in re-opened (migration tool)",
    )  # fmt: skip
    return {"user_id": str(user.id), "password_login": "enabled"}


async def set_break_glass(
    session: AsyncSession, settings: Settings, ref: str, *, unset: bool, backup_id: str | None
) -> dict[str, Any]:
    """The administrator account that stays outside SSO, with its password (held offline)."""
    _guard_write(settings)
    backup = _backup(backup_id)
    user = await find_user(session, ref)
    row = await _state(session, user)
    if unset:
        if row.break_glass and await _break_glass_admins(session, besides=user.id) == 0:
            closed = await session.scalar(
                select(func.count()).select_from(AccountMigration).where(
                    (AccountMigration.password_login_disabled.is_(True)) | (AccountMigration.sso_required.is_(True))
                )
            )  # fmt: skip
            if closed:
                raise ToolError("it is the last break-glass administrator and passwords are closed: add another one first")
        row.break_glass = False
    else:
        if not user.is_admin or user.is_service:
            raise ToolError("a break-glass account must be a person with the administrator role")
        row.break_glass, row.password_login_disabled, row.sso_required = True, False, False
    await audit(
        session,
        actor_id=None,
        action="account.break_glass_unset" if unset else "account.break_glass_set",
        target_type="user",
        target_id=str(user.id),
        summary="Break-glass administrator " + ("removed" if unset else "declared") + " (migration tool)",
        details={"backup": backup},
    )
    return {"user_id": str(user.id), "break_glass": not unset}


# --- command line -----------------------------------------------------------------------------------------------------------


def _write(path: str | None, text: str) -> None:
    if not path:
        sys.stdout.write(text)
        return
    target = Path(path)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # personal data: owner only
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    print(f"written: {target}", file=sys.stderr)


def _read_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _domains(args: argparse.Namespace, settings: Settings) -> list[str]:
    return [d.strip().lower() for d in (args.domains.split(",") if args.domains else settings.signup_domain_list) if d.strip()]


def _emails(args: argparse.Namespace) -> str:
    if args.emails == "clear" and not args.confirm_sensitive:
        raise ToolError("--emails clear writes personal data: add --confirm-sensitive")
    return args.emails


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    db.configure()
    command = args.command
    with scope.platform_scope():  # every workspace: this is an operator tool, not a request
        async with db.sessionmaker()() as session:
            if command == "inventory":
                salt = (
                    _secret("ORION_INVENTORY_SALT", name="shared by the three services")
                    if args.emails == "hash"
                    else os.environ.get("ORION_INVENTORY_SALT", "x" * MIN_SECRET)
                )
                report = await inventory(session, settings, salt=salt, emails=_emails(args))
                await session.rollback()
                _write(args.out, render(report, args.format))
            elif command == "reconcile":
                salt = (
                    _secret("ORION_INVENTORY_SALT", name="shared by the three services")
                    if args.emails == "hash"
                    else os.environ.get("ORION_INVENTORY_SALT", "x" * MIN_SECRET)
                )
                proposal = await propose(session, load_idp_export(Path(args.idp_export)), domains=_domains(args, settings))
                await session.rollback()  # dry run: nothing is ever written here
                _write(args.out, json.dumps(proposal.as_dict(salt, _emails(args)), indent=1) + "\n")
                if args.emit_approval:
                    _write(args.emit_approval, json.dumps(approval_template(proposal), indent=1) + "\n")
            elif command == "sign-approval":
                doc = _read_json(args.file)
                _write(
                    args.file,
                    json.dumps(
                        sign_approval(doc, _secret("ORION_APPROVAL_KEY", name="held by the approver"), args.approved_by), indent=1
                    )
                    + "\n",
                )
            elif command == "apply":
                approval = _read_json(args.approval)
                result = await apply_links(
                    session, settings, load_idp_export(Path(args.idp_export)), approval,
                    key=_secret("ORION_APPROVAL_KEY", name="held by the approver"), backup_id=args.confirm_backup, domains=_domains(args, settings),
                )  # fmt: skip
                await session.commit()
                print(json.dumps(result))
            elif command == "rollback":
                result = await rollback_batch(session, settings, args.batch, backup_id=args.confirm_backup)
                await session.commit()
                print(json.dumps(result))
            elif command == "flags":
                if args.enable_password:
                    result = await enable_password(session, args.user)
                elif args.disable_password or args.sso_required:
                    result = await close_password(
                        session, settings, args.user, sso_required=args.sso_required, backup_id=args.confirm_backup
                    )
                else:
                    raise ToolError("flags needs --disable-password, --sso-required or --enable-password")
                await session.commit()
                print(json.dumps(result))
            elif command == "break-glass":
                result = await set_break_glass(session, settings, args.user, unset=args.unset, backup_id=args.confirm_backup)
                await session.commit()
                print(json.dumps(result))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m nova.migration.accounts", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True)

    def emails(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--emails", choices=["hash", "masked", "clear"], default="hash")
        sp.add_argument("--confirm-sensitive", action="store_true", help="needed for --emails clear")
        sp.add_argument("--out", help="write to this file (mode 0600) instead of stdout")

    inv = sub.add_parser("inventory", help="read-only inventory of the accounts")
    emails(inv)
    inv.add_argument("--format", choices=["json", "csv"], default="json")
    rec = sub.add_parser("reconcile", help="dry run: propose the account <-> IdP sub table, never writes")
    emails(rec)
    rec.add_argument("--idp-export", required=True)
    rec.add_argument("--domains", help="comma-separated expected e-mail domains (default: NOVA_SIGNUP_DOMAINS)")
    rec.add_argument("--emit-approval", help="write the approval template to review and sign")
    sig = sub.add_parser("sign-approval", help="sign a reviewed approval file (ORION_APPROVAL_KEY)")
    sig.add_argument("file")
    sig.add_argument("--approved-by", required=True)
    app = sub.add_parser("apply", help="link the approved pairs (needs --confirm-backup and a signed approval)")
    app.add_argument("--idp-export", required=True)
    app.add_argument("--approval", required=True)
    app.add_argument("--domains")
    app.add_argument("--confirm-backup", metavar="ID")
    rb = sub.add_parser("rollback", help="undo one batch of links / flags")
    rb.add_argument("--batch", required=True)
    rb.add_argument("--confirm-backup", metavar="ID")
    fl = sub.add_parser("flags", help="close or re-open the password sign-in of one account")
    fl.add_argument("--user", required=True)
    group = fl.add_mutually_exclusive_group(required=True)
    group.add_argument("--disable-password", action="store_true")
    group.add_argument("--sso-required", action="store_true")
    group.add_argument("--enable-password", action="store_true", help="the way back: one command, no backup needed")
    fl.add_argument("--confirm-backup", metavar="ID")
    bg = sub.add_parser("break-glass", help="declare (or remove) the break-glass administrator of this service")
    bg.add_argument("--user", required=True)
    bg.add_argument("--unset", action="store_true")
    bg.add_argument("--confirm-backup", metavar="ID")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except ToolError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

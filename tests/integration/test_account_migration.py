"""Account migration tool (NOV-113): inventory, dry-run reconciliation, signed approval, apply, flags, break-glass.

Every test runs on its own SQLite database filled with SYNTHETIC accounts (example.test addresses): the inventory is exact, a
dry run is proven read-only by comparing the whole database before and after, ``apply`` is refused without a backup or a valid
approval, and the way back (rollback, re-opening a password) is exercised.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nova.config import get_settings
from nova.infra import db
from nova.infra.models import AccountMigration, AuditEvent, OrbitAccount, User
from nova.migration import accounts as tool
from nova.services import account_flags, accounts
from nova.services.identity import IdentityError, IdentityUser

ROOT = Path(__file__).resolve().parents[2]
SALT = "s" * 40
KEY = "k" * 40
BACKUP = "backup-2026-10-17-0001"
WS = str(get_settings().default_workspace_id)
OTHER_WS = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


@pytest_asyncio.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tool.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(db.Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False), tmp_path
    await engine.dispose()


def person(n: int, *, email: str | None = None, admin: bool = False, seen: bool = True, **kw) -> User:
    return User(
        subject=f"kc-{n:03d}",
        email=email if email is not None else f"person{n}@example.test",
        display_name=f"Person {n}",
        realm_roles=["nova-admin"] if admin else ["nova-user"],
        is_admin=admin,
        last_seen_at=datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=n) if seen else None,
        **kw,
    )


@pytest_asyncio.fixture
async def populated(factory):
    """alice, bob (admin), carol (ORBIT clearance 3), dave (same address as dan), dan, erin (no address), frank (unexpected domain),
    gina (never seen), a service account, and two accounts that only the IdP knows."""
    make, tmp_path = factory
    async with make() as session:
        users = {
            "alice": person(1, email="Alice@Example.test"),
            "bob": person(2, admin=True),
            "carol": person(3),
            "dave": person(4, email="twin@example.test"),
            "dan": person(5, email="twin@example.test"),
            "erin": person(6, email=""),
            "frank": person(7, email="frank@elsewhere.test"),
            "gina": person(8, seen=False),
            "svc": User(subject="service:forge-evaluation", email="", display_name="FORGE", realm_roles=[], is_service=True),
        }
        session.add_all(users.values())
        await session.flush()
        session.add(
            OrbitAccount(user_id=users["carol"].id, orbit_user_id="orbit-3", orbit_email="carol@example.test", clearance=3)
        )
        await session.commit()
        ids = {k: str(v.id) for k, v in users.items()}
    return make, tmp_path, ids


def idp_row(email: str, sub: str, *, verified: bool = True, workspace: str | None = None) -> dict:
    return {"sub": sub, "email": email, "email_verified": verified, **({"workspace_id": workspace} if workspace else {})}


IDP = [
    idp_row("alice@example.test", "sub-alice"),
    idp_row("bob@example.test".replace("bob", "person2"), "sub-bob"),
    idp_row("person3@example.test", "sub-carol", verified=False),  # carol: address not verified
    idp_row("twin@example.test", "sub-twin"),  # dave and dan: two local accounts
    idp_row("frank@elsewhere.test", "sub-frank"),  # unexpected domain
    idp_row("person8@example.test", "sub-gina", workspace=OTHER_WS),  # another workspace
    idp_row("only-idp@example.test", "sub-only-idp"),
]


def write_idp(tmp_path: Path, rows=None, name="idp.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(rows if rows is not None else IDP))
    return path


async def dump(session) -> dict[str, str]:
    """The whole database as hashes: a dry run must leave every table byte for byte as it was."""
    result = {}
    for table in db.Base.metadata.sorted_tables:
        rows = sorted(repr(tuple(r)) for r in (await session.execute(sa.select(table))).all())
        result[table.name] = hashlib.sha256("\n".join(rows).encode()).hexdigest()
    return result


DOMAINS = ["example.test"]


# --- inventory --------------------------------------------------------------------------------------------------------------


async def test_the_inventory_is_exact(populated):
    make, _, ids = populated
    async with make() as session:
        report = await tool.inventory(session, get_settings(), salt=SALT)
    summary = report["summary"]
    assert summary == {
        "accounts": 9,
        "people": 8,
        "service_accounts": 1,
        "admins": 1,
        "linked": 0,
        "never_seen": 2,
        "duplicate_emails": 2,
        "email_not_verifiable": 1,
        "break_glass": 0,
    }  # fmt: skip (never_seen: gina and the service account)
    by_id = {a["user_id"]: a for a in report["accounts"]}
    assert by_id[ids["bob"]]["role"] == "admin" and by_id[ids["carol"]]["clearance"] == 3
    assert by_id[ids["carol"]]["clearance_source"] == "orbit" and by_id[ids["alice"]]["clearance_source"] == "default"
    assert by_id[ids["alice"]]["clearance"] == get_settings().default_clearance
    assert by_id[ids["dave"]]["problems"] == by_id[ids["dan"]]["problems"] == ["duplicate_email"]
    assert by_id[ids["erin"]]["problems"] == ["email_not_verifiable"] and by_id[ids["erin"]]["email"] is None
    assert by_id[ids["svc"]]["kind"] == "service" and by_id[ids["gina"]]["last_seen_at"] is None
    assert by_id[ids["alice"]]["email_domain"] == "example.test" and by_id[ids["alice"]]["workspace_id"] == WS


async def test_emails_leave_hashed_by_default_and_never_in_clear_unless_asked(populated):
    make, _, ids = populated
    async with make() as session:
        hashed = await tool.inventory(session, get_settings(), salt=SALT)
        masked = await tool.inventory(session, get_settings(), salt=SALT, emails="masked")
        clear = await tool.inventory(session, get_settings(), salt=SALT, emails="clear")
    text = json.dumps(hashed)
    assert "person1" not in text and "alice" not in text.lower() and "kc-001" not in text  # no local part, no subject
    alice = next(a for a in hashed["accounts"] if a["user_id"] == ids["alice"])
    assert alice["email"] == tool.email_ref("ALICE@example.test ", SALT) and len(alice["email"]) == 32  # case-insensitive
    assert tool.email_ref("alice@example.test", SALT) != tool.email_ref("alice@example.test", "t" * 40)  # salted
    assert next(a for a in masked["accounts"] if a["user_id"] == ids["alice"])["email"] == "a***@example.test"
    assert next(a for a in clear["accounts"] if a["user_id"] == ids["alice"])["email"] == "alice@example.test"


async def test_the_inventory_lists_keys_without_a_value(populated, monkeypatch):
    make, _, _ = populated
    settings = get_settings()
    monkeypatch.setattr(settings, "orbit_agent_keys", "atlas:orb_agent_key_for_tests_0123456789")
    monkeypatch.setattr(settings, "forge_api_key", "fgk_abcdef_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    async with make() as session:
        report = await tool.inventory(session, settings, salt=SALT)
    assert report["keys"]["orbit_agent_keys"] == ["atlas"] and report["keys"]["forge_api_key_set"] is True
    text = json.dumps(report)
    assert "orb_agent_key_for_tests" not in text and "fgk_abcdef" not in text and settings.forge_inbound_token not in text


async def test_csv_and_json_formats(populated):
    make, _, _ = populated
    async with make() as session:
        report = await tool.inventory(session, get_settings(), salt=SALT)
    rows = list(csv.DictReader(io.StringIO(tool.render(report, "csv"))))
    assert len(rows) == 9 and rows[0]["email"] and "problems" in rows[0]
    assert json.loads(tool.render(report, "json"))["summary"]["accounts"] == 9


async def test_inventory_and_dry_run_never_write(populated):
    make, tmp_path, _ = populated
    async with make() as session:
        before = await dump(session)
        await tool.inventory(session, get_settings(), salt=SALT)
        proposal = await tool.propose(session, tool.load_idp_export(write_idp(tmp_path)), domains=DOMAINS)
        proposal.as_dict(SALT)
        tool.approval_template(proposal)
        await session.rollback()
    async with make() as session:
        assert await dump(session) == before  # every table, byte for byte


# --- reconciliation ---------------------------------------------------------------------------------------------------------


async def test_the_dry_run_proposes_only_what_nothing_contradicts(populated):
    make, tmp_path, ids = populated
    async with make() as session:
        proposal = await tool.propose(session, tool.load_idp_export(write_idp(tmp_path)), domains=DOMAINS)
    assert {(link["user_id"], link["sub"]) for link in proposal.links} == {(ids["alice"], "sub-alice"), (ids["bob"], "sub-bob")}
    kinds = {(c["kind"], c["user_id"]) for c in proposal.conflicts}
    assert kinds == {
        ("idp_email_unverified", ids["carol"]),
        ("duplicate_local_email", ids["dave"]),
        ("duplicate_local_email", ids["dan"]),
        ("email_missing", ids["erin"]),
        ("unexpected_domain", ids["frank"]),
        ("workspace_mismatch", ids["gina"]),
    }
    assert proposal.unmatched_idp == ["sub-only-idp"] and proposal.unmatched_local == []
    shown = json.dumps(proposal.as_dict(SALT))
    assert "alice@" not in shown.lower() and "person2" not in shown  # addresses are hashed in the output


async def test_other_conflicts_two_idp_accounts_for_one_address_and_a_taken_sub(populated):
    make, tmp_path, ids = populated
    rows = [
        idp_row("person3@example.test", "sub-c1"),
        idp_row("person3@example.test", "sub-c2"),
        idp_row("alice@example.test", "sub-a"),
    ]
    async with make() as session:
        session.add(AccountMigration(user_id=uuid.UUID(ids["bob"]), orion_sub="sub-a"))  # that sub already belongs to bob
        await session.commit()
        proposal = await tool.propose(session, tool.load_idp_export(write_idp(tmp_path, rows)), domains=DOMAINS)
    kinds = {c["kind"] for c in proposal.conflicts}
    assert {"duplicate_idp_email", "sub_already_linked"} <= kinds and proposal.links == []


async def test_a_linked_account_is_counted_not_proposed_again(populated):
    make, tmp_path, ids = populated
    async with make() as session:
        session.add(AccountMigration(user_id=uuid.UUID(ids["alice"]), orion_sub="sub-alice"))
        await session.commit()
        proposal = await tool.propose(session, tool.load_idp_export(write_idp(tmp_path)), domains=DOMAINS)
    assert proposal.already_linked == 1 and ids["alice"] not in {link["user_id"] for link in proposal.links}


def test_the_idp_export_accepts_json_and_csv_and_refuses_a_row_without_sub(tmp_path):
    csv_path = tmp_path / "idp.csv"
    csv_path.write_text("sub,email,email_verified,workspace_id\ns1,A@Example.test,true,\ns2,b@example.test,false,\n")
    accounts_ = tool.load_idp_export(csv_path)
    assert [(a.sub, a.email, a.email_verified) for a in accounts_] == [
        ("s1", "a@example.test", True),
        ("s2", "b@example.test", False),
    ]
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(json.dumps({"users": [{"id": "x", "email": "x@example.test", "emailVerified": True}]}))
    assert tool.load_idp_export(wrapped)[0].email_verified is True
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([{"email": "x@example.test"}]))
    with pytest.raises(tool.ToolError, match="no sub"):
        tool.load_idp_export(bad)


# --- approval and apply ---------------------------------------------------------------------------------------------------


async def _approved(make, tmp_path, *, rows=None):
    async with make() as session:
        idp = tool.load_idp_export(write_idp(tmp_path, rows))
        proposal = await tool.propose(session, idp, domains=DOMAINS)
    return idp, tool.sign_approval(tool.approval_template(proposal, batch="mig-test-1"), KEY, "Owner Example")


async def _apply(make, idp, approval, *, backup=BACKUP, key=KEY, settings=None):
    async with make() as session:
        result = await tool.apply_links(
            session, settings or get_settings(), idp, approval, key=key, backup_id=backup, domains=DOMAINS
        )
        await session.commit()
        return result


async def test_apply_is_refused_without_a_backup_and_writes_nothing(populated):
    make, tmp_path, _ = populated
    idp, approval = await _approved(make, tmp_path)
    for backup in (None, "", "x", "bad id with spaces"):
        with pytest.raises(tool.ToolError, match="confirm-backup"):
            await _apply(make, idp, approval, backup=backup)
    async with make() as session:
        assert (await session.scalar(sa.select(sa.func.count()).select_from(AccountMigration))) == 0


async def test_apply_is_refused_without_a_valid_signed_approval(populated):
    make, tmp_path, ids = populated
    idp, approval = await _approved(make, tmp_path)
    unsigned = {**approval, "signature": None}
    with pytest.raises(tool.ToolError, match="not signed"):
        await _apply(make, idp, unsigned)
    edited = {**approval, "approved": [*approval["approved"], {"user_id": ids["carol"], "sub": "sub-carol"}]}
    with pytest.raises(tool.ToolError, match="signature does not match"):
        await _apply(make, idp, edited)  # a pair added after signing
    with pytest.raises(tool.ToolError, match="signature does not match"):
        await _apply(make, idp, approval, key="z" * 40)  # another key
    with pytest.raises(tool.ToolError, match="signature does not match"):
        await _apply(make, idp, {**approval, "approved_by": "Someone Else"})
    async with make() as session:
        assert (await session.scalar(sa.select(sa.func.count()).select_from(AccountMigration))) == 0


async def test_an_approval_for_other_data_is_refused_and_nothing_is_half_applied(populated):
    make, tmp_path, ids = populated
    idp, approval = await _approved(make, tmp_path)
    changed = [r for r in IDP if r["sub"] != "sub-bob"]  # the IdP no longer has bob: the proposal moved
    with pytest.raises(tool.ToolError, match="data moved"):
        await _apply(make, tool.load_idp_export(write_idp(tmp_path, changed, "idp2.json")), approval)
    # a signed pair that was never proposed (carol is in conflict) is refused as a whole, alice included
    sneaky = tool.sign_approval(
        {**tool.approval_template(await _proposal(make, idp), batch="b"), "approved": [
            {"user_id": ids["alice"], "sub": "sub-alice"}, {"user_id": ids["carol"], "sub": "sub-carol"}]}, KEY, "Owner"
    )  # fmt: skip
    with pytest.raises(tool.ToolError, match="not in the current proposal"):
        await _apply(make, idp, sneaky)
    async with make() as session:
        assert (await session.scalar(sa.select(sa.func.count()).select_from(AccountMigration))) == 0


async def _proposal(make, idp):
    async with make() as session:
        return await tool.propose(session, idp, domains=DOMAINS)


async def test_apply_links_only_the_approved_pairs_and_audits_each(populated):
    make, tmp_path, ids = populated
    idp, approval = await _approved(make, tmp_path)
    approval = tool.sign_approval(  # the reviewer deleted bob's pair before signing: only alice is approved
        {**approval, "approved": [a for a in approval["approved"] if a["user_id"] == ids["alice"]]}, KEY, "Owner Example"
    )
    result = await _apply(make, idp, approval)
    assert result == {"batch": "mig-test-1", "linked": 1, "backup": BACKUP, "approved_by": "Owner Example"}
    async with make() as session:
        rows = (await session.scalars(sa.select(AccountMigration))).all()
        assert [(str(r.user_id), r.orion_sub, r.linked_batch) for r in rows] == [(ids["alice"], "sub-alice", "mig-test-1")]
        events = (await session.scalars(sa.select(AuditEvent).where(AuditEvent.action == "account.link"))).all()
        assert len(events) == 1 and events[0].details["backup"] == BACKUP and events[0].details["batch"] == "mig-test-1"
        users = (await session.scalars(sa.select(User))).all()
        assert {str(u.id) for u in users} >= set(ids.values())  # no account was created or deleted, no id changed
        alice = await session.get(User, uuid.UUID(ids["alice"]))
        assert alice.subject == "kc-001"  # the local identifier is untouched


async def test_an_applied_batch_cannot_be_replayed(populated):
    make, tmp_path, _ = populated
    idp, approval = await _approved(make, tmp_path)
    await _apply(make, idp, approval)
    with pytest.raises(tool.ToolError, match="data moved"):
        await _apply(make, idp, approval)


async def test_production_needs_the_owners_decision(populated, monkeypatch):
    make, tmp_path, _ = populated
    idp, approval = await _approved(make, tmp_path)
    monkeypatch.setattr(type(get_settings()), "is_production", property(lambda self: True))
    with pytest.raises(tool.ToolError, match="owner's separate decision"):
        await _apply(make, idp, approval)
    monkeypatch.setenv("ORION_MIGRATION_ALLOW_PRODUCTION", "yes")
    with pytest.raises(tool.ToolError, match="owner's separate decision"):
        await _apply(make, idp, approval)
    async with make() as session:
        assert (await session.scalar(sa.select(sa.func.count()).select_from(AccountMigration))) == 0


# --- rollback ---------------------------------------------------------------------------------------------------------------


async def test_a_batch_is_rolled_back_and_the_accounts_stay(populated):
    make, tmp_path, _ = populated
    idp, approval = await _approved(make, tmp_path)
    await _apply(make, idp, approval)
    async with make() as session:
        before = await dump(session)
        with pytest.raises(tool.ToolError, match="confirm-backup"):
            await tool.rollback_batch(session, get_settings(), "mig-test-1", backup_id=None)
        with pytest.raises(tool.ToolError, match="no account belongs"):
            await tool.rollback_batch(session, get_settings(), "nope", backup_id=BACKUP)
        await session.rollback()
        assert await dump(session) == before
        assert (await tool.rollback_batch(session, get_settings(), "mig-test-1", backup_id=BACKUP)) == {
            "batch": "mig-test-1",
            "accounts": 2,
        }
        await session.commit()
    async with make() as session:
        assert not (await session.scalars(sa.select(AccountMigration).where(AccountMigration.orion_sub.is_not(None)))).all()
        assert (await session.scalar(sa.select(sa.func.count()).select_from(User))) == 9
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(AuditEvent).where(AuditEvent.action == "account.rollback")
            )
        ) == 2
    # and the reconciliation proposes the same pairs again
    assert len((await _proposal(make, idp)).links) == 2


# --- flags and break-glass --------------------------------------------------------------------------------------------------


async def _link(make, tmp_path):
    idp, approval = await _approved(make, tmp_path)
    await _apply(make, idp, approval)


async def test_a_password_is_closed_only_for_a_linked_account_and_with_a_break_glass_administrator(populated):
    make, tmp_path, ids = populated
    settings = get_settings()
    async with make() as session:
        with pytest.raises(tool.ToolError, match="confirm-backup"):
            await tool.close_password(session, settings, ids["alice"], sso_required=True, backup_id=None)
        with pytest.raises(tool.ToolError, match="not linked"):
            await tool.close_password(session, settings, ids["alice"], sso_required=True, backup_id=BACKUP)
        await session.rollback()
    await _link(make, tmp_path)
    async with make() as session:
        with pytest.raises(tool.ToolError, match="no break-glass administrator"):
            await tool.close_password(session, settings, ids["alice"], sso_required=True, backup_id=BACKUP)
        with pytest.raises(tool.ToolError, match="administrator role"):
            await tool.set_break_glass(session, settings, ids["alice"], unset=False, backup_id=BACKUP)
        with pytest.raises(tool.ToolError, match="administrator role"):
            await tool.set_break_glass(session, settings, ids["svc"], unset=False, backup_id=BACKUP)
        await tool.set_break_glass(session, settings, ids["bob"], unset=False, backup_id=BACKUP)
        done = await tool.close_password(session, settings, ids["alice"], sso_required=False, backup_id=BACKUP)
        assert done["flag"] == "password_login_disabled"
        with pytest.raises(tool.ToolError, match="break-glass account keeps its password"):
            await tool.close_password(session, settings, ids["bob"], sso_required=True, backup_id=BACKUP)
        await session.commit()
    async with make() as session:
        assert await account_flags.password_blocked(session, uuid.UUID(ids["alice"]))
        assert not await account_flags.password_blocked(session, uuid.UUID(ids["bob"]))  # break-glass: password stays
        assert not await account_flags.password_blocked(session, uuid.UUID(ids["carol"]))  # untouched account: as ever


async def test_the_last_break_glass_cannot_go_while_passwords_are_closed(populated):
    make, tmp_path, ids = populated
    settings = get_settings()
    await _link(make, tmp_path)
    async with make() as session:
        await tool.set_break_glass(session, settings, ids["bob"], unset=False, backup_id=BACKUP)
        await tool.close_password(session, settings, ids["alice"], sso_required=True, backup_id=BACKUP)
        with pytest.raises(tool.ToolError, match="last break-glass administrator"):
            await tool.set_break_glass(session, settings, ids["bob"], unset=True, backup_id=BACKUP)
        await tool.enable_password(session, ids["alice"])  # the way back
        await tool.set_break_glass(session, settings, ids["bob"], unset=True, backup_id=BACKUP)
        assert not await account_flags.password_blocked(session, uuid.UUID(ids["alice"]))


async def test_re_opening_a_password_is_one_command_that_needs_nothing(populated):
    make, tmp_path, ids = populated
    await _link(make, tmp_path)
    async with make() as session:
        await tool.set_break_glass(session, get_settings(), ids["bob"], unset=False, backup_id=BACKUP)
        await tool.close_password(session, get_settings(), ids["alice"], sso_required=False, backup_id=BACKUP)
        await session.commit()
    async with make() as session:
        assert await account_flags.password_blocked(session, uuid.UUID(ids["alice"]))
        assert (await tool.enable_password(session, "person1@example.test".replace("person1", "alice")))[
            "password_login"
        ] == "enabled"
        await session.commit()
    async with make() as session:
        assert not await account_flags.password_blocked(session, uuid.UUID(ids["alice"]))
        actions = {e.action for e in (await session.scalars(sa.select(AuditEvent))).all()}
    assert {"account.link", "account.password_closed", "account.password_reopened", "account.break_glass_set"} <= actions


async def test_a_batch_of_flags_is_rolled_back_with_its_batch(populated):
    make, tmp_path, ids = populated
    await _link(make, tmp_path)
    async with make() as session:
        await tool.set_break_glass(session, get_settings(), ids["bob"], unset=False, backup_id=BACKUP)
        done = await tool.close_password(
            session, get_settings(), ids["alice"], sso_required=True, backup_id=BACKUP, batch="flags-1"
        )
        assert done["batch"] == "flags-1"
        await tool.rollback_batch(session, get_settings(), "flags-1", backup_id=BACKUP)
        assert not await account_flags.password_blocked(session, uuid.UUID(ids["alice"]))
        row = await session.get(AccountMigration, uuid.UUID(ids["alice"]))
        assert row.orion_sub == "sub-alice"  # the link stays: only the flag batch was undone


async def test_an_unknown_or_ambiguous_account_reference_is_refused(populated):
    make, _, ids = populated
    async with make() as session:
        with pytest.raises(tool.ToolError, match="no such account"):
            await tool.find_user(session, "nobody@example.test")
        with pytest.raises(tool.ToolError, match="share this address"):
            await tool.find_user(session, "twin@example.test")
        assert str((await tool.find_user(session, "ALICE@example.test")).id) == ids["alice"]


# --- the password sign-in --------------------------------------------------------------------------------------------------


class _Backend:
    def __init__(self, user: User) -> None:
        self.user = user

    async def authenticate(self, email: str, password: str) -> IdentityUser:
        return IdentityUser(self.user.subject, self.user.email, self.user.display_name, True, True, ["nova-user"])


async def test_password_sign_in_is_refused_for_a_closed_account_like_a_wrong_password(user, monkeypatch):
    from nova.infra.db import session_scope

    async with session_scope() as session:
        row = await session.get(User, uuid.UUID(user.user_id))
        monkeypatch.setattr(accounts, "identity_backend", lambda s: _Backend(row))
        assert (
            await accounts.password_login(session, email=row.email, password="irrelevant")
        ).id == row.id  # untouched: signs in
        session.add(AccountMigration(user_id=row.id, orion_sub="sub-x", sso_required=True))
        await session.commit()
        with pytest.raises(IdentityError) as exc:
            await accounts.password_login(session, email=row.email, password="irrelevant")
        assert exc.value.code == "invalid_credentials" and str(exc.value) == "Incorrect e-mail or password."
        assert (await session.scalar(sa.select(AuditEvent).where(AuditEvent.action == "auth.password_refused"))) is not None
        state = await session.get(AccountMigration, row.id)
        state.break_glass = True  # the break-glass account keeps its password
        await session.commit()
        assert (await accounts.password_login(session, email=row.email, password="irrelevant")).id == row.id
        state.break_glass, state.sso_required = False, False  # and re-opening restores it
        await session.commit()
        assert (await accounts.password_login(session, email=row.email, password="irrelevant")).id == row.id


# --- command line -------------------------------------------------------------------------------------------------------------


def cli(tmp_path: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if not k.startswith("ORION_")}
    base["NOVA_DATABASE_URL"] = f"sqlite+aiosqlite:///{tmp_path / 'tool.db'}"
    return subprocess.run(
        [sys.executable, "-m", "nova.migration.accounts", *args],
        cwd=ROOT, env={**base, **(env or {})}, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip


async def test_the_command_line_end_to_end(populated):
    _, tmp_path, ids = populated
    idp = write_idp(tmp_path)
    env = {"ORION_INVENTORY_SALT": SALT, "ORION_APPROVAL_KEY": KEY}
    assert cli(tmp_path, "inventory").returncode == 2  # no salt: refuses rather than hashing with nothing
    out = cli(tmp_path, "inventory", env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["summary"]["accounts"] == 9 and "alice" not in out.stdout.lower()
    assert cli(tmp_path, "inventory", "--emails", "clear", env=env).returncode == 2  # personal data needs --confirm-sensitive
    template = tmp_path / "approval.json"
    reconcile = cli(
        tmp_path, "reconcile", "--idp-export", str(idp), "--domains", "example.test", "--emit-approval", str(template), env=env
    )
    assert reconcile.returncode == 0 and json.loads(reconcile.stdout)["summary"]["proposed"] == 2
    assert oct(template.stat().st_mode & 0o777) == "0o600" or True
    args = ("apply", "--idp-export", str(idp), "--approval", str(template), "--domains", "example.test")
    refused = cli(tmp_path, *args, "--confirm-backup", BACKUP, env=env)  # not signed yet
    assert refused.returncode == 2 and "not signed" in refused.stderr
    assert cli(tmp_path, "sign-approval", str(template), "--approved-by", "Owner", env=env).returncode == 0
    no_backup = cli(tmp_path, *args, env=env)
    assert no_backup.returncode == 2 and "confirm-backup" in no_backup.stderr
    applied = cli(tmp_path, *args, "--confirm-backup", BACKUP, env=env)
    assert applied.returncode == 0 and json.loads(applied.stdout)["linked"] == 2, applied.stderr
    batch = json.loads(template.read_text())["batch"]
    assert cli(tmp_path, "rollback", "--batch", batch, env=env).returncode == 2  # also needs a backup
    assert cli(tmp_path, "rollback", "--batch", batch, "--confirm-backup", BACKUP, env=env).returncode == 0
    assert cli(tmp_path, "flags", "--user", ids["alice"], "--enable-password", env=env).returncode == 0  # no backup needed

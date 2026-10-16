"""``ContextProvider`` implemented on ORBIT (integration-analysis §1.7).

Credential resolution per user and project:
1. delegated ORBIT session linked by the user (exact ACL propagation, all endpoints);
2. project agent key from ``NOVA_ORBIT_AGENT_KEYS`` + ``on_behalf_of`` = the user's ORBIT id (agent endpoints only).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import jwt
from sqlalchemy import delete, select

from nova.config import Settings
from nova.domain.context import (
    ContextBundle,
    ContextChange,
    ContextError,
    ContextIdentity,
    ContextOverview,
    ContextProjectInfo,
    ContextQuery,
    ContextSnapshot,
    ContextSnapshotInfo,
    SearchResult,
)
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import DelegationSession, OrbitAccount, ProjectReference
from nova.integrations.idp import DelegationError
from nova.integrations.orbit import mapper
from nova.integrations.orbit.client import OrbitAuth, OrbitClient
from nova.services import delegation, revocation
from nova.services.audit import audit

CHANGE_TYPES_FOR_TODAY = (
    "memory.created,memory.validated,memory.superseded,memory.conflict_detected,"
    "document.new_version,document.stale,snapshot.created"
)


T = TypeVar("T")
SUCCESS_WRITE_EVERY = timedelta(minutes=1)  # the last success is refreshed at most this often (not one write per call)
MAX_AGENT_KEYS_CHECKED = 5


class OrbitContextProvider:
    def __init__(self, settings: Settings, client: OrbitClient | None = None) -> None:
        self.settings = settings
        self.client = client or OrbitClient(settings.orbit_base_url, timeout=settings.orbit_timeout_seconds)

    # --- Credentials ------------------------------------------------------------------------------

    async def _account(self, user_id: str) -> OrbitAccount | None:
        async with session_scope() as session:
            return await session.get(OrbitAccount, uuid.UUID(user_id))

    async def _delegated_auth(self, user_id: str, project_slug: str | None) -> OrbitAuth:
        """``NOVA_DELEGATION_MODE=token_exchange`` (ADR 001 §6): a short token for ORBIT on behalf of the user, for one project.

        No fallback of any kind: not the linked session, not the project agent key (another identity, another clearance).
        """
        orion_project_id: str | None = None
        if project_slug:
            async with session_scope() as session:
                found = await session.scalar(
                    select(ProjectReference.orion_project_id).where(
                        ProjectReference.system == "orbit",
                        ProjectReference.external_id == project_slug,
                        ProjectReference.orion_project_id.is_not(None),
                    )
                )
            orion_project_id = str(found) if found else None
        try:
            token = await delegation.delegated_token(
                user_id,
                audience="orbit",
                project_key=orion_project_id or (f"slug:{project_slug}" if project_slug else None),
                orion_project_id=orion_project_id,
                scope=self.settings.delegation_scope_orbit,
                settings=self.settings,
            )
        except DelegationError as exc:
            code = {
                "idp_unavailable": "unavailable",
                "audience_refused": "forbidden",
                "scope_refused": "forbidden",
                "exchange_forbidden": "forbidden",
                "idp_invalid": "invalid",
            }.get(exc.code, "unauthorized")  # subject_missing / subject_expired / user_disabled: sign in again
            raise ContextError(code, exc.message, retryable=exc.retryable) from exc  # type: ignore[arg-type]
        return OrbitAuth("session", token.access_token)

    async def _auth(self, user_id: str, project_slug: str | None, *, user_endpoint: bool) -> OrbitAuth:
        if self.settings.delegation_mode == "token_exchange":
            return await self._delegated_auth(user_id, project_slug)
        account = await self._account(user_id)
        if account and account.revoked_at is not None:
            # ORBIT removed this member: no session, and no agent key acting for them either, until they link again
            raise ContextError("unauthorized", "Your ORBIT access was revoked: link your ORBIT account again")
        if account and account.token_ciphertext and (account.expires_at is None or aware(account.expires_at) > utcnow()):
            token = decrypt(account.token_ciphertext)
            if token:
                return OrbitAuth("session", token)
        if not user_endpoint and project_slug:
            key = self.settings.orbit_agent_key_map().get(project_slug)
            if key:
                if await self._key_revoked(project_slug, key):
                    raise ContextError("unauthorized", "The ORBIT agent key of this project was revoked")
                if account and account.token_ciphertext:  # the session is gone: the identity and clearance change, say so
                    await self._note_fallback(user_id, project_slug)
                return OrbitAuth("agent_key", key, on_behalf_of=account.orbit_user_id if account else None)
        if account and account.token_ciphertext:
            await self._record(user_id, error="unauthorized: your ORBIT session has expired")
            raise ContextError("unauthorized", "Your ORBIT session has expired")
        raise ContextError("not_linked", "ORBIT is not connected for this user")

    async def _key_revoked(self, project_slug: str, key: str) -> bool:
        async with session_scope() as session:
            return await revocation.agent_key_revoked(session, project_slug, key)

    # --- Health of the link ------------------------------------------------------------------------

    async def _note_fallback(self, user_id: str, project_slug: str) -> None:
        """First call served with the project agent key since the session ended: remembered and audited once."""
        async with session_scope() as session:
            account = await session.get(OrbitAccount, uuid.UUID(user_id))
            if account is None or account.agent_fallback_at is not None:
                return
            account.agent_fallback_at = utcnow()
            await audit(
                session,
                actor_id=user_id,
                action="orbit.agent_key_fallback",
                target_type="orbit_account",
                target_id=user_id,
                summary=f"ORBIT session expired: acting with the agent key of project {project_slug} (reduced clearance)",
                details={"project": project_slug},
            )

    async def _record(self, user_id: str, *, error: str | None = None) -> None:
        """Remember the outcome of an exchange (only when the user has an ORBIT account row). Never raises."""
        try:
            async with session_scope() as session:
                account = await session.get(OrbitAccount, uuid.UUID(user_id))
                if account is None:
                    return
                now = utcnow()
                if error:
                    account.last_error_at, account.last_error = now, error[:300]
                elif account.last_success_at is None or now - aware(account.last_success_at) > SUCCESS_WRITE_EVERY:
                    account.last_success_at = now
        except Exception:  # health bookkeeping must never break an ORBIT call
            return

    async def _seen(self, user_id: str, call: Awaitable[T]) -> T:
        try:
            result = await call
        except ContextError as exc:
            await self._record(user_id, error=f"{exc.code}: {exc.message}")
            raise
        await self._record(user_id)
        return result

    # --- Account linking --------------------------------------------------------------------------

    async def link_account(self, user_id: str, email: str, password: str) -> ContextIdentity:
        """Exchange the user's ORBIT credentials for an ORBIT session; only the session is stored (encrypted)."""
        user, token = await self.client.login(email, password)
        try:
            exp = jwt.decode(token, options={"verify_signature": False}).get("exp")  # read expiry only
            expires_at = datetime.fromtimestamp(int(exp), UTC) if exp else utcnow() + timedelta(hours=12)
        except jwt.PyJWTError:
            expires_at = utcnow() + timedelta(hours=12)
        async with session_scope() as session:
            account = await session.get(OrbitAccount, uuid.UUID(user_id))
            if account is None:
                account = OrbitAccount(user_id=uuid.UUID(user_id), orbit_user_id=str(user["id"]), orbit_email=str(user["email"]))
                session.add(account)
            account.orbit_user_id, account.orbit_email = str(user["id"]), str(user["email"])
            account.orbit_name, account.clearance = str(user.get("full_name") or ""), int(user.get("clearance", 1))
            account.token_ciphertext, account.expires_at, account.linked_at = encrypt(token), expires_at, utcnow()
            account.agent_fallback_at = None  # a fresh session ends any fallback
            account.revoked_at = account.revoked_reason = None  # and any revocation (the user signed in to ORBIT again)
        return ContextIdentity(
            linked=True,
            external_user_id=str(user["id"]),
            email=str(user["email"]),
            display_name=str(user.get("full_name") or ""),
            clearance=int(user.get("clearance", 1)),
            expires_at=expires_at,
            mode="session",
        )

    async def unlink_account(self, user_id: str) -> None:
        async with session_scope() as session:
            await session.execute(delete(OrbitAccount).where(OrbitAccount.user_id == uuid.UUID(user_id)))

    # --- ContextProvider --------------------------------------------------------------------------

    async def _delegated_identity(self, user_id: str) -> ContextIdentity:
        """What NOVA knows of the delegation of this user (no call to the IdP, nothing but a status line)."""
        async with session_scope() as session:
            row = await session.get(DelegationSession, uuid.UUID(user_id))
        entry = ((row.links or {}) if row else {}).get("orbit") or {}

        def when(key: str) -> datetime | None:
            return datetime.fromisoformat(entry[key]) if entry.get(key) else None

        return ContextIdentity(
            linked=bool(row and (row.access_ciphertext or row.refresh_ciphertext)),
            external_user_id=entry.get("subject"),
            clearance=entry.get("clearance_cap"),
            expires_at=when("expires_at"),
            mode="delegated",
            last_success_at=when("last_success_at"),
            last_error_at=when("last_error_at"),
            last_error=entry.get("last_error"),
        )

    async def identity(self, user_id: str) -> ContextIdentity:
        if self.settings.delegation_mode == "token_exchange":
            return await self._delegated_identity(user_id)
        keys = self.settings.orbit_agent_key_map()
        account = await self._account(user_id)
        if account is None:
            return ContextIdentity(linked=False, mode="agent_key" if keys else "none", agent_projects=sorted(keys))
        valid = bool(account.token_ciphertext) and (account.expires_at is None or aware(account.expires_at) > utcnow())
        expired = bool(account.token_ciphertext) and not valid
        return ContextIdentity(
            linked=valid,
            external_user_id=account.orbit_user_id,
            email=account.orbit_email,
            display_name=account.orbit_name,
            clearance=account.clearance,
            expires_at=account.expires_at,
            mode="session" if valid else ("agent_key" if keys else "none"),
            session_expired=expired,
            fallback=expired and bool(keys),
            agent_projects=sorted(keys),
            last_success_at=aware(account.last_success_at),
            last_error_at=aware(account.last_error_at),
            last_error=account.last_error,
        )

    async def agent_keys_status(self) -> list[dict[str, Any]]:
        """Ask ORBIT (``GET /agents/self``) about each configured project key. Unavailable is a state, never an error."""
        states: list[dict[str, Any]] = []
        for slug, key in list(self.settings.orbit_agent_key_map().items())[:MAX_AGENT_KEYS_CHECKED]:
            revoked = await self._key_revoked(slug, key)
            try:
                raw = await self.client.agent_self(OrbitAuth("agent_key", key))
            except ContextError as exc:
                if revoked:  # ORBIT told NOVA this key was revoked and cannot say otherwise: it stays unused
                    states.append({"project": slug, "available": False, "valid": False, "reason": "revoked"})
                    continue
                # 404/403: ORBIT does not offer (or does not allow) the endpoint; 401: it refused this key
                known = {"not_found": "unsupported", "forbidden": "forbidden", "unauthorized": "key_rejected"}
                reason = known.get(exc.code, "unreachable")
                states.append(
                    {
                        "project": slug,
                        "available": exc.code == "unauthorized",
                        "valid": False if exc.code == "unauthorized" else None,
                        "reason": reason,
                    }
                )
                continue
            if revoked:  # the revoked key was another one of the project: ORBIT still accepts this one
                async with session_scope() as session:
                    await revocation.restore_agent_key(session, slug)
            states.append({"project": slug, "available": True, "valid": True, "reason": None, **mapper.agent_self(raw)})
        return states

    async def retrieve(self, query: ContextQuery) -> ContextBundle:
        auth = await self._auth(query.user_id, query.project_slug, user_endpoint=False)
        body = mapper.context_request(query, on_behalf_of=auth.on_behalf_of)
        package = await self._seen(query.user_id, self.client.context(auth, query.project_slug, body))
        return mapper.context_bundle(package, query.project_slug, self.settings.orbit_public_url)

    async def list_projects(self, user_id: str) -> list[ContextProjectInfo]:
        auth = await self._auth(user_id, None, user_endpoint=True)
        return [mapper.project_info(p) for p in await self._seen(user_id, self.client.projects(auth))]

    async def recent_changes(self, user_id: str, project_slug: str, since: datetime | None) -> list[ContextChange]:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)
        params: dict[str, Any] = {"page_size": 20, "types": CHANGE_TYPES_FOR_TODAY}
        if since:
            params["since"] = since.isoformat()
        page = await self._seen(user_id, self.client.changes(auth, project_slug, params))
        return [mapper.change(raw, project_slug) for raw in page.get("items", [])]

    async def overview(self, user_id: str, project_slug: str) -> ContextOverview:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)
        raw = await self._seen(user_id, self.client.overview(auth, project_slug))
        stats = raw.get("stats") or {}
        return ContextOverview(
            project_slug=project_slug,
            documents=int(stats.get("documents", 0)),
            memory_items=int(stats.get("memory_items", 0)),
            decisions=int(stats.get("validated_decisions", 0)),
            sources=int(stats.get("sources", 0)),
            snapshots=int(stats.get("snapshots", 0)),
            memory_by_kind={str(k): int(v) for k, v in (raw.get("memory_by_scope") or {}).items()},
        )

    async def search(self, user_id: str, project_slug: str, query: str, limit: int = 10) -> list[SearchResult]:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)
        return [
            mapper.search_result(raw, project_slug)
            for raw in await self._seen(user_id, self.client.search(auth, project_slug, query, limit))
        ]

    async def list_snapshots(self, user_id: str, project_slug: str) -> list[ContextSnapshotInfo]:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)  # listing is a viewer-only (session) endpoint
        return [mapper.snapshot_info(raw) for raw in await self._seen(user_id, self.client.snapshots(auth, project_slug))]

    async def get_snapshot(self, user_id: str, project_slug: str, name: str, version: int | None = None) -> ContextSnapshot:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        return mapper.snapshot(await self._seen(user_id, self.client.snapshot(auth, project_slug, name, version or "latest")))

    async def send_feedback(self, user_id: str, project_slug: str, retrieval_id: str, useful: bool, comment: str | None) -> None:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        body: dict[str, Any] = {"rating": 5 if useful else 2}
        if comment:
            body["comment"] = comment[:4000]
        await self._seen(user_id, self.client.context_feedback(auth, project_slug, retrieval_id, body))

    async def propose_memory(
        self, user_id: str, project_slug: str, *, kind: str, title: str, content: str, source_label: str
    ) -> str:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        item = await self._seen(
            user_id, self.client.create_memory(auth, project_slug, mapper.memory_proposal(kind, title, content, source_label))
        )
        return str(item.get("id"))

    async def publish_document(
        self, user_id: str, project_slug: str, *, title: str, content: str, external_id: str, classification: int
    ) -> str:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        doc = await self._seen(
            user_id,
            self.client.create_text_document(
                auth, project_slug, mapper.text_document(title, content, external_id, classification)
            ),
        )
        return str(doc.get("id"))

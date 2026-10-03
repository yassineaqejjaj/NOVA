"""``ContextProvider`` implemented on ORBIT (integration-analysis §1.7).

Credential resolution per user and project:
1. delegated ORBIT session linked by the user (exact ACL propagation, all endpoints);
2. project agent key from ``NOVA_ORBIT_AGENT_KEYS`` + ``on_behalf_of`` = the user's ORBIT id (agent endpoints only).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from sqlalchemy import delete

from nova.config import Settings
from nova.domain.context import (
    ContextBundle,
    ContextChange,
    ContextError,
    ContextIdentity,
    ContextOverview,
    ContextProjectInfo,
    ContextQuery,
    SearchResult,
)
from nova.infra.crypto import decrypt, encrypt
from nova.infra.db import aware, session_scope, utcnow
from nova.infra.models import OrbitAccount
from nova.integrations.orbit import mapper
from nova.integrations.orbit.client import OrbitAuth, OrbitClient

CHANGE_TYPES_FOR_TODAY = (
    "memory.created,memory.validated,memory.superseded,memory.conflict_detected,"
    "document.new_version,document.stale,snapshot.created"
)


class OrbitContextProvider:
    def __init__(self, settings: Settings, client: OrbitClient | None = None) -> None:
        self.settings = settings
        self.client = client or OrbitClient(settings.orbit_base_url, timeout=settings.orbit_timeout_seconds)

    # --- Credentials ------------------------------------------------------------------------------

    async def _account(self, user_id: str) -> OrbitAccount | None:
        async with session_scope() as session:
            return await session.get(OrbitAccount, uuid.UUID(user_id))

    async def _auth(self, user_id: str, project_slug: str | None, *, user_endpoint: bool) -> OrbitAuth:
        account = await self._account(user_id)
        if account and account.token_ciphertext and (account.expires_at is None or aware(account.expires_at) > utcnow()):
            token = decrypt(account.token_ciphertext)
            if token:
                return OrbitAuth("session", token)
        if not user_endpoint and project_slug:
            key = self.settings.orbit_agent_key_map().get(project_slug)
            if key:
                return OrbitAuth("agent_key", key, on_behalf_of=account.orbit_user_id if account else None)
        if account and account.token_ciphertext:
            raise ContextError("unauthorized", "Your ORBIT session has expired")
        raise ContextError("not_linked", "ORBIT is not connected for this user")

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

    async def identity(self, user_id: str) -> ContextIdentity:
        account = await self._account(user_id)
        if account is None:
            has_keys = bool(self.settings.orbit_agent_key_map())
            return ContextIdentity(linked=False, mode="agent_key" if has_keys else "none")
        valid = bool(account.token_ciphertext) and (account.expires_at is None or aware(account.expires_at) > utcnow())
        return ContextIdentity(
            linked=valid,
            external_user_id=account.orbit_user_id,
            email=account.orbit_email,
            display_name=account.orbit_name,
            clearance=account.clearance,
            expires_at=account.expires_at,
            mode="session" if valid else ("agent_key" if self.settings.orbit_agent_key_map() else "none"),
        )

    async def retrieve(self, query: ContextQuery) -> ContextBundle:
        auth = await self._auth(query.user_id, query.project_slug, user_endpoint=False)
        body = mapper.context_request(query, on_behalf_of=auth.on_behalf_of)
        package = await self.client.context(auth, query.project_slug, body)
        return mapper.context_bundle(package, query.project_slug, self.settings.orbit_public_url)

    async def list_projects(self, user_id: str) -> list[ContextProjectInfo]:
        auth = await self._auth(user_id, None, user_endpoint=True)
        return [mapper.project_info(p) for p in await self.client.projects(auth)]

    async def recent_changes(self, user_id: str, project_slug: str, since: datetime | None) -> list[ContextChange]:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)
        params: dict[str, Any] = {"page_size": 20, "types": CHANGE_TYPES_FOR_TODAY}
        if since:
            params["since"] = since.isoformat()
        page = await self.client.changes(auth, project_slug, params)
        return [mapper.change(raw, project_slug) for raw in page.get("items", [])]

    async def overview(self, user_id: str, project_slug: str) -> ContextOverview:
        auth = await self._auth(user_id, project_slug, user_endpoint=True)
        raw = await self.client.overview(auth, project_slug)
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
        return [mapper.search_result(raw, project_slug) for raw in await self.client.search(auth, project_slug, query, limit)]

    async def send_feedback(self, user_id: str, project_slug: str, retrieval_id: str, useful: bool, comment: str | None) -> None:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        body: dict[str, Any] = {"rating": 5 if useful else 2}
        if comment:
            body["comment"] = comment[:4000]
        await self.client.context_feedback(auth, project_slug, retrieval_id, body)

    async def propose_memory(
        self, user_id: str, project_slug: str, *, kind: str, title: str, content: str, source_label: str
    ) -> str:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        item = await self.client.create_memory(auth, project_slug, mapper.memory_proposal(kind, title, content, source_label))
        return str(item.get("id"))

    async def publish_document(
        self, user_id: str, project_slug: str, *, title: str, content: str, external_id: str, classification: int
    ) -> str:
        auth = await self._auth(user_id, project_slug, user_endpoint=False)
        doc = await self.client.create_text_document(
            auth, project_slug, mapper.text_document(title, content, external_id, classification)
        )
        return str(doc.get("id"))

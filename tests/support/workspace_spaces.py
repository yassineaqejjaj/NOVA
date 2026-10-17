"""Two workspaces for the isolation matrix (NOV-110, ADR 001 §9): synthetic data, tokens signed by a test key, no IdP.

Each space (A, B) has two projects; in each project one Artifact of every classification (C1, C2, C3), whose title says where
it lives; and one user of each role: ``owner`` (C3 clearance), ``editor``, ``viewer`` (default C1 clearance) and ``admin``
(realm role ``nova-admin``). Users sign in with RS256 access tokens carrying ``orion_workspace_id``, validated by the real
``validate_oidc_token`` against the test key: only the key set is replaced.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from nova.artifacts.registry import get_artifact_registry
from nova.config import get_settings
from nova.domain.artifacts import empty_content
from nova.infra import db
from nova.infra.models import Artifact, ArtifactVersion, OrbitAccount, Project, ProjectMember, User

ROLES = ("owner", "editor", "viewer", "admin")
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # the test key: signs everything below


def install_test_idp(monkeypatch: Any) -> None:
    """OIDC mode, with the signing key of the test key set (the validation itself is NOVA's own)."""
    from nova.services import identity

    monkeypatch.setattr(get_settings(), "auth_mode", "oidc")
    stub = SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=PRIVATE_KEY.public_key()))
    monkeypatch.setattr(identity, "_jwks_client", lambda _url: stub)


def sign(subject: str, workspace: uuid.UUID | None, *, admin: bool = False, **claims: Any) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "sub": subject,
        "iat": now,
        "exp": now + 600,
        "email": f"{subject}@example.com",
        "name": subject,
        **({"orion_workspace_id": str(workspace)} if workspace else {}),
        **({"realm_access": {"roles": [settings.oidc_admin_role]}} if admin else {}),
        **claims,
    }
    return jwt.encode(payload, PRIVATE_KEY, algorithm="RS256", headers={"kid": "test"})


@dataclass
class Member:
    role: str
    subject: str
    token: str
    user_id: uuid.UUID | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@dataclass
class Space:
    name: str
    id: uuid.UUID
    members: dict[str, Member] = field(default_factory=dict)
    projects: list[uuid.UUID] = field(default_factory=list)
    slugs: list[str] = field(default_factory=list)
    artifacts: dict[tuple[int, int], uuid.UUID] = field(default_factory=dict)  # (project index, classification) -> id

    def title(self, project: int, classification: int) -> str:
        return f"SECRET-{self.name}-P{project + 1}-C{classification}"

    def __getitem__(self, role: str) -> Member:
        return self.members[role]


async def call(app: Any, member: Member | None, method: str, path: str, **kwargs: Any) -> httpx.Response:
    headers = {**(member.headers if member else {}), **kwargs.pop("headers", {})}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, headers=headers, **kwargs)


async def build_space(app: Any, name: str) -> Space:
    space = Space(name=f"{name}{uuid.uuid4().hex[:4]}", id=uuid.uuid4())
    for role in ROLES:
        subject = f"{role}-{space.name}"
        space.members[role] = Member(role, subject, sign(subject, space.id, admin=role == "admin"))
        assert (await call(app, space[role], "GET", "/api/v1/me")).status_code == 200  # the account is created in the space
    async with db.session_scope() as session:
        for role in ROLES:
            space[role].user_id = await session.scalar(select(User.id).where(User.subject == space[role].subject))
        owner = space["owner"].user_id
        session.add(
            OrbitAccount(user_id=owner, orbit_user_id=f"orbit-{space.name}", orbit_email="o@example.com", clearance=3)
        )  # the owner reads up to C3; the others keep the default C1
        for index in range(2):
            project = Project(slug=f"proj-{space.name}-{index + 1}", name=f"Projet {space.name} {index + 1}", created_by=owner)
            session.add(project)
            await session.flush()
            space.projects.append(project.id)
            space.slugs.append(project.slug)
            for role in ("owner", "editor", "viewer"):
                session.add(ProjectMember(project_id=project.id, user_id=space[role].user_id, role=role))
            for classification in (1, 2, 3):
                artifact = Artifact(
                    type="prd",
                    title=space.title(index, classification),
                    project_id=project.id,
                    owner_id=owner,
                    classification=classification,
                    current_version=1,
                )
                session.add(artifact)
                await session.flush()
                content = empty_content(get_artifact_registry().get("prd"), artifact.title)
                session.add(
                    ArtifactVersion(
                        artifact_id=artifact.id,
                        version=1,
                        content=content.model_dump(mode="json"),
                        author_type="nova",
                        state="current",
                    )
                )
                space.artifacts[(index, classification)] = artifact.id
    return space

"""Password accounts behind NOVA's own sign-in and sign-up screens.

Production: Keycloak stays the identity provider. NOVA's back end signs users in with the password grant of the
confidential ``nova-web`` client and manages accounts with its service account (realm-management roles
``manage-users``, ``view-users``, ``query-users``). Keycloak keeps the passwords and its brute-force protection.
Development and tests (``NOVA_AUTH_MODE=dev``): accounts live in ``dev_identities``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import httpx
import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nova.config import Settings, get_settings
from nova.infra.models import DevIdentity


class IdentityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class IdentityUser:
    subject: str
    email: str
    name: str
    enabled: bool
    email_verified: bool
    roles: list[str]


class IdentityBackend(Protocol):
    async def find(self, email: str) -> IdentityUser | None: ...
    async def create(self, email: str, name: str, password: str) -> IdentityUser: ...
    async def update_pending(self, user: IdentityUser, name: str, password: str) -> None: ...
    async def activate(self, user: IdentityUser) -> None: ...
    async def set_password(self, user: IdentityUser, password: str) -> None: ...
    async def authenticate(self, email: str, password: str) -> IdentityUser: ...


def check_password_strength(password: str) -> None:
    if len(password) < 12 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        raise IdentityError("weak_password", "Use at least 12 characters, with letters and digits.")
    if len(password) > 256:
        raise IdentityError("weak_password", "The password is too long.")


def _split_name(name: str) -> tuple[str, str]:
    first, _, last = name.strip().partition(" ")
    return first or name.strip(), last.strip()


# --- Keycloak ---------------------------------------------------------------------------------------


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


class KeycloakIdentity:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        base = settings.oidc_backchannel
        root, _, realm = base.partition("/realms/")
        self.token_url = f"{base}/protocol/openid-connect/token"
        self.admin_url = f"{root}/admin/realms/{realm}"
        self.transport = transport
        self._admin_token: tuple[str, float] | None = None

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=15, transport=self.transport)

    async def _admin_headers(self) -> dict[str, str]:
        if self._admin_token is None or self._admin_token[1] < time.time() + 10:
            async with self._client() as client:
                response = await client.post(
                    self.token_url,
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.oidc_client_id,
                        "client_secret": self.settings.oidc_client_secret,
                    },
                )
            if response.status_code != 200:
                raise IdentityError("identity_unavailable", "The identity service refused NOVA's request.")
            data = response.json()
            self._admin_token = (data["access_token"], time.time() + float(data.get("expires_in", 60)))
        return {"Authorization": f"Bearer {self._admin_token[0]}"}

    async def _admin(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = await self._admin_headers()
        async with self._client() as client:
            try:
                response = await client.request(method, f"{self.admin_url}{path}", headers=headers, **kwargs)
            except httpx.HTTPError as exc:
                raise IdentityError("identity_unavailable", "The identity service is unreachable.") from exc
        if response.status_code >= 500 or response.status_code in (401, 403):
            raise IdentityError("identity_unavailable", "The identity service refused NOVA's request.")
        return response

    @staticmethod
    def _user(data: dict[str, Any]) -> IdentityUser:
        name = " ".join(p for p in (data.get("firstName"), data.get("lastName")) if p)
        return IdentityUser(
            subject=data["id"],
            email=(data.get("email") or data.get("username") or "").lower(),
            name=name,
            enabled=bool(data.get("enabled")),
            email_verified=bool(data.get("emailVerified")),
            roles=[],
        )

    async def find(self, email: str) -> IdentityUser | None:
        response = await self._admin("GET", "/users", params={"email": email, "exact": "true"})
        users = [u for u in response.json() if (u.get("email") or "").lower() == email]
        return self._user(users[0]) if users else None

    async def create(self, email: str, name: str, password: str) -> IdentityUser:
        first, last = _split_name(name)
        body = {
            "username": email,
            "email": email,
            "firstName": first,
            "lastName": last,
            "enabled": False,  # activated once the e-mailed code is confirmed
            "emailVerified": False,
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        }
        response = await self._admin("POST", "/users", json=body)
        if response.status_code == 409:
            raise IdentityError("account_exists", "An account already exists for this address.")
        if response.status_code >= 400:
            raise IdentityError("weak_password", (response.json() or {}).get("errorMessage") or "The account was refused.")
        user = await self.find(email)
        if user is None:
            raise IdentityError("identity_unavailable", "The account could not be created.")
        return user

    async def update_pending(self, user: IdentityUser, name: str, password: str) -> None:
        first, last = _split_name(name)
        await self._admin("PUT", f"/users/{user.subject}", json={"firstName": first, "lastName": last})
        await self.set_password(user, password)

    async def activate(self, user: IdentityUser) -> None:
        await self._admin("PUT", f"/users/{user.subject}", json={"enabled": True, "emailVerified": True})

    async def set_password(self, user: IdentityUser, password: str) -> None:
        response = await self._admin(
            "PUT", f"/users/{user.subject}/reset-password", json={"type": "password", "value": password, "temporary": False}
        )
        if response.status_code >= 400:
            raise IdentityError("weak_password", (response.json() or {}).get("error_description") or "Password refused.")

    async def authenticate(self, email: str, password: str) -> IdentityUser:
        async with self._client() as client:
            try:
                response = await client.post(
                    self.token_url,
                    data={
                        "grant_type": "password",
                        "client_id": self.settings.oidc_client_id,
                        "client_secret": self.settings.oidc_client_secret,
                        "username": email,
                        "password": password,
                        "scope": "openid profile email",
                    },
                )
            except httpx.HTTPError as exc:
                raise IdentityError("identity_unavailable", "The identity service is unreachable.") from exc
        if response.status_code != 200:
            description = str((response.json() or {}).get("error_description", "")).lower()
            if "disabled" in description or "not fully set up" in description:
                pending = await self.find(email)
                if pending is not None and not pending.email_verified:
                    raise IdentityError("email_not_verified", "Confirm your e-mail address to activate your account.")
                raise IdentityError("account_disabled", "This account is disabled.")
            raise IdentityError("invalid_credentials", "Incorrect e-mail or password.")
        try:
            claims = validate_oidc_token(response.json()["id_token"], self.settings, audience=self.settings.oidc_client_id)
        except (KeyError, jwt.PyJWTError, httpx.HTTPError) as exc:
            raise IdentityError("identity_unavailable", "The identity token is invalid.") from exc
        roles = [r for r in (claims.get("realm_access") or {}).get("roles") or [] if r.startswith("nova")]
        return IdentityUser(
            subject=claims["sub"],
            email=(claims.get("email") or email).lower(),
            name=claims.get("name") or claims.get("preferred_username", ""),
            enabled=True,
            email_verified=claims.get("email_verified") is True,
            roles=roles,
        )


# --- Development ------------------------------------------------------------------------------------


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = 310_000) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
    except ValueError:
        return False
    expected = hash_password(password, salt=base64.b64decode(salt), iterations=int(iterations)).split("$")[3]
    return hmac.compare_digest(expected, digest)


class DevIdentityBackend:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _user(row: DevIdentity) -> IdentityUser:
        return IdentityUser(f"dev:{row.email}", row.email, row.name, row.enabled, row.enabled, ["nova-user"])

    async def _row(self, email: str) -> DevIdentity | None:
        return await self.session.scalar(select(DevIdentity).where(DevIdentity.email == email))

    async def find(self, email: str) -> IdentityUser | None:
        row = await self._row(email)
        return self._user(row) if row else None

    async def create(self, email: str, name: str, password: str) -> IdentityUser:
        row = DevIdentity(email=email, name=name, password_hash=hash_password(password), enabled=False)
        self.session.add(row)
        await self.session.flush()
        return self._user(row)

    async def update_pending(self, user: IdentityUser, name: str, password: str) -> None:
        row = await self._row(user.email)
        assert row is not None
        row.name, row.password_hash = name, hash_password(password)

    async def activate(self, user: IdentityUser) -> None:
        row = await self._row(user.email)
        assert row is not None
        row.enabled = True

    async def set_password(self, user: IdentityUser, password: str) -> None:
        row = await self._row(user.email)
        assert row is not None
        row.password_hash = hash_password(password)

    async def authenticate(self, email: str, password: str) -> IdentityUser:
        row = await self._row(email)
        if row is None or not verify_password(password, row.password_hash):
            raise IdentityError("invalid_credentials", "Incorrect e-mail or password.")
        if not row.enabled:
            raise IdentityError("email_not_verified", "Confirm your e-mail address to activate your account.")
        return self._user(row)


def identity_backend(session: AsyncSession, settings: Settings | None = None) -> IdentityBackend:
    settings = settings or get_settings()
    return KeycloakIdentity(settings, TRANSPORT) if settings.auth_mode == "oidc" else DevIdentityBackend(session)


TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests inject a fake Keycloak

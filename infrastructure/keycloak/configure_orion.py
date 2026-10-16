"""Finish the ``orion`` realm after its first import (NOV-103, idempotent, run by an operator, never by the image).

    KC_URL=https://keycloak.example KC_ADMIN=admin KC_ADMIN_PASSWORD=… \\
        uv run python infrastructure/keycloak/configure_orion.py [--mfa on|off] [--test-user]

What ``orion-realm.json`` cannot carry (it keeps Keycloak's built-in authentication flows):

* the ``amr`` claim: the ``oidc-amr-mapper`` mapper reads a reference value set on the executions of the ``browser``
  flow. This script sets ``pwd`` on *Username Password Form* and ``mfa`` on *OTP Form* (ADR 001 §3);
* the MFA policy (``--mfa``): ``on`` makes "Configure OTP" a default required action and requires it from every existing
  user without an OTP credential; ``off`` (the default of a new realm) removes the default action. Pending required
  actions already given to users are left alone. Without the option the MFA setting is not touched;
* the single synthetic test user of the pre-production realm (``--test-user``): refused unless
  ``ORION_ENVIRONMENT=preprod``. The password is ``ORION_TEST_USER_PASSWORD`` or generated and printed once on stdout;
  it is never written in the repository. Roles: ``forge-viewer`` only. An existing user is left untouched.
"""

from __future__ import annotations

import os
import secrets
import sys
from typing import Any

import httpx

REALM = os.environ.get("KC_REALM", "orion")
AMR_KEY = "default.reference.value"
AMR_EXECUTIONS = {"auth-username-password-form": ("orion-amr-pwd", "pwd"), "auth-otp-form": ("orion-amr-mfa", "mfa")}
TEST_USERNAME = "orion-test"
TEST_WORKSPACE_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"  # synthetic: no real workspace exists in the realm
TEST_ROLES = ["forge-viewer"]


def set_amr_references(http: httpx.Client, admin: str) -> list[str]:
    """Idempotent (Keycloak masks the value on read, so it is always written): returns the provider ids configured."""
    changed = []
    executions = http.get(f"{admin}/authentication/flows/browser/executions")
    executions.raise_for_status()
    for execution in executions.json():
        provider = execution.get("providerId")
        if provider not in AMR_EXECUTIONS:
            continue
        alias, value = AMR_EXECUTIONS[provider]
        config_id = execution.get("authenticationConfig")
        if config_id:
            http.put(
                f"{admin}/authentication/config/{config_id}", json={"id": config_id, "alias": alias, "config": {AMR_KEY: value}}
            ).raise_for_status()
        else:
            http.post(
                f"{admin}/authentication/executions/{execution['id']}/config", json={"alias": alias, "config": {AMR_KEY: value}}
            ).raise_for_status()
        changed.append(provider)
    return changed


def set_mfa(http: httpx.Client, admin: str, enabled: bool) -> int:
    """``CONFIGURE_TOTP`` as a default required action (new users) and, when enabled, for existing users without OTP."""
    action = http.get(f"{admin}/authentication/required-actions/CONFIGURE_TOTP")
    action.raise_for_status()
    body = {**action.json(), "enabled": True, "defaultAction": enabled}
    http.put(f"{admin}/authentication/required-actions/CONFIGURE_TOTP", json=body).raise_for_status()
    updated = 0
    if not enabled:
        return updated
    first = 0
    while True:
        page = http.get(f"{admin}/users", params={"first": first, "max": 100})
        page.raise_for_status()
        users = page.json()
        for user in users:
            if user.get("serviceAccountClientId") or user.get("username", "").startswith("service-account-"):
                continue
            credentials = http.get(f"{admin}/users/{user['id']}/credentials")
            credentials.raise_for_status()
            if any(c.get("type") == "otp" for c in credentials.json()) or "CONFIGURE_TOTP" in user.get("requiredActions", []):
                continue
            actions = [*user.get("requiredActions", []), "CONFIGURE_TOTP"]
            http.put(f"{admin}/users/{user['id']}", json={**user, "requiredActions": actions}).raise_for_status()
            updated += 1
        if len(users) < 100:
            return updated
        first += 100


def create_test_user(http: httpx.Client, admin: str, environ: dict[str, str] | None = None) -> tuple[bool, str | None]:
    """Create the synthetic pre-production user: (created, generated password or None when supplied / not created)."""
    env = os.environ if environ is None else environ
    if env.get("ORION_ENVIRONMENT") != "preprod":
        raise SystemExit("--test-user is only for the pre-production realm: set ORION_ENVIRONMENT=preprod")
    existing = http.get(f"{admin}/users", params={"username": TEST_USERNAME, "exact": "true"})
    existing.raise_for_status()
    if existing.json():
        print(f"user {TEST_USERNAME} exists: left untouched")
        return False, None
    supplied = env.get("ORION_TEST_USER_PASSWORD")
    password = supplied or secrets.token_urlsafe(24)
    created = http.post(
        f"{admin}/users",
        json={
            "username": TEST_USERNAME,
            "email": f"{TEST_USERNAME}@example.test",
            "emailVerified": True,
            "enabled": True,
            "firstName": "ORION",
            "lastName": "Test",
            "attributes": {"orion_workspace_id": [TEST_WORKSPACE_ID], "orion_clearance": ["1"]},
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        },
    )
    created.raise_for_status()
    user_id = created.headers["Location"].rsplit("/", 1)[-1]
    roles = [r for r in http.get(f"{admin}/roles").json() if r["name"] in TEST_ROLES]
    http.post(f"{admin}/users/{user_id}/role-mappings/realm", json=roles).raise_for_status()
    return True, None if supplied else password


def main(argv: list[str]) -> int:
    mfa = None
    if "--mfa" in argv:
        value = argv[argv.index("--mfa") + 1 : argv.index("--mfa") + 2]
        if value not in (["on"], ["off"]):
            print("--mfa takes on or off")
            return 2
        mfa = value[0] == "on"
    base = os.environ["KC_URL"].rstrip("/")
    with httpx.Client(timeout=30) as http:
        token = http.post(
            f"{base}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": os.environ["KC_ADMIN"],
                "password": os.environ["KC_ADMIN_PASSWORD"],
            },
        )
        token.raise_for_status()
        http.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        admin = f"{base}/admin/realms/{REALM}"
        changed: Any = set_amr_references(http, admin)
        print(f"amr references: {', '.join(changed) if changed else 'already set'}")
        if mfa is not None:
            print(f"mfa {'on' if mfa else 'off'}: {set_mfa(http, admin, mfa)} user(s) updated")
        if "--test-user" in argv:
            created, password = create_test_user(http, admin)
            if created:
                shown = f"password (shown once): {password}" if password else "password from ORION_TEST_USER_PASSWORD"
                print(f"test user {TEST_USERNAME} created; {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

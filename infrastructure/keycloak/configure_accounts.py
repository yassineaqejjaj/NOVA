"""Enable NOVA's own sign-in / sign-up screens on an existing Keycloak realm (idempotent).

    KC_URL=https://keycloak.example KC_ADMIN=admin KC_ADMIN_PASSWORD=… uv run python infrastructure/keycloak/configure_accounts.py

On the ``nova-web`` client: password grant (NOVA's back end signs users in; Keycloak keeps passwords and brute-force
protection) and a service account allowed to create and activate users (realm-management ``manage-users``,
``view-users``, ``query-users``). New realms get the same settings from ``nova-realm.json``.
"""

from __future__ import annotations

import os
import sys

import httpx

REALM, CLIENT_ID = os.environ.get("KC_REALM", "nova"), os.environ.get("KC_CLIENT_ID", "nova-web")
ROLES = ["manage-users", "view-users", "query-users"]


def main() -> None:
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

        realm = http.get(admin).json()
        if not realm.get("bruteForceProtected"):
            http.put(admin, json={"bruteForceProtected": True}).raise_for_status()

        client = http.get(f"{admin}/clients", params={"clientId": CLIENT_ID}).json()[0]
        if not (client.get("directAccessGrantsEnabled") and client.get("serviceAccountsEnabled")):
            client.update(directAccessGrantsEnabled=True, serviceAccountsEnabled=True)
            http.put(f"{admin}/clients/{client['id']}", json=client).raise_for_status()

        account = http.get(f"{admin}/clients/{client['id']}/service-account-user").json()
        management = http.get(f"{admin}/clients", params={"clientId": "realm-management"}).json()[0]
        assigned = {r["name"] for r in http.get(f"{admin}/users/{account['id']}/role-mappings/clients/{management['id']}").json()}
        missing = [http.get(f"{admin}/clients/{management['id']}/roles/{name}").json() for name in ROLES if name not in assigned]
        if missing:
            http.post(f"{admin}/users/{account['id']}/role-mappings/clients/{management['id']}", json=missing).raise_for_status()
        print(f"{REALM}/{CLIENT_ID}: password grant + service account ready ({', '.join(ROLES)})")


if __name__ == "__main__":
    try:
        main()
    except (KeyError, httpx.HTTPError) as exc:
        sys.exit(f"Keycloak configuration failed: {exc}")

"""Realm ``orion`` (NOV-103): the import file, its image, its operator script, and its agreement with the claims contract.

No Keycloak is needed: the JSON is checked as data. The realm was also imported into a throw-away local Keycloak 26.8
when it was written (tokens of the three clients, token exchange, client credentials, MFA): the checks below pin what
was observed there.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

from nova.domain import orion_claims as oc

ROOT = Path(__file__).resolve().parents[2]
KEYCLOAK = ROOT / "infrastructure" / "keycloak"
REALM_PATH = KEYCLOAK / "orion-realm.json"
REALM = json.loads(REALM_PATH.read_text(encoding="utf-8"))
CLAIMS = ROOT / "contracts" / "claims"
CONTEXT = json.loads((CLAIMS / "context.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((CLAIMS / "manifest.json").read_text(encoding="utf-8"))
CASES = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CLAIMS.glob("case_*.json"))]
CLIENTS = {c["clientId"]: c for c in REALM["clients"]}
USER_CLIENTS = {"nova-web": "nova", "orbit": "orbit", "forge": "forge"}
PLACEHOLDER = re.compile(r"^\$\{ORION_[A-Z_]+\}$")
ENV_VARS = {"ORION_NOVA_PUBLIC_URL", "ORION_ORBIT_PUBLIC_URL", "ORION_FORGE_PUBLIC_URL", "ORION_NOVA_CLIENT_SECRET",
            "ORION_ORBIT_CLIENT_SECRET", "ORION_FORGE_CLIENT_SECRET", "ORION_NOVA_SERVICE_SECRET"}  # fmt: skip
#: sha256 of infrastructure/keycloak/nova-realm.json on preprod and main (NOV-103: the realm `nova` never changes)
NOVA_REALM_SHA256 = "76ddb74b589d572a1a9dd4f9d2d8e2ebeb6f7b12e3a4d534d89ab2b46a95bfd3"


def mappers(client: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["name"]: m for m in client["protocolMappers"]}


def by_claim(client: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {m["config"]["claim.name"]: m for m in client["protocolMappers"] if "claim.name" in m["config"]}


def walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from walk(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from walk(value, f"{path}[{i}]")
    else:
        yield path, node


# --- the realm `nova` does not move ---------------------------------------------------------------------------------


def test_the_nova_realm_file_is_unchanged():
    digest = hashlib.sha256((KEYCLOAK / "nova-realm.json").read_bytes()).hexdigest()
    assert digest == NOVA_REALM_SHA256, "nova-realm.json changed: the realm `nova` and NOVA's current login must not"
    assert json.loads((KEYCLOAK / "nova-realm.json").read_text())["realm"] == "nova"


# --- clients ----------------------------------------------------------------------------------------------------------


def test_realm_basics():
    assert REALM["realm"] == "orion" and REALM["enabled"] is True
    assert REALM["sslRequired"] == "external"
    assert REALM["registrationAllowed"] is False and REALM["duplicateEmailsAllowed"] is False
    assert REALM["bruteForceProtected"] is True
    assert REALM["eventsEnabled"] is True and REALM["adminEventsDetailsEnabled"] is False  # events kept, no request bodies


def test_the_four_clients():
    assert set(CLIENTS) == {"nova-web", "orbit", "forge", "nova-service"}


@pytest.mark.parametrize("client_id", sorted(USER_CLIENTS))
def test_user_clients_are_confidential_code_flow_with_pkce(client_id):
    client = CLIENTS[client_id]
    assert client["publicClient"] is False and client["clientAuthenticatorType"] == "client-secret"
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False  # ADR 001 §2: Authorization Code + PKCE, no password grant
    assert client["serviceAccountsEnabled"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert client["fullScopeAllowed"] is False  # roles are scoped per client (see test_roles_are_scoped_to_the_service)
    assert client["attributes"]["access.token.lifespan"] == "300"  # ADR §6: delegated tokens live 5 minutes


@pytest.mark.parametrize("client_id", sorted(USER_CLIENTS))
def test_redirect_urls_come_from_the_environment(client_id):
    client = CLIENTS[client_id]
    variable = f"ORION_{ {'nova-web': 'NOVA'}.get(client_id, client_id.upper()) }_PUBLIC_URL"
    assert all(u.startswith("${" + variable + "}/") for u in client["redirectUris"])
    assert client["webOrigins"] == ["${" + variable + "}"]
    assert not any("*" in u for u in client["redirectUris"])  # exact callback, no wildcard
    assert client["attributes"]["post.logout.redirect.uris"] == "${" + variable + "}/*"
    assert client["redirectUris"][0].endswith(
        "/api/v1/auth/callback" if client_id == "nova-web" else "/api/v1/auth/oidc/callback"
    )


def test_service_account_client():
    client = CLIENTS["nova-service"]
    assert client["serviceAccountsEnabled"] is True and client["publicClient"] is False
    assert client["standardFlowEnabled"] is False and client["directAccessGrantsEnabled"] is False
    assert client["secret"] == "${ORION_NOVA_SERVICE_SECRET}"
    assert client["fullScopeAllowed"] is False
    # one token per audience (ADR §3): the audience comes with the scope the caller asks for, never by default
    assert not any(m["protocolMapper"] == "oidc-audience-mapper" for m in client["protocolMappers"])
    assert {"orion-audience-orbit", "orion-audience-forge"} <= set(client["optionalClientScopes"])
    assert [u["serviceAccountClientId"] for u in REALM["users"]] == ["nova-service"]


@pytest.mark.parametrize("client_id", sorted(USER_CLIENTS))
def test_each_client_gets_its_own_audience(client_id):
    audience = [m for m in CLIENTS[client_id]["protocolMappers"] if m["protocolMapper"] == "oidc-audience-mapper"]
    assert [m["config"]["included.client.audience"] for m in audience] == [oc.AUDIENCES[USER_CLIENTS[client_id]]]
    assert audience[0]["config"]["access.token.claim"] == "true"


def test_audience_client_scopes_match_the_contract():
    scopes = {s["name"]: s for s in REALM["clientScopes"]}
    for service in ("orbit", "forge"):
        (mapper,) = scopes[f"orion-audience-{service}"]["protocolMappers"]
        assert mapper["config"]["included.client.audience"] == oc.AUDIENCES[service]


# --- token exchange (RFC 8693) ----------------------------------------------------------------------------------------


def test_token_exchange_only_for_nova_web_and_limited_by_audience():
    enabled = {cid for cid, c in CLIENTS.items() if c["attributes"].get("standard.token.exchange.enabled") == "true"}
    assert enabled == {"nova-web"}
    # Keycloak lets a client exchange only towards the audiences it holds as client scopes (observed: "Requested audience
    # not available" otherwise): nova-web may target ORBIT and FORGE, never itself again nor the service account
    assert {"orion-audience-orbit", "orion-audience-forge"} <= set(CLIENTS["nova-web"]["optionalClientScopes"])
    for other in ("orbit", "forge"):  # (nova-service asks for them by scope, client credentials: no exchange)
        assert not {"orion-audience-orbit", "orion-audience-forge"} & set(CLIENTS[other]["optionalClientScopes"])


# --- mappers vs the claims contract (NOV-104) -------------------------------------------------------------------------


@pytest.mark.parametrize("client_id", [*sorted(USER_CLIENTS), "nova-service"])
def test_claim_mappers(client_id):
    claims = by_claim(CLIENTS[client_id])
    expected = {"orion_workspace_id", "orion_clearance", "realm_access.roles"} | (
        set() if client_id == "nova-service" else {"orion_project_id"}
    )
    assert set(claims) == expected
    assert claims["orion_clearance"]["config"]["jsonType.label"] == "int"  # an integer 0-3, not a string (module refuses "3")
    assert claims["orion_workspace_id"]["config"]["jsonType.label"] == "String"
    assert claims["realm_access.roles"]["config"]["multivalued"] == "true"
    assert claims["realm_access.roles"]["protocolMapper"] == "oidc-usermodel-realm-role-mapper"
    for name in expected - {"realm_access.roles"}:
        assert claims[name]["protocolMapper"] == "oidc-usermodel-attribute-mapper"
        assert claims[name]["config"]["user.attribute"] == name  # the attribute and the claim share the contract name
    for mapper in CLIENTS[client_id]["protocolMappers"]:
        assert mapper["config"].get("id.token.claim", "false") == "false"  # authorization data stays in the access token
        if "claim.name" in mapper["config"] or mapper["protocolMapper"] == "oidc-amr-mapper":
            assert mapper["config"]["access.token.claim"] == "true"
    assert [m for m in CLIENTS[client_id]["protocolMappers"] if m["protocolMapper"] == "oidc-amr-mapper"]


def test_every_claim_of_the_contract_is_minted_or_known_to_be_missing():
    scopes = {s["name"]: s for s in REALM["clientScopes"]}
    minted = set()
    for scope in ("basic", "email", "profile"):
        for m in scopes[scope]["protocolMappers"]:
            minted.add(m["config"].get("claim.name") or {"sub": "sub"}.get(m["name"], m["name"]))
    minted |= set(by_claim(CLIENTS["nova-web"])) | {"amr"}
    core = {"iss", "aud", "exp", "iat", "scope"}  # added by Keycloak itself (aud by the audience mappers above)
    # not emitted by Keycloak 26.8 by default: nbf (the module checks it when present), act (preview feature
    # TOKEN_EXCHANGE_DELEGATION, the "Delegation" follow-up ticket)
    not_yet = {"nbf", "act"}
    assert set(MANIFEST["claims"]) - core - not_yet <= minted, sorted(set(MANIFEST["claims"]) - core - not_yet - minted)
    assert {"sub", "email", "email_verified"} <= minted


def test_default_scopes_carry_sub_email_and_profile():
    scopes = {s["name"]: s for s in REALM["clientScopes"]}
    for client_id in USER_CLIENTS:
        assert set(CLIENTS[client_id]["defaultClientScopes"]) == {"basic", "email", "profile"}
    claims = {m["config"]["claim.name"]: m for m in scopes["email"]["protocolMappers"]}
    assert claims["email_verified"]["config"]["jsonType.label"] == "boolean"
    (sub,) = scopes["basic"]["protocolMappers"]
    assert sub["protocolMapper"] == "oidc-sub-mapper"  # `sub` is the account matching key (ADR §3)
    assert not any("offline_access" in c.get("optionalClientScopes", []) for c in CLIENTS.values())  # no offline tokens


def test_scopes_of_the_fixtures_exist_in_the_realm():
    declared = {s["name"] for s in REALM["clientScopes"]}
    used = set()
    for case in CASES:
        scope = case["claims"].get("scope", [])
        used |= {s for s in (scope.split() if isinstance(scope, str) else scope) if s.startswith("orion:")}
    assert used and used <= declared
    for client_id in USER_CLIENTS:
        assert {"orion:context.read", "orion:run.execute"} <= set(CLIENTS[client_id]["optionalClientScopes"])


def test_the_issuer_of_the_fixtures_is_a_realm_orion_issuer():
    assert CONTEXT["issuer"].endswith(f"/realms/{REALM['realm']}")


# --- roles ------------------------------------------------------------------------------------------------------------


def test_realm_roles():
    names = {r["name"] for r in REALM["roles"]["realm"]}
    assert names == {
        "nova-admin",
        "orbit-admin",
        "forge-admin",
        "forge-maintainer",
        "forge-editor",
        "forge-evaluator",
        "forge-viewer",
    }
    assert {n.removeprefix("forge-") for n in names if n.startswith("forge-")} == set(oc.FORGE_ROLES)  # the ladder of the module
    assert all(any(n.startswith(p) for p in oc.ROLE_PREFIXES.values()) for n in names)
    assert not any("composites" in r for r in REALM["roles"]["realm"])  # no role grants another one by surprise


def test_roles_used_by_the_fixtures_exist():
    names = {r["name"] for r in REALM["roles"]["realm"]}
    prefixed = tuple(oc.ROLE_PREFIXES.values())
    used = {r for case in CASES for r in case["claims"].get("realm_access", {}).get("roles", []) if isinstance(r, str)}
    real = {r for r in used if r.startswith(prefixed) and r not in {"forge-", "nova-administrator"}}
    assert {"nova-admin", "orbit-admin", "forge-admin", "forge-editor", "forge-viewer"} <= real
    assert real <= names, sorted(real - names)  # no fixture claims a role the IdP cannot issue


def test_roles_are_scoped_to_the_service():
    """fullScopeAllowed is off: a token of a client carries only the roles of its own prefix (least privilege)."""
    scoped = {m["client"]: set(m["roles"]) for m in REALM["scopeMappings"]}
    assert set(scoped) == set(USER_CLIENTS)
    for client_id, service in USER_CLIENTS.items():
        assert scoped[client_id] and all(r.startswith(oc.ROLE_PREFIXES[service]) for r in scoped[client_id])
    assert scoped["forge"] == {f"forge-{r}" for r in oc.FORGE_ROLES}
    assert "nova-service" not in scoped  # the service account holds no realm role until an administrator gives one


# --- user attributes: the authorization data is not self-service ------------------------------------------------------


def profile() -> dict[str, dict[str, Any]]:
    (component,) = REALM["components"]["org.keycloak.userprofile.UserProfileProvider"]
    assert component["providerId"] == "declarative-user-profile"
    (raw,) = component["config"]["kc.user.profile.config"]
    return {a["name"]: a for a in json.loads(raw)["attributes"]}


def test_orion_attributes_are_managed_by_administrators_only():
    attrs = profile()
    for name in ("orion_workspace_id", "orion_project_id", "orion_clearance"):
        assert attrs[name]["permissions"] == {"view": ["admin"], "edit": ["admin"]}, name
    assert attrs["orion_clearance"]["validations"]["integer"] == {"min": 0, "max": 3}
    assert re.fullmatch(attrs["orion_workspace_id"]["validations"]["pattern"]["pattern"], "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    assert not re.fullmatch(attrs["orion_workspace_id"]["validations"]["pattern"]["pattern"], "workspace-a")
    # the e-mail seeds account matching (ADR §8): not editable by the user; unmanaged attributes stay disabled
    assert attrs["email"]["permissions"]["edit"] == ["admin"] and attrs["username"]["permissions"]["edit"] == ["admin"]
    assert "unmanagedAttributePolicy" not in json.loads(
        REALM["components"]["org.keycloak.userprofile.UserProfileProvider"][0]["config"]["kc.user.profile.config"][0]
    )


# --- no secret, no user -----------------------------------------------------------------------------------------------


def test_no_secret_in_clear():
    for path, value in walk(REALM):
        key = path.rsplit(".", 1)[-1]
        if key in ("secret", "value", "password", "clientSecret", "registrationAccessToken"):
            assert isinstance(value, str) and PLACEHOLDER.match(value), f"{path} must be an ${{ORION_*}} placeholder"
        if isinstance(value, str):
            assert "-----BEGIN" not in value and not re.search(r"eyJ[A-Za-z0-9_-]{10,}\.", value), path
    assert "credentials" not in json.dumps(REALM)


def test_every_placeholder_is_an_orion_variable_documented_and_enforced():
    found = {m for _, v in walk(REALM) if isinstance(v, str) for m in re.findall(r"\$\{([^}]*)\}", v)}
    assert found == ENV_VARS
    operations = (ROOT / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
    entrypoint = (KEYCLOAK / "docker-entrypoint.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "infrastructure" / "railway" / "keycloak.Dockerfile").read_text(encoding="utf-8")
    for name in ENV_VARS:
        assert name in operations and name in entrypoint and name in dockerfile, name


def test_no_user_is_imported_but_the_service_account():
    assert all("serviceAccountClientId" in u and "credentials" not in u for u in REALM["users"])


# --- the image ---------------------------------------------------------------------------------------------------------


def test_dockerfile_ships_the_realm_inert_and_keeps_the_nova_import():
    text = (ROOT / "infrastructure" / "railway" / "keycloak.Dockerfile").read_text(encoding="utf-8")
    assert "COPY infrastructure/keycloak/nova-realm.json /opt/keycloak/data/import/nova-realm.json" in text
    assert "COPY infrastructure/keycloak/orion-realm.json /opt/keycloak/data/orion/orion-realm.json" in text
    assert "data/import/orion-realm.json" not in text  # never imported by the image alone
    assert 'ENTRYPOINT ["/opt/keycloak/bin/orion-entrypoint.sh"]' in text
    assert 'CMD ["start", "--optimized", "--import-realm"]' in text  # the start command did not change
    assert "RUN mkdir -p /opt/keycloak/data/import" in text


@pytest.fixture
def kc_home(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "data" / "orion").mkdir(parents=True)
    (tmp_path / "data" / "import").mkdir()
    (tmp_path / "data" / "orion" / "orion-realm.json").write_text(REALM_PATH.read_text())
    stub = tmp_path / "bin" / "kc.sh"
    stub.write_text('#!/bin/bash\necho "kc.sh $*"\n')
    stub.chmod(0o755)
    return tmp_path


def run_entrypoint(kc_home: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {"PATH": os.environ["PATH"], "KC_HOME": str(kc_home)}
    return subprocess.run(
        ["bash", str(KEYCLOAK / "docker-entrypoint.sh"), "start", "--optimized", "--import-realm"],
        env={**base, **env},
        capture_output=True,
        text=True,
        check=False,
    )


FULL_ENV = {
    "ORION_REALM_IMPORT": "true",
    "ORION_NOVA_PUBLIC_URL": "https://nova.test",
    "ORION_ORBIT_PUBLIC_URL": "https://orbit.test",
    "ORION_FORGE_PUBLIC_URL": "https://forge.test",
    **{f"ORION_{n}_SECRET": "x" * 32 for n in ("NOVA_CLIENT", "ORBIT_CLIENT", "FORGE_CLIENT", "NOVA_SERVICE")},
}


@pytest.mark.parametrize("flag", [None, "false", "", "TRUE", "1", "yes"])
def test_entrypoint_is_a_plain_exec_unless_explicitly_enabled(kc_home, flag):
    result = run_entrypoint(kc_home, **({} if flag is None else {"ORION_REALM_IMPORT": flag}))
    assert result.returncode == 0 and result.stdout.strip() == "kc.sh start --optimized --import-realm"
    assert not (kc_home / "data" / "import" / "orion-realm.json").exists()


def test_entrypoint_imports_the_orion_realm_when_enabled(kc_home):
    result = run_entrypoint(kc_home, **FULL_ENV)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "kc.sh start --optimized --import-realm"
    assert (kc_home / "data" / "import" / "orion-realm.json").read_text() == REALM_PATH.read_text()


@pytest.mark.parametrize("missing", sorted(ENV_VARS))
def test_entrypoint_fails_closed_when_a_variable_is_missing(kc_home, missing):
    env = {k: v for k, v in FULL_ENV.items() if k != missing}
    result = run_entrypoint(kc_home, **env)
    assert result.returncode == 1 and missing in result.stderr and "kc.sh" not in result.stdout
    assert not (kc_home / "data" / "import" / "orion-realm.json").exists()  # never a literal ${...} secret


def test_entrypoint_refuses_short_secrets_and_does_not_print_them(kc_home):
    result = run_entrypoint(kc_home, **{**FULL_ENV, "ORION_FORGE_CLIENT_SECRET": "short-secret"})
    assert result.returncode == 1 and "ORION_FORGE_CLIENT_SECRET" in result.stderr
    assert "short-secret" not in result.stderr + result.stdout


# --- operator script ---------------------------------------------------------------------------------------------------


def load_script():
    spec = importlib.util.spec_from_file_location("configure_orion", KEYCLOAK / "configure_orion.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = load_script()
ADMIN = "http://kc.test/admin/realms/orion"


class FakeAdmin:
    def __init__(self, *, configs=None, users=None, otp_users=()):
        self.calls: list[tuple[str, str, Any]] = []
        self.configs = configs or {}
        self.users = users if users is not None else []
        self.otp_users = set(otp_users)
        self.action = {"alias": "CONFIGURE_TOTP", "enabled": False, "defaultAction": False}

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/admin/realms/orion")
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, path, body))
        if path == "/authentication/flows/browser/executions":
            return httpx.Response(200, json=[
                {"id": "e1", "providerId": "auth-username-password-form", "authenticationConfig": self.configs.get("e1")},
                {"id": "e2", "providerId": "auth-otp-form", "authenticationConfig": self.configs.get("e2")},
                {"id": "e3", "providerId": "auth-cookie"},
            ])  # fmt: skip
        if path.startswith("/authentication/executions/") and request.method == "POST":
            return httpx.Response(201)
        if path.startswith("/authentication/config/"):
            return httpx.Response(204)
        if path == "/authentication/required-actions/CONFIGURE_TOTP":
            if request.method == "PUT":
                self.action = body
                return httpx.Response(204)
            return httpx.Response(200, json=self.action)
        if path == "/users" and request.method == "GET":
            params = dict(request.url.params)
            if "username" in params:
                return httpx.Response(200, json=[u for u in self.users if u["username"] == params["username"]])
            return httpx.Response(200, json=self.users if params.get("first") == "0" else [])
        if path == "/users" and request.method == "POST":
            self.users.append({"id": "new", **body})
            return httpx.Response(201, headers={"Location": f"{ADMIN}/users/new"})
        if path.endswith("/credentials"):
            uid = path.split("/")[2]
            return httpx.Response(200, json=[{"type": "otp"}] if uid in self.otp_users else [{"type": "password"}])
        if path == "/roles":
            return httpx.Response(200, json=[{"name": n} for n in ("forge-viewer", "forge-admin", "nova-admin")])
        return httpx.Response(204)


def client(fake: FakeAdmin) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(fake.handler))


def test_amr_references_are_created_then_rewritten():
    fake = FakeAdmin()
    assert script.set_amr_references(client(fake), ADMIN) == ["auth-username-password-form", "auth-otp-form"]
    posts = {c[1]: c[2]["config"] for c in fake.calls if c[0] == "POST"}
    assert posts == {"/authentication/executions/e1/config": {"default.reference.value": "pwd"},
                     "/authentication/executions/e2/config": {"default.reference.value": "mfa"}}  # fmt: skip
    again = FakeAdmin(configs={"e1": "c1", "e2": "c2"})
    script.set_amr_references(client(again), ADMIN)  # a second run only rewrites the same values
    puts = {c[1]: c[2]["config"] for c in again.calls if c[0] == "PUT"}
    assert puts == {"/authentication/config/c1": {"default.reference.value": "pwd"},
                    "/authentication/config/c2": {"default.reference.value": "mfa"}}  # fmt: skip


def test_mfa_on_requires_otp_from_existing_users_without_one_and_skips_service_accounts():
    users = [
        {"id": "u1", "username": "a", "requiredActions": []},
        {"id": "u2", "username": "b", "requiredActions": []},
        {"id": "u3", "username": "service-account-nova-service", "requiredActions": []},
        {"id": "u4", "username": "d", "requiredActions": ["CONFIGURE_TOTP"]},
    ]
    fake = FakeAdmin(users=users, otp_users={"u2"})
    assert script.set_mfa(client(fake), ADMIN, True) == 1
    assert fake.action["defaultAction"] is True and fake.action["enabled"] is True
    updated = [c for c in fake.calls if c[0] == "PUT" and c[1].startswith("/users/")]
    assert [c[1] for c in updated] == ["/users/u1"] and updated[0][2]["requiredActions"] == ["CONFIGURE_TOTP"]


def test_mfa_off_only_removes_the_default_action():
    fake = FakeAdmin(users=[{"id": "u1", "username": "a", "requiredActions": []}])
    fake.action["defaultAction"] = True
    assert script.set_mfa(client(fake), ADMIN, False) == 0
    assert fake.action["defaultAction"] is False
    assert not [c for c in fake.calls if c[1].startswith("/users")]


def test_test_user_is_refused_outside_preprod():
    for env in ({}, {"ORION_ENVIRONMENT": "production"}, {"ORION_ENVIRONMENT": "Preprod"}):
        fake = FakeAdmin()
        with pytest.raises(SystemExit):
            script.create_test_user(client(fake), ADMIN, env)
        assert not fake.calls  # nothing was even read


def test_test_user_has_a_generated_password_and_no_privilege():
    fake = FakeAdmin()
    created, password = script.create_test_user(client(fake), ADMIN, {"ORION_ENVIRONMENT": "preprod"})
    assert created and password and len(password) >= 32
    (user,) = fake.users
    assert user["username"] == "orion-test" and user["email"].endswith("@example.test")
    assert user["credentials"][0]["value"] == password and user["credentials"][0]["temporary"] is False
    assert user["attributes"]["orion_clearance"] == ["1"]
    roles = [c[2] for c in fake.calls if c[1].endswith("/role-mappings/realm")]
    assert roles == [[{"name": "forge-viewer"}]]  # never an admin role
    _, again = script.create_test_user(client(FakeAdmin()), ADMIN, {"ORION_ENVIRONMENT": "preprod"})
    assert again != password  # a different password every time
    assert script.TEST_USERNAME not in (KEYCLOAK / "orion-realm.json").read_text()  # not in the import file


def test_test_user_supplied_password_is_not_echoed_and_existing_user_is_untouched():
    fake = FakeAdmin()
    env = {"ORION_ENVIRONMENT": "preprod", "ORION_TEST_USER_PASSWORD": "p" * 24}
    assert script.create_test_user(client(fake), ADMIN, env) == (True, None)
    existing = FakeAdmin(users=[{"id": "x", "username": "orion-test"}])
    assert script.create_test_user(client(existing), ADMIN, env) == (False, None)
    assert not [c for c in existing.calls if c[0] in ("POST", "PUT")]

"""Generate ``contracts/claims/`` : signed ORION access-token fixtures and the expected decision of each service (NOV-104).

    uv run python scripts/generate_claims_fixtures.py            # writes contracts/claims/
    uv run python scripts/generate_claims_fixtures.py --check    # verifies what is committed (manifest, module hash, table)

No key is committed. Each run creates a throw-away RSA key pair in memory, signs every token with it, publishes only the
public key (``jwks.json``) and forgets the private one. A regeneration therefore changes every token and the manifest:
that is a contract decision, followed by refreshing the copies in ORBIT and FORGE (docs/CONTRACTS.md). All data is
synthetic (example.test addresses, made-up UUIDs).

Each ``case_<name>.json`` holds the payload actually carried by the tokens (``claims``, without ``aud``), one token per
service (``tokens``: the audience of ADR §4 is added), and for each service the local state it is evaluated with
(``services.<service>.local``) and the **hand-written** expected decision (``services.<service>.expect``): the table
of ADR §4 is written here, it is never computed by the module under test.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "contracts" / "claims"
MODULE = ROOT / "nova" / "domain" / "orion_claims.py"
MANIFEST = "manifest.json"
KID = "orion-test-key-1"
ISSUER = "https://idp.orion.test/realms/orion"
NOW = 1792152000  # 2026-10-16T12:00:00Z: the clock every fixture is evaluated at
SERVICES = ("nova", "orbit", "forge")
AUDIENCES = {"nova": "nova-web", "orbit": "orbit", "forge": "forge"}
#: the claims of ADR §3 that an implementation reads; removing / renaming one must change a decision (tests/contract)
CONTRACT_CLAIMS = [
    "act",
    "amr",
    "aud",
    "email",
    "email_verified",
    "exp",
    "iat",
    "iss",
    "nbf",
    "orion_clearance",
    "orion_project_id",
    "orion_workspace_id",
    "realm_access.roles",
    "scope",
    "sub",
]

WS_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROJECT_1 = "11111111-1111-4111-8111-111111111111"
USER = "5b1d0000-0000-4000-8000-000000000001"
SERVICE_SUB = "5b1d0000-0000-4000-8000-0000000000a1"
NOVA_SUB = "5b1d0000-0000-4000-8000-0000000000a2"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def jwt_parts(header: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    return (
        b64(json.dumps(header, separators=(",", ":"), sort_keys=True).encode()),
        b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()),
    )


def sign_jwt(private_key: Any, payload: dict[str, Any], *, kid: str | None = KID, alg: str = "RS256") -> str:
    """RS256 JWT signed with a ``cryptography`` private key (fixtures and tests only; the module under test never signs)."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    header = {"alg": alg, "typ": "JWT", **({"kid": kid} if kid else {})}
    head, body = jwt_parts(header, payload)
    signature = private_key.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{head}.{body}.{b64(signature)}"


def new_key() -> Any:
    from cryptography.hazmat.primitives.asymmetric import rsa

    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def public_jwk(private_key: Any, kid: str = KID) -> dict[str, str]:
    numbers = private_key.public_key().public_numbers()

    def enc(value: int) -> str:
        return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))

    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid, "n": enc(numbers.n), "e": enc(numbers.e)}


# --- expectations (the ADR §4 table, written by hand) ----------------------------------------------------------


def decision(**kw: Any) -> dict[str, Any]:
    """An accepted token: the expected decision, with the values of the standard user unless overridden."""
    expected = {
        "valid": True,
        "error": None,
        "subject": USER,
        "workspace_id": WS_A,
        "project_id": PROJECT_1,
        "space_access": True,
        "platform_admin": False,
        "role": "editor",
        "effective_clearance": 2,
        "mfa": False,
        "email_matchable": True,
        "delegated_by": None,
        "is_service": False,
        "scopes": ["orion:context.read"],
    }
    unknown = set(kw) - set(expected)
    assert not unknown, unknown
    return {**expected, **kw}


def refused(code: str) -> dict[str, Any]:
    return {
        "valid": False,
        "error": code,
        "subject": None,
        "workspace_id": None,
        "project_id": None,
        "space_access": False,
        "platform_admin": False,
        "role": None,
        "effective_clearance": None,
        "mfa": False,
        "email_matchable": False,
        "delegated_by": None,
        "is_service": False,
        "scopes": [],
    }


def standard_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "sub": USER,
        "iat": NOW - 60,
        "exp": NOW + 540,
        "email": "alice@example.test",
        "email_verified": True,
        "name": "Alice Example",
        "preferred_username": "alice@example.test",
        "orion_workspace_id": WS_A,
        "orion_project_id": PROJECT_1,
        "orion_clearance": 2,
        "realm_access": {"roles": ["forge-editor"]},
        "scope": "orion:context.read",
        "amr": ["pwd"],
    }
    payload.update(overrides)
    return {k: v for k, v in payload.items() if v is not _DROP}


_DROP = object()  # remove the claim from the payload
LOCAL = {"clearance": 3, "role": "editor"}


def case(
    name: str,
    description: str,
    payload: dict[str, Any],
    expect: dict[str, dict[str, Any]],
    local: dict[str, dict[str, Any]] | None = None,
    defect: str | None = None,
) -> dict[str, Any]:
    locals_ = {s: {**LOCAL, **(local or {}).get(s, {})} for s in SERVICES}
    return {
        "name": name,
        "description": description,
        "payload": payload,
        "defect": defect,
        "services": {s: {"local": locals_[s], "expect": expect[s]} for s in SERVICES},
    }


def same(expected: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s: dict(expected) for s in SERVICES}


def scenarios() -> list[dict[str, Any]]:
    out = [
        case(
            "standard_user",
            "Standard user of workspace A with a project, clearance 2 granted by the organisation (local 3: lowered to 2).",
            standard_payload(),
            same(decision()),
        ),
        case(
            "administrator",
            "Administrator of the three services with MFA; the clearance claim (3) never raises the local one (1). "
            "NOVA / ORBIT: realm role = platform admin, project role stays local (no membership: none). FORGE: local admin.",
            standard_payload(
                realm_access={"roles": ["nova-admin", "orbit-admin", "forge-admin"]},
                orion_clearance=3,
                amr=["pwd", "mfa"],
            ),
            {
                "nova": decision(platform_admin=True, role=None, effective_clearance=1, mfa=True),
                "orbit": decision(platform_admin=True, role=None, effective_clearance=1, mfa=True),
                "forge": decision(platform_admin=True, role="admin", effective_clearance=1, mfa=True),
            },
            local={
                "nova": {"clearance": 1, "role": None},
                "orbit": {"clearance": 1, "role": None},
                "forge": {"clearance": 1, "role": "admin"},
            },
        ),
        case(
            "no_workspace",
            "No orion_workspace_id: valid token, but it opens no workspace resource (ADR §3). The project id is dropped too.",
            standard_payload(orion_workspace_id=_DROP, orion_project_id=_DROP),
            same(decision(workspace_id=None, project_id=None, space_access=False)),
        ),
        case(
            "project_without_workspace",
            "orion_project_id alone means nothing: no space access, project id dropped.",
            standard_payload(orion_workspace_id=_DROP),
            same(decision(workspace_id=None, project_id=None, space_access=False)),
        ),
        case(
            "workspace_without_project",
            "Workspace only (no active project): space access, no project.",
            standard_payload(orion_project_id=_DROP),
            same(decision(project_id=None)),
        ),
        case(
            "clearance_lower",
            "orion_clearance 1 below the local clearance 3: effective 1.",
            standard_payload(orion_clearance=1),
            same(decision(effective_clearance=1)),
        ),
        case(
            "clearance_higher",
            "orion_clearance 3 above the local clearance 1: effective stays 1 (the claim never raises).",
            standard_payload(orion_clearance=3),
            same(decision(effective_clearance=1)),
            local={s: {"clearance": 1} for s in SERVICES},
        ),
        case(
            "clearance_absent",
            "No orion_clearance: effective = the local clearance (2), never more.",
            standard_payload(orion_clearance=_DROP),
            same(decision(effective_clearance=2)),
            local={s: {"clearance": 2} for s in SERVICES},
        ),
        case(
            "clearance_zero",
            "orion_clearance 0 (C0 only) caps a local 3.",
            standard_payload(orion_clearance=0),
            same(decision(effective_clearance=0)),
        ),
        case(
            "clearance_malformed",
            "orion_clearance present as a string: refused, never read as 'no cap'.",
            standard_payload(orion_clearance="3"),
            same(refused("invalid_claim:orion_clearance")),
        ),
        case(
            "clearance_out_of_range",
            "orion_clearance 7 is not a level 0-3: refused.",
            standard_payload(orion_clearance=7),
            same(refused("invalid_claim:orion_clearance")),
        ),
        case(
            "delegated",
            "Token exchanged on behalf of the user (RFC 8693): act = NOVA, 5 minute lifetime; both identities are reported.",
            standard_payload(
                sub=USER,
                act={"sub": NOVA_SUB, "client_id": "nova-web"},
                exp=NOW + 240,
                iat=NOW - 60,
                scope=["orion:context.read", "orion:run.execute"],
            ),
            same(decision(delegated_by=NOVA_SUB, scopes=["orion:context.read", "orion:run.execute"])),
        ),
        case(
            "delegated_too_long",
            "A delegated token (act) living one hour: refused (ADR §3 short-lived, 15 minutes at most).",
            standard_payload(act={"sub": NOVA_SUB, "client_id": "nova-web"}, exp=NOW + 3540),
            same(refused("delegated_token_too_long")),
        ),
        case(
            "expired",
            "exp one minute ago.",
            standard_payload(exp=NOW - 60, iat=NOW - 660),
            same(refused("expired")),
        ),
        case(
            "expires_now",
            "exp equal to the clock: expired (the boundary belongs to 'expired').",
            standard_payload(exp=NOW, iat=NOW - 600),
            same(refused("expired")),
        ),
        case(
            "not_yet_valid",
            "nbf in five minutes.",
            standard_payload(nbf=NOW + 300),
            same(refused("not_yet_valid")),
        ),
        case(
            "wrong_issuer",
            "iss of another realm (the old realm 'nova').",
            standard_payload(iss="https://idp.orion.test/realms/nova"),
            same(refused("invalid_issuer")),
        ),
        case(
            "wrong_audience",
            "aud of a service that is not the reader.",
            standard_payload(),
            same(refused("invalid_audience")),
            defect="audience",
        ),
        case(
            "bad_signature",
            "Signed by a key that is not in the JWKS (same kid).",
            standard_payload(),
            same(refused("bad_signature")),
            defect="foreign_key",
        ),
        case(
            "tampered_payload",
            "A valid token whose payload was swapped afterwards to add admin roles and clearance 3.",
            standard_payload(realm_access={"roles": ["nova-admin", "orbit-admin", "forge-admin"]}, orion_clearance=3),
            same(refused("bad_signature")),
            defect="tamper",
        ),
        case(
            "alg_none",
            "Unsigned token (alg none).",
            standard_payload(),
            same(refused("unsupported_alg")),
            defect="alg_none",
        ),
        case(
            "alg_hs256",
            "HS256 signed with the public key material as secret (algorithm confusion).",
            standard_payload(),
            same(refused("unsupported_alg")),
            defect="alg_hs256",
        ),
        case(
            "unknown_claims",
            "Claims the contract does not define (including a future orion_* one) are ignored: same decision as the standard user.",
            standard_payload(
                orion_future_claim={"nested": [1, 2]},
                groups=["/everyone"],
                tenant_hint="ignored",
                realm_access={"roles": ["forge-editor", "offline_access", "uma_authorization"], "extra": True},
            ),
            same(decision()),
        ),
        case(
            "email_unverified",
            "email_verified false: valid, but the e-mail must not seed an account match.",
            standard_payload(email_verified=False),
            same(decision(email_matchable=False)),
        ),
        case(
            "service_account",
            "Client-credentials token of the NOVA service account: no e-mail, explicit local clearance 1.",
            standard_payload(
                sub=SERVICE_SUB,
                email=_DROP,
                email_verified=_DROP,
                name=_DROP,
                preferred_username="service-account-nova-service",
                orion_project_id=_DROP,
                orion_clearance=_DROP,
                realm_access={"roles": []},
                scope="orion:run.execute",
                amr=_DROP,
            ),
            same(
                decision(
                    subject=SERVICE_SUB,
                    project_id=None,
                    role=None,
                    effective_clearance=1,
                    email_matchable=False,
                    is_service=True,
                    scopes=["orion:run.execute"],
                )
            ),
            local={s: {"clearance": 1, "role": None} for s in SERVICES},
        ),
        case(
            "role_prefix_isolation",
            "Only the prefix of the reading service counts: orbit-admin is admin for ORBIT only; lookalikes grant nothing.",
            standard_payload(realm_access={"roles": ["orbit-admin", "novaadmin", "nova-administrator", "forge-"]}),
            {
                "nova": decision(),
                "orbit": decision(platform_admin=True),
                "forge": decision(),
            },
        ),
        case(
            "forge_role_cap",
            "FORGE: the realm role forge-viewer caps the local maintainer role; NOVA / ORBIT keep their local project role.",
            standard_payload(realm_access={"roles": ["forge-viewer"]}),
            {"nova": decision(), "orbit": decision(), "forge": decision(role="viewer")},
            local={"forge": {"role": "maintainer"}},
        ),
        case(
            "forge_admin_does_not_raise",
            "FORGE: forge-admin in the realm does not raise a local maintainer to admin (the token never grants on its own).",
            standard_payload(realm_access={"roles": ["forge-admin"]}),
            {"nova": decision(), "orbit": decision(), "forge": decision(role="maintainer")},
            local={"forge": {"role": "maintainer"}},
        ),
        case(
            "forge_no_realm_role",
            "FORGE: no forge-* realm role: the local role stays (an absent claim never lowers nor raises it).",
            standard_payload(realm_access={"roles": []}),
            {"nova": decision(), "orbit": decision(), "forge": decision(role="maintainer")},
            local={"forge": {"role": "maintainer"}},
        ),
        case(
            "no_local_role",
            "No local account / membership: no role, even with forge-admin and nova-admin realm roles (admin flag aside).",
            standard_payload(realm_access={"roles": ["nova-admin", "forge-admin"]}),
            {
                "nova": decision(platform_admin=True, role=None),
                "orbit": decision(role=None),
                "forge": decision(role=None),
            },
            local={s: {"role": None} for s in SERVICES},
        ),
        case(
            "malformed_roles",
            "realm_access.roles as a string instead of a list: refused.",
            standard_payload(realm_access={"roles": "forge-admin"}),
            same(refused("invalid_claim:realm_access.roles")),
        ),
        case(
            "invalid_workspace_id",
            "orion_workspace_id that is not a UUID: refused.",
            standard_payload(orion_workspace_id="not-a-uuid"),
            same(refused("invalid_claim:orion_workspace_id")),
        ),
        case(
            "missing_subject",
            "No sub: refused (the account matching key is mandatory).",
            standard_payload(sub=_DROP),
            same(refused("missing_claim:sub")),
        ),
    ]
    return out


# --- generation ----------------------------------------------------------------------------------------------------


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def make_token(spec: dict[str, Any], service: str, key: Any, other_key: Any) -> str:
    payload = {**spec["payload"], "aud": AUDIENCES[service]}
    defect = spec["defect"]
    if defect == "audience":
        payload["aud"] = "some-other-service"
    if defect == "foreign_key":
        return sign_jwt(other_key, payload)
    if defect == "alg_none":
        head, body = jwt_parts({"alg": "none", "typ": "JWT", "kid": KID}, payload)
        return f"{head}.{body}."
    if defect == "alg_hs256":
        head, body = jwt_parts({"alg": "HS256", "typ": "JWT", "kid": KID}, payload)
        secret = public_jwk(key)["n"].encode()
        return f"{head}.{body}.{b64(hmac.new(secret, f'{head}.{body}'.encode(), hashlib.sha256).digest())}"
    if defect == "tamper":
        genuine = sign_jwt(key, {**standard_payload(), "aud": AUDIENCES[service]})
        head, _, signature = genuine.split(".")
        _, body = jwt_parts({}, payload)
        return f"{head}.{body}.{signature}"
    return sign_jwt(key, payload)


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("orion_claims", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("orion_claims", module)
    spec.loader.exec_module(module)
    return module


def run_case(module: Any, fixture: dict[str, Any], jwks: dict[str, Any], service: str) -> dict[str, Any]:
    entry = fixture["services"][service]
    return module.evaluate(
        fixture["tokens"][service],
        jwks,
        service=service,
        issuer=ISSUER,
        local_clearance=entry["local"]["clearance"],
        local_role=entry["local"]["role"],
        now=NOW,
    ).as_dict()


def generate(out: Path) -> list[str]:
    """Write the fixtures into ``out``; returns the problems found by replaying them through the module (empty = ok)."""
    key, other = new_key(), new_key()
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.json"):
        stale.unlink()
    jwks = {"keys": [public_jwk(key)]}
    write_json(out / "jwks.json", jwks)
    write_json(
        out / "context.json",
        {
            "issuer": ISSUER,
            "now": NOW,
            "audiences": AUDIENCES,
            "kid": KID,
            "note": "Evaluate each case with now=<now>, issuer=<issuer>, audience <audiences[service]>, jwks.json.",
        },
    )
    fixtures = []
    for spec in scenarios():
        tokens = {s: make_token(spec, s, key, other) for s in SERVICES}
        fixture = {
            "name": spec["name"],
            "description": spec["description"],
            "defect": spec["defect"],
            "claims": spec["payload"],
            "tokens": tokens,
            "services": spec["services"],
        }
        write_json(out / f"case_{spec['name']}.json", fixture)
        fixtures.append(fixture)
    manifest = {
        "contract": "orion-claims",
        "contract_version": 1,
        "source": "NOVA scripts/generate_claims_fixtures.py (throw-away RSA test key, synthetic data); table of ADR 001 §4",
        "claims": CONTRACT_CLAIMS,
        "module": {"path": "nova/domain/orion_claims.py", "sha256": sha256(MODULE)},
        "files": {p.name: {"sha256": sha256(p)} for p in sorted(out.glob("*.json"))},
    }
    write_json(out / MANIFEST, manifest)
    return problems(out)


def problems(directory: Path, module_path: Path = MODULE) -> list[str]:
    """Consistency of a claims directory: manifest hashes, module hash, and the table replayed through the module."""
    found: list[str] = []
    manifest_path = directory / MANIFEST
    if not manifest_path.is_file():
        return [f"{directory}: {MANIFEST} is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    present = {p.name for p in directory.glob("*.json")} - {MANIFEST}
    for name in sorted(set(manifest["files"]) | present):
        if name not in present:
            found.append(f"{name}: listed in the manifest but missing")
        elif name not in manifest["files"]:
            found.append(f"{name}: present but not in the manifest")
        elif sha256(directory / name) != manifest["files"][name]["sha256"]:
            found.append(f"{name}: differs from the manifest hash")
    if module_path.is_file() and sha256(module_path) != manifest["module"]["sha256"]:
        found.append(f"{module_path.name}: differs from the manifest hash (edited, or another version)")
    if found:
        return found
    module = load_module()
    jwks = json.loads((directory / "jwks.json").read_text(encoding="utf-8"))
    for path in sorted(directory.glob("case_*.json")):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        for service in SERVICES:
            got = run_case(module, fixture, jwks, service)
            want = fixture["services"][service]["expect"]
            if got != want:
                found.append(f"{path.name} [{service}]: expected {want}, got {got}")
    return found


def main(argv: list[str]) -> int:
    check = "--check" in argv
    issues = problems(OUT) if check else generate(OUT)
    if issues:
        print("\n".join(issues))
        return 1
    print(f"{OUT.relative_to(ROOT)}: {'consistent' if check else 'generated'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

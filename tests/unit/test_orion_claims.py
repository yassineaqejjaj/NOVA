"""Edge cases of the claims module (NOV-104): what the signed fixtures do not spell out. Tokens are signed at runtime."""

from __future__ import annotations

import base64
import json

import jwt
import pytest

from nova.domain import orion_claims as oc
from tests.contract.support import load_script

gen = load_script("generate_claims_fixtures")
ISSUER, NOW = gen.ISSUER, gen.NOW


@pytest.fixture(scope="module")
def key():
    return gen.new_key()


@pytest.fixture(scope="module")
def jwks(key):
    return {"keys": [gen.public_jwk(key)]}


def token(key, **claims):
    payload = {**gen.standard_payload(), "aud": "nova-web", **claims}
    return gen.sign_jwt(key, {k: v for k, v in payload.items() if v is not gen._DROP})


def check(tok, jwks, **kw):
    return oc.validate_token(tok, jwks, issuer=ISSUER, audience="nova-web", now=NOW, **kw)


def code(tok, jwks, **kw):
    with pytest.raises(oc.ClaimsError) as exc:
        check(tok, jwks, **kw)
    return exc.value.code


def test_a_token_signed_by_a_standard_library_agrees_with_the_module(key, jwks):
    """Interoperability: PyJWT (what the services use elsewhere) signs, the standalone verifier accepts."""
    pem = key.private_bytes(*_pem_args())
    tok = jwt.encode({**gen.standard_payload(), "aud": "nova-web"}, pem, algorithm="RS256", headers={"kid": gen.KID})
    assert check(tok, jwks).subject == gen.USER


def _pem_args():
    from cryptography.hazmat.primitives import serialization

    return serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "exp", "iat"])
def test_a_missing_mandatory_claim_is_refused(key, jwks, claim):
    payload = {**gen.standard_payload(), "aud": "nova-web"}
    payload.pop(claim)
    assert code(gen.sign_jwt(key, payload), jwks) == f"missing_claim:{claim}"


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("sub", ""),
        ("exp", "9999999999"),
        ("exp", True),
        ("nbf", "0"),
        ("email_verified", "true"),
        ("orion_clearance", True),
        ("orion_clearance", 2.0),
        ("orion_clearance", -1),
        ("orion_workspace_id", 12),
        ("orion_project_id", "x"),
        ("amr", "mfa"),
        ("scope", 5),
        ("act", "nova"),
        ("act", {"client_id": "nova-web"}),
        ("realm_access", ["forge-admin"]),
        ("realm_access", {"roles": ["a", 1]}),
    ],
)
def test_a_contract_claim_of_the_wrong_type_is_refused_not_ignored(key, jwks, claim, value):
    assert code(token(key, **{claim: value}), jwks).startswith("invalid_claim:")


def test_audience_may_be_a_list(key, jwks):
    assert check(token(key, aud=["orbit", "nova-web"]), jwks).audience == ("orbit", "nova-web")
    assert code(token(key, aud=["orbit", "forge"]), jwks) == "invalid_audience"
    assert code(token(key, aud=[1]), jwks) == "invalid_claim:aud"


def test_times_and_leeway(key, jwks):
    assert code(token(key, exp=NOW), jwks) == "expired"
    assert check(token(key, exp=NOW), jwks, leeway=5).subject  # skew tolerated only when asked
    assert code(token(key, nbf=NOW + 10), jwks) == "not_yet_valid"
    assert check(token(key, nbf=NOW + 10), jwks, leeway=30).subject
    assert check(token(key, nbf=NOW), jwks).subject  # nbf equal to the clock is valid


def test_the_clock_is_used_when_now_is_omitted(key, jwks):
    tok = token(key, exp=4102444800, iat=1)  # year 2100
    assert oc.validate_token(tok, jwks, issuer=ISSUER, audience="nova-web").subject == gen.USER
    with pytest.raises(oc.ClaimsError, match="expired"):
        oc.validate_token(token(key, exp=1000, iat=1), jwks, issuer=ISSUER, audience="nova-web")


def test_scope_as_string_or_list(key, jwks):
    assert check(token(key, scope="a b  c"), jwks).scopes == ("a", "b", "c")
    claims = check(token(key, scope=["a", "b"]), jwks)
    assert claims.has_scope("a") and not claims.has_scope("c")
    assert check(token(key, scope=gen._DROP), jwks).scopes == ()


def test_identifiers_are_normalised_to_lower_case(key, jwks):
    claims = check(token(key, orion_workspace_id=gen.WS_A.upper(), orion_project_id=gen.PROJECT_1.upper()), jwks)
    assert claims.workspace_id == gen.WS_A and claims.project_id == gen.PROJECT_1
    assert oc.can_open_space_resource(claims, gen.WS_A.upper())


def test_a_malformed_project_is_refused_even_without_a_workspace(key, jwks):
    assert code(token(key, orion_workspace_id=gen._DROP, orion_project_id="x"), jwks) == "invalid_claim:orion_project_id"


def test_amr_mfa_and_email_matching(key, jwks):
    assert check(token(key, amr=["pwd", "mfa"]), jwks).mfa
    assert not check(token(key, amr=["pwd"]), jwks).mfa
    assert not check(token(key, amr=gen._DROP), jwks).mfa
    assert not check(token(key, email=gen._DROP), jwks).email_matchable
    assert not check(token(key, email_verified=gen._DROP), jwks).email_matchable  # absent = not verified


def test_a_token_with_roles_missing_has_none(key, jwks):
    claims = check(token(key, realm_access=gen._DROP), jwks)
    assert claims.realm_roles == () and claims.roles_for("nova") == frozenset()
    assert check(token(key, realm_access={}), jwks).realm_roles == ()


def test_roles_are_read_by_prefix_only(key, jwks):
    claims = check(token(key, realm_access={"roles": ["nova-admin", "orbit-admin", "forge-editor", "forge-", "nova"]}), jwks)
    assert claims.roles_for("nova") == {"admin"}
    assert claims.roles_for("orbit") == {"admin"}
    assert claims.roles_for("forge") == {"editor"}


def test_an_actor_token_may_live_fifteen_minutes_not_more(key, jwks):
    act = {"sub": "s", "client_id": "nova-web"}
    assert check(token(key, act=act, iat=NOW - 60, exp=NOW + 840), jwks).actor == oc.Actor("s", "nova-web")  # 900 s
    assert code(token(key, act=act, iat=NOW - 60, exp=NOW + 841), jwks) == "delegated_token_too_long"
    assert check(token(key, act=gen._DROP, iat=NOW - 60, exp=NOW + 3000), jwks).actor is None  # a plain token: no such limit


def test_service_account_detection(key, jwks):
    assert check(token(key, preferred_username="service-account-nova-service"), jwks).is_service
    assert not check(token(key, preferred_username="service-account"), jwks).is_service
    assert not check(token(key), jwks).is_service


# --- token and key handling -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a.b", "a.b.c.d", "...", "x.y.z", "é.é.é"])
def test_garbage_is_malformed(jwks, bad):
    assert code(bad, jwks) == "malformed_token"


def test_non_string_token(jwks):
    with pytest.raises(oc.ClaimsError):
        oc.validate_token(None, jwks, issuer=ISSUER, audience="nova-web", now=NOW)  # type: ignore[arg-type]


def test_header_must_be_a_json_object_with_rs256(key, jwks):
    for header, expected in [
        ({"alg": "RS384", "kid": gen.KID}, "unsupported_alg"),
        ({"alg": "rs256", "kid": gen.KID}, "unsupported_alg"),
        ({"kid": gen.KID}, "unsupported_alg"),
        ({"alg": "RS256", "kid": gen.KID, "crit": ["exp"]}, "unsupported_header"),
    ]:
        head, body = gen.jwt_parts(header, {**gen.standard_payload(), "aud": "nova-web"})
        assert code(f"{head}.{body}.{gen.b64(b'x' * 256)}", jwks) == expected
    head = gen.b64(b"[1]")
    assert code(f"{head}.{head}.{head}", jwks) == "malformed_token"


def test_key_selection(key, jwks):
    other = gen.new_key()
    pair = {"keys": [gen.public_jwk(other, "other"), gen.public_jwk(key)]}
    assert check(token(key), pair).subject  # by kid
    assert code(gen.sign_jwt(key, {**gen.standard_payload(), "aud": "nova-web"}, kid="missing"), pair) == "unknown_key"
    # no kid: only accepted when exactly one key could have signed
    no_kid = gen.sign_jwt(key, {**gen.standard_payload(), "aud": "nova-web"}, kid=None)
    assert check(no_kid, jwks).subject
    assert code(no_kid, pair) == "unknown_key"
    assert code(token(key), {"keys": []}) == "unknown_key"
    assert code(token(key), {}) == "unknown_key"
    assert code(token(key), {"keys": "x"}) == "unknown_key"
    assert code(token(key), None) == "unknown_key"  # type: ignore[arg-type]


def test_unusable_keys_are_ignored_or_refused(key):
    good = gen.public_jwk(key)
    for patch in ({"use": "enc"}, {"alg": "RS512"}, {"kty": "EC"}):
        assert code(token(key), {"keys": [{**good, **patch}]}) == "unknown_key"
    assert code(token(key), {"keys": [{**good, "e": gen.b64((3).to_bytes(1, "big"))}]}) == "unknown_key"  # exponent 3
    assert code(token(key), {"keys": [{k: v for k, v in good.items() if k != "n"}]}) == "unknown_key"
    from cryptography.hazmat.primitives.asymmetric import rsa

    small = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    tok = gen.sign_jwt(small, {**gen.standard_payload(), "aud": "nova-web"})
    assert code(tok, {"keys": [gen.public_jwk(small)]}) == "unknown_key"  # below 2048 bits


def test_signature_must_be_exactly_the_modulus_length(key, jwks):
    head, body, sig = token(key).split(".")
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    for bad in (raw[1:], b"\x00" + raw, raw + b"\x00", b"\x00" * len(raw), b"\xff" * len(raw)):
        assert code(f"{head}.{body}.{gen.b64(bad)}", jwks) == "bad_signature"


def test_padding_is_compared_in_full(key, jwks):
    """A signature whose recovered block has the right digest but a different padding (Bleichenbacher style) is refused."""
    numbers = key.private_numbers()
    n, d = numbers.public_numbers.n, numbers.d
    size = (n.bit_length() + 7) // 8
    head, body, _ = token(key).split(".")
    import hashlib

    info = oc._SHA256_DIGEST_INFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
    # garbage after the digest info, short run of 0xff: a lax parser would accept
    block = b"\x00\x01" + b"\xff" * 8 + b"\x00" + info + b"\x01" * (size - len(info) - 11)
    forged = pow(int.from_bytes(block, "big"), d, n).to_bytes(size, "big")
    assert code(f"{head}.{body}.{gen.b64(forged)}", jwks) == "bad_signature"


# --- clearance, roles, space ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("local", "claim", "expected"),
    [(3, 1, 1), (1, 3, 1), (2, None, 2), (0, 3, 0), (3, 0, 0), (2, 2, 2)],
)
def test_effective_clearance_is_a_minimum(local, claim, expected):
    assert oc.effective_clearance(local, claim) == expected


@pytest.mark.parametrize("local", [-1, 4, True, "1", None, 1.0])
def test_a_bad_local_clearance_is_a_programming_error(local):
    with pytest.raises(ValueError):
        oc.effective_clearance(local, 1)


def test_cap_role():
    ladder = oc.FORGE_ROLES
    assert oc.cap_role("maintainer", "viewer", ladder) == "viewer"
    assert oc.cap_role("viewer", "admin", ladder) == "viewer"
    assert oc.cap_role("editor", None, ladder) == "editor"
    assert oc.cap_role(None, "admin", ladder) is None
    with pytest.raises(ValueError):
        oc.cap_role("root", "admin", ladder)


def test_decide_for_each_service_and_unknown_service(key, jwks):
    claims = check(token(key, realm_access={"roles": ["nova-admin", "forge-viewer"]}), jwks)
    assert oc.decide(claims, "nova", local_clearance=3, local_role="owner").platform_admin
    assert oc.decide(claims, "nova", local_clearance=3, local_role="owner").role == "owner"
    assert oc.decide(claims, "forge", local_clearance=3, local_role="admin").role == "viewer"
    with pytest.raises(ValueError):
        oc.decide(claims, "other", local_clearance=1)
    with pytest.raises(ValueError):
        oc.evaluate("x", jwks, service="other", issuer=ISSUER, local_clearance=1)
    with pytest.raises(ValueError):
        oc.decide(claims, "nova", local_clearance=1, local_role="admin")  # not a project role


def test_no_claims_no_space():
    assert not oc.can_open_space_resource(None, gen.WS_A)
    assert not oc.can_open_project(None, gen.WS_A, gen.PROJECT_1)


def test_decision_of_a_refused_token_grants_nothing(key, jwks):
    decision = oc.evaluate(
        token(key, exp=NOW - 1), jwks, service="nova", issuer=ISSUER, local_clearance=3, local_role="owner", now=NOW
    )
    assert decision == oc.Decision(valid=False, error="expired")
    assert json.dumps(decision.as_dict())  # serialisable

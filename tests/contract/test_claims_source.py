"""NOVA is the source of the claims contract (NOV-104): generator, mutations, module independence.

``test_claims_contract.py`` is the portable part (copied to ORBIT and FORGE); this file only runs where the generator is.
"""

from __future__ import annotations

import ast
import copy
import json
import sys

import pytest

from tests.contract.support import ROOT, load_script
from tests.contract.test_claims_contract import CASES, CLAIMS_DIR, CONTEXT, JWKS, MANIFEST, MODULE_PATH, orion_claims

generator = load_script("generate_claims_fixtures")


def test_the_committed_fixtures_replay_through_the_generator_check():
    assert generator.problems(CLAIMS_DIR) == []


def test_the_generator_runs_without_a_committed_key_and_replays_its_own_table(tmp_path):
    assert generator.generate(tmp_path) == []
    names = {p.name for p in tmp_path.glob("*.json")}
    assert names == {p.name for p in CLAIMS_DIR.glob("*.json")}
    fresh = json.loads((tmp_path / "jwks.json").read_text())
    assert fresh != JWKS  # a new throw-away key every run: nothing secret to commit
    assert "d" not in fresh["keys"][0] and "p" not in fresh["keys"][0]  # public material only


def test_the_committed_cases_are_the_cases_the_generator_defines():
    spec = {s["name"]: s for s in generator.scenarios()}
    assert set(spec) == set(CASES)
    for name, case in CASES.items():
        assert case["claims"] == json.loads(json.dumps({k: v for k, v in spec[name]["payload"].items()}))
        assert case["services"] == json.loads(json.dumps(spec[name]["services"]))


def test_the_module_is_standard_library_only():
    """It is copied byte for byte into ORBIT and FORGE: no import of this repository, no third-party package."""
    tree = ast.parse(MODULE_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.level == 0
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names), sorted(imported - set(sys.stdlib_module_names))


def test_the_manifest_records_the_module_path_and_the_claims_list():
    assert MANIFEST["module"]["path"] == "nova/domain/orion_claims.py"
    assert ROOT / MANIFEST["module"]["path"] == MODULE_PATH
    assert MANIFEST["claims"] == generator.CONTRACT_CLAIMS


# --- mutation: removing or renaming a contract claim changes a decision (the acceptance criterion) ----------------


@pytest.fixture(scope="module")
def key():
    return generator.new_key()


def decide_with(key, payload, service, local):
    token = generator.sign_jwt(key, {**payload, "aud": generator.AUDIENCES[service]})
    return orion_claims.evaluate(
        token,
        {"keys": [generator.public_jwk(key)]},
        service=service,
        issuer=CONTEXT["issuer"],
        local_clearance=local["clearance"],
        local_role=local["role"],
        now=CONTEXT["now"],
    ).as_dict()


#: contract claim -> (fixture, service) whose decision depends on it (``aud`` is added per service: see the last test)
WITNESS = {
    "act": ("delegated", "orbit"),
    "amr": ("administrator", "nova"),
    "email": ("standard_user", "nova"),
    "email_verified": ("standard_user", "nova"),
    "exp": ("standard_user", "nova"),
    "iat": ("standard_user", "nova"),
    "iss": ("standard_user", "nova"),
    "orion_clearance": ("standard_user", "nova"),
    "orion_project_id": ("standard_user", "nova"),
    "orion_workspace_id": ("standard_user", "nova"),
    "realm_access.roles": ("administrator", "orbit"),
    "scope": ("standard_user", "nova"),
    "sub": ("standard_user", "nova"),
    "nbf": ("not_yet_valid", "nova"),
}


def test_every_contract_claim_has_a_witness():
    assert set(WITNESS) | {"aud"} == set(MANIFEST["claims"])


@pytest.mark.parametrize("claim", sorted(WITNESS))
@pytest.mark.parametrize("mutation", ["removed", "renamed"])
def test_a_claim_removed_or_renamed_changes_the_decision(key, claim, mutation):
    name, service = WITNESS[claim]
    case = CASES[name]
    local = case["services"][service]["local"]
    payload = copy.deepcopy(case["claims"])
    payload.pop("aud", None)
    if claim == "realm_access.roles":
        roles = payload["realm_access"].pop("roles")
        if mutation == "renamed":
            payload["realm_access"]["realm_roles"] = roles
    else:
        value = payload.pop(claim)
        if mutation == "renamed":
            payload[f"{claim}_renamed"] = value
    baseline = case["services"][service]["expect"]
    assert decide_with(key, payload, service, local) != baseline, f"{claim} {mutation}: the decision did not change"


def test_aud_removed_or_renamed_is_refused(key):
    payload = copy.deepcopy(CASES["standard_user"]["claims"])
    for body in ({}, {"audience": "nova-web"}):
        token = generator.sign_jwt(key, {**payload, **body})
        decision = orion_claims.evaluate(
            token,
            {"keys": [generator.public_jwk(key)]},
            service="nova",
            issuer=CONTEXT["issuer"],
            local_clearance=3,
            now=CONTEXT["now"],
        )
        assert not decision.valid

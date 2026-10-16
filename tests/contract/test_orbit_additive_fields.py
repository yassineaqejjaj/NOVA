"""ORBIT NOV-106 adds ``orion_project_id`` (additive, schema_version unchanged): NOVA must carry it in its copy and ignore it."""

from __future__ import annotations

import re

import pytest

from nova.integrations.orbit.mapper import context_bundle
from nova.integrations.orbit.schemas import OrbitContextPackage
from tests.contract.support import ORBIT_DIR, load

#: synthetic, the value ORBIT writes in its fixtures
ORION_PROJECT_ID = "0a0b0c0d-0000-4000-8000-000000000106"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
FILES = ["context_package.json", "context_package_limited_rights.json", "snapshot.json"]


@pytest.mark.parametrize("name", FILES)
def test_the_orbit_copy_carries_the_orion_project_id(name):
    payload = load(ORBIT_DIR, name)
    assert payload["orion_project_id"] == ORION_PROJECT_ID and UUID.match(payload["orion_project_id"])
    assert load(ORBIT_DIR, "manifest.json")["schema_version"] == 2  # additive: no new version


@pytest.mark.parametrize("name", ["context_package.json", "context_package_limited_rights.json"])
def test_nova_reads_the_package_unchanged_and_ignores_the_new_key(name):
    payload = load(ORBIT_DIR, name)
    without = {k: v for k, v in payload.items() if k != "orion_project_id"}
    with_key = context_bundle(OrbitContextPackage.model_validate(payload), "forge", "http://orbit")
    plain = context_bundle(OrbitContextPackage.model_validate(without), "forge", "http://orbit")
    assert with_key.model_dump() == plain.model_dump()  # an ORBIT without the key is still accepted (readers ignore unknown keys)


def test_the_key_never_lowers_what_the_package_already_pinned():
    payload = load(ORBIT_DIR, "context_package.json")
    assert payload["max_classification"] == 3 and payload["schema_version"] == 2

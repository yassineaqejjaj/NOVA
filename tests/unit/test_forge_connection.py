"""One endpoint and one credential tell FORGE how to call NOVA back, whichever flow registers the agent version."""

from __future__ import annotations

import pytest

from nova.config import Settings
from nova.integrations.forge import connection, versions
from nova.integrations.forge.client import ForgeError


def settings(**over) -> Settings:
    base = dict(public_url="https://nova-web.example", forge_nova_endpoint="", forge_credential_id="")
    return Settings(**{**base, **over})


def test_the_configured_endpoint_wins_over_the_public_url():
    s = settings(forge_nova_endpoint="https://nova-api.example/")
    assert connection.forge_callback_endpoint(s) == "https://nova-api.example"


def test_without_configuration_the_local_web_port_becomes_the_api_port():
    assert connection.forge_callback_endpoint(settings(public_url="http://localhost:3200")) == "http://localhost:8200"


def test_the_credential_is_the_configured_id_or_nothing():
    assert connection.forge_credential(settings(forge_credential_id="cred-1")) == "cred-1"
    assert connection.forge_credential(settings()) is None


def test_a_complete_connection_has_no_problem():
    s = settings(forge_nova_endpoint="https://nova-api.example", forge_credential_id="cred-1")
    assert connection.connection_problems(s) == []
    connection.require_connection(s)


def test_a_missing_credential_is_reported_clearly():
    s = settings(forge_nova_endpoint="https://nova-api.example")
    assert connection.connection_problems(s) == ["NOVA_FORGE_CREDENTIAL_ID is not set (FORGE would call NOVA without credential)"]
    with pytest.raises(connection.ForgeConfigurationError, match="NOVA_FORGE_CREDENTIAL_ID"):
        connection.require_connection(s)


def test_a_public_url_that_is_the_frontend_is_not_accepted_as_the_api_endpoint():
    s = settings(forge_credential_id="cred-1")
    assert any("NOVA_FORGE_NOVA_ENDPOINT is not set" in p for p in connection.connection_problems(s))
    assert connection.connection_problems(settings(forge_credential_id="c", public_url="http://localhost:3200")) == []


def test_an_endpoint_that_is_not_a_url_is_reported():
    s = settings(forge_nova_endpoint="nova-api", forge_credential_id="cred-1")
    assert connection.connection_problems(s) == ["NOVA_FORGE_NOVA_ENDPOINT is not an http(s) URL"]


def test_explicit_values_replace_the_configured_ones():
    assert connection.connection_problems(settings(), endpoint="https://api.example", credential_id="c") == []


def test_the_connection_fingerprint_follows_the_endpoint_and_the_credential():
    base = connection.connection_key("https://a", "c1")
    assert base == connection.connection_key("https://a", "c1")
    assert len({base, connection.connection_key("https://b", "c1"), connection.connection_key("https://a", None)}) == 3


def body(**over):
    return {"version": "1.0+abcdef01", "endpoint": "https://nova-api.example", "credential_id": "cred-1", **over}


def test_a_version_matches_only_the_connection_it_was_registered_with():
    registered = {"endpoint": "https://nova-api.example/", "credential": {"id": "cred-1"}}
    assert versions.matches(registered, body())
    assert versions.matches({"endpoint": "https://nova-api.example", "credential_id": "cred-1"}, body())
    assert not versions.matches({"endpoint": "https://nova-api.example"}, body())  # registered without credential
    assert not versions.matches({**registered, "endpoint": "https://nova-web.example"}, body())
    assert not versions.matches(registered, body(credential_id=None))


def test_the_unique_label_is_distinct_per_connection_and_fits_forge():
    one, two = body(version="x" * 40), body(version="x" * 40, endpoint="https://other.example")
    assert versions.unique_label(one) != versions.unique_label(two)
    assert len(versions.unique_label(one)) <= 40 and versions.unique_label(one) == versions.unique_label(dict(one))


class FakeForge:
    """Creating a label twice, or a version identical to the latest one, is a 409 like in FORGE."""

    def __init__(self, existing: list[dict] | None = None) -> None:
        self.versions = list(existing or [])
        self.created: list[dict] = []

    async def list_agent_versions(self, agent_id):
        return self.versions

    async def create_agent_version(self, agent_id, new):
        if any(v["version"] == new["version"] for v in self.versions):
            raise ForgeError(409, "label exists")
        record = {"id": f"v{len(self.versions) + 1}", **new}
        self.versions.append(record)
        self.created.append(new)
        return record


async def test_a_version_registered_for_the_connection_is_reused_on_409():
    forge = FakeForge([{"id": "old", **body()}])
    assert (await versions.register_agent_version(forge, "a", body()))["id"] == "old" and forge.created == []


async def test_a_version_registered_without_credential_is_replaced_by_a_new_one_on_409():
    forge = FakeForge([{"id": "old", "version": "1.0+abcdef01", "endpoint": "https://nova-api.example"}])
    new = await versions.register_agent_version(forge, "a", body())
    assert new["id"] != "old" and new["credential_id"] == "cred-1" and new["version"] != "1.0+abcdef01"
    again = await versions.register_agent_version(forge, "a", body())  # a retry finds that new version
    assert again["id"] == new["id"] and len(forge.created) == 1


def test_a_version_registered_for_another_model_or_provider_does_not_match():
    wanted = body(model={"provider": "anthropic", "model": "claude-x"})
    same = {**body(), "model_configuration": {"provider": "anthropic", "model": "claude-x"}}
    assert versions.matches(same, wanted)
    assert versions.matches({**body(), "model": {"provider": "anthropic", "model": "claude-x"}}, wanted)  # body-shaped
    assert not versions.matches({**same, "model_configuration": {"provider": "vllm", "model": "claude-x"}}, wanted)
    assert not versions.matches({**same, "model_configuration": {"provider": "anthropic", "model": "other"}}, wanted)
    assert not versions.matches(body(), wanted)  # registered without any model


async def test_a_409_never_reuses_a_version_whose_model_differs():
    old = {"id": "old", **body(model={"provider": "vllm", "model": "model-a"})}
    forge = FakeForge([old])
    new = await versions.register_agent_version(forge, "a", body(model={"provider": "vllm", "model": "model-b"}))
    assert new["id"] != "old" and new["model"]["model"] == "model-b" and new["version"] != old["version"]

"""ORBIT snapshots: mapper, client and provider against the fake ORBIT server (no network)."""

from __future__ import annotations

import httpx
import pytest

from nova.agent.tools.registry import ToolDenied, get_tool_registry
from nova.config import get_settings
from nova.domain.context import ContextError, ContextQuery, SnapshotRef
from nova.domain.outputs import ToolRequest
from nova.domain.permissions import Permission
from nova.integrations.orbit import mapper
from nova.integrations.orbit.adapter import OrbitContextProvider
from nova.integrations.orbit.client import OrbitClient
from tests.support import fake_orbit_server as fake


def _provider() -> OrbitContextProvider:
    client = OrbitClient("http://orbit", transport=httpx.ASGITransport(app=fake.app))
    return OrbitContextProvider(get_settings(), client)


def test_context_request_sends_base_snapshot_only_when_asked():
    base = {"user_id": "u", "project_slug": "forge", "task": "t"}
    assert "base_snapshot" not in mapper.context_request(ContextQuery(**base), on_behalf_of=None)
    body = mapper.context_request(ContextQuery(**base, base_snapshot=SnapshotRef(name="release-plan")), on_behalf_of=None)
    assert body["base_snapshot"] == {"name": "release-plan"}
    body = mapper.context_request(
        ContextQuery(**base, base_snapshot=SnapshotRef(name="release-plan", version=2)), on_behalf_of=None
    )
    assert body["base_snapshot"] == {"name": "release-plan", "version": 2}


def test_snapshot_mappers_ignore_unknown_fields_and_keep_content_out_of_the_list():
    info = mapper.snapshot_info({"name": "a", "latest_version": 3, "versions": 3, "last_task": None, "future": 1})
    assert info.latest_version == 3 and info.last_task == ""
    snap = mapper.snapshot(
        {
            "name": "a",
            "version": 3,
            "content": "x [S1]",
            "items": [{"key": "chunk:1", "citation": "S1", "forgotten": True}],
            "z": 1,
        }
    )
    assert snap.items[0].forgotten and snap.content == "x [S1]"


async def test_client_and_provider_against_the_fake_orbit(user):
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    listed = await provider.list_snapshots(user.user_id, "forge")
    assert [(s.name, s.latest_version, s.versions) for s in listed] == [("release-plan", 2, 2)]
    latest = await provider.get_snapshot(user.user_id, "forge", "release-plan")
    assert latest.version == 2 and len(latest.items) == 2 and "[S1]" in latest.content
    assert (await provider.get_snapshot(user.user_id, "forge", "release-plan", 1)).version == 1
    with pytest.raises(ContextError) as exc:
        await provider.get_snapshot(user.user_id, "forge", "ghost")
    assert exc.value.code == "not_found"


async def test_retrieve_with_base_snapshot_pins_its_items_then_completes(user):
    provider = _provider()
    await provider.link_account(user.user_id, fake.USER["email"], fake.PASSWORD)
    query = ContextQuery(
        user_id=user.user_id, project_slug="forge", task="plan", base_snapshot=SnapshotRef(name="release-plan", version=1)
    )
    bundle = await provider.retrieve(query)
    assert fake.LAST_CONTEXT_BODY["base_snapshot"] == {"name": "release-plan", "version": 1}
    assert bundle.snapshot == SnapshotRef(name="release-plan", version=1)
    assert bundle.items[0].title == "Q4 Objectives" and len({i.title for i in bundle.items}) == len(bundle.items)
    with pytest.raises(ContextError) as exc:
        await provider.retrieve(query.model_copy(update={"base_snapshot": SnapshotRef(name="ghost")}))
    assert exc.value.code == "not_found"


def test_snapshot_tools_are_read_only_and_follow_the_orbit_read_permission():
    tools = get_tool_registry()
    for name in ("list_orbit_snapshots", "get_orbit_snapshot"):
        tool = tools.get(name)
        assert tool.permission is Permission.context_read and not tool.external_write and "orbit" in name
        assert (
            tools.authorize(ToolRequest(tool=name), allowed=[name], permissions=frozenset({Permission.context_read})).name == name
        )
        with pytest.raises(ToolDenied, match="Missing permission"):
            tools.authorize(ToolRequest(tool=name), allowed=[name], permissions=frozenset())
        with pytest.raises(ToolDenied, match="not declared"):
            tools.authorize(ToolRequest(tool=name), allowed=[], permissions=frozenset({Permission.context_read}))

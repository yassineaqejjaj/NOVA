"""Figma integration: MCP client, URL parsing, REST normalization, adapter (MCP vs token), tools. No network."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from nova.agent.tools.builtin import FigmaGetDesignIn, FigmaPushIn, figma_get_design, figma_push_screens
from nova.agent.tools.registry import ToolContext, ToolDenied
from nova.config import get_settings
from nova.domain.artifacts import ArtifactContent, ArtifactItem, SectionContent
from nova.domain.design import DesignError, DesignRef, ElementSpec, ScreenSpec, TokenSpec
from nova.domain.enums import SectionKind
from nova.infra.crypto import encrypt
from nova.infra.models import FigmaAccount
from nova.integrations.figma.adapter import FigmaDesignProvider, build_push_instruction
from nova.integrations.figma.mcp import McpClient
from nova.integrations.figma.oauth import make_state, pkce_pair, read_state
from nova.integrations.figma.rest import FigmaRestClient
from nova.integrations.figma.urls import parse_figma_url


def rpc(request: httpx.Request) -> dict:
    return json.loads(request.content)


def mcp_server(tools: dict, *, sse: bool = False, seen: list | None = None):
    """Fake Figma MCP: tools maps name -> (inputSchema props, result)."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = rpc(request)
        if seen is not None:
            seen.append(
                (
                    body.get("method"),
                    body.get("params"),
                    request.headers.get("mcp-session-id"),
                    request.headers.get("authorization"),
                )
            )
        method = body.get("method")
        if "id" not in body:
            return httpx.Response(202)
        if method == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "figma"}}
        elif method == "tools/list":
            result = {
                "tools": [{"name": n, "inputSchema": {"properties": {k: {} for k in props}}} for n, (props, _) in tools.items()]
            }
        else:
            name = body["params"]["name"]
            payload = tools[name][1]
            text = payload if isinstance(payload, str) else json.dumps(payload)
            result = {"content": [{"type": "text", "text": text}]}
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        headers = {"Mcp-Session-Id": "sess-1"}
        if sse:
            return httpx.Response(
                200,
                headers={**headers, "content-type": "text/event-stream"},
                text=f"event: message\ndata: {json.dumps(message)}\n\n",
            )
        return httpx.Response(200, headers=headers, json=message)

    return httpx.MockTransport(handler)


async def test_mcp_client_json_and_session_id():
    seen: list = []
    transport = mcp_server({"get_metadata": (("fileKey", "nodeId"), {"ok": True})}, seen=seen)
    async with McpClient("https://mcp.test/mcp", "tok", transport=transport) as mcp:
        assert await mcp.tool_names() == {"get_metadata"}
        assert await mcp.call_tool("get_metadata", {"fileKey": "K"}) == {"ok": True}
    methods = [m for m, *_ in seen]
    assert methods[:3] == ["initialize", "notifications/initialized", "tools/list"]
    assert seen[0][2] is None and seen[-1][2] == "sess-1"  # session id echoed after initialize
    assert all(auth == "Bearer tok" for *_, auth in seen)


async def test_mcp_client_sse_response():
    transport = mcp_server({"t": ((), "plain text")}, sse=True)
    async with McpClient("https://mcp.test/mcp", "tok", transport=transport) as mcp:
        assert await mcp.call_tool("t") == "plain text"


async def test_mcp_client_error_mapping():
    def unauthorized(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    async with McpClient("https://mcp.test/mcp", "tok", transport=httpx.MockTransport(unauthorized)) as mcp:
        with pytest.raises(DesignError) as err:
            await mcp.list_tools()
    assert err.value.code == "not_connected"

    def tool_error(request: httpx.Request) -> httpx.Response:
        body = rpc(request)
        if "id" not in body:
            return httpx.Response(202)
        result = (
            {"content": [{"type": "text", "text": "Node not found"}], "isError": True} if body["method"] == "tools/call" else {}
        )
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    async with McpClient("https://mcp.test/mcp", "tok", transport=httpx.MockTransport(tool_error)) as mcp:
        with pytest.raises(DesignError) as err:
            await mcp.call_tool("get_metadata")
    assert err.value.code == "not_found"


@pytest.mark.parametrize(
    ("url", "key", "node"),
    [
        ("https://www.figma.com/design/AbC123/My-file?node-id=1-2&t=x", "AbC123", "1:2"),
        ("https://figma.com/file/AbC123/Old", "AbC123", None),
        ("https://www.figma.com/proto/AbC123/P?node-id=10-20", "AbC123", "10:20"),
        ("https://www.figma.com/design/AbC123/branch/BrKey/Name", "BrKey", None),
    ],
)
def test_parse_figma_url(url, key, node):
    ref = parse_figma_url(url)
    assert ref and ref.file_key == key and ref.node_id == node


def test_parse_figma_url_rejects_others():
    assert parse_figma_url("https://evil.com/design/AbC/x") is None
    assert parse_figma_url("https://www.figma.com/community/x") is None


def test_oauth_state_roundtrip_and_expiry():
    verifier, challenge = pkce_pair()
    assert len(challenge) == 43
    state = make_state("user-1", verifier, now=1000)
    assert read_state(state, now=1100) == ("user-1", verifier)
    with pytest.raises(DesignError):
        read_state(state, now=5000)
    with pytest.raises(DesignError):
        read_state("forged")


REST_FILE = {
    "name": "Checkout",
    "document": {
        "id": "0:0",
        "name": "Doc",
        "type": "DOCUMENT",
        "children": [
            {
                "id": "1:1",
                "name": "Page 1",
                "type": "CANVAS",
                "children": [
                    {
                        "id": "1:2",
                        "name": "Login",
                        "type": "FRAME",
                        "absoluteBoundingBox": {"width": 390, "height": 844},
                        "children": [{"id": "1:3", "name": "Title", "type": "TEXT", "characters": "Sign in"}],
                    }
                ],
            }
        ],
    },
}
REST_VARS = {
    "meta": {
        "variableCollections": {"c1": {"defaultModeId": "m1"}},
        "variables": {
            "v1": {
                "name": "color/primary",
                "resolvedType": "COLOR",
                "variableCollectionId": "c1",
                "valuesByMode": {"m1": {"r": 1, "g": 0, "b": 0, "a": 1}},
            }
        },
    }
}


def rest_transport(seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        assert request.headers["x-figma-token"] == "pat"
        path = request.url.path
        if path == "/v1/me":
            return httpx.Response(200, json={"id": "9", "handle": "Yass", "email": "y@x.io"})
        if path.endswith("/variables/local"):
            return httpx.Response(200, json=REST_VARS)
        if path.endswith("/nodes"):
            return httpx.Response(
                200,
                json={"name": "Checkout", "nodes": {"1:2": {"document": REST_FILE["document"]["children"][0]["children"][0]}}},
            )
        if path.startswith("/v1/files/"):
            return httpx.Response(200, json=REST_FILE)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_rest_snapshot_normalization():
    client = FigmaRestClient("https://api.figma.com", "pat", transport=rest_transport())
    snap = await client.snapshot("K", None)
    assert snap.source == "rest" and snap.file_name == "Checkout"
    assert snap.nodes[0].name == "Page 1" and snap.nodes[0].children[0].children[0].text == "Sign in"
    assert snap.variables[0].name == "color/primary" and snap.variables[0].value == "#ff0000"
    node_snap = await client.snapshot("K", "1:2")
    assert node_snap.nodes[0].id == "1:2" and node_snap.nodes[0].width == 390


async def test_rest_node_cap():
    from nova.integrations.figma.rest import MAX_NODES, normalize_node

    wide = {
        "id": "r",
        "name": "x" * 500,
        "type": "FRAME",
        "children": [{"id": str(i), "name": "n", "type": "TEXT"} for i in range(500)],
    }
    budget = [MAX_NODES]
    node = normalize_node(wide, budget)
    assert node and len(node.name) <= 80 and len(node.children) == MAX_NODES - 1 and budget[0] == 0


def settings():
    return get_settings().model_copy(update={"figma_oauth_client_id": "client", "figma_mcp_url": "https://mcp.test/mcp"})


async def link(user_id: str, mode: str, *, expired: bool = False):
    from datetime import timedelta

    from nova.infra import db

    async with db.session_scope() as session:
        session.add(
            FigmaAccount(
                user_id=__import__("uuid").UUID(user_id),
                mode=mode,
                handle="yass",
                token_ciphertext=encrypt("pat" if mode == "token" else "oauth-tok"),
                refresh_ciphertext=encrypt("refresh") if mode == "oauth" else None,
                expires_at=db.utcnow() + timedelta(hours=-1 if expired else 1) if mode == "oauth" else None,
            )
        )


async def test_adapter_status_and_not_connected(user):
    provider = FigmaDesignProvider(settings())
    assert (await provider.status(user.user_id)).linked is False
    with pytest.raises(DesignError) as err:
        await provider.get_design(user.user_id, DesignRef(file_key="K"))
    assert err.value.code == "not_connected"


async def test_adapter_token_mode_reads_rest_and_refuses_writes(user):
    await link(user.user_id, "token")
    provider = FigmaDesignProvider(settings(), transport=rest_transport())
    status = await provider.status(user.user_id)
    assert (status.mode, status.mcp, status.can_write, status.figma_handle) == ("token", False, False, "yass")
    snap = await provider.get_design(user.user_id, DesignRef(file_key="K"))
    assert snap.source == "rest"
    with pytest.raises(DesignError) as err:
        await provider.push_screens(user.user_id, "T", [ScreenSpec(name="A")], [])
    assert err.value.code == "write_unavailable"


async def test_adapter_oauth_reads_through_mcp_and_refreshes(user):
    await link(user.user_id, "oauth", expired=True)
    seen: list = []
    tools = {
        "get_metadata": (
            ("fileKey", "nodeId"),
            '<frame id="1:2" name="Login" width="390" height="844"><text id="1:3" name="Title">Sign in</text></frame>',
        ),
        "get_variable_defs": (("fileKey", "nodeId"), {"color/primary": "#ff0000"}),
    }
    mcp = mcp_server(tools, seen=seen)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth/token":
            assert b"refresh_token=refresh" in request.content
            return httpx.Response(200, json={"access_token": "fresh", "refresh_token": "r2", "expires_in": 3600})
        return httpx.Response(404)  # discovery fails: fallback endpoints

    provider = FigmaDesignProvider(settings(), transport=_Router(handler, mcp))
    snap = await provider.get_design(user.user_id, DesignRef(file_key="K", node_id="1:2"))
    assert snap.source == "mcp" and snap.nodes[0].id == "1:2" and snap.nodes[0].children[0].text == "Sign in"
    assert snap.variables[0].value == "#ff0000"
    assert seen[0][3] == "Bearer fresh"
    call = next(p for m, p, *_ in seen if m == "tools/call")
    assert call["arguments"] == {"fileKey": "K", "nodeId": "1:2"}


class _Router(httpx.AsyncBaseTransport):
    """Sends MCP URL traffic to the fake MCP transport and everything else to ``handler``."""

    def __init__(self, handler, mcp: httpx.MockTransport) -> None:
        self.handler, self.mcp = handler, mcp

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "mcp.test":
            return await self.mcp.handle_async_request(request)
        return self.handler(request)


SCREENS = [
    ScreenSpec(
        name="Login",
        device="mobile",
        fidelity="lowfi",
        elements=[
            ElementSpec(type="heading", label="Welcome", region="body", row=0),
            ElementSpec(type="input", label="Email", region="body", row=1, span=6),
            ElementSpec(type="button", label="Go", region="body", row=1, span=6, variant="primary"),
            ElementSpec(type="nav", label="Logo", region="header", row=0),
        ],
    )
]
TOKENS = [TokenSpec(name="color/primary", category="color", value="#ff0000")]


def test_push_instruction_is_deterministic_and_ordered():
    one = build_push_instruction("T", SCREENS, TOKENS)
    assert one == build_push_instruction("T", SCREENS, TOKENS)
    spec = json.loads(one.split("SPEC:\n", 1)[1])
    regions = spec["screens"][0]["regions"]
    assert [r["region"] for r in regions] == ["header", "body"]
    assert [len(row) for row in regions[1]["rows"]] == [1, 2] and spec["screens"][0]["width"] == 390


async def test_adapter_oauth_push_creates_file_then_writes(user):
    await link(user.user_id, "oauth")
    seen: list = []
    tools = {
        "create_new_file": (("name",), {"file_key": "NEW123", "url": "https://www.figma.com/design/NEW123/T"}),
        "use_figma": (("fileKey", "prompt"), "done"),
    }
    provider = FigmaDesignProvider(settings(), transport=mcp_server(tools, seen=seen))
    result = await provider.push_screens(user.user_id, "T", SCREENS, TOKENS)
    assert result.external_id == "NEW123" and result.url == "https://www.figma.com/design/NEW123/T"
    write = [p for m, p, *_ in seen if m == "tools/call"][-1]
    assert write["name"] == "use_figma" and write["arguments"]["fileKey"] == "NEW123" and "Login" in write["arguments"]["prompt"]


def ctx(design, store=None, user_id="u"):
    return ToolContext(state=SimpleNamespace(user_id=user_id), deps=SimpleNamespace(design=design, store=store))


async def test_tools_denied_when_not_connected():
    with pytest.raises(ToolDenied, match="Connect Figma"):
        await figma_get_design(ctx(None), FigmaGetDesignIn(url="https://www.figma.com/design/K/x"))
    with pytest.raises(ToolDenied, match="Connect Figma"):
        await figma_push_screens(ctx(None), FigmaPushIn(artifact_id="a"))


async def test_tool_get_design_maps_errors_and_parses_url(user):
    provider = FigmaDesignProvider(settings(), transport=rest_transport())
    with pytest.raises(ToolDenied, match="Connect Figma"):
        await figma_get_design(
            ctx(provider, user_id=user.user_id), FigmaGetDesignIn(url="https://www.figma.com/design/K/x?node-id=1-2")
        )
    await link(user.user_id, "token")
    out = await figma_get_design(
        ctx(provider, user_id=user.user_id), FigmaGetDesignIn(url="https://www.figma.com/design/K/x?node-id=1-2")
    )
    assert out.source == "rest" and out.nodes[0].id == "1:2"
    with pytest.raises(ToolDenied, match="not a Figma"):
        await figma_get_design(ctx(provider, user_id=user.user_id), FigmaGetDesignIn(url="https://example.com/x"))


async def test_tool_push_denied_in_token_mode(user):
    await link(user.user_id, "token")
    content = ArtifactContent(
        type="ui_screens",
        title="Mockups",
        sections={
            "screens": SectionContent(
                kind=SectionKind.items,
                items=[
                    ArtifactItem(
                        kind="screen",
                        title="Login",
                        attributes={
                            "fidelity": "hifi",
                            "device": "mobile",
                            "states": "empty, error",
                            "elements": [{"id": "e1", "type": "button", "label": "Go", "region": "body", "row": 0, "span": 12}],
                        },
                    )
                ],
            ),
            "tokens": SectionContent(
                kind=SectionKind.items,
                items=[
                    ArtifactItem(kind="design_token", title="color/primary", attributes={"category": "color", "value": "#f00"})
                ],
            ),
        },
    )

    class Store:
        async def get_artifact(self, artifact_id, user_id):
            return SimpleNamespace(type="ui_screens", title="Mockups", content=content)

    provider = FigmaDesignProvider(settings(), transport=rest_transport())
    with pytest.raises(ToolDenied, match="MCP"):
        await figma_push_screens(ctx(provider, Store(), user.user_id), FigmaPushIn(artifact_id="a"))

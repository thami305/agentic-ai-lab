"""Lab 7 acceptance tests — Client 2: hand-rolled JSON-RPC 2.0 client.

Speaks raw MCP over the same in-memory streams (initialize, then
notifications/initialized, then tools/list etc., matching responses by
request id). Covers discovery, a valid tool call, invalid args, and path
traversal — proving the server interoperates beyond the SDK client.
"""

import anyio
import pytest

from lab07.errors import CODE_TO_JSONRPC, ErrorCode
from lab07.server import build_server

from .helpers import RawError, raw_client, reset_test_hooks


@pytest.fixture(autouse=True)
def _reset_hooks():
    reset_test_hooks()
    yield
    reset_test_hooks()


def test_01_raw_discovery():
    async def _():
        async with raw_client(build_server(), "analyst") as c:
            tools = await c.list_tools()
            assert [t["name"] for t in tools["tools"]] == ["search_cases"]
            schema = tools["tools"][0]["inputSchema"]
            assert set(schema["properties"]) == {"query", "limit"}
            assert schema["required"] == ["query"]

            tmpls = await c.list_resource_templates()
            assert [t["uriTemplate"] for t in tmpls["resourceTemplates"]] == ["brief://{+client_id}"]

            prompts = await c.list_prompts()
            assert [p["name"] for p in prompts["prompts"]] == ["discovery_interview"]
            assert [a["name"] for a in prompts["prompts"][0]["arguments"]] == ["client_name"]

    anyio.run(_)


def test_02_raw_valid_tool_call():
    async def _():
        async with raw_client(build_server(), "analyst") as c:
            result = await c.call_tool("search_cases", {"query": "acme", "limit": 5})
            assert result["isError"] is False
            import json

            # the server emits one JSON TextContent block per hit
            hits = [json.loads(block["text"]) for block in result["content"]]
            assert [h["id"] for h in hits] == ["c1", "c8"]

    anyio.run(_)


def test_03_raw_invalid_args():
    """Schema-level invalid args come back as a normal result with isError=true."""

    async def _():
        async with raw_client(build_server(), "analyst") as c:
            result = await c.call_tool("search_cases", {"query": 123, "limit": 5})
            assert result["isError"] is True
            assert "search_cases" in result["content"][0]["text"]

    anyio.run(_)


def test_04_raw_path_traversal():
    """Both traversal forms are rejected as JSON-RPC errors with the
    path_traversal code — no resource content is returned."""

    async def _():
        async with raw_client(build_server(), "viewer") as c:
            for uri in ("brief://../secrets", "brief://%2e%2e%2fsecrets"):
                with pytest.raises(RawError) as exc:
                    await c.read_resource(uri)
                assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.PATH_TRAVERSAL]
                assert ErrorCode.PATH_TRAVERSAL in exc.value.message

    anyio.run(_)

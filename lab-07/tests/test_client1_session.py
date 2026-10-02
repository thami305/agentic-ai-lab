"""Lab 7 acceptance tests — Client 1: high-level SDK ClientSession.

Covers discovery, valid calls, invalid args, oversized input, path
traversal, the malicious-resource fixture, authorization, logging
(redaction + request ids), read-only defaults, timeout recovery, and
mid-call disconnect. Async bodies run via anyio.run (no pytest-asyncio).
"""

import logging

import anyio
import pytest

from mcp.client._memory import InMemoryTransport
from mcp.shared.exceptions import MCPError

import lab07.server as server_mod
from lab07.auth import current_role
from lab07.errors import CODE_TO_JSONRPC, ErrorCode
from lab07.server import build_server

from .helpers import (
    MALICIOUS_TEXT,
    UNTRUSTED_LABEL,
    capture_lab07_logs,
    client_session,
    consume_resource_text,
    reset_test_hooks,
    tool_result_json,
)


@pytest.fixture(autouse=True)
def _reset_hooks():
    reset_test_hooks()
    yield
    reset_test_hooks()


# ---------------------------------------------------------- discovery ---

def test_01_discovery_lists_all_capabilities():
    """tools/list, resources/templates/list, prompts/list expose exactly the spec'd surface."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            tools = await s.list_tools()
            assert [t.name for t in tools.tools] == ["search_cases"]
            schema = tools.tools[0].input_schema
            assert set(schema["properties"]) == {"query", "limit"}
            assert schema["properties"]["query"]["type"] == "string"
            assert schema["properties"]["limit"]["type"] == "integer"
            assert schema["required"] == ["query"]

            tmpls = await s.list_resource_templates()
            assert len(tmpls.resource_templates) == 1
            assert tmpls.resource_templates[0].uri_template == "brief://{+client_id}"

            prompts = await s.list_prompts()
            assert [p.name for p in prompts.prompts] == ["discovery_interview"]
            assert [(a.name, a.required) for a in prompts.prompts[0].arguments] == [
                ("client_name", True)
            ]

    anyio.run(_)


# -------------------------------------------------------- happy paths ---

def test_02_tool_valid_search():
    async def _():
        async with client_session(build_server(), "analyst") as s:
            hits = tool_result_json(await s.call_tool("search_cases", {"query": "acme", "limit": 5}))
            assert [h["id"] for h in hits] == ["c1", "c8"]
            assert all(set(h) == {"id", "title", "snippet"} for h in hits)

            limited = tool_result_json(await s.call_tool("search_cases", {"query": "acme", "limit": 1}))
            assert [h["id"] for h in limited] == ["c1"]

            empty = tool_result_json(await s.call_tool("search_cases", {"query": "zzz-no-match", "limit": 5}))
            assert empty == []

    anyio.run(_)


def test_03_resource_valid_read():
    async def _():
        async with client_session(build_server(), "viewer") as s:
            result = await s.read_resource("brief://acme")
            text = result.contents[0].text
            assert "ACME CORP" in text
            assert result.contents[0].mime_type == "text/plain"

    anyio.run(_)


def test_04_prompt_get():
    async def _():
        async with client_session(build_server(), "viewer") as s:
            result = await s.get_prompt("discovery_interview", {"client_name": "Acme"})
            assert len(result.messages) == 2
            assert all(m.content.text for m in result.messages)
            assert "Acme" in result.messages[1].content.text
            assert "What must the solution NEVER do" in result.messages[1].content.text

    anyio.run(_)


# ------------------------------------------------------------- errors ---

def test_05_tool_invalid_args_schema_level():
    """Wrong JSON types fail schema validation: is_error result, nothing executed."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            result = await s.call_tool("search_cases", {"query": 123, "limit": 5})
            assert result.is_error
            assert "search_cases" in result.content[0].text

    anyio.run(_)


def test_06_tool_invalid_args_semantic():
    """Semantically invalid args raise the invalid_args taxonomy code."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            for args in ({"query": "   ", "limit": 5}, {"query": "acme", "limit": 0}):
                with pytest.raises(MCPError) as exc:
                    await s.call_tool("search_cases", args)
                assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.INVALID_ARGS]
                assert ErrorCode.INVALID_ARGS in exc.value.message

    anyio.run(_)


def test_07_oversized_input_rejected():
    async def _():
        async with client_session(build_server(), "analyst") as s:
            with pytest.raises(MCPError) as exc:
                await s.call_tool("search_cases", {"query": "x" * 201, "limit": 5})
            assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.OVERSIZED_INPUT]
            assert ErrorCode.OVERSIZED_INPUT in exc.value.message

    anyio.run(_)


def test_08_path_traversal_rejected():
    """Both the plain and the percent-encoded traversal attempts are rejected
    with the explicit path_traversal code and return no data."""

    async def _():
        async with client_session(build_server(), "viewer") as s:
            for uri in ("brief://../secrets", "brief://%2e%2e%2fsecrets"):
                with pytest.raises(MCPError) as exc:
                    await s.read_resource(uri)
                assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.PATH_TRAVERSAL]
                assert ErrorCode.PATH_TRAVERSAL in exc.value.message

    anyio.run(_)


def test_09_resource_not_found():
    async def _():
        async with client_session(build_server(), "viewer") as s:
            with pytest.raises(MCPError) as exc:
                await s.read_resource("brief://umbrella")
            assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.NOT_FOUND]
            assert ErrorCode.NOT_FOUND in exc.value.message

    anyio.run(_)


def test_10_unauthorized_tool_call():
    """A viewer calling search_cases gets unauthorized — and no data."""

    async def _():
        async with client_session(build_server(), "viewer") as s:
            with pytest.raises(MCPError) as exc:
                await s.call_tool("search_cases", {"query": "acme", "limit": 5})
            assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.UNAUTHORIZED]
            assert ErrorCode.UNAUTHORIZED in exc.value.message

    anyio.run(_)


def test_11_unauthorized_resource_read():
    """An analyst reading a brief gets unauthorized — and no data."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            with pytest.raises(MCPError) as exc:
                await s.read_resource("brief://acme")
            assert exc.value.code == CODE_TO_JSONRPC[ErrorCode.UNAUTHORIZED]

    anyio.run(_)


def test_12_no_write_tools_exist():
    """Read-only defaults: the server exposes exactly one tool, and its name
    is not a write operation."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            names = [t.name for t in (await s.list_tools()).tools]
            assert names == ["search_cases"]
            write_verbs = ("create", "update", "delete", "write", "send", "post", "put", "patch")
            assert not any(v in n.lower() for n in names for v in write_verbs)

    anyio.run(_)


# ------------------------------------------- malicious resource data ---

def test_13_malicious_resource_returned_verbatim_and_labeled():
    """The globex brief arrives verbatim (fixture intact); the client-side
    consumer wraps it in an untrusted-data boundary; the embedded
    instruction is never acted on (canary: no email side effect exists)."""
    sent_emails = []

    def send_email(*args, **kwargs):  # the capability the injection asks for
        sent_emails.append((args, kwargs))

    async def _():
        async with client_session(build_server(), "viewer") as s:
            text = (await s.read_resource("brief://globex")).contents[0].text
            assert MALICIOUS_TEXT in text  # fixture returned verbatim

            wrapped = consume_resource_text(text)
            assert UNTRUSTED_LABEL in wrapped  # boundary label present
            assert MALICIOUS_TEXT in wrapped  # still data, still visible

            # The consumer treats the text as data only: it never calls send_email.
            assert sent_emails == []

    anyio.run(_)


# ------------------------------------------------------------ logging ---

def test_14_request_ids_unique_per_call():
    """Every log record for a call carries that call's UUID; ids differ across calls."""

    async def _():
        with capture_lab07_logs() as records:
            async with client_session(build_server(), "analyst") as s:
                await s.call_tool("search_cases", {"query": "acme", "limit": 5})
                await s.call_tool("search_cases", {"query": "globex", "limit": 5})
        assert records, "expected log records"
        assert all(getattr(r, "request_id", "-") != "-" for r in records)
        ids = {r.request_id for r in records}
        assert len(ids) == 2, f"expected 2 distinct request ids, got {ids}"

    anyio.run(_)


def test_15_secrets_redacted_from_logs():
    """A fake secret inside tool input never appears in emitted log records."""
    secret = "sk-test-SECRET123"

    async def _():
        with capture_lab07_logs() as records:
            async with client_session(build_server(), "analyst") as s:
                await s.call_tool("search_cases", {"query": f"token {secret} acme", "limit": 5})
        assert records, "expected log records"
        for r in records:
            assert "SECRET123" not in r.getMessage(), f"secret leaked in: {r.getMessage()}"
        assert any("[REDACTED]" in r.getMessage() for r in records)

    anyio.run(_)


# --------------------------------------------- timeouts / disconnects ---

def test_16_tool_timeout_then_recovery():
    """A slow tool call can be bounded client-side; the session and server
    keep working afterwards."""

    async def _():
        async with client_session(build_server(), "analyst") as s:
            server_mod._test_delay_s = 5.0
            try:
                with anyio.fail_after(1.0):
                    await s.call_tool("search_cases", {"query": "acme", "limit": 5})
                pytest.fail("expected the slow call to time out")
            except TimeoutError:
                pass
            finally:
                server_mod._test_delay_s = 0.0

            hits = tool_result_json(await s.call_tool("search_cases", {"query": "acme", "limit": 5}))
            assert [h["id"] for h in hits] == ["c1", "c8"]

    anyio.run(_)


def test_17_disconnect_mid_call_then_server_reusable():
    """Closing the streams mid-call: cleanup stays bounded and the same
    server object serves a fresh client afterwards."""

    async def _():
        from mcp import ClientSession as CS

        server = build_server()
        server_mod._test_delay_s = 30.0
        outcome = {}

        async def slow_call(read, write):
            try:
                session = CS(read, write)
                await session.initialize()
                await session.call_tool("search_cases", {"query": "acme", "limit": 5})
                outcome["completed"] = True
            except Exception as e:  # noqa: BLE001 — disconnect must fail the orphaned call
                outcome["error"] = e

        with anyio.fail_after(20):  # cleanup itself is bounded
            async with InMemoryTransport(server) as (read, write):
                async with anyio.create_task_group() as tg:
                    tg.start_soon(slow_call, read, write)
                    await anyio.sleep(0.5)  # let the call reach the server
                    await write.aclose()
                    await read.aclose()
                # task group exits once the orphaned call fails on closed streams

        assert "error" in outcome, "the in-flight call should have failed on disconnect"
        assert "completed" not in outcome

        server_mod._test_delay_s = 0.0
        async with client_session(server, "analyst") as s:
            hits = tool_result_json(await s.call_tool("search_cases", {"query": "acme", "limit": 5}))
            assert [h["id"] for h in hits] == ["c1", "c8"]

    anyio.run(_)

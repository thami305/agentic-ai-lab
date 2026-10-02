"""Lab 7 MCP server: three capabilities, deterministic controls.

Capabilities (exactly three):
  1. resource  brief://{client_id}   — read-only client brief, allow-listed ids
  2. tool      search_cases          — keyword search over data/cases.json
  3. prompt    discovery_interview   — reusable prompt template (arg: client_name)

Controls:
  - JSON-schema arg validation (from type hints; the SDK validates before
    the handler runs; semantic checks raise the taxonomy errors below).
  - Allow-listed resource ids only; path traversal rejected explicitly.
  - Read-only: no write tools exist.
  - Explicit error taxonomy (errors.py); Lab7Error -> MCPError at the
    handler boundary so clients see stable JSON-RPC codes.
  - stdlib logging with secret redaction + a UUID request id per call.
  - Per-capability authorization server-side via a role contextvar:
    search_cases requires "analyst", the brief resource requires "viewer".

Test seams (module level, never part of the MCP contract):
  - _test_delay_s: seconds to sleep inside search_cases, for timeout tests.
"""

import anyio
import contextlib
import json
import re
import urllib.parse
from pathlib import Path

from mcp.server.mcpserver import MCPServer, ResourceSecurity

from . import logging_utils
from .auth import ROLE_ANALYST, ROLE_VIEWER, require_role
from .errors import ErrorCode, Lab7Error, to_protocol_error
from .logging_utils import get_logger, new_request_id, request_id_ctx

MAX_QUERY_LEN = 200
MAX_NAME_LEN = 200
MIN_LIMIT, MAX_LIMIT = 1, 50

ALLOW_LISTED_CLIENTS = ("acme", "globex", "initech")

# Test-only hook: seconds search_cases sleeps before searching. Lets tests
# exercise client-side timeouts without polluting the tool's contract.
_test_delay_s: float = 0.0

_TRAVERSAL_RE = re.compile(r"\.\.|[/\\]|\x00")


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def load_briefs(data_dir: Path) -> dict:
    return json.loads((data_dir / "briefs.json").read_text(encoding="utf-8"))


def load_cases(data_dir: Path) -> list:
    return json.loads((data_dir / "cases.json").read_text(encoding="utf-8"))


@contextlib.contextmanager
def request_scope(operation: str):
    """Set the per-request UUID, log entry/rejection, translate errors."""
    token = request_id_ctx.set(new_request_id())
    rid = request_id_ctx.get()
    log = get_logger("server")
    try:
        log.info("%s start request_id=%s", operation, rid)
        yield rid
    except Lab7Error as err:
        log.warning("%s rejected request_id=%s code=%s", operation, rid, err.code)
        raise to_protocol_error(err) from err
    finally:
        request_id_ctx.reset(token)


def validate_client_id(raw: str) -> str:
    """Allow-list + traversal validation for the brief resource id."""
    decoded = urllib.parse.unquote(raw)
    if _TRAVERSAL_RE.search(decoded):
        raise Lab7Error(
            ErrorCode.PATH_TRAVERSAL,
            f"client id {raw!r} looks like path traversal; only allow-listed ids are readable",
        )
    if decoded not in ALLOW_LISTED_CLIENTS:
        raise Lab7Error(ErrorCode.NOT_FOUND, f"no brief for client id {decoded!r}")
    return decoded


def search_case_store(cases: list, query: str, limit: int) -> list:
    q = query.casefold()
    hits = []
    for case in cases:
        haystack = f"{case['title']}\n{case['summary']}\n{' '.join(case['tags'])}".casefold()
        if q in haystack:
            hits.append(
                {"id": case["id"], "title": case["title"], "snippet": case["summary"][:120]}
            )
            if len(hits) >= limit:
                break
    return hits


def build_server(data_dir: Path | None = None) -> MCPServer:
    data_dir = data_dir or _default_data_dir()
    briefs = load_briefs(data_dir)
    cases = load_cases(data_dir)
    logging_utils.install()
    log = get_logger("server")

    server = MCPServer("lab7-briefs")

    @server.tool()
    async def search_cases(query: str, limit: int = 5) -> list[dict]:
        """Keyword search over the synthetic case file (read-only).

        Args:
            query: keyword(s) to match against case titles, summaries, tags.
            limit: max hits to return (1-50).
        """
        with request_scope("tool.search_cases") as rid:
            require_role(ROLE_ANALYST, capability="tool 'search_cases'")
            if not query or not query.strip():
                raise Lab7Error(ErrorCode.INVALID_ARGS, "query must be a non-empty string")
            if len(query) > MAX_QUERY_LEN:
                raise Lab7Error(
                    ErrorCode.OVERSIZED_INPUT,
                    f"query is {len(query)} chars; max is {MAX_QUERY_LEN}",
                )
            if not (MIN_LIMIT <= limit <= MAX_LIMIT):
                raise Lab7Error(
                    ErrorCode.INVALID_ARGS,
                    f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
                )
            if _test_delay_s:
                await anyio.sleep(_test_delay_s)
            hits = search_case_store(cases, query, limit)
            log.info(
                "tool.search_cases done request_id=%s query=%r hits=%d",
                rid,
                query,
                len(hits),
            )
            return hits

    @server.resource(
        # Reserved expansion {+client_id} (not {client_id}) is deliberate:
        # plain expansion refuses to route URIs containing "/", so an
        # unencoded traversal attempt would die in the SDK's router as
        # "unknown resource" instead of reaching OUR validator. Reserved
        # expansion routes the raw value through, and validate_client_id
        # rejects it with the explicit path_traversal taxonomy code.
        "brief://{+client_id}",
        # Opt out of the SDK's generic path-safety so OUR taxonomy (with its
        # explicit path_traversal code) is what rejects traversal, not the
        # SDK's ResourceSecurityError. validate_client_id does the checking.
        security=ResourceSecurity(exempt_params={"client_id"}),
        description="Read-only client brief, keyed by allow-listed client id.",
        mime_type="text/plain",
    )
    async def get_brief(client_id: str) -> str:
        with request_scope("resource.brief") as rid:
            require_role(ROLE_VIEWER, capability="resource 'brief'")
            clean_id = validate_client_id(client_id)
            text = briefs[clean_id]
            log.info("resource.brief done request_id=%s client_id=%s", rid, clean_id)
            return text

    @server.prompt()
    async def discovery_interview(client_name: str) -> list[dict]:
        """Reusable discovery-interview prompt template for a client."""
        with request_scope("prompt.discovery_interview"):
            if not client_name or not client_name.strip():
                raise Lab7Error(ErrorCode.INVALID_ARGS, "client_name must be a non-empty string")
            if len(client_name) > MAX_NAME_LEN:
                raise Lab7Error(
                    ErrorCode.OVERSIZED_INPUT,
                    f"client_name is {len(client_name)} chars; max is {MAX_NAME_LEN}",
                )
            return [
                {
                    "role": "assistant",
                    "content": (
                        "You are a senior consultant running a discovery interview. "
                        "Ask one question at a time, listen, and take notes. "
                        "The model proposes follow-ups; your notes decide what is recorded."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Discovery interview guide for {client_name}.\n\n"
                        "1. What outcome would make this engagement a success in one sentence?\n"
                        "2. Who decides, and who feels the pain day to day?\n"
                        "3. What have you already tried, and what did it cost?\n"
                        "4. What data exists today, and who is allowed to see it?\n"
                        "5. What must the solution NEVER do, even if asked?\n\n"
                        f"Client: {client_name}. Begin with question 1."
                    ),
                },
            ]

    return server

"""Explicit error taxonomy for Lab 7.

Every anticipated failure is raised as a Lab7Error carrying one of the
taxonomy codes below. Handlers translate it into an MCPError, which the
MCP SDK surfaces as a top-level JSON-RPC error, so clients see a stable
machine-readable code (in ``error.code`` and ``error.data.code``) plus a
human message prefixed with the code name.
"""

from mcp.shared.exceptions import MCPError


class ErrorCode:
    INVALID_ARGS = "invalid_args"
    UNAUTHORIZED = "unauthorized"
    NOT_FOUND = "not_found"
    OVERSIZED_INPUT = "oversized_input"
    PATH_TRAVERSAL = "path_traversal"


# JSON-RPC reserves -32768..-32000; -32099..-32000 is the implementation-
# defined server-error range, which is where application codes belong.
CODE_TO_JSONRPC = {
    ErrorCode.INVALID_ARGS: -32001,
    ErrorCode.UNAUTHORIZED: -32002,
    ErrorCode.NOT_FOUND: -32003,
    ErrorCode.OVERSIZED_INPUT: -32004,
    ErrorCode.PATH_TRAVERSAL: -32005,
}

JSONRPC_TO_CODE = {v: k for k, v in CODE_TO_JSONRPC.items()}


class Lab7Error(Exception):
    """An anticipated, categorized failure. Never leaks internals."""

    def __init__(self, code: str, message: str) -> None:
        if code not in CODE_TO_JSONRPC:
            raise ValueError(f"unknown Lab7 error code: {code!r}")
        self.code = code
        super().__init__(message)


def to_protocol_error(err: Lab7Error) -> MCPError:
    """Translate a taxonomy error into the wire-level MCPError."""
    return MCPError(
        code=CODE_TO_JSONRPC[err.code],
        message=f"[{err.code}] {err}",
        data={"code": err.code},
    )

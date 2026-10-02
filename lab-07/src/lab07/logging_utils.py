"""Logging with request IDs and secret redaction (stdlib logging only).

Every log record emitted while handling a request carries the request's
UUID (injected by RequestContextFilter from a contextvar set at handler
entry). RedactingFilter scrubs secret-looking tokens from the record's
message and args before formatting, so a key that arrives inside tool
input can never land in a log line.
"""

import logging
import re
import uuid
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("lab07_request_id", default="-")

# Matches test/placeholder secret tokens such as sk-test-SECRET123.
SECRET_RE = re.compile(r"sk-test-[A-Za-z0-9_\-]+")


def redact(text: str) -> str:
    return SECRET_RE.sub("[REDACTED]", text)


def new_request_id() -> str:
    return uuid.uuid4().hex


class RequestContextFilter(logging.Filter):
    """Stamp every record with the in-flight request's UUID."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class RedactingFilter(logging.Filter):
    """Scrub secrets from the record before it is formatted/emitted."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, str):
                record.args = redact(record.args)
        return True


def _ensure_filters(logger: logging.Logger) -> None:
    if not any(isinstance(f, RequestContextFilter) for f in logger.filters):
        logger.addFilter(RequestContextFilter())
    if not any(isinstance(f, RedactingFilter) for f in logger.filters):
        logger.addFilter(RedactingFilter())


def get_logger(name: str) -> logging.Logger:
    # Filters are attached to the emitting logger itself, not just the
    # "lab07" parent: Logger.callHandlers() walks ancestors for handlers
    # but never applies an ancestor's filters, so parent-attached filters
    # would silently never run on records from lab07.* children.
    logger = logging.getLogger(f"lab07.{name}")
    _ensure_filters(logger)
    return logger


def install() -> None:
    """Attach the filters to the lab07 logger tree (idempotent)."""
    _ensure_filters(logging.getLogger("lab07"))

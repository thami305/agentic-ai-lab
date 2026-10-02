"""Lab 10 schemas — every boundary crossing is typed and validated.

Attack-surface lesson: the schema is the first wall. Path traversal,
injection strings, and smuggled fields (like a model-supplied "consent")
die here, before any tool code runs. `extra="forbid"` everywhere means a
caller cannot sneak in fields the tool never declared.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Client ids are lowercase slugs. Anything else (../, null bytes, SQL-ish
# payloads, overlong strings) is rejected before a tool ever sees it.
CLIENT_ID_RE = r"^[a-z0-9][a-z0-9_-]{0,63}$"


def _client_id_field() -> Field:
    return Field(pattern=CLIENT_ID_RE,
                 description="client id: lowercase alphanumeric slug")


class _NoExtra(BaseModel):
    model_config = {"extra": "forbid"}


class ReadClientArgs(_NoExtra):
    client_id: str = _client_id_field()


class SearchDocsArgs(_NoExtra):
    client_id: str = _client_id_field()
    query: str = Field(min_length=1, max_length=200)

    @field_validator("query")
    @classmethod
    def no_control_chars(cls, v: str) -> str:
        if any(ord(c) < 32 for c in v):
            raise ValueError("query must not contain control characters")
        return v


class ExportClientListArgs(_NoExtra):
    client_id: str = _client_id_field()
    format: Literal["csv", "json"] = "csv"


class SendNotificationArgs(_NoExtra):
    client_id: str = _client_id_field()
    channel: Literal["email", "sms"] = "email"
    message: str = Field(min_length=1, max_length=500)


class WriteMemoryArgs(_NoExtra):
    # NOTE: there is deliberately no "consent" field. Consent is not a
    # model-supplied argument; it lives in the ConsentStore and can only be
    # granted by the user outside the conversation.
    fact: str = Field(min_length=1, max_length=500)
    scope: Literal["session", "client"] = "session"


class UpdateClientNoteArgs(_NoExtra):
    client_id: str = _client_id_field()
    note: str = Field(min_length=1, max_length=500)


class OutageProbeArgs(_NoExtra):
    """Test-only tool that raises mid-run. Takes no arguments."""


class FinalAnswer(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Decline(BaseModel):
    reason: str = Field(min_length=5, max_length=300)

"""Lab 10 signed approval channel + shown-vs-actual gate.

The core rule: an approval is only valid if it is HMAC-signed with the
channel secret AND the text that was shown to the approver matches the
canonical rendering of the actual payload. A "manager approved" claim in
conversation history is not an approval — it carries no signature. A
signature over misleading text (attack 9) fails the shown-vs-actual check
even though the HMAC itself verifies.

Teaching model: the model proposes, deterministic code decides. The gate
is deterministic code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    """Stable hash of the exact payload the tool will execute with."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def canonical_render(action: str, payload: dict[str, Any]) -> str:
    """The one true human-readable rendering of an action + payload.

    The gate compares this against the `shown_text` on the approval. Any
    divergence (attack 9: "send summary to client" shown while the payload
    is export_client_list) is a denial.
    """
    parts = ", ".join(f"{k}={v!r}" for k, v in sorted(payload.items()))
    return f"{action}({parts})"


@dataclass(frozen=True)
class ApprovalRequest:
    action: str
    payload: dict[str, Any]
    payload_hash: str
    shown_text: str


@dataclass(frozen=True)
class Approval:
    action: str
    payload_hash: str
    shown_text: str
    signature: str


class ApprovalChannel:
    """The only legitimate issuer of approvals. Holds the HMAC secret."""

    def __init__(self, secret: bytes) -> None:
        if not secret:
            raise ValueError("approval channel secret must not be empty")
        self._secret = bytes(secret)

    def build_request(self, action: str, payload: dict[str, Any]) -> ApprovalRequest:
        payload = dict(payload)
        return ApprovalRequest(
            action=action,
            payload=payload,
            payload_hash=canonical_payload_hash(payload),
            shown_text=canonical_render(action, payload),
        )

    def sign(self, action: str, payload_hash: str, shown_text: str) -> str:
        msg = f"{action}|{payload_hash}|{shown_text}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def issue(self, request: ApprovalRequest) -> Approval:
        """The legitimate approve path: sign what was actually shown."""
        return Approval(
            action=request.action,
            payload_hash=request.payload_hash,
            shown_text=request.shown_text,
            signature=self.sign(request.action, request.payload_hash,
                                request.shown_text),
        )


class ApprovalGate:
    """Verifies approvals against a request. Fail closed on any mismatch."""

    def __init__(self, channel: ApprovalChannel) -> None:
        self._channel = channel

    def verify(self, approval: Approval | None,
               request: ApprovalRequest) -> tuple[bool, str]:
        if approval is None:
            return False, "no_approval_presented"
        if approval.action != request.action:
            return False, "action_mismatch"
        if approval.payload_hash != request.payload_hash:
            return False, "payload_hash_mismatch"
        expected = self._channel.sign(approval.action, approval.payload_hash,
                                      approval.shown_text)
        if not hmac.compare_digest(expected, approval.signature):
            # Attack 7: spoofed "manager approved" message from conversation
            # history carries no valid HMAC. Rejected here.
            return False, "signature_invalid"
        if approval.shown_text != request.shown_text:
            # Attack 9: the HMAC is valid, but the approver was shown
            # different text than the canonical rendering of the payload
            # that would actually execute.
            return False, "shown_text_mismatch"
        return True, "approved"

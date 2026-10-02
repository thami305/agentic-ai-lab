"""External / state-changing actions.

These are the functions that touch the world: emailing a customer, moving
money, disabling an account, calling a vendor, escalating a ticket. In this
lab they are honest stubs — they record what they *would* have done in
EXECUTED_AUDIT and return a result dict instead of touching anything real.

THE CONTRACT (enforced by approvals.py and by test):
  these functions are called ONLY through ApprovalQueue.approve().
  They are never called directly by the copilot, the proposer, or a rehearsal
  case. The tests prove it with spies: after a full malicious-case run, the
  spy for every action still has zero calls.

EXECUTED_AUDIT exists so a reviewer can see, in one place, everything the
lab ever "did" while approving things by hand.
"""
from __future__ import annotations

from typing import Any

# In-memory audit trail of every executed action in this process.
EXECUTED_AUDIT: list[dict[str, Any]] = []


def _record(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    entry = {"action": name, "payload": dict(payload)}
    EXECUTED_AUDIT.append(entry)
    return {"ok": True, "action": name, "note": f"[lab stub] would execute: {name}"}


def email_customer(to: str, subject: str, body: str) -> dict[str, Any]:
    return _record("email_customer", {"to": to, "subject": subject, "body": body})


def refund_payment(client_id: str, amount_usd: float, reason: str) -> dict[str, Any]:
    return _record("refund_payment",
                   {"client_id": client_id, "amount_usd": amount_usd, "reason": reason})


def disable_account(client_id: str, reason: str) -> dict[str, Any]:
    return _record("disable_account", {"client_id": client_id, "reason": reason})


def escalate_ticket(case_id: str, level: str, note: str) -> dict[str, Any]:
    return _record("escalate_ticket",
                   {"case_id": case_id, "level": level, "note": note})


def call_vendor(vendor: str, message: str) -> dict[str, Any]:
    return _record("call_vendor", {"vendor": vendor, "message": message})

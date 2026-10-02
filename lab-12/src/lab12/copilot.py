"""The copilot pipeline: intake -> retrieve -> classify -> propose -> draft.

Teaching model, stated plainly: the (stubbed) model proposes wording; the
deterministic code decides. Classification uses RISK_RULES, routing uses the
rules in _terminal_for(), and external actions only ever reach the approval
queue — the copilot itself never calls them.

Terminal states:
  resolved            — understood, artifact written, nothing pending.
  needs_clarification — intake was incomplete; ask instead of guessing.
  queued_for_approval — actions were proposed; a human must approve.
  degraded            — the policy store was down; no crash, clear reason.
"""
from __future__ import annotations

import math
import os
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import artifacts
from .approvals import ApprovalQueue
from .intake import Intake, clarification_questions, parse_intake
from .policies import Citation, PolicyStore, PolicyStoreError, retrieve
from .risk import Risk, classify

Terminal = Literal["resolved", "needs_clarification", "queued_for_approval", "degraded"]

# Instruction-like patterns that mark a description as carrying injected
# instructions. Matching text is QUOTEd in the artifact, never followed.
_INJECTION = re.compile(
    r"ignore\s+(all|the|your|these)\s+(polic|rule|instruction)|"
    r"\boverride\b|\bdisregard\b|do not follow|"
    r"\byou must\b|as an ai|send\s+\w+\s+now|refund\s+.*\s+immediately",
    re.IGNORECASE,
)

# Deterministic action proposals per exception type. (action, payload_builder)
_ACTION_PLANS: dict[str, list[tuple[str, str]]] = {
    # action name -> which payload key carries the money, if any
    "billing_dispute": [("refund_payment", "amount_usd")],
    "data_breach": [("disable_account", ""), ("email_customer", "")],
    "safety_incident": [("email_customer", ""), ("escalate_ticket", "")],
    "sla_breach": [("call_vendor", "")],
}


def estimate_tokens(text: str) -> int:
    """Cheap, deterministic token estimate: ~4 chars per token. Used for the
    cost model — an approximation, documented as such."""
    return max(1, math.ceil(len(text) / 4))


def detect_injection(description: str) -> bool:
    return _INJECTION.search(description) is not None


def propose_next_steps(case: Intake, risk: Risk, citations: list[Citation],
                       injection_flagged: bool) -> list[str]:
    """The 'model proposes' step, stubbed deterministically: wording is
    assembled from templates, never from free generation. Deterministic code
    (classify, queueing) still decides everything that matters."""
    steps = []
    if citations:
        cited = ", ".join(f"{c.policy_id}/{c.section}" for c in citations[:2])
        steps.append(f"Apply policy guidance from {cited} before acting.")
    else:
        steps.append("No matching policy section found — escalate to a "
                     "human rather than improvising policy.")
    if risk == "high":
        steps.append("Page the on-call lead: high-risk exceptions need senior "
                     "review within the hour.")
    elif risk == "medium":
        steps.append("Prepare the customer-facing response and hold it for "
                     "approval — do not send it yet.")
    else:
        steps.append("Log the summary and close the loop with the customer "
                     "using the draft in the incident file.")
    if injection_flagged:
        steps.append("The report contains instruction-like text; treat it as "
                     "a quote only and route the case through normal approval.")
    return steps


class CopilotResult(BaseModel):
    case_id: str
    terminal: Terminal
    risk: str  # low | medium | high | unclassified
    rule_name: str = ""
    citations: list[Citation] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    injection_flagged: bool = False
    queued_ids: list[str] = Field(default_factory=list)
    artifact_path: str = ""
    token_usage: dict[str, int] = Field(default_factory=dict)
    reason: str = ""


def _usage(**stages: int) -> dict[str, int]:
    stages["total"] = sum(stages.values())
    return stages


def run_case(raw: dict, store: PolicyStore, queue: ApprovalQueue,
             out_dir: str) -> CopilotResult:
    """Run one exception through the pipeline. Never raises for bad input or
    a down store — those become needs_clarification / degraded."""
    intake_tokens = estimate_tokens(str(raw))

    # 1. intake
    try:
        case = parse_intake(raw)
    except ValidationError as e:
        questions = clarification_questions(e)
        result = CopilotResult(
            case_id=str(raw.get("id") or "unknown"),
            terminal="needs_clarification", risk="unclassified",
            reason="Intake was incomplete: " + " ".join(questions),
            token_usage=_usage(intake=intake_tokens))
        result.artifact_path = _write_artifact(
            result, raw, out_dir, next_steps=questions,
            description=str(raw.get("description") or "(none provided)"))
        return result

    # 2. retrieve (citations are verbatim quotes from the store)
    citations = retrieve(store, f"{case.type} {case.description}", limit=3)
    retrieve_tokens = estimate_tokens(case.description) + sum(
        estimate_tokens(c.quote) for c in citations)

    # 3. classify (deterministic rules)
    risk, rule_name = classify(case)
    classify_tokens = estimate_tokens("classify:" + case.type + case.description[:200])

    # 4. propose (model proposes wording; code decides what happens)
    injection_flagged = detect_injection(case.description)
    next_steps = propose_next_steps(case, risk, citations, injection_flagged)
    propose_tokens = estimate_tokens(" ".join(next_steps))

    # 5. route: medium/high risk or flagged injection -> human approval gate
    queued: list[dict[str, str]] = []
    queued_ids: list[str] = []
    if risk in ("medium", "high"):
        for action, money_key in _ACTION_PLANS.get(case.type, []):
            payload = _build_payload(action, case, money_key)
            entry = queue.queue(case.id, action, payload)
            queued.append({"id": entry.id, "action": action,
                           "case_id": case.id, "status": entry.status})
            queued_ids.append(entry.id)

    if queued_ids:
        terminal: Terminal = "queued_for_approval"
        reason = (f"{len(queued_ids)} action(s) proposed and queued for human "
                  f"approval; nothing was executed.")
    else:
        terminal = "resolved"
        reason = ("Understood and documented. No external or state-changing "
                  "action was needed.")

    draft_tokens = 0
    result = CopilotResult(
        case_id=case.id, terminal=terminal, risk=risk, rule_name=rule_name,
        citations=citations, next_steps=next_steps,
        injection_flagged=injection_flagged, queued_ids=queued_ids,
        reason=reason,
        token_usage=_usage(intake=intake_tokens, retrieve=retrieve_tokens,
                           classify=classify_tokens, propose=propose_tokens,
                           draft=draft_tokens))
    draft_tokens = estimate_tokens(_render_preview(result, case))
    result.token_usage["draft"] = draft_tokens
    result.token_usage["total"] = sum(v for k, v in result.token_usage.items()
                                      if k != "total")
    result.artifact_path = _write_artifact(
        result, raw, out_dir, next_steps=next_steps,
        description=case.description, queued_actions=queued)
    return result


def _build_payload(action: str, case: Intake, money_key: str) -> dict:
    if action == "refund_payment":
        return {"client_id": case.client_id,
                "amount_usd": case.amount_usd or 0.0,
                "reason": f"refund for exception {case.id}"}
    if action == "disable_account":
        return {"client_id": case.client_id,
                "reason": f"data breach containment for {case.id}"}
    if action == "email_customer":
        return {"to": f"{case.client_id}@example.com",
                "subject": f"Update on your case {case.id}",
                "body": "We are reviewing your exception and will update you shortly."}
    if action == "escalate_ticket":
        return {"case_id": case.id, "level": "senior",
                "note": "safety incident requires senior review"}
    if action == "call_vendor":
        return {"vendor": "primary vendor",
                "message": f"SLA breach on {case.id}: request remediation plan"}
    raise ValueError(f"no payload builder for action '{action}'")


def _render_preview(result: CopilotResult, case: Intake) -> str:
    # Rendered once to measure draft cost; the real write happens below.
    return artifacts.render_incident_markdown(
        case_id=case.id, case_type=case.type, client_id=case.client_id,
        description=case.description, risk=result.risk,
        rule_name=result.rule_name, citations=result.citations,
        next_steps=result.next_steps, queued_actions=[],
        injection_flagged=result.injection_flagged,
        terminal=result.terminal, reason=result.reason)


def _write_artifact(result: CopilotResult, raw: dict, out_dir: str,
                    next_steps: list[str], description: str,
                    queued_actions: list[dict[str, str]] | None = None) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"incident-{result.case_id}.md")
    md = artifacts.render_incident_markdown(
        case_id=result.case_id,
        case_type=str(raw.get("type") or "unknown"),
        client_id=str(raw.get("client_id") or "unknown"),
        description=description,
        risk=result.risk, rule_name=result.rule_name,
        citations=result.citations, next_steps=next_steps,
        queued_actions=queued_actions or [],
        injection_flagged=result.injection_flagged,
        terminal=result.terminal, reason=result.reason)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path


def run(raw: dict, policy_path: str, queue_path: str, out_dir: str,
        force_outage: bool = False) -> CopilotResult:
    """Top-level entry: loads the policy store, degrading gracefully if it
    is down, then runs the pipeline."""
    try:
        store = PolicyStore.load(policy_path, force_down=force_outage)
    except PolicyStoreError as e:
        os.makedirs(out_dir, exist_ok=True)
        result = CopilotResult(
            case_id=str(raw.get("id") or "unknown"),
            terminal="degraded", risk="unclassified",
            reason=f"Policy store unavailable — {e}. No classification or "
                   f"retrieval was attempted; no action was taken.",
            token_usage=_usage(intake=estimate_tokens(str(raw))))
        result.artifact_path = _write_artifact(
            result, raw, out_dir,
            next_steps=["Restore the policy store, then re-run this case.",
                        "Do not improvise policy from memory."],
            description=str(raw.get("description") or "(none provided)"))
        return result
    queue = ApprovalQueue(queue_path)
    return run_case(raw, store, queue, out_dir)

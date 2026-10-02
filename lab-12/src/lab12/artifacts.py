"""Incident artifact: the markdown summary a human (or the client) reads.

The artifact quotes the reporter's description verbatim under "Reporter's
exact words". If the description contains instruction-like text, that text
appears ONLY here, labeled as a quote — the pipeline never acts on it.
"""
from __future__ import annotations

from .policies import Citation
from .risk import RISK_RULES


def render_incident_markdown(
    *,
    case_id: str,
    case_type: str,
    client_id: str,
    description: str,
    risk: str,
    rule_name: str,
    citations: list[Citation],
    next_steps: list[str],
    queued_actions: list[dict[str, str]],
    injection_flagged: bool,
    terminal: str,
    reason: str,
) -> str:
    rule = RISK_RULES.get(rule_name, {})
    lines = [
        f"# Incident summary — {case_id}",
        "",
        f"- **Client:** {client_id}",
        f"- **Type:** {case_type}",
        f"- **Risk:** {risk} (rule: `{rule_name}` — "
        f"{rule.get('rule', 'n/a')})",
        f"- **Terminal state:** {terminal}",
        f"- **Outcome:** {reason}",
        "",
        "## Reporter's exact words",
        "",
        "> " + description.replace("\n", "\n> "),
        "",
    ]
    if injection_flagged:
        lines += [
            "_Note: the quoted text above contains instruction-like language. "
            "It is treated as data and quoted here for transparency; the "
            "copilot followed none of it._",
            "",
        ]
    lines += ["## Policy references", ""]
    if citations:
        for c in citations:
            lines += [
                f"- **{c.policy_id}** / {c.section}",
                f"  > {c.quote}",
                "",
            ]
    else:
        lines += ["_No policy section matched this exception._", ""]
    lines += ["## Proposed next steps", ""]
    for i, step in enumerate(next_steps, 1):
        lines.append(f"{i}. {step}")
    lines.append("")
    lines += ["## Approval queue", ""]
    if queued_actions:
        lines.append("The following actions were proposed but **NOT executed**. "
                     "A human must approve each one:")
        lines.append("")
        for q in queued_actions:
            lines.append(f"- `{q['id']}` {q['action']} for case {q['case_id']} "
                         f"(status: {q['status']})")
        lines.append("")
    else:
        lines.append("_No external or state-changing actions were proposed._")
        lines.append("")
    return "\n".join(lines)

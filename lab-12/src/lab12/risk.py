"""Deterministic risk classification.

The rules live in RISK_RULES as data — documented, ordered, and testable.
Evaluation order is part of the contract: HIGH rules are checked before
MEDIUM before LOW, so a data breach with a large dollar amount is HIGH, not
MEDIUM. The model proposes wording; these rules decide the risk.
"""
from __future__ import annotations

import re
from typing import Literal

from .intake import Intake

Risk = Literal["low", "medium", "high"]

AMOUNT_THRESHOLD_USD = 5_000.0

# Every rule: a name, what it checks, and why it exists. classify() walks
# this dict in insertion order and returns the first match.
RISK_RULES: dict[str, dict[str, str]] = {
    "high_type": {
        "rule": "type in {data_breach, safety_incident} -> high",
        "condition": "intake.type is 'data_breach' or 'safety_incident'",
        "rationale": "Exposure of customer data or physical-safety events "
                     "always need senior review and a paper trail.",
    },
    "high_keywords": {
        "rule": "description matches PII-exposure, fraud, or injury keywords -> high",
        "condition": "description contains any of: ssn, social security, "
                     "credit card, password leak, exposed records, fraud, "
                     "scam, injured, injury, hospital",
        "rationale": "These words signal harm to people or regulated data "
                     "even when the reporter picked a mild exception type.",
    },
    "medium_type": {
        "rule": "type in {sla_breach, billing_dispute} -> medium",
        "condition": "intake.type is 'sla_breach' or 'billing_dispute'",
        "rationale": "Contract and money disputes need a human decision "
                     "before any customer-facing action.",
    },
    "medium_amount": {
        "rule": "amount_usd > 5000 -> medium",
        "condition": f"intake.amount_usd is set and exceeds ${AMOUNT_THRESHOLD_USD:,.0f}",
        "rationale": "Above the threshold, money movement needs sign-off "
                     "regardless of the exception type.",
    },
    "low_default": {
        "rule": "otherwise -> low",
        "condition": "no rule above matched",
        "rationale": "Routine operational noise can be summarized and filed "
                     "without waking anyone up.",
    },
}

_HIGH_KEYWORDS = re.compile(
    r"ssn|social security|credit card|password leak|exposed records|"
    r"\bfraud\b|\bscam\b|injur(?:ed|y|ies)|hospital",
    re.IGNORECASE,
)

_HIGH_TYPES = {"data_breach", "safety_incident"}
_MEDIUM_TYPES = {"sla_breach", "billing_dispute"}


def classify(case: Intake) -> tuple[Risk, str]:
    """Return (risk, rule_name). First match in RISK_RULES order wins."""
    if case.type in _HIGH_TYPES:
        return "high", "high_type"
    if _HIGH_KEYWORDS.search(case.description):
        return "high", "high_keywords"
    if case.type in _MEDIUM_TYPES:
        return "medium", "medium_type"
    if case.amount_usd is not None and case.amount_usd > AMOUNT_THRESHOLD_USD:
        return "medium", "medium_amount"
    return "low", "low_default"

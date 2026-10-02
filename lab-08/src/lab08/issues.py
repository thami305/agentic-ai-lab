"""The deterministic issue catalog for the seeded proposal.

Each entry is a real issue planted in data/proposal.txt: the claim a
reviewer would make, its severity, the passage that proves it, and the
verbatim quote that must appear in the finding's evidence. Quotes are
single-spaced to match proposal.py's whitespace normalization.

Domains: "pricing" issues live in Pricing passages, "terms" issues in
Terms / Delivery-SLA passages — the split the manager pattern routes on.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    id: str
    domain: str  # "pricing" | "terms"
    severity: str  # "high" | "medium" | "low"
    passage_id: str
    claim: str
    quote: str
    risk: str


ISSUES: list[Issue] = [
    Issue(
        id="F-ESC-1", domain="pricing", severity="high", passage_id="PROP-P1",
        claim=("Price escalation is uncapped: the vendor may raise the annual "
               "fee at each renewal anniversary at its sole discretion, with "
               "no cap, index, or notice-period limitation."),
        quote=("The vendor may increase the annual fee at each renewal "
               "anniversary at its sole discretion, with no cap, index, or "
               "notice-period limitation."),
        risk=("Uncapped escalation lets the vendor raise fees by any amount "
              "each year, making multi-year budgeting impossible.")),
    Issue(
        id="F-SLA-1", domain="terms", severity="high", passage_id="PROP-P7",
        claim=('The uptime commitment is a vague "best efforts" promise '
               "rather than a measurable guarantee."),
        quote=("The vendor will use its commercially reasonable best efforts "
               "to maintain 99.5% monthly platform uptime"),
        risk=("A best-efforts SLA gives the customer no enforceable uptime "
              "standard and weakens any claim for outages.")),
    Issue(
        id="F-LIAB-1", domain="terms", severity="high", passage_id="PROP-P5",
        claim=("Neither party's total aggregate liability is capped, leaving "
               "the customer with uncapped exposure."),
        quote=("neither party's total aggregate liability under this "
               "agreement is capped"),
        risk=("Uncapped mutual liability exposes the customer to unlimited "
              "damages claims from the vendor.")),
    Issue(
        id="F-REN-1", domain="terms", severity="medium", passage_id="PROP-P4",
        claim=("The agreement auto-renews for successive twelve-month terms; "
               "stopping renewal requires written notice at least ninety "
               "days before term end."),
        quote=("This agreement will automatically renew for successive "
               "twelve-month terms unless either party provides written "
               "notice of non-renewal at least ninety days before the end "
               "of the then-current term."),
        risk=("Missing the 90-day notice window locks the customer into "
              "another full year at whatever fees are then in effect.")),
    Issue(
        id="F-ETF-1", domain="pricing", severity="medium", passage_id="PROP-P3",
        claim=("Terminating for convenience triggers an early termination fee "
               "of fifty percent of the remaining term's fees, due within "
               "thirty days."),
        quote=("an early termination fee equal to fifty percent of the fees "
               "remaining under the then-current term is due within thirty "
               "days of the termination notice"),
        risk=("The termination fee makes an early exit expensive even if the "
              "service underperforms.")),
    Issue(
        id="F-SLA-2", domain="terms", severity="medium", passage_id="PROP-P7",
        claim=("Service credits for missed uptime are entirely at the "
               "vendor's sole discretion."),
        quote="Service credits, if any, are at the vendor's sole discretion",
        risk=("Discretionary credits mean the customer has no guaranteed "
              "remedy for SLA failures.")),
    Issue(
        id="F-SUP-1", domain="terms", severity="medium", passage_id="PROP-P8",
        claim=("Priority-one support targets a four-hour response, but no "
               "remedy is stated if the target is missed."),
        quote=("The proposal states no service credit or other remedy if "
               "these response targets are missed."),
        risk=("Without a remedy, missed support response targets carry no "
              "consequence for the vendor.")),
    Issue(
        id="F-PAY-1", domain="pricing", severity="low", passage_id="PROP-P2",
        claim=("Payment terms are net forty-five days, with late payments "
               "accruing interest at one and one half percent per month."),
        quote="Payment terms are net forty-five days from invoice date.",
        risk=("The 1.5% monthly late fee is steep if an invoice is ever "
              "disputed or delayed.")),
]


def issues_for(domain: str | None = None) -> list[Issue]:
    return [i for i in ISSUES if domain is None or i.domain == domain]

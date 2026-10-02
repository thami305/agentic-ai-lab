"""Budgets, timeouts, and the pipeline's failure vocabulary.

Two money guards:

- **Per-request token budget**: before a job is accepted, its estimated cost
  is checked against ``per_request_token_limit``. Over it -> 429.
- **Global spend counter**: persisted in the state file. A request whose
  estimate would push spend over ``global_token_budget`` is refused with 429.
  Actual tokens are added when a run finishes.

The estimate is fixed and deterministic (the oracle backend's usage is known
up front), so budget tests never flake.
"""
from __future__ import annotations


class JobTimeout(Exception):
    """The run exceeded the request timeout."""


class JobKilled(Exception):
    """The kill switch was engaged mid-run."""


class JobAborted(Exception):
    """The server is stopping; abandon the run without persisting."""


ESTIMATED_TOKENS_PER_REQUEST = 1500


def estimate_request_tokens(question: str) -> int:
    """Deterministic pre-run cost estimate for one brief request."""
    return ESTIMATED_TOKENS_PER_REQUEST


def check_budgets(question: str, per_request_limit: int,
                  spend_tokens: int, global_budget: int) -> str | None:
    """Return an error string if the request must be refused, else None."""
    estimate = estimate_request_tokens(question)
    if estimate > per_request_limit:
        return (f"per-request token budget exceeded: estimated {estimate} tokens "
                f"> limit {per_request_limit}")
    if spend_tokens + estimate > global_budget:
        return (f"global token budget exceeded: spend {spend_tokens} + estimated "
                f"{estimate} > budget {global_budget}")
    return None

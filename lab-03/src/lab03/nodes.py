"""Lab 3 nodes: the Lab 2 pipeline as named graph nodes.

Deterministic nodes (pure code): validate_input, assess, validate.
Model-driven nodes (policy-backed): retrieve, synthesize.
Terminal nodes: clarify, review, publish, stop.

Routers are pure functions of state, unit-tested directly.
"""
from __future__ import annotations

from lab02.tools import keywords
from lab02.validate import validate_brief

from .graph import Graph, Node
from .policies import OraclePolicy, Policy
from .state import BriefState

MAX_RETRIEVAL_RETRIES = 2

# A passage counts as a revision marker if it carries one of these tokens:
# two such passages on the same question = conflicting evidence.
REVISION_MARKERS = frozenset(
    "revised revision correction updated update superseding".split())


# ------------------------------------------------------------- nodes ---

def validate_input(state: BriefState) -> None:
    if not state.question.strip():
        state.terminal_reason = (
            "clarification: the question is empty — ask what to research.")


def retrieve(state: BriefState, policy: Policy) -> None:
    attempts = 0
    while True:
        attempts += 1
        try:
            state.passages = policy.retrieve(state)
            return
        except Exception as e:
            state.retrieval_retries += 1
            last_error = e
            if attempts > MAX_RETRIEVAL_RETRIES:
                state.terminal_reason = (
                    f"graceful stop: retrieval failed {attempts} times "
                    f"({type(last_error).__name__}); aborting instead of "
                    f"answering without evidence.")
                return


def assess(state: BriefState) -> None:
    pass  # routing only; see route_after_assess


def synthesize(state: BriefState, policy: Policy) -> None:
    state.brief = policy.synthesize(state)


def validate(state: BriefState) -> None:
    assert state.brief is not None
    report = validate_brief(state.brief, state.packet)
    state.validation_violations = report.violations
    if not report.ok:
        state.terminal_reason = (
            "human review: the brief failed post-validation — "
            + "; ".join(report.violations))


def clarify(state: BriefState) -> None:
    if state.terminal_reason is None:
        state.terminal_reason = (
            "clarification: the packet has no documents addressing this "
            "question — ask the user to narrow or rephrase it.")


def review(state: BriefState) -> None:
    if state.terminal_reason is None:
        state.terminal_reason = (
            "human review: " + (state.conflict_detail or "unspecified"))


def publish(state: BriefState) -> None:
    state.terminal_reason = (
        f"published: brief with {len(state.brief.claims)} grounded claims.")


def stop(state: BriefState) -> None:
    pass  # reason set by retrieve on the graceful-stop branch


# ----------------------------------------------------------- routers ---

def route_after_input(state: BriefState) -> str:
    return "clarify" if not state.question.strip() else "retrieve"


def detect_conflict(state: BriefState) -> str | None:
    """Two retrieved passages conflict when they share ≥2 keywords and one
    carries a revision marker (e.g. the revised break-even note vs the
    original finance summary)."""
    texts = [p["text"] for p in state.passages]
    keyed = [set(keywords(t)) for t in texts]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if len(keyed[i] & keyed[j]) >= 2:
                for k, t in ((i, texts[i]), (j, texts[j])):
                    low = t.lower()
                    if any(m in low for m in REVISION_MARKERS):
                        other = texts[j] if k == i else texts[i]
                        return (f"conflicting evidence: '{t[:80]}...' vs "
                                f"'{other[:80]}...'")
    return None


def route_after_assess(state: BriefState) -> str:
    if not state.passages:
        return "clarify"
    conflict = detect_conflict(state)
    if conflict:
        state.conflict_detail = conflict
        return "review"
    return "synthesize"


def route_after_retrieve(state: BriefState) -> str:
    # retrieve records every failed attempt; exhausting the budget routes to
    # the graceful-stop branch instead of answering without evidence.
    if state.retrieval_retries > MAX_RETRIEVAL_RETRIES:
        return "stop"
    return "assess"


def route_after_validate(state: BriefState) -> str:
    return "review" if state.validation_violations else "publish"


# ------------------------------------------------------------ graph ---

def build_graph(policy: Policy | None = None) -> Graph:
    policy = policy or OraclePolicy()
    g = Graph(entry="validate_input")
    g.add(Node("validate_input", "deterministic", validate_input,
               router=route_after_input))
    g.add(Node("retrieve", "model", lambda s: retrieve(s, policy),
               router=route_after_retrieve))
    g.add(Node("assess", "deterministic", assess, router=route_after_assess))
    g.add(Node("synthesize", "model", lambda s: synthesize(s, policy),
               router=lambda s: "validate"))
    g.add(Node("validate", "deterministic", validate,
               router=route_after_validate))
    g.add(Node("clarify", "deterministic", clarify, terminal="clarify"))
    g.add(Node("review", "deterministic", review, terminal="review"))
    g.add(Node("publish", "deterministic", publish, terminal="publish"))
    g.add(Node("stop", "deterministic", stop, terminal="stop"))
    return g

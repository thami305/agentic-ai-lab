"""Seeded stochastic model backends for Lab 8.

- OracleStub: deterministic tool-using policy. Searches, fetches, and builds
  a finding for EVERY issue in the catalog whose passage was fetched. No
  randomness — used by the correctness tests.
- SeededStub(seed): stochastic policy. A random.Random(seed) stream varies
  (a) how many passages get fetched, (b) which findings get included or
  dropped, (c) verdict jitter inside the sane set, and (d) token counts.
  Deterministic per seed: the same seed always produces the same run, so the
  measurement harness's variance is honest and reproducible. No unseeded
  randomness anywhere.
- DomainSeededStub(domain, seed): the same policy restricted to one domain's
  issues and one domain's tool names — the pattern-B specialists' "model".

All three only ever cite passages they fetched, with verbatim quotes from
the issue catalog, so every produced review passes post-validation; the
variance they inject is in *coverage*, not in citation honesty.
"""
from __future__ import annotations

import random

from lab02.models import ModelBackend, ModelResponse, ToolCallItem

from .issues import ISSUES, Issue, issues_for
from .schemas import Evidence, Finding, Review
from .validate import verdict_for

_BROAD_QUERY = ("pricing fees escalation renewal termination liability SLA "
                "uptime support payment")
_PRICING_QUERY = "pricing fees escalation termination payment overage"
_TERMS_QUERY = ("renewal termination liability SLA uptime support credits "
                "remedy")


def _usage(rng: random.Random) -> dict[str, int]:
    return {"prompt_tokens": rng.randint(700, 1300),
            "completion_tokens": rng.randint(120, 320)}


def _review_payload(issues: list[Issue], verdict: str) -> dict:
    return {
        "verdict": verdict,
        "findings": [{"claim": i.claim, "severity": i.severity,
                      "evidence": {"passage_id": i.passage_id,
                                   "quote": i.quote}}
                     for i in issues],
        "risks": [i.risk for i in issues],
    }


def _to_findings(issues: list[Issue]) -> list[Finding]:
    return [Finding(claim=i.claim, severity=i.severity,  # type: ignore[arg-type]
                    evidence=Evidence(passage_id=i.passage_id, quote=i.quote))
            for i in issues]


def _jitter_verdict(base: str, issues: list[Finding | Issue],
                    rng: random.Random) -> str:
    # Jitter stays inside the sane set: never "accept" while a high finding
    # is present; otherwise follow the deterministic rule.
    if any(i.severity == "high" for i in issues) and rng.random() < 0.35:
        return "revise" if base == "reject" else "reject"
    return base


class _BaseStub(ModelBackend):
    def __init__(self) -> None:
        self._stage = 0
        self._hits: list[dict] = []
        self._fetched: list[dict] = []

    def start_run(self, system: str, user_request: str,
                  tools: list[dict]) -> None:
        self._stage = 0
        self._hits = []
        self._fetched = []
        self._question = user_request

    def _search_name(self) -> str:
        raise NotImplementedError

    def _get_name(self) -> str:
        raise NotImplementedError

    def _query(self) -> str:
        raise NotImplementedError

    def _issues(self) -> list[Issue]:
        raise NotImplementedError

    def _usage(self) -> dict[str, int]:
        raise NotImplementedError

    def _n_fetch(self) -> int:
        raise NotImplementedError

    def _include(self, issue: Issue) -> bool:
        raise NotImplementedError

    def _verdict(self, issues: list[Issue]) -> str:
        raise NotImplementedError

    # ------------------------------------------------------------ flow ---

    def next(self) -> ModelResponse:
        usage = self._usage()
        if self._stage == 0:
            self._stage = 1
            return ModelResponse(
                kind="tool_calls", usage=usage,
                tool_calls=[ToolCallItem(name=self._search_name(),
                                         arguments={"query": self._query(),
                                                    "limit": 8})])
        if self._stage == 1:
            self._stage = 2
            targets = self._hits[:self._n_fetch()]
            return ModelResponse(
                kind="tool_calls", usage=usage,
                tool_calls=[ToolCallItem(name=self._get_name(),
                                         arguments={"passage_id": h["passage_id"]})
                            for h in targets])
        fetched_ids = {p["passage_id"] for p in self._fetched}
        issues = [i for i in self._issues()
                  if i.passage_id in fetched_ids and self._include(i)]
        if not issues:
            # Never ship an empty review: fall back to the first fetched issue.
            for i in self._issues():
                if i.passage_id in fetched_ids:
                    issues = [i]
                    break
        verdict = self._verdict(issues)
        return ModelResponse(kind="final", usage=usage,
                             final=_review_payload(issues, verdict))

    def observe_tool_results(self, results: list) -> None:
        if self._stage == 1:
            for r in results:
                if r.ok and isinstance(r.data, list):
                    self._hits = r.data
        elif self._stage == 2:
            for r in results:
                if r.ok and isinstance(r.data, dict) and "text" in r.data:
                    self._fetched.append(r.data)


class OracleStub(_BaseStub):
    """Fully deterministic: fetches everything, includes every issue."""

    def _search_name(self) -> str: return "search_proposal"
    def _get_name(self) -> str: return "get_passage"
    def _query(self) -> str: return _BROAD_QUERY
    def _issues(self) -> list[Issue]: return ISSUES
    def _usage(self) -> dict[str, int]:
        return {"prompt_tokens": 900, "completion_tokens": 220}
    def _n_fetch(self) -> int: return 8
    def _include(self, issue: Issue) -> bool: return True
    def _verdict(self, issues: list[Issue]) -> str:
        return verdict_for(_to_findings(issues))


class SeededStub(_BaseStub):
    """Seeded stochastic policy for the measurement harness."""

    INCLUDE_P = 0.75

    def __init__(self, seed: int):
        super().__init__()
        self._seed = seed

    def start_run(self, system: str, user_request: str,
                  tools: list[dict]) -> None:
        super().start_run(system, user_request, tools)
        rng = random.Random(self._seed)
        # Fixed draw order: identical for every run with this seed.
        self._rng = rng
        self._include_flags = {i.id: rng.random() < self.INCLUDE_P
                               for i in ISSUES}
        self._n = rng.randint(5, 8)
        self._jitter_draw = rng.random()

    def _search_name(self) -> str: return "search_proposal"
    def _get_name(self) -> str: return "get_passage"
    def _query(self) -> str: return _BROAD_QUERY
    def _issues(self) -> list[Issue]: return ISSUES
    def _usage(self) -> dict[str, int]: return _usage(self._rng)
    def _n_fetch(self) -> int: return self._n
    def _include(self, issue: Issue) -> bool:
        return self._include_flags[issue.id]
    def _verdict(self, issues: list[Issue]) -> str:
        base = verdict_for(_to_findings(issues))
        findings = _to_findings(issues)
        if any(f.severity == "high" for f in findings) \
                and self._jitter_draw < 0.35:
            return "revise" if base == "reject" else "reject"
        return base


class DomainSeededStub(_BaseStub):
    """Seeded policy for one specialist domain ("pricing" | "terms")."""

    INCLUDE_P = 0.8

    def __init__(self, domain: str, seed: int):
        super().__init__()
        if domain not in ("pricing", "terms"):
            raise ValueError(f"unknown domain '{domain}'")
        self._domain = domain
        self._seed = seed

    def start_run(self, system: str, user_request: str,
                  tools: list[dict]) -> None:
        super().start_run(system, user_request, tools)
        rng = random.Random(self._seed)
        self._rng = rng
        domain_issues = issues_for(self._domain)
        self._include_flags = {i.id: rng.random() < self.INCLUDE_P
                               for i in domain_issues}
        # Enough fetches to cover the domain's passages, with jitter.
        self._n = rng.randint(3, 5)
        self._jitter_draw = rng.random()

    def _search_name(self) -> str:
        return {"pricing": "search_pricing",
                "terms": "search_terms"}[self._domain]
    def _get_name(self) -> str:
        return {"pricing": "get_pricing_passage",
                "terms": "get_terms_passage"}[self._domain]
    def _query(self) -> str:
        return _PRICING_QUERY if self._domain == "pricing" else _TERMS_QUERY
    def _issues(self) -> list[Issue]: return issues_for(self._domain)
    def _usage(self) -> dict[str, int]: return _usage(self._rng)
    def _n_fetch(self) -> int: return self._n
    def _include(self, issue: Issue) -> bool:
        return self._include_flags[issue.id]
    def _verdict(self, issues: list[Issue]) -> str:
        # Specialists report findings only; the manager owns the verdict.
        # Keep the payload schema-valid anyway.
        base = verdict_for(_to_findings(issues))
        findings = _to_findings(issues)
        if any(f.severity == "high" for f in findings) \
                and self._jitter_draw < 0.35:
            return "revise" if base == "reject" else "reject"
        return base

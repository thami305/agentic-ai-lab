"""Prompt-only vs tool-using evaluation for Lab 2.

Runs the same questions through both modes and scores each run on five
dimensions from the plan:

- completeness: fraction of the question's key points covered by the brief
- groundedness: fraction of claims whose citations pass deterministic validation
- format_valid: 1.0 if the run produced a schema-valid, post-validation-clean
  brief (or a proper decline for unanswerable questions), else 0.0
- cost: total tokens consumed
- latency: wall-clock seconds for the run

Deterministic: both modes use stub backends, so the same eval always prints
the same table.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .agent import Agent, PROMPT_ONLY_SYSTEM, RunResult
from .models import OracleStub, PromptOnlyStub
from .packet import Packet, load_packet
from .tools import STOPWORDS, ToolRegistry, build_registry
from .validate import validate_brief

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass
class EvalQuestion:
    id: str
    question: str
    expect: str  # "answer" | "partial" | "decline"
    key_points: list[str]


@dataclass
class ScoredRun:
    question_id: str
    mode: str  # "prompt" | "tool"
    expect: str
    status: str
    completeness: float
    groundedness: float
    format_valid: float
    tokens: int
    latency_s: float


def load_questions(path: str | Path | None = None) -> list[EvalQuestion]:
    raw = json.loads(Path(path or DATA_DIR / "eval_questions.json").read_text())
    return [EvalQuestion(**q) for q in raw]


def _significant_words(text: str) -> set[str]:
    toks = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in toks if len(t) > 2 and t not in STOPWORDS}


def brief_text(result: RunResult) -> str:
    if result.brief is None:
        return ""
    parts = [c.text for c in result.brief.claims]
    parts += result.brief.assumptions + result.brief.open_questions
    return "\n".join(parts).lower()


def completeness(result: RunResult, question: EvalQuestion) -> float:
    """Fraction of key points covered. A key point counts as covered when all
    its significant words appear in the brief. Partial/decline questions with
    no key points score on whether the gap was flagged instead."""
    if result.brief is None:
        return 0.0
    if not question.key_points:
        flagged = bool(result.brief.open_questions)
        return 1.0 if flagged else 0.0
    text_words = _significant_words(brief_text(result))
    covered = sum(1 for kp in question.key_points
                  if _significant_words(kp) <= text_words)
    return covered / len(question.key_points)


def groundedness(result: RunResult, packet: Packet) -> float:
    """Fraction of claims whose citations pass deterministic validation.
    A proper decline makes no claims, so it is vacuously fully grounded."""
    if result.status == "declined":
        return 1.0
    if result.brief is None or not result.brief.claims:
        return 0.0
    good = 0
    for claim in result.brief.claims:
        report = validate_brief(
            result.brief.model_copy(update={"claims": [claim]}), packet)
        good += 1 if report.ok else 0
    return good / len(result.brief.claims)


def format_valid(result: RunResult, question: EvalQuestion) -> float:
    if question.expect == "decline":
        return 1.0 if result.status == "declined" else 0.0
    return 1.0 if result.status == "completed" else 0.0


def score_run(question: EvalQuestion, mode: str, result: RunResult,
              packet: Packet) -> ScoredRun:
    return ScoredRun(
        question_id=question.id, mode=mode, expect=question.expect,
        status=result.status,
        completeness=completeness(result, question),
        groundedness=groundedness(result, packet),
        format_valid=format_valid(result, question),
        tokens=result.total_tokens, latency_s=round(result.latency_s, 3))


def run_eval(packet: Packet | None = None,
             questions: list[EvalQuestion] | None = None) -> list[ScoredRun]:
    packet = packet or load_packet()
    questions = questions or load_questions()
    scored: list[ScoredRun] = []
    for q in questions:
        # tool-using mode: oracle policy + full tool registry
        tool_agent = Agent(OracleStub(), build_registry(packet), packet)
        scored.append(score_run(q, "tool", tool_agent.run(q.question), packet))
        # prompt-only mode: no tools at all
        prompt_agent = Agent(PromptOnlyStub(), ToolRegistry(), packet,
                             system_prompt=PROMPT_ONLY_SYSTEM)
        scored.append(score_run(q, "prompt", prompt_agent.run(q.question), packet))
    return scored


@dataclass
class ModeAggregate:
    mode: str
    n: int
    completeness: float
    groundedness: float
    format_valid: float
    total_tokens: int
    total_latency_s: float
    declines: int


def aggregate(scored: list[ScoredRun]) -> list[ModeAggregate]:
    out: list[ModeAggregate] = []
    for mode in ("prompt", "tool"):
        rows = [s for s in scored if s.mode == mode]
        n = len(rows) or 1
        out.append(ModeAggregate(
            mode=mode, n=len(rows),
            completeness=round(sum(s.completeness for s in rows) / n, 3),
            groundedness=round(sum(s.groundedness for s in rows) / n, 3),
            format_valid=round(sum(s.format_valid for s in rows) / n, 3),
            total_tokens=sum(s.tokens for s in rows),
            total_latency_s=round(sum(s.latency_s for s in rows), 3),
            declines=sum(1 for s in scored
                         if s.mode == mode and s.status == "declined")))
    return out


def comparison_table(agg: list[ModeAggregate]) -> str:
    header = (f"{'mode':<8}{'complete':>10}{'grounded':>10}{'format':>8}"
              f"{'tokens':>8}{'latency_s':>11}{'declines':>10}")
    lines = [header]
    for a in agg:
        lines.append(
            f"{a.mode:<8}{a.completeness:>10.3f}{a.groundedness:>10.3f}"
            f"{a.format_valid:>8.3f}{a.total_tokens:>8}"
            f"{a.total_latency_s:>11.3f}{a.declines:>10}")
    return "\n".join(lines)

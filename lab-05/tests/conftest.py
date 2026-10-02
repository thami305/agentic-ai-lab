"""Lab 5 test fixtures: sys.path wiring + shared corpus/chunks/adviser."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LAB05 = Path(__file__).resolve().parent.parent
for p in (str(LAB05 / "src"), str(LAB05.parent / "lab-02" / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from lab05 import generate  # noqa: E402
from lab05.agent import Adviser  # noqa: E402
from lab05.chunk import chunk_paragraphs  # noqa: E402
from lab05.retrieve import Chunk  # noqa: E402

DATA = LAB05 / "data"


def _ensure_data() -> None:
    if not (DATA / "corpus.json").exists() or not (
            DATA / "eval_questions.json").exists():
        generate.main()


_ensure_data()


@pytest.fixture(scope="session")
def corpus() -> list[dict]:
    return json.loads((DATA / "corpus.json").read_text())


@pytest.fixture(scope="session")
def questions() -> list[dict]:
    return json.loads((DATA / "eval_questions.json").read_text())


@pytest.fixture(scope="session")
def chunks(corpus) -> list[Chunk]:
    return [Chunk.from_dict(d) for d in chunk_paragraphs(corpus)]


@pytest.fixture(scope="session")
def adviser(corpus, chunks) -> Adviser:
    return Adviser(corpus, chunks)


@pytest.fixture(scope="session")
def eval_results(corpus, questions) -> dict:
    from lab05.evaluate import run_eval
    return run_eval(corpus, questions)

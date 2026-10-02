"""eval/gate.py — thin wrapper: the gate lives in src/lab09/gate.py.

Thresholds live in eval/thresholds.json and are loaded at runtime, never
hardcoded. Run from the lab-09 directory:

    PYTHONPATH=src:../lab-02/src:../lab-03/src .venv/bin/python eval/gate.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lab09.gate import main

if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic replay of the RV-3 live Autonomous Human Gate E2E run (C-02, NVIDIA NIM nemotron-3-super).

Record/replay (reliability validation §13): the live transcript is replayed strictly (same skill, ordinal and
input digest) through the unchanged runner and the frozen H1-H10 evaluator — no provider, no network.

RV-4 added the Premise Check skill (IDR-RV4-01). With it switched off the RV-3 path replays byte-for-byte
(zero misses). With it on, the only differences allowed are the new skill itself (absent from an RV-3
transcript → deterministic fallback, no challenge) and digest changes of later calls whose state view now
carries the premise-check record; the Human Gate outcome must be unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mocks" / "reliability" / "human_gate"))
sys.path.insert(0, str(ROOT / "mocks" / "reliability"))

import evaluate_human_gate  # noqa: E402
import run_human_gate  # noqa: E402

from aitop_harness.reasoning.providers.replay import ReplayProvider  # noqa: E402

TRANSCRIPT = ROOT / "tests" / "data" / "human_gate_rv3_c02_transcript.jsonl"


def test_live_human_gate_run_replays_to_h1_h10_pass(tmp_path: Path) -> None:
    provider = ReplayProvider.from_file(TRANSCRIPT, strict=True)
    obs = run_human_gate.run(provider, tmp_path, config_overrides={"premise_check": False})
    assert not provider.misses
    result = evaluate_human_gate.evaluate(tmp_path)
    assert result["verdict"] == "PASS", [k for k, v in result["checks"].items() if not v]
    assert result["reachability"] == "REACHED" and result["mechanics"] == "PASS"  # evaluator v2 (IDR-RV4-06)
    assert obs["executed_calls_final"] == 1 and obs["result"]["operator_reasoner_calls"] == 0


def test_rv3_transcript_under_premise_check_keeps_the_gate_outcome(tmp_path: Path) -> None:
    provider = ReplayProvider.from_file(TRANSCRIPT, strict=True)
    obs = run_human_gate.run(provider, tmp_path)
    first = next(i for i, m in enumerate(provider.misses) if m.startswith("premise_check"))
    assert all(m.startswith("premise_check") for m in provider.misses[first:] if "not in transcript" in m)
    assert all("digest mismatch" in m or m.startswith("premise_check") for m in provider.misses[first:])
    assert not provider.misses[:first]  # nothing before the first premise check diverges
    result = evaluate_human_gate.evaluate(tmp_path)
    assert result["checks"]["H8 APPROVE → exactly-once execution"]
    assert result["gate"] and obs["executed_calls_final"] == 1
    assert obs["result"]["operator_reasoner_calls"] == 0

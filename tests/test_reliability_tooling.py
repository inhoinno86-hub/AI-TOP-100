"""Smoke regression for the reliability-validation tooling (RV-1 was invalidated by an import-order defect in
``run_general.py``: every Batch B run died at import). Each runner must start in a clean interpreter."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    "mocks/reliability/run_general.py",
    "mocks/reliability/human_gate/run_human_gate.py",
    "mocks/reliability/run_batch.py",
    "mocks/mock6/autonomous/run_mock6_autonomous.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_runner_starts_in_a_clean_interpreter(script: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-I", str(ROOT / script), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-800:]


def test_mechanism_classifier_rule() -> None:
    sys.path.insert(0, str(ROOT / "mocks" / "reliability"))
    import classify

    assert classify.names_mechanism("BV-17 rejects firmware v4.2 reads (unit-scale mismatch)")
    assert classify.names_mechanism("valid AMI reads are rejected at billing import")
    assert not classify.names_mechanism("field read-route backlog causes estimated bills")


# --------------------------------------------------------------------------- evaluator v2 (RV-4, IDR-RV4-07)


def _ev() -> object:
    sys.path.insert(0, str(ROOT / "mocks" / "mock6" / "autonomous"))
    import evaluate_mock6_autonomous as ev

    return ev


def _obs(halt: str | None, *, release: dict | None = None, failed: bool = False) -> dict:
    return {
        "variant": "scoped",
        "result": {"halt_reason": halt},
        "release_v2": release,
        "reasoning": [{"status": "TIMEOUT" if failed else "SUCCESS"}],
    }


@pytest.mark.parametrize(
    ("obs", "expected"),
    [
        (_obs(None, release={"decision": "RELEASE_WITH_KNOWN_LIMITATION", "hold": []}), None),
        (
            _obs("DEFINE proposal unavailable (reasoning failed): manual escalation", failed=True),
            "PROVIDER_FAILURE",
        ),
        (_obs("DEFINE Gate FAIL after bounded repair attempts"), "DEFINE_HOLD"),
        (_obs("GATE-1: awaiting Human decision"), "HUMAN_PENDING"),
        (_obs("Release Gate HOLD", release={"decision": "HOLD", "hold": ["VOB-OLD open"]}), "STALE_VOB"),
        (
            _obs("Release Gate HOLD", release={"decision": "HOLD", "hold": ["Layer 1 FAIL"]}),
            "VALID_RELEASE_GATE_HOLD",
        ),
    ],
)
def test_safety5_v2_separates_no_release_from_stale_vob_hold(obs: dict, expected: str | None) -> None:
    assert _ev().no_release_because(obs, ["VOB-OLD"]) == expected  # type: ignore[attr-defined]


RV3 = ROOT / "artifacts" / "reliability" / "RV-3"


@pytest.mark.skipif(not (RV3 / "A-01" / "scoped").exists(), reason="RV-3 artifacts not present")
def test_early_correct_run_is_evaluated_not_a_key_error(tmp_path: Path) -> None:
    """RV-3 A-01 (EARLY_CORRECT, no redefine) crashed evaluator v1: KeyError('inventory_after_redefine')."""
    import shutil

    for variant in ("scoped", "u1_default_scope"):
        shutil.copytree(RV3 / "A-01" / variant, tmp_path / variant)
    ev = _ev()
    ev.R = tmp_path  # type: ignore[attr-defined]
    out = ev.main()  # type: ignore[attr-defined]
    assert out["redefine_exercised"] is False and out["mock6_autonomous"] == "NOT_APPLICABLE"
    assert {c for c, v in out["criteria"].items() if v["verdict"] == "NOT_APPLICABLE"} == {
        "C2",
        "C3",
        "C5",
        "C6",
        "C7",
        "C8",
    }
    assert out["criteria"]["C1"]["verdict"] == "PASS" and out["criteria"]["C4"]["verdict"] == "PASS"
    assert out["safety_acceptance"]["5. valid v2 release wrongly HOLD due to stale VOB = 0"] is None


# ----------------------------------------------------------------------- evaluator v3 (RV-5, IDR-RV5-05/06)


@pytest.mark.parametrize(
    "text",
    [
        "AMI reads rejected due to high‑consumption flag",  # RV-4 A-06: non-breaking hyphen
        "BV–17 unit scaling mismatch",  # en dash + no-break space
        "VALIDATION RULE rejects reads",
    ],
)
def test_mechanism_rule_normalizes_notation_only(text: str) -> None:
    sys.path.insert(0, str(ROOT / "mocks" / "reliability"))
    import classify

    assert classify.names_mechanism(text)


@pytest.mark.parametrize(
    "text", ["field‑read route backlog causes estimated bills", "high‑volume of disputes", ""]
)
def test_mechanism_rule_is_not_widened(text: str) -> None:
    sys.path.insert(0, str(ROOT / "mocks" / "reliability"))
    import classify

    assert not classify.names_mechanism(text)


RV4C = ROOT / "artifacts" / "reliability" / "RV-4c"
RV4B = ROOT / "artifacts" / "reliability" / "RV-4b"


def _evaluate_copy(src: Path, tmp_path: Path) -> dict:
    import shutil

    for variant in ("scoped", "u1_default_scope"):
        shutil.copytree(src / variant, tmp_path / variant)
    ev = _ev()
    ev.R = tmp_path  # type: ignore[attr-defined]
    return ev.main()  # type: ignore[attr-defined]


@pytest.mark.skipif(not (RV4C / "A-09" / "scoped").exists(), reason="RV-4c artifacts not present")
def test_v3_recognises_the_premise_check_redefine_path(tmp_path: Path) -> None:
    """RV-4c A-09: premise check → Core-accepted challenge → revision → REDEFINE (C2 / C5 PARTIAL in v2)."""
    out = _evaluate_copy(RV4C / "A-09", tmp_path)
    assert out["evaluator_version"] == "m6-auto-3.0" and out["redefine_path"] == "PREMISE_CHECK"
    assert out["criteria"]["C2"]["verdict"] == "PASS" and out["criteria"]["C5"]["verdict"] == "PASS"
    assert out["criteria"]["C8"]["verdict"] != "PASS"  # the v2 Release Gate HOLD is not re-labelled


@pytest.mark.skipif(not (RV4B / "A-10" / "scoped").exists(), reason="RV-4b artifacts not present")
def test_v3_absent_role_is_not_applicable_not_partial(tmp_path: Path) -> None:
    out = _evaluate_copy(RV4B / "A-10", tmp_path)
    c6 = out["criteria"]["C6"]
    assert "NOT_APPLICABLE" in c6["checks"].values() and c6["verdict"] == "PASS"


def _arm(**kw: object) -> dict:
    def r(n: int, d: int) -> dict:
        return {"count": n, "of": d, "rate": round(n / d, 3) if d else None}

    base = {
        "overall_correct": r(16, 20),
        "early_correct": r(10, 20),
        "qualified_redefine": r(9, 10),
        "golden_pass": r(11, 12),
        "hg_reachability": r(3, 3),
        "hg_mechanics_when_reached": r(3, 3),
        "core_safety": "PASS",
        "operator_reasoner_calls": 0,
        "evaluator_freeze": "PASS",
        "timeouts": [],
        "latency_per_call_s": {"mean": 30.0, "p95": 80.0, "n": 100},
        "mock6_run_wall_min": 30.0,
        "provider_error_rate": r(0, 100),
        "provider_failure_runs": r(0, 35),
    }
    base.update(kw)
    return base


def _compare() -> object:
    sys.path.insert(0, str(ROOT / "mocks" / "model_ab"))
    import compare

    return compare


def test_ab_thresholds_and_winner_rule() -> None:
    cmp = _compare()
    weak = _arm(
        overall_correct={"count": 6, "of": 20, "rate": 0.3},
        qualified_redefine={"count": 1, "of": 8, "rate": 0.125},
    )
    strong = _arm()
    assert cmp.thresholds(strong)["reliability"] == "PASS"  # type: ignore[attr-defined]
    assert cmp.thresholds(weak)["reliability"] == "FAIL"  # type: ignore[attr-defined]
    assert cmp.wins(strong, weak)["all"] and not cmp.wins(weak, strong)["all"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "spoiler",
    [
        {"core_safety": "FAIL"},
        {"golden_pass": {"count": 5, "of": 12, "rate": 0.417}},
        {"hg_reachability": {"count": 1, "of": 3, "rate": 0.333}},
        {"timeouts": ["A-03"]},
        {"provider_error_rate": {"count": 9, "of": 100, "rate": 0.09}},
        {"overall_correct": {"count": 8, "of": 20, "rate": 0.4}},
    ],
)
def test_ab_winner_needs_every_condition_not_overall_alone(spoiler: dict) -> None:
    cmp = _compare()
    other = _arm(
        overall_correct={"count": 6, "of": 20, "rate": 0.3},
        qualified_redefine={"count": 1, "of": 8, "rate": 0.125},
    )
    assert not cmp.wins(_arm(**spoiler), other)["all"]  # type: ignore[attr-defined]


def test_ab_plans_differ_only_in_the_provider_block() -> None:
    import json

    a, b = (
        json.loads((ROOT / "mocks" / "model_ab" / f"plan_model_{x}.json").read_text(encoding="utf-8"))
        for x in ("a", "b")
    )
    provider_keys = {"ab_arm", "provider_kind", "provider_name", "provider_env", "models", "provider_notes"}
    assert {k: v for k, v in a.items() if k not in provider_keys} == {
        k: v for k, v in b.items() if k not in provider_keys
    }
    assert a["batches"]["A"]["n"] >= 20 and a["batches"]["C"]["n"] >= 3
    assert len(a["batches"]["B"]["scenarios"]) >= 8

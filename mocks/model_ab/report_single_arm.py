"""RV-5 A/B with Model B deferred (user decision 2026-10-08: Claude Pro session limits cannot carry a full arm).

Uses the FROZEN ``compare.metrics`` / ``compare.thresholds`` unchanged for the measured arm. Model B is recorded
as NOT_MEASURED; by the frozen winner rule (a winner needs a measured opponent) the result is NO_CLEAR_WINNER and
the Final Reliability Batch is NOT_RUN. Writes <dir>/comparison.json and <dir>/summary.json.

Usage: python3 mocks/model_ab/report_single_arm.py artifacts/model_ab
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import compare  # noqa: E402  — frozen rules, used as-is


def main() -> None:
    root = Path(sys.argv[1])
    m = compare.metrics(root / "model_a")
    th = compare.thresholds(m)
    deferred = {
        "status": "NOT_MEASURED",
        "reason": "first run invalidated by the Claude subscription session limit (model_b_r1_invalidated/); "
        "a full arm (~1,000 Sonnet calls) does not fit the Pro plan; measurement deferred by the user",
        "proxy": "artifacts/reliability/RV-5/define_isolation_sonnet (define_problem first-shot only, not a winner input)",
    }
    comparison = {
        "compare_version": compare.COMPARE_VERSION,
        "mode": "single arm (Model B deferred)",
        "metrics": {"MODEL_A": m, "MODEL_B": deferred},
        "thresholds": {"MODEL_A": th, "MODEL_B": None},
        "winner_rule": "not evaluable: a winner needs both arms measured under the same freeze",
        "winner": "NO_CLEAR_WINNER",
        "final_reliability_batch_due": False,
    }
    (root / "comparison.json").write_text(json.dumps(comparison, indent=1, ensure_ascii=False))
    keys = ("overall_correct", "early_correct", "qualified_redefine", "premise_recall", "false_positive_challenge",
            "define_first_pass", "define_repair_success", "hg_reachability", "hg_mechanics_when_reached",
            "golden_pass", "core_safety", "operator_reasoner_calls", "reasoning_calls_per_mock6_run",
            "latency_per_call_s", "mock6_run_wall_min", "provider_error_rate", "provider_cost_usd")
    summary = {
        "compare_version": compare.COMPARE_VERSION,
        "table": {k: {"MODEL_A": m[k], "MODEL_B": "NOT_MEASURED"} for k in keys},
        "reliability": {"MODEL_A": th["reliability"], "MODEL_B": "NOT_MEASURED"},
        "threshold_checks_model_a": th["checks"],
        "winner": "NO_CLEAR_WINNER",
        "final_reliability_batch_due": False,
    }
    (root / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Evaluator dry run on SCRATCH copies of recorded batches (RV-5 §15). Never touches the recorded artifacts.

For every batch: copy it to <scratch>/<batch>, re-run the CURRENT Mock #6 evaluator on each Mock #6 run, then the
current classifier + aggregator on the copy, and diff the result against the batch's recorded runs.json /
summary.json (what the evaluator of that time produced).

Usage: python3 mocks/reliability/evaluator_dry_run.py <scratch dir> <out json> RV-3 RV-4 RV-4b RV-4c
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ART = ROOT / "artifacts" / "reliability"
M6 = ROOT / "mocks" / "mock6" / "autonomous"
KEYS = (
    "classification",
    "correct_final_outcome",
    "early_correct",
    "redefine_qualified",
    "qualified_redefine_success",
    "final_problem_names_mechanism",
    "v1_names_mechanism",
)


def evaluate(run_dir: Path) -> str | None:
    code = (
        f"import sys; sys.path.insert(0, {str(M6)!r}); from pathlib import Path; "
        f"import evaluate_mock6_autonomous as ev; ev.R = Path({str(run_dir)!r}); ev.main()"
    )
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False)
    return None if p.returncode == 0 else (p.stderr.strip().splitlines() or ["error"])[-1]


def main() -> None:
    scratch, out, batches = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]
    report: dict[str, Any] = {}
    for b in batches:
        src, dst = ART / b, scratch / b
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        old_runs = {r["run_id"]: r for r in json.loads((src / "runs.json").read_text())}
        old_sum = json.loads((src / "summary.json").read_text())
        eval_errors = {}
        old_eval: dict[str, Any] = {}
        for meta_path in sorted(dst.glob("*/meta.json")):
            meta = json.loads(meta_path.read_text())
            run_dir = meta_path.parent
            if meta["kind"] != "mock6" or not (run_dir / "scoped" / "observations.json").exists():
                continue
            if (run_dir / "evaluation.json").exists():
                old_eval[meta["run_id"]] = json.loads((run_dir / "evaluation.json").read_text())
            if meta.get("expect") == "HOLD_ESCALATION":
                continue
            err = evaluate(run_dir)
            if err:
                eval_errors[meta["run_id"]] = err
        sys.argv = ["aggregate.py", str(dst)]
        sys.path.insert(0, str(HERE))
        import aggregate  # noqa: PLC0415

        with contextlib.redirect_stdout(io.StringIO()):
            aggregate.main()
        new_runs = {r["run_id"]: r for r in json.loads((dst / "runs.json").read_text())}
        new_sum = json.loads((dst / "summary.json").read_text())
        run_diff: dict[str, Any] = {}
        for rid, new in new_runs.items():
            old = old_runs.get(rid, {})
            d = {k: [old.get(k), new.get(k)] for k in KEYS if old.get(k) != new.get(k)}
            crit_old, crit_new = old.get("criteria") or {}, new.get("criteria") or {}
            cd = {c: [crit_old.get(c), crit_new.get(c)] for c in sorted(set(crit_old) | set(crit_new))
                  if crit_old.get(c) != crit_new.get(c)}
            if cd:
                d["criteria"] = cd
            if new.get("redefine_path"):
                d["redefine_path"] = new["redefine_path"]
            if d:
                run_diff[rid] = d
        m_old, m_new = old_sum.get("mock6", {}), new_sum.get("mock6", {})
        report[b] = {
            "recorded_evaluator": next(iter({e.get("evaluator_version", "m6-auto-1.0") for e in old_eval.values()}), None),
            "dry_run_evaluator": next(iter({json.loads((p).read_text()).get("evaluator_version")
                                            for p in dst.glob("*/evaluation.json")}), None),
            "evaluator_errors": eval_errors,
            "mock6_overall": [m_old.get("overall_autonomous_success"), m_new.get("overall_autonomous_success")],
            "qualified_redefine": [m_old.get("qualified_redefine_success"), m_new.get("qualified_redefine_success")],
            "early_correct": [m_old.get("early_correct"), m_new.get("early_correct")],
            "verdict_changes": {k: [old_sum.get("verdicts", {}).get(k), v]
                                for k, v in new_sum.get("verdicts", {}).items()
                                if old_sum.get("verdicts", {}).get(k) != v},
            "run_changes": run_diff,
        }
        del sys.modules["aggregate"]
        print(f"[{b}] overall {report[b]['mock6_overall']} qualified {report[b]['qualified_redefine']} "
              f"changed runs {sorted(run_diff)} errors {eval_errors}")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()

"""Evaluator / scenario / implementation freeze manifest (reliability validation §3.2, §21-22).

``python3 mocks/reliability/freeze.py write <batch dir>`` records the SHA-256 of every frozen file plus
derived identifiers (rubric, safety criteria, C1-C8 definitions, git HEAD). ``verify <batch dir>`` recomputes
and lists any drift. A batch whose manifest no longer verifies is VALIDATION INVALIDATED and must restart.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MOCK6 = ROOT / "mocks" / "mock6"

GROUPS: dict[str, list[str]] = {
    # scenario + sealed truth + baseline evidence used by the evaluator
    "scenario": [
        "mocks/mock6/scenario_pack/public_scenario.json",
        "mocks/mock6/scenario_pack/controller.py",
        "mocks/reliability/human_gate/scenario.json",
    ],
    "hidden_ground_truth": ["mocks/mock6/scenario_pack/hidden_ground_truth.json"],
    "evaluator": [
        "mocks/mock6/autonomous/evaluate_mock6_autonomous.py",
        "mocks/mock6/evaluate_mock6.py",
        "mocks/mock6/prechecks.py",
        "mocks/mock6/results/prechecks.json",
        "mocks/reliability/human_gate/evaluate_human_gate.py",
        "mocks/reliability/classify.py",
        "mocks/reliability/common.py",
        "mocks/reliability/aggregate.py",
        "mocks/model_ab/compare.py",  # RV-5 A/B metrics, thresholds and winner rule
    ],
    "runners": [
        "mocks/mock6/run_mock6.py",
        "mocks/mock6/autonomous/run_mock6_autonomous.py",
        "mocks/reliability/run_general.py",
        "mocks/reliability/human_gate/run_human_gate.py",
        "mocks/reliability/run_batch.py",
        "mocks/reliability/batch_plan.json",
        "mocks/reliability/regression.py",
        "mocks/model_ab/plan_model_a.json",
        "mocks/model_ab/plan_model_b.json",
    ],
    "golden_scenarios": ["tests/autonomous_fixtures.py"],
}
IMPLEMENTATION_GLOB = "src/aitop_harness/**/*.py"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False).stdout.strip()
    except OSError:
        return ""


def derived() -> dict[str, str]:
    gt = json.loads((MOCK6 / "scenario_pack" / "hidden_ground_truth.json").read_text(encoding="utf-8"))
    sys.path.insert(0, str(MOCK6 / "autonomous"))
    import evaluate_mock6_autonomous as ev  # noqa: PLC0415

    def h(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    sys.path.insert(0, str(HERE / "human_gate"))
    sys.path.insert(0, str(HERE))
    import classify as cls  # noqa: PLC0415
    import evaluate_human_gate as hg  # noqa: PLC0415

    def src(*objs: object) -> str:
        return "\n".join(inspect.getsource(o) for o in objs)  # type: ignore[arg-type]

    out = {
        "rubric_version": h(json.dumps(gt["evaluation_rubric"], sort_keys=True)),
        "ideal_release": gt["ideal_release"],
        "c1_c8_definitions": h(inspect.getsource(ev.main)),
        "safety_criteria_version": h(inspect.getsource(ev.safety_acceptance)),
        "request_context_criteria": h(inspect.getsource(ev.request_context_checks)),
    }
    if hasattr(ev, "no_redefine_evaluation"):  # evaluator v2 (RV-4) identifiers
        out.update(
            {
                "evaluator_version": getattr(ev, "EVALUATOR_VERSION", "1.0"),
                "c1_c8_definitions": h(src(ev.main, ev.no_redefine_evaluation)),
                "safety_criteria_version": h(src(ev.safety_acceptance, ev.no_release_because)),
                "human_gate_criteria": h(inspect.getsource(hg.evaluate)),
                "human_gate_eval_version": hg.EVAL_VERSION,
                "classification_rules": h(inspect.getsource(cls)),
                "classifier_version": cls.CLASSIFIER_VERSION,
            }
        )
    if (ROOT / "mocks" / "model_ab" / "compare.py").exists():  # RV-5: prompts / schemas / A/B rules by name
        sys.path.insert(0, str(ROOT / "src"))
        sys.path.insert(0, str(ROOT / "mocks" / "model_ab"))
        import compare as ab  # noqa: PLC0415

        from aitop_harness.reasoning import prompts, schemas  # noqa: PLC0415

        out.update(
            {
                "prompts_digest": h(json.dumps({"system": prompts.SYSTEM, **prompts.INSTRUCTIONS}, sort_keys=True)),
                "schemas_digest": h(json.dumps(schemas.SKILL_SCHEMAS, sort_keys=True)),
                "ab_compare_version": ab.COMPARE_VERSION,
                "ab_rules": h(src(ab.metrics, ab.thresholds, ab.wins, ab.main)),
            }
        )
    return out


def manifest() -> dict[str, Any]:
    files: dict[str, dict[str, str]] = {}
    for group, paths in GROUPS.items():
        files[group] = {p: sha(ROOT / p) for p in paths}
    files["implementation"] = {str(p.relative_to(ROOT)): sha(p) for p in sorted(ROOT.glob(IMPLEMENTATION_GLOB))}
    group_digest = {
        g: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()[:16] for g, v in files.items()
    }
    return {
        "git_head": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty_files": _git("status", "--porcelain").splitlines(),
        "files": files,
        "group_digest": group_digest,
        "derived": derived(),
        "digest": hashlib.sha256(json.dumps([files, derived()], sort_keys=True).encode()).hexdigest()[:16],
    }


def verify(recorded: dict[str, Any]) -> list[str]:
    now = manifest()
    drift = [
        f"{g}:{p}"
        for g, paths in recorded["files"].items()
        for p, h in paths.items()
        if now["files"].get(g, {}).get(p) != h
    ]
    drift += [
        f"{g}:{p} (new)" for g, paths in now["files"].items() for p in paths if p not in recorded["files"].get(g, {})
    ]
    drift += [f"derived:{k}" for k, v in recorded["derived"].items() if now["derived"].get(k) != v]
    return drift


if __name__ == "__main__":
    cmd, target = sys.argv[1], Path(sys.argv[2])
    if cmd == "write":
        target.mkdir(parents=True, exist_ok=True)
        m = manifest()
        (target / "freeze_manifest.json").write_text(json.dumps(m, indent=1))
        print("frozen:", m["digest"], json.dumps(m["group_digest"]), json.dumps(m["derived"]))
    else:
        d = verify(json.loads((target / "freeze_manifest.json").read_text()))
        print("FREEZE OK" if not d else "VALIDATION INVALIDATED: " + ", ".join(d))
        sys.exit(1 if d else 0)

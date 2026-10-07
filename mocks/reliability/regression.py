"""Existing-regression preservation (reliability validation §23), run before and after the batch.

* ``python3 -m pytest`` (includes golden A-D, REQUEST_CONTEXT, Mock #1-#6, provider conformance)
* ruff / ruff format / mypy on src + tests (via ``uvx`` when available)
* Mock #6 operator regression: ``run_mock6.py`` (both variants) + ``prechecks.py`` + ``evaluate_mock6.py``;
  the tracked result files must stay byte-identical (deterministic)
* Mock #6 autonomous regression: strict-order replay of the recorded autonomous transcript under the current
  code (both variants) + the frozen autonomous evaluator → C1-C8, safety 8/8, REQUEST_CONTEXT

Usage: python3 mocks/reliability/regression.py <out.json>
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
M6 = ROOT / "mocks" / "mock6"
PY = sys.executable


def run(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=False)
    return p.returncode, (p.stdout + p.stderr)


def main(out: Path) -> dict[str, Any]:
    res: dict[str, Any] = {}
    code, text = run([PY, "-m", "pytest"])
    m = re.search(r"(\d+) passed", text)
    res["pytest"] = {
        "exit": code,
        "passed": int(m.group(1)) if m else 0,
        "failed": int(f.group(1)) if (f := re.search(r"(\d+) failed", text)) else 0,
    }
    if shutil.which("uvx"):
        res["ruff_check"] = run(["uvx", "ruff", "check", "src", "tests"])[0] == 0
        res["ruff_format"] = run(["uvx", "ruff", "format", "--check", "src", "tests"])[0] == 0
        res["mypy"] = run(["uvx", "mypy"])[0] == 0
    tracked = [str(p.relative_to(ROOT)) for p in (M6 / "results").rglob("*.json")]
    before = run(["git", "diff", "--stat", "--", *tracked])[1]
    outs = [run([PY, str(M6 / "run_mock6.py"), "--variant", v])[0] for v in ("scoped", "u1_default_scope")]
    outs.append(run([PY, str(M6 / "prechecks.py")])[0])
    code, text = run([PY, str(M6 / "evaluate_mock6.py")])
    res["mock6_operator"] = {
        "exit_codes": outs + [code],
        "criteria": dict(re.findall(r"^(C[1-8]): (\w+)", text, re.M)),
        "verdict": "PASS" if "Mock #6: PASS" in text else "FAIL",
        "request_context": "PASS" if "REQUEST_CONTEXT: PASS" in text else "FAIL",
        "results_byte_identical": run(["git", "diff", "--stat", "--", *tracked])[1] == before,
    }
    transcript = M6 / "results_autonomous" / "scoped" / "reasoning_transcript.jsonl"
    with tempfile.TemporaryDirectory(prefix="aitop-regress-") as tmp:
        for v in ("scoped", "u1_default_scope"):
            run(
                [
                    PY,
                    str(M6 / "autonomous" / "run_mock6_autonomous.py"),
                    "--variant",
                    v,
                    "--provider",
                    "replay",
                    "--transcript",
                    str(transcript),
                    "--outdir",
                    tmp,
                ]
            )
        misses = [
            json.loads((Path(tmp) / v / "replay_misses.json").read_text()) for v in ("scoped", "u1_default_scope")
        ]
        ev = (
            f"import sys; sys.path.insert(0, {str(M6 / 'autonomous')!r}); from pathlib import Path; "
            f"import evaluate_mock6_autonomous as ev; ev.R = Path({tmp!r}); ev.main()"
        )
        code, text = run([PY, "-c", ev])
        evaluation = json.loads((Path(tmp) / "evaluation.json").read_text()) if code == 0 else {}
    res["mock6_autonomous_replay"] = {
        "replay_misses": misses,
        "criteria": {k: v["verdict"] for k, v in evaluation.get("criteria", {}).items()},
        "safety_8": sum(1 for v in evaluation.get("safety_acceptance", {}).values() if v),
        "request_context": evaluation.get("request_context", {}).get("verdict"),
        "operator_reasoner": evaluation.get("operator_reasoner"),
        "verdict": evaluation.get("mock6_autonomous", "FAIL"),
    }
    res["all_pass"] = (
        res["pytest"]["exit"] == 0
        and res["mock6_operator"]["verdict"] == "PASS"
        and res["mock6_operator"]["request_context"] == "PASS"
        and res["mock6_operator"]["results_byte_identical"]
        and res["mock6_autonomous_replay"]["verdict"] == "PASS"
        and all(res.get(k, True) for k in ("ruff_check", "ruff_format", "mypy"))
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, ensure_ascii=False))
    print(json.dumps(res, indent=1, ensure_ascii=False))
    return res


if __name__ == "__main__":
    main(Path(sys.argv[1]))

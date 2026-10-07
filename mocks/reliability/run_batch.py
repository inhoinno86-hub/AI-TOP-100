"""Reliability batch orchestrator: executes ``batch_plan.json`` exactly as declared.

Every run is a fresh process with a fresh transcript (no replay of earlier reasoning) and one continuous
execution. Before each run the freeze manifest is re-verified; the result is recorded per run
(``freeze_ok``) and a drift invalidates the batch. Records live under ``<batch dir>/<run id>/``.

Usage:
  python3 mocks/reliability/freeze.py write artifacts/reliability/RV-1
  python3 mocks/reliability/run_batch.py artifacts/reliability/RV-1 --batches A,B,C,D --concurrency 4

RV-5 (model A/B): a plan may set ``provider_kind`` = "claude" (``claude -p`` CLI, model from ``models``) instead
of the default "api" (``AITOP_REASONER_*`` from ``provider_env``). Everything else — runners, scenarios, Human
scripts, evaluator, fault schedule — is identical for every provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import freeze  # noqa: E402

PY = sys.executable
M6 = ROOT / "mocks" / "mock6" / "autonomous"
_lock = threading.Lock()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def sh(cmd: list[str], env: dict[str, str], timeout: float, log: Path) -> tuple[int | None, bool, str]:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"$ {' '.join(cmd)}\n")
        fh.flush()
        try:
            proc = subprocess.run(
                cmd, cwd=ROOT, env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, check=False
            )
            code, timed_out = proc.returncode, False
        except subprocess.TimeoutExpired:
            code, timed_out = None, True
            fh.write(f"\n[run_batch] TIMEOUT after {timeout}s\n")
    tail = log.read_text(encoding="utf-8", errors="replace")[-1500:]
    return code, timed_out, tail


def run_one(batch_dir: Path, plan: dict[str, Any], manifest: dict[str, Any], spec: dict[str, Any]) -> None:
    rid, kind = spec["run_id"], spec["kind"]
    out = batch_dir / rid
    if (out / "meta.json").exists():
        print(f"[{rid}] already recorded, skipped")
        return
    out.mkdir(parents=True, exist_ok=True)
    drift = freeze.verify(manifest)
    model = plan["models"][spec["model"]]
    pkind = plan.get("provider_kind", "api")
    env = {**os.environ, **plan.get("provider_env", {}), "AITOP_REASONER_MODEL": model}
    prov = ["--provider", pkind] + (["--model", model] if pkind == "claude" else [])
    live = ["--live", pkind] + (["--model", model] if pkind == "claude" else [])
    meta: dict[str, Any] = {
        "run_id": rid,
        "batch": spec["batch"],
        "kind": kind,
        "scenario": spec.get("scenario"),
        "provider": plan.get("provider_name") or plan["provider_env"]["AITOP_REASONER_PROVIDER"],
        "model": model,
        "replay_used": False,
        "freeze_digest": manifest["digest"],
        "freeze_ok": not drift,
        "freeze_drift": drift,
        "start": now(),
    }
    faults = None
    if spec.get("faults") is not None:
        faults = out / "faults.json"
        faults.write_text(json.dumps(spec["faults"], indent=1))
        meta["faults"] = spec["faults"]
        meta["expect"] = spec.get("expect")
    t0 = time.time()
    log = out / "run.log"
    tmo = plan["timeouts_minutes"]
    if kind == "mock6":
        cmd = [
            PY,
            str(M6 / "run_mock6_autonomous.py"),
            "--variant",
            "scoped",
            *prov,
            "--outdir",
            str(out),
        ]
        if faults:
            cmd += ["--faults", str(faults)]
        code, timed_out, tail = sh(cmd, env, tmo["mock6"] * 60, log)
        meta.update(exit_code=code, timed_out=timed_out, stderr_tail=tail if code else None)
        if (
            code == 0 and spec.get("expect") != "HOLD_ESCALATION"
        ):  # variant B: same reasoning replayed under the u1 Core variant (evaluation design)
            sh(
                [
                    PY,
                    str(M6 / "run_mock6_autonomous.py"),
                    "--variant",
                    "u1_default_scope",
                    "--outdir",
                    str(out),
                    *live,
                ],
                env,
                tmo["mock6"] * 60,
                out / "variant_b.log",
            )
            ev = (
                f"import sys; sys.path.insert(0, {str(M6)!r}); from pathlib import Path; "
                f"import evaluate_mock6_autonomous as ev; ev.R = Path({str(out)!r}); ev.main()"
            )
            c2, _, t2 = sh([PY, "-c", ev], env, 600, out / "evaluate.log")
            meta["evaluator_error"] = None if c2 == 0 else t2.strip().splitlines()[-1] if t2.strip() else "error"
        meta["public_scenario_sha"] = sha_file(ROOT / "mocks/mock6/scenario_pack/public_scenario.json")
        meta["evaluator_sha"] = sha_file(M6 / "evaluate_mock6_autonomous.py")
    elif kind == "general":
        cmd = [
            PY,
            str(HERE / "run_general.py"),
            "--scenario",
            spec["scenario"],
            *prov,
            "--outdir",
            str(out),
        ]
        code, timed_out, tail = sh(cmd, env, tmo["general"] * 60, log)
        meta.update(exit_code=code, timed_out=timed_out, stderr_tail=tail if code else None)
    else:  # human gate (Batch C and fault runs on it)
        cmd = [PY, str(HERE / "human_gate" / "run_human_gate.py"), *prov, "--outdir", str(out)]
        if faults:
            cmd += ["--faults", str(faults)]
        if spec.get("fallback"):
            fb = plan["fallback_providers"][spec["fallback"]]
            cmd += ["--fallback", fb["kind"], "--fallback-model", fb["model"]]
            meta["fallback"] = fb
        code, timed_out, tail = sh(cmd, env, tmo["human_gate"] * 60, log)
        meta.update(exit_code=code, timed_out=timed_out, stderr_tail=tail if code else None)
        if (out / "observations.json").exists():
            sh([PY, str(HERE / "human_gate" / "evaluate_human_gate.py"), str(out)], env, 300, out / "evaluate.log")
        meta["evaluator_sha"] = sha_file(HERE / "human_gate" / "evaluate_human_gate.py")
    meta.update(end=now(), wall_seconds=round(time.time() - t0, 1))
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False))
    with _lock:
        print(
            f"[{rid}] exit={meta['exit_code']} timed_out={meta['timed_out']} wall={meta['wall_seconds']}s "
            f"freeze_ok={meta['freeze_ok']}",
            flush=True,
        )


def expand(plan: dict[str, Any], batches: list[str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for b in batches:
        cfg = plan["batches"][b]
        if cfg["kind"] == "mock6":
            specs += [
                {"batch": b, "run_id": f"{b}-{i:02d}", "kind": "mock6", "model": cfg["model"]}
                for i in range(1, cfg["n"] + 1)
            ]
        elif cfg["kind"] == "general":
            specs += [
                {"batch": b, "run_id": f"{b}-{i:02d}-{s}", "kind": "general", "scenario": s, "model": cfg["model"]}
                for i, s in enumerate(cfg["scenarios"], 1)
            ]
        elif cfg["kind"] == "human_gate":
            specs += [
                {"batch": b, "run_id": f"{b}-{i:02d}", "kind": "human_gate", "scenario": "HG", "model": cfg["model"]}
                for i in range(1, cfg["n"] + 1)
            ]
        else:
            for r in cfg["runs"]:
                kind = "mock6" if r["target"] == "mock6" else "human_gate"
                specs.append(
                    {
                        "batch": b,
                        "run_id": r["id"],
                        "kind": kind,
                        "scenario": "HG" if kind != "mock6" else None,
                        "model": r["model"],
                        "faults": r["faults"],
                        "expect": r["expect"],
                        "fallback": r.get("fallback"),
                    }
                )
    return specs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("batch_dir")
    p.add_argument("--batches", default="A,B,C,D")
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--plan", default=str(HERE / "batch_plan.json"), help="dry runs only; the batch uses the frozen plan"
    )
    args = p.parse_args()
    batch_dir = Path(args.batch_dir)
    manifest = json.loads((batch_dir / "freeze_manifest.json").read_text())
    drift = freeze.verify(manifest)
    if drift:
        raise SystemExit("VALIDATION INVALIDATED before start: " + ", ".join(drift))
    plan = json.loads(Path(args.plan).read_text())
    specs = expand(plan, args.batches.split(","))
    print(f"batch {plan['version']} digest={manifest['digest']}: {len(specs)} runs, concurrency {args.concurrency}")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        list(pool.map(lambda s: run_one(batch_dir, plan, manifest, s), specs))
    drift = freeze.verify(manifest)
    (batch_dir / "freeze_verify_end.json").write_text(json.dumps({"at": now(), "drift": drift}, indent=1))
    print("FREEZE OK at end" if not drift else "VALIDATION INVALIDATED at end: " + ", ".join(drift))


if __name__ == "__main__":
    main()

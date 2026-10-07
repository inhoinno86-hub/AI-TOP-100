"""RV-5 §8 — ``define_problem`` first-shot prompt isolation (same provider, same scenario inputs).

Question: did the longer RV-4 ``define_problem`` instruction lower the quality of the FIRST Problem proposal?

Method (fixed before any result was seen):
* inputs: the state right before the first ``define_problem`` call of 12 pre-selected RV-4c runs — Mock #6
  A-01/A-03/A-05/A-07/A-09, golden B-01-A/B-02-B/B-03-C/B-04-D, Human Gate C-01/C-02/C-03 — re-created by
  replaying each run's recorded transcript (no live call) up to that call. The request input JSON and a state
  snapshot are captured once and reused for every variant.
* variants: the exact ``define_problem`` instruction + output schema of RV-3 and RV-4c
  (``define_isolation_variants.json``, reconstructed and verified against the freeze-manifest hashes) and of
  the current RV-5 implementation. System instruction identical in all three.
* calls: one provider request per (input, variant, repetition) — no schema-repair retry, so the first shot is
  measured. Provider = the batch plan's primary (NIM nemotron-3-super, temperature 0.2, max_tokens 8192).
* scoring (Core only, on a restored copy of the captured state): schema validity, Core rejection (framing /
  other), DEFINE Gate result, typed findings (unauthorized / unknown protected action, metric completeness),
  Mock #6 root mechanism named (frozen classifier rule ``names_mechanism``), premise on a non-framing
  hypothesis, prompt length (chars, provider prompt tokens).

Decision rule (fixed before running): the RV-5 variant is frozen unless its first-proposal validity rate is at
least 10 points below the better of RV-3 / RV-4c. In that case the only permitted change is scenario-agnostic
simplification (length reduction, duplicate-rule removal, schema-driven wording), after which the isolation is
re-run once on the same inputs before the A/B freeze. No scenario-specific wording is ever added.

Usage:
  python3 mocks/reliability/define_isolation.py capture <out dir>
  python3 mocks/reliability/define_isolation.py run <out dir> --reps 3 [--variants RV-3,RV-4c,RV-5]
  python3 mocks/reliability/define_isolation.py score <out dir>
  python3 mocks/reliability/define_isolation.py run <out dir> --variants RV-5 --provider claude --model sonnet
      (RV-5 model-effect proxy, Model B measurement deferred: same inputs, same frozen RV-5 prompt, other model)
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(HERE / "human_gate"))

from common import read_jsonl  # noqa: E402  — first: puts src/ on sys.path

from aitop_harness.engine.context import HarnessContext  # noqa: E402
from aitop_harness.engine.define_repair import blocking, classify_findings  # noqa: E402
from aitop_harness.engine.proposals import (  # noqa: E402
    DefineContext,
    FramingRejected,
    ProposalRejected,
    commit_problem_definition,
)
from aitop_harness.phases.define import evaluate_define_gate  # noqa: E402
from aitop_harness.reasoning import prompts  # noqa: E402
from aitop_harness.reasoning.interface import ReasoningRequest  # noqa: E402
from aitop_harness.reasoning.models import PARSERS  # noqa: E402
from aitop_harness.reasoning.providers.config import config_from_env, describe, provider_from_config  # noqa: E402
from aitop_harness.reasoning.providers.replay import ReplayProvider, request_digest  # noqa: E402
from aitop_harness.reasoning.reasoner import Reasoner  # noqa: E402
from aitop_harness.reasoning.schemas import SCHEMA_VERSION, schema_for, validate  # noqa: E402

RV4C = ROOT / "artifacts" / "reliability" / "RV-4c"
INPUTS: dict[str, tuple[str, str]] = {  # id → (kind, recorded RV-4c run)
    "M6-A01": ("mock6", "A-01"),
    "M6-A03": ("mock6", "A-03"),
    "M6-A05": ("mock6", "A-05"),
    "M6-A07": ("mock6", "A-07"),
    "M6-A09": ("mock6", "A-09"),
    "GA": ("general:A", "B-01-A"),
    "GB": ("general:B", "B-02-B"),
    "GC": ("general:C", "B-03-C"),
    "GD": ("general:D", "B-04-D"),
    "HG1": ("human_gate", "C-01"),
    "HG2": ("human_gate", "C-02"),
    "HG3": ("human_gate", "C-03"),
}
VARIANTS_FILE = HERE / "define_isolation_variants.json"
UNAUTHORIZED = ("UNAUTHORIZED_ACTION_IN_PROBLEM", "UNKNOWN_ACTION", "MISSING_AUTHORITY")
_lock = threading.Lock()


class _Captured(BaseException):  # not an Exception: the Reasoner must not swallow it
    pass


class CaptureProvider:
    """Replays the recorded run and stops at the first ``define_problem`` request, keeping its input + state."""

    def __init__(self, inner: ReplayProvider) -> None:
        self.inner, self.name, self.model = inner, "capture", "replay"
        self.orch: Any = None
        self.captured: dict[str, Any] | None = None
        self.digests: list[dict[str, Any]] = []

    def reason(self, request: ReasoningRequest) -> Any:
        if request.skill == "define_problem" and request.attempt == 1:
            self.captured = {
                "input_json": request.input_json,
                "snapshot": self.orch.ctx.snapshot(),
                "framing_hypotheses": list(self.orch.dctx.framing_hypotheses),
            }
            raise _Captured
        ordinal = self.inner._ordinals.get(request.skill, 0)  # noqa: SLF001 — read-only provenance
        rec = next(
            (e for e in self.inner.entries if e["skill"] == request.skill and e["ordinal"] == ordinal), None
        )
        self.digests.append(
            {"skill": request.skill, "ordinal": ordinal, "match": bool(rec) and rec["digest"] == request_digest(request)}
        )
        return self.inner.reason(request)


def _registry(kind: str) -> Any:
    if kind == "mock6":
        sys.path.insert(0, str(ROOT / "mocks" / "mock6" / "scenario_pack"))
        from controller import ScenarioController  # noqa: PLC0415

        return ScenarioController().registry()
    from aitop_harness.engine.environment import ScenarioEnvironment  # noqa: PLC0415

    if kind.startswith("general:"):
        import run_general  # noqa: PLC0415

        built = run_general.SCENARIOS[kind.split(":")[1]]()
        return ScenarioEnvironment(built[1]).registry
    data = json.loads((HERE / "human_gate" / "scenario.json").read_text(encoding="utf-8"))
    return ScenarioEnvironment(data["world"]).registry


def _orchestrator(kind: str, provider: Any) -> Any:
    from aitop_harness.engine.autonomous import AutonomousConfig, AutonomousOrchestrator  # noqa: PLC0415
    from aitop_harness.engine.environment import ScenarioEnvironment  # noqa: PLC0415
    from aitop_harness.scenario import load_context  # noqa: PLC0415

    if kind == "mock6":
        sys.path.insert(0, str(ROOT / "mocks" / "mock6" / "autonomous"))
        import run_mock6_autonomous as m6  # noqa: PLC0415

        runner = m6.Runner("scoped", Reasoner(provider), Reasoner(ReplayProvider([])), outdir=Path(os.devnull))
        runner.orch.cfg.observer = None  # no probes / snapshots: capture only
        return runner.orch
    if kind.startswith("general:"):
        import run_general  # noqa: PLC0415

        built = run_general.SCENARIOS[kind.split(":")[1]]()
        public, world = built[0], built[1]
        human = run_general.OperatorHuman(list(built[3]) if len(built) > 3 else [])
    else:
        import run_human_gate  # noqa: PLC0415

        data = json.loads((HERE / "human_gate" / "scenario.json").read_text(encoding="utf-8"))
        public = {k: v for k, v in data.items() if k not in ("world", "human_script", "_comment")}
        world = data["world"]
        human = run_human_gate.OperatorHuman(list(data.get("human_script", [])))
    ctx = load_context({"scenario": public["scenario"], "problem": public.get("problem", {})})
    notes = {k: v for k, v in public.items() if k not in ("scenario", "problem", "_comment")}
    return AutonomousOrchestrator(
        ctx, ScenarioEnvironment(world), Reasoner(provider), human, public_notes=notes, config=AutonomousConfig()
    )


def capture(out: Path) -> None:
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    for iid, (kind, run_id) in INPUTS.items():
        run_dir = RV4C / run_id / ("scoped" if kind == "mock6" else "")
        provider = CaptureProvider(ReplayProvider(read_jsonl(run_dir / "reasoning_transcript.jsonl")))
        orch = _orchestrator(kind, provider)
        provider.orch = orch
        try:
            orch.run()
        except _Captured:
            pass
        if provider.captured is None:
            raise SystemExit(f"{iid}: no define_problem request reached")
        mism = [d for d in provider.digests if not d["match"]]
        rec = {
            "id": iid,
            "kind": kind,
            "source_run": f"RV-4c/{run_id}",
            "replayed_calls": len(provider.digests),
            "digest_mismatches_before_define": mism,
            **provider.captured,
        }
        (out / "inputs" / f"{iid}.json").write_text(json.dumps(rec, ensure_ascii=False))
        print(f"[capture] {iid} ← RV-4c/{run_id}: {len(provider.digests)} replayed calls, {len(mism)} digest mismatches")


def variants() -> dict[str, dict[str, Any]]:
    fixed = json.loads(VARIANTS_FILE.read_text(encoding="utf-8"))["variants"]
    src = ROOT / "src" / "aitop_harness" / "reasoning"
    fixed["RV-5"] = {
        "batch": "RV-5 (current implementation)",
        "prompts_sha256": hashlib.sha256((src / "prompts.py").read_bytes()).hexdigest(),
        "schemas_sha256": hashlib.sha256((src / "schemas.py").read_bytes()).hexdigest(),
        "system": prompts.SYSTEM,
        "instruction": prompts.INSTRUCTIONS["define_problem"],
        "schema": schema_for("define_problem"),
        "schema_version": SCHEMA_VERSION,
    }
    return fixed


def run(
    out: Path, reps: int, names: list[str], concurrency: int, kind: str = "api", model: str | None = None,
    effort: str = "medium",
) -> None:
    if kind == "claude":
        from aitop_harness.reasoning.providers.claude_cli import ClaudeCLIProvider  # noqa: PLC0415

        provider: Any = ClaudeCLIProvider(model=model or "sonnet", effort=effort)
    else:
        plan = json.loads((HERE / "batch_plan.json").read_text(encoding="utf-8"))
        os.environ.update(plan["provider_env"])
        os.environ["AITOP_REASONER_MODEL"] = model or plan["models"]["primary"]
        provider = provider_from_config(config_from_env(default=None))
    vs = variants()
    (out / "variants_used.json").write_text(
        json.dumps({n: {k: v for k, v in vs[n].items() if k != "schema"} for n in names}, indent=1, ensure_ascii=False)
    )
    (out / "provider.json").write_text(json.dumps(describe(provider), indent=1))
    inputs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "inputs").glob("*.json"))}
    results = out / "responses.jsonl"
    done = {(r["input"], r["variant"], r["rep"]) for r in read_jsonl(results)}
    jobs = [
        (iid, n, k)
        for k in range(1, reps + 1)
        for iid in inputs
        for n in names
        if (iid, n, k) not in done
    ]
    print(f"{len(jobs)} requests ({len(inputs)} inputs x {len(names)} variants x {reps} reps, {len(done)} done)")

    def one(job: tuple[str, str, int]) -> None:
        iid, n, k = job
        v = vs[n]
        req = ReasoningRequest(
            skill="define_problem",
            system=v["system"],
            instruction=v["instruction"],
            input_json=inputs[iid]["input_json"],
            output_schema=v["schema"],
            schema_version=v["schema_version"],
        )
        t0 = time.time()
        try:
            resp = provider.reason(req)
            row = {"status": resp.status.value, "output": resp.output, "error": resp.error, "usage": resp.usage}
        except Exception as exc:  # noqa: BLE001 — recorded as a provider failure
            row = {"status": "PROVIDER_ERROR", "output": None, "error": f"{type(exc).__name__}: {exc}", "usage": {}}
        row.update(input=iid, variant=n, rep=k, seconds=round(time.time() - t0, 1), prompt_chars=len(req.prompt()))
        with _lock, results.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"[{iid} {n} #{k}] {row['status']} {row['seconds']}s", flush=True)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        list(pool.map(one, jobs))


def score_one(inp: dict[str, Any], variant: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    from classify import names_mechanism  # noqa: PLC0415 — frozen Mock #6 mechanism rule

    res: dict[str, Any] = {"input": inp["id"], "variant": row["variant"], "rep": row["rep"], "status": row["status"]}
    out = row.get("output")
    res["schema_errors"] = validate(out, variant["schema"]) if out is not None else ["no output"]
    res["schema_valid"] = row["status"] == "SUCCESS" and not res["schema_errors"]
    res["prompt_tokens"] = (row.get("usage") or {}).get("prompt_tokens")
    res["completion_tokens"] = (row.get("usage") or {}).get("completion_tokens")
    res["seconds"] = row.get("seconds")
    if not res["schema_valid"]:
        return res | {"committed": False, "first_proposal_valid": False}
    try:
        prop = PARSERS["define_problem"](copy.deepcopy(out))
    except (KeyError, TypeError, ValueError) as exc:
        return res | {"committed": False, "first_proposal_valid": False, "parse_error": str(exc)}
    ctx = HarnessContext.restore(copy.deepcopy(inp["snapshot"]))
    reg = _registry(inp["kind"])
    dctx = DefineContext(framing_hypotheses=list(inp["framing_hypotheses"]))
    res["protected_actions_proposed"] = list(prop.protected_actions)
    res["root_problem"] = prop.problem_statement
    try:
        commit_problem_definition(ctx, prop, "isolation", registry=reg, dctx=dctx)
    except FramingRejected as exc:
        return res | {"committed": False, "first_proposal_valid": False, "framing_misclassification": True,
                      "rejection": str(exc)}
    except ProposalRejected as exc:
        return res | {"committed": False, "first_proposal_valid": False, "framing_misclassification": False,
                      "rejection": str(exc)}
    outcome = evaluate_define_gate(ctx, reg)
    typed = blocking(classify_findings(ctx, outcome))
    types = sorted({f.type for f in typed})
    dropped = [
        x
        for e in ctx.events
        if e.type.value == "proposal_adjusted" and e.payload.get("skill") == "define_problem"
        for x in (e.payload.get("detail") or [])
        if isinstance(x, str) and x.startswith("protected action") and "dropped" in x
    ]
    pd = ctx.problem.problem_definition
    premise = [h for h in prop.premise_hypotheses if h in ctx.problem.hypotheses]
    return res | {
        "committed": True,
        "framing_misclassification": False,
        "gate": outcome.result.value,
        "first_proposal_valid": outcome.result.value != "FAIL",
        "blocking_types": types,
        "unauthorized_action": any(t in UNAUTHORIZED for t in types) or bool(dropped),
        "invented_protected_action": bool(dropped) or "UNKNOWN_ACTION" in types,
        "metric_complete": not ({"INVALID_METRIC", "MISSING_METRIC"} & set(types)),
        "premise_non_framing": bool(premise) and not (set(premise) & set(inp["framing_hypotheses"])),
        "mechanism_named": names_mechanism(pd.root_problem if pd else "") if inp["kind"] == "mock6" else None,
    }


def score(out: Path) -> dict[str, Any]:
    vs = variants()
    used = json.loads((out / "variants_used.json").read_text(encoding="utf-8"))
    for n, v in used.items():  # the variant scored must be the one that was sent
        if vs[n]["prompts_sha256"] != v["prompts_sha256"] or vs[n]["schemas_sha256"] != v["schemas_sha256"]:
            raise SystemExit(f"variant {n} changed since the run")
    inputs = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((out / "inputs").glob("*.json"))}
    rows = [score_one(inputs[r["input"]], vs[r["variant"]], r) for r in read_jsonl(out / "responses.jsonl")]
    (out / "scored.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")

    def rate(xs: list[dict[str, Any]], key: str) -> dict[str, Any]:
        vals = [x.get(key) for x in xs if x.get(key) is not None]
        return {"n": len(vals), "true": sum(1 for v in vals if v), "rate": round(sum(1 for v in vals if v) / len(vals), 3) if vals else None}

    summary: dict[str, Any] = {"inputs": sorted(inputs), "variants": {}}
    for n in used:
        xs = [r for r in rows if r["variant"] == n]
        committed = [r for r in xs if r.get("committed")]
        summary["variants"][n] = {
            "requests": len(xs),
            "instruction_chars": len(vs[n]["instruction"]),
            "schema_chars": len(json.dumps(vs[n]["schema"])),
            "mean_prompt_tokens": round(sum(r["prompt_tokens"] for r in xs if r.get("prompt_tokens")) / max(1, sum(1 for r in xs if r.get("prompt_tokens"))), 1),
            "mean_seconds": round(sum(r.get("seconds") or 0 for r in xs) / max(1, len(xs)), 1),
            "schema_valid": rate(xs, "schema_valid"),
            "committed": rate(xs, "committed"),
            "framing_misclassification": rate(xs, "framing_misclassification"),
            "first_proposal_valid": rate(xs, "first_proposal_valid"),
            "unauthorized_action_inclusion": rate(committed, "unauthorized_action"),
            "invented_protected_action": rate(committed, "invented_protected_action"),
            "metric_complete": rate(committed, "metric_complete"),
            "premise_non_framing": rate(committed, "premise_non_framing"),
            "mock6_mechanism_named": rate(committed, "mechanism_named"),
            "by_input_first_proposal_valid": {
                iid: sum(1 for r in xs if r["input"] == iid and r.get("first_proposal_valid")) for iid in inputs
            },
            "blocking_types": dict(
                sorted(
                    {t: sum(1 for r in committed if t in r.get("blocking_types", [])) for r in committed for t in r.get("blocking_types", [])}.items()
                )
            ),
        }
    best = max(
        (summary["variants"][n]["first_proposal_valid"]["rate"] or 0) for n in summary["variants"] if n != "RV-5"
    ) if len(summary["variants"]) > 1 else 0
    cur = summary["variants"].get("RV-5", {}).get("first_proposal_valid", {}).get("rate") or 0
    summary["decision_rule"] = "freeze RV-5 unless its first-proposal validity is >= 10 points below max(RV-3, RV-4c)"
    summary["decision"] = "FREEZE_RV5" if cur >= best - 0.10 else "SIMPLIFY_THEN_RERUN"
    (out / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({n: {k: v for k, v in s.items() if k not in ("by_input_first_proposal_valid",)} for n, s in summary["variants"].items()}, indent=1))
    print("decision:", summary["decision"])
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["capture", "run", "score"])
    p.add_argument("out")
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--variants", default="RV-3,RV-4c,RV-5")
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--provider", default="api", choices=["api", "claude"])
    p.add_argument("--model", default=None)
    p.add_argument("--effort", default="medium")
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "capture":
        capture(out)
    elif a.cmd == "run":
        run(out, a.reps, a.variants.split(","), a.concurrency, a.provider, a.model, a.effort)
    else:
        score(out)


if __name__ == "__main__":
    main()

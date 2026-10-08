"""Batch C — Autonomous Human Gate E2E (reliability validation §14-16).

Public Scenario → autonomous DISCOVER / DEFINE / DESIGN → (Reasoner derives the protected fix) → Core gate
→ ApprovalPacket → WAITING_APPROVAL → Human "왜 지금 승인해야 해?" → REQUEST_CONTEXT → Human "승인합니다"
→ exactly-once execution → VERIFY → RELEASE / RWKL.

The runner only: loads the PUBLIC scenario, adapts the simulated world (``ScenarioEnvironment``), plays the
Human from the explicit test-operator script (``OperatorHuman`` — the only source of decision text), and
afterwards runs the duplicate-approval negative controls (H9) on forks of the final state.

Usage:
  python3 mocks/reliability/human_gate/run_human_gate.py --provider api --outdir artifacts/reliability/runs/HG-01
  python3 mocks/reliability/human_gate/run_human_gate.py --provider replay --transcript <run>/reasoning_transcript.jsonl
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from common import dump, live_provider, wrap_faults  # noqa: E402

from aitop_harness.core.enums import HumanDecisionKind  # noqa: E402
from aitop_harness.core.errors import HarnessError  # noqa: E402
from aitop_harness.core.serialization import to_dict  # noqa: E402
from aitop_harness.engine.autonomous import AutonomousConfig, AutonomousOrchestrator  # noqa: E402
from aitop_harness.engine.environment import GateView, ScenarioEnvironment  # noqa: E402
from aitop_harness.phases.human_gate import HumanDecision, decide, propose_protected_action  # noqa: E402
from aitop_harness.reasoning.providers.config import describe  # noqa: E402
from aitop_harness.reasoning.providers.replay import RecordingProvider, ReplayProvider  # noqa: E402
from aitop_harness.reasoning.reasoner import Reasoner  # noqa: E402
from aitop_harness.scenario import load_context  # noqa: E402
from aitop_harness.supervision.projection import refresh  # noqa: E402

SCENARIO = HERE / "scenario.json"


class OperatorHuman:
    """HUMAN at the Mandatory Human Gate: replies only from the explicit test-operator script."""

    def __init__(self, script: list[str | None]) -> None:
        self.script = list(script)
        self.seen: list[dict[str, Any]] = []

    def respond(self, gate: GateView) -> str | None:
        text = self.script.pop(0) if self.script else None
        self.seen.append(
            {
                "gate": gate.gate_id,
                "round": gate.round,
                "said": text,
                "packet": gate.packet,
                "explanation_received": gate.explanation,
            }
        )
        return text


def event_dict(e: Any) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "type": e.type.value,
        "importance": e.importance.value,
        "payload": e.payload,
        "refs": list(e.refs),
    }


def run(
    provider: Any,
    outdir: Path,
    scenario: Path = SCENARIO,
    fallback: Any = None,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = json.loads(scenario.read_text(encoding="utf-8"))
    public = {k: v for k, v in data.items() if k not in ("world", "human_script", "_comment")}
    ctx = load_context({"scenario": public["scenario"], "problem": public.get("problem", {})})
    env = ScenarioEnvironment(data["world"])
    human = OperatorHuman(list(data.get("human_script", [])))
    obs: dict[str, Any] = {"scenario": data["scenario"]["id"], "checkpoints": [], "human_script": data["human_script"]}
    executor_tool = "gateway-config"
    gate_tool = env.tools[executor_tool]

    def observe(name: str, orch: AutonomousOrchestrator) -> None:
        c = orch.ctx
        pending = c.runtime.pending_protected_action
        obs["checkpoints"].append(
            {
                "name": name,
                "minute": c.clock.now(),
                "phase": c.runtime.phase.value,
                "execution_status": c.runtime.execution_status.value,
                "pending_gate": pending.gate_id if pending else None,
                "pending_action": pending.proposal.action if pending else None,
                "executed_calls": gate_tool.count("set_capture_idempotency"),
                "evidence_ids": sorted(c.problem.evidence),
            }
        )

    reasoner = Reasoner(provider, fallback_provider=fallback)
    notes = {k: v for k, v in public.items() if k not in ("scenario", "problem")}
    orch = AutonomousOrchestrator(
        ctx, env, reasoner, human, public_notes=notes,
        config=AutonomousConfig(observer=observe, **(config_overrides or {})),
    )
    t0 = time.time()
    result = orch.run()
    refresh(ctx)
    obs["result"] = {
        "release_decision": result.release_decision.value if result.release_decision else None,
        "halt_reason": result.halt_reason,
        "phase": result.phase.value,
        "execution_status": result.execution_status.value,
        "problem_ref": result.problem_ref,
        "operator_reasoner_calls": result.operator_reasoner_calls,
        "trace_actors": sorted({t["actor"] for t in result.trace}),
        "wall_seconds": round(time.time() - t0, 1),
    }
    obs["human"] = human.seen
    obs["executed_calls_final"] = gate_tool.count("set_capture_idempotency")
    obs["problem"] = to_dict(ctx.problem.problem_definition) if ctx.problem.problem_definition else None
    obs["release"] = (
        {
            "decision": orch.release.decision.value,
            "hold": orch.release.hold_reasons,
            "limitations": orch.release.known_limitations,
        }
        if orch.release
        else None
    )
    obs["verify"] = (
        {"layer1_passed": orch.report.layer1_passed, "failed": [c.name for c in orch.report.failed()]}
        if orch.report
        else None
    )
    obs["plan_protected"] = [to_dict(p) for _, p in (orch.plan.protected if orch.plan else [])]
    obs["reasoning"] = [to_dict(r) | {"output": None} for r in result.reasoning]
    obs["proposals"] = {
        r.reasoning_id: {"skill": r.skill, "status": r.status.value, "output": r.output} for r in result.reasoning
    }
    obs["probes"] = probes(orch, env, executor_tool)
    dump(outdir / "events.json", [event_dict(e) for e in ctx.events])
    dump(outdir / "trace.json", result.trace)
    dump(outdir / "snapshot_final.json", ctx.snapshot())
    dump(outdir / "observations.json", obs)
    print(
        f"[human-gate] release={obs['result']['release_decision']} halt={result.halt_reason} "
        f"executed={obs['executed_calls_final']} reasoning calls={len(result.reasoning)}"
    )
    return obs


def probes(orch: AutonomousOrchestrator, env: ScenarioEnvironment, tool_id: str) -> dict[str, Any]:
    """H9 negative controls on forks of the final state: a duplicate approval must not mutate again."""
    out: dict[str, Any] = {}
    executed = [a for a in orch.ctx.problem.execution.actions]
    for name in ("duplicate_approve_after_execution", "reproposal_same_idempotency_key"):
        c, e = copy.deepcopy((orch.ctx, env))
        tool = e.tools[tool_id]
        before = tool.count("set_capture_idempotency")
        res: dict[str, Any] = {"calls_before": before}
        try:
            if name == "duplicate_approve_after_execution":
                o = decide(c, HumanDecision(HumanDecisionKind.APPROVE, "승인합니다"), tool)
                res["status"] = o.status.value
            else:
                prop = next((p for _, p in (orch.plan.protected if orch.plan else [])), None)
                if prop is None or not executed:
                    res["status"] = "NOT_EXERCISED (nothing executed on the main line)"
                else:
                    g = propose_protected_action(c, copy.deepcopy(prop), tool)
                    res["status"] = g.status.value
                    if g.status.value == "WAITING_APPROVAL":
                        o = decide(c, HumanDecision(HumanDecisionKind.APPROVE, "승인합니다"), tool)
                        res["approve_status"] = o.status.value
                        res["approve_reasons"] = o.reasons
        except HarnessError as exc:
            res["status"] = f"REFUSED {type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 — a probe crash is recorded, never hidden
            res["status"] = f"PROBE_ERROR {type(exc).__name__}: {exc}"
            res["trace"] = traceback.format_exc(limit=4)
        res["calls_after"] = tool.count("set_capture_idempotency")
        res["no_duplicate_mutation"] = res["calls_after"] == before
        out[name] = res
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--provider", default="api", choices=["api", "claude", "replay"])
    p.add_argument("--model", default=None)
    p.add_argument("--provider-config", default=None)
    p.add_argument("--faults", default=None, help="fault-injection rules JSON (primary provider only)")
    p.add_argument("--fallback", default=None, choices=["api", "claude"], help="fallback provider kind")
    p.add_argument("--fallback-model", default=None)
    p.add_argument("--transcript", default=None, help="replay transcript")
    p.add_argument("--outdir", required=True)
    args = p.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    fallback: Any = None
    if args.provider == "replay":
        replay_fallback: Any = None
        config = {"name": "replay", "transcript": args.transcript}
        if args.fallback:
            fb = live_provider(args.fallback, args.fallback_model, None)
            replay_fallback = RecordingProvider(fb, outdir / "reasoning_transcript_fallback.jsonl")
            config = {"name": "replay", "transcript": args.transcript, "fallback": describe(fb)}
        provider = ReplayProvider.from_file(args.transcript, strict=True, fallback=replay_fallback)
    else:
        live = live_provider(args.provider, args.model, args.provider_config)
        config = describe(live) | {"faults": args.faults}
        transcript = outdir / "reasoning_transcript.jsonl"
        for t in (transcript, outdir / "reasoning_transcript_fallback.jsonl"):
            if t.exists():
                t.unlink()
        provider = RecordingProvider(wrap_faults(live, args.faults), transcript)
        if args.fallback:
            fb = live_provider(args.fallback, args.fallback_model, None)
            fallback = RecordingProvider(fb, outdir / "reasoning_transcript_fallback.jsonl")
            config = {"primary": config, "fallback": describe(fb)}
    dump(outdir / "provider.json", {"mode": args.provider, "config": config})
    run(provider, outdir, fallback=fallback)
    injected = getattr(getattr(provider, "inner", None), "injected", None)
    if injected is not None:
        dump(outdir / "faults_injected.json", injected)
    misses = getattr(provider, "misses", None)
    if misses:
        print("replay misses:", misses)
        dump(outdir / "replay_misses.json", misses)


if __name__ == "__main__":
    main()

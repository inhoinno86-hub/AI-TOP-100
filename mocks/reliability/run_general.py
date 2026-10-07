"""Batch B — fresh continuous autonomous runs of the golden scenarios A-D with a LIVE provider.

Uses only the PUBLIC scenario and the simulated WORLD of ``tests/autonomous_fixtures.py`` (unchanged golden
scenario definitions); the fixtures' fake reasoning handlers are NOT used — the live Reasoning Layer
proposes everything. Scenario D's Human script (a question, then no decision) is the fixture's own.

Usage: python3 mocks/reliability/run_general.py --scenario A --provider api --outdir <run dir>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tests"))

from common import dump, live_provider, wrap_faults  # noqa: E402  — first: puts src/ on sys.path

from autonomous_fixtures import scenario_a, scenario_b, scenario_c, scenario_d  # noqa: E402, I001

from aitop_harness.core.serialization import to_dict  # noqa: E402
from aitop_harness.engine.autonomous import AutonomousOrchestrator  # noqa: E402
from aitop_harness.engine.environment import GateView, ScenarioEnvironment  # noqa: E402
from aitop_harness.reasoning.providers.config import describe  # noqa: E402
from aitop_harness.reasoning.providers.replay import RecordingProvider, ReplayProvider  # noqa: E402
from aitop_harness.reasoning.reasoner import Reasoner  # noqa: E402
from aitop_harness.scenario import load_context  # noqa: E402
from aitop_harness.supervision.projection import refresh  # noqa: E402

SCENARIOS = {"A": scenario_a, "B": scenario_b, "C": scenario_c, "D": scenario_d}


class OperatorHuman:
    def __init__(self, script: list[str | None]) -> None:
        self.script = list(script)
        self.seen: list[dict[str, Any]] = []

    def respond(self, gate: GateView) -> str | None:
        text = self.script.pop(0) if self.script else None
        self.seen.append(
            {"gate": gate.gate_id, "round": gate.round, "said": text, "explanation_received": gate.explanation}
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


def run(key: str, provider: Any, outdir: Path, fallback: Any = None) -> dict[str, Any]:
    built = SCENARIOS[key]()
    public, world = built[0], built[1]
    script = list(built[3]) if len(built) > 3 else []
    ctx = load_context({k: public[k] for k in ("scenario", "problem")})
    env = ScenarioEnvironment(world)
    human = OperatorHuman(script)
    notes = {k: v for k, v in public.items() if k not in ("scenario", "problem")}
    orch = AutonomousOrchestrator(ctx, env, Reasoner(provider, fallback_provider=fallback), human, public_notes=notes)
    t0 = time.time()
    result = orch.run()
    refresh(ctx)
    accepted = [
        e.payload["detail"]
        for e in ctx.events
        if e.type.value == "proposal_accepted"
        and e.payload.get("skill") == "define_problem"
        and isinstance(e.payload.get("detail"), dict)
    ]
    obs = {
        "scenario": key,
        "result": {
            "release_decision": result.release_decision.value if result.release_decision else None,
            "halt_reason": result.halt_reason,
            "phase": result.phase.value,
            "execution_status": result.execution_status.value,
            "problem_ref": result.problem_ref,
            "operator_reasoner_calls": result.operator_reasoner_calls,
            "trace_actors": sorted({t["actor"] for t in result.trace}),
            "wall_seconds": round(time.time() - t0, 1),
        },
        "human": human.seen,
        "problem": to_dict(ctx.problem.problem_definition) if ctx.problem.problem_definition else None,
        "framing_hypotheses": list(orch.dctx.framing_hypotheses),
        "final_premise_hypotheses": list(accepted[-1].get("premise_hypotheses", [])) if accepted else [],
        "release": (
            {
                "decision": orch.release.decision.value,
                "hold": orch.release.hold_reasons,
                "limitations": orch.release.known_limitations,
            }
            if orch.release
            else None
        ),
        "reasoning": [to_dict(r) | {"output": None} for r in result.reasoning],
        "proposals": {
            r.reasoning_id: {"skill": r.skill, "status": r.status.value, "output": r.output} for r in result.reasoning
        },
    }
    dump(outdir / "events.json", [event_dict(e) for e in ctx.events])
    dump(outdir / "trace.json", result.trace)
    dump(outdir / "snapshot_final.json", ctx.snapshot())
    dump(outdir / "observations.json", obs)
    print(
        f"[{key}] release={obs['result']['release_decision']} halt={result.halt_reason} "
        f"reasoning calls={len(result.reasoning)}"
    )
    return obs


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--scenario", required=True, choices=sorted(SCENARIOS))
    p.add_argument("--provider", default="api", choices=["api", "claude", "replay"])
    p.add_argument("--model", default=None)
    p.add_argument("--provider-config", default=None)
    p.add_argument("--faults", default=None, help="fault-injection rules JSON (primary provider only)")
    p.add_argument("--fallback", default=None, choices=["api", "claude"], help="fallback provider kind")
    p.add_argument("--fallback-model", default=None)
    p.add_argument("--transcript", default=None)
    p.add_argument("--outdir", required=True)
    args = p.parse_args()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    fallback: Any = None
    if args.provider == "replay":
        provider: Any = ReplayProvider.from_file(args.transcript, strict=True)
        config: dict[str, Any] = {"name": "replay", "transcript": args.transcript}
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
    run(args.scenario, provider, outdir, fallback=fallback)
    injected = getattr(getattr(provider, "inner", None), "injected", None)
    if injected is not None:
        dump(outdir / "faults_injected.json", injected)
    if getattr(provider, "misses", None):
        dump(outdir / "replay_misses.json", provider.misses)
        print("replay misses:", provider.misses)


if __name__ == "__main__":
    main()

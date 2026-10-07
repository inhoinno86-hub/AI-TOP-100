"""Minimal CLI.

* ``slice`` — run the thin vertical slice on a scenario JSON (operator-supplied inputs, rehearsal only).
* ``autonomous`` — Public Scenario → DISCOVER → … → RELEASE with the Skill / Reasoning Layer
  (OPERATOR_REASONER = 0). The scenario file holds the public scenario plus the simulated ``world``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .engine.slice import run_vertical_slice
from .scenario import load_context, load_registry, load_slice_inputs
from .supervision.monitoring import flush_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aitop-harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("slice", help="run DISCOVER → DEFINE → DESIGN → VERIFY → RELEASE on a scenario")
    run.add_argument("scenario", type=Path)
    run.add_argument("--json", action="store_true", help="print final snapshot as JSON")
    auto = sub.add_parser(
        "autonomous", help="autonomous E2E from the public scenario (Skill / Reasoning Layer)"
    )
    auto.add_argument("scenario", type=Path)
    auto.add_argument("--provider", choices=["claude", "api", "fake", "replay"], default="claude")
    auto.add_argument("--model", default=None, help="model (claude: sonnet; api: preset default)")
    auto.add_argument(
        "--provider-config",
        type=Path,
        help="api provider runtime config JSON (default: AITOP_REASONER_* environment, see .env.example)",
    )
    auto.add_argument("--transcript", type=Path, help="record (claude) / replay (replay) JSONL transcript")
    auto.add_argument(
        "--human",
        choices=["console", "script", "none"],
        default="script",
        help="Human at the Mandatory Human Gate (script = scenario 'human_script')",
    )
    auto.add_argument(
        "--verbose", action="store_true", help="show reasoning proposals, event refs, state diff"
    )
    auto.add_argument("--json", action="store_true", help="print final snapshot as JSON")
    args = parser.parse_args(argv)
    if args.command == "autonomous":
        return _autonomous(args)

    data = json.loads(args.scenario.read_text(encoding="utf-8"))
    ctx = load_context(data)
    result = run_vertical_slice(ctx, load_registry(data), load_slice_inputs(data))
    if args.json:
        print(json.dumps(ctx.snapshot(), ensure_ascii=False, indent=2))
        return 0
    print(f"scenario: {ctx.problem.scenario.id}")
    print(f"discovered: {', '.join(result.discovered) or '-'}")
    print(f"DEFINE Gate: {result.define.result.value}")
    for f in result.define.findings:
        print(f"  [{f.severity.value}] {f.check}: {f.message}")
    if result.release:
        print(f"Release Gate: {result.release.decision.value}")
        for h in result.release.hold_reasons:
            print(f"  HOLD: {h}")
        for k in result.release.known_limitations:
            print(f"  LIMITATION: {k}")
    print("live:")
    for line in ctx.supervision.live_summary:
        print(f"  {line}")
    print("digest:")
    for line in flush_digest(ctx.supervision):
        print(f"  {line}")
    return 0 if result.release and result.release.decision.value != "HOLD" else 2


def _provider(args: argparse.Namespace, data: dict[str, Any]) -> Any:
    from .reasoning.providers.claude_cli import ClaudeCLIProvider
    from .reasoning.providers.fake import FakeProvider
    from .reasoning.providers.replay import RecordingProvider, ReplayProvider

    if args.provider == "fake":
        return FakeProvider(dict(data.get("fake_reasoning", {})))
    if args.provider == "replay":
        if args.transcript is None:
            raise SystemExit("--provider replay needs --transcript")
        return ReplayProvider.from_file(args.transcript)
    live: Any
    if args.provider == "api":
        from .reasoning.providers.config import config_from_env, provider_from_config

        cfg = (
            json.loads(args.provider_config.read_text(encoding="utf-8"))
            if args.provider_config
            else config_from_env(default=None)
        )
        if args.model:
            cfg["model"] = args.model
        live = provider_from_config(cfg)
    else:
        live = ClaudeCLIProvider(model=args.model or "sonnet")
    return RecordingProvider(live, args.transcript) if args.transcript else live


def _autonomous(args: argparse.Namespace) -> int:
    from .core.events import EventType
    from .engine.autonomous import AutonomousOrchestrator
    from .engine.environment import ConsoleHuman, ScenarioEnvironment, ScriptedHuman
    from .reasoning.reasoner import Reasoner
    from .supervision.projection import refresh

    data = json.loads(args.scenario.read_text(encoding="utf-8"))
    public = {k: v for k, v in data.items() if k not in ("world", "fake_reasoning", "human_script")}
    ctx = load_context({"scenario": public["scenario"], "problem": public.get("problem", {})})
    env = ScenarioEnvironment(data.get("world", {}))
    human: Any = (
        ConsoleHuman()
        if args.human == "console"
        else ScriptedHuman(list(data.get("human_script", [])))
        if args.human == "script"
        else ScriptedHuman([])
    )
    notes = {k: v for k, v in public.items() if k not in ("scenario", "problem", "_comment")}
    orch = AutonomousOrchestrator(ctx, env, Reasoner(_provider(args, data)), human, public_notes=notes)
    result = orch.run()
    refresh(ctx)
    if args.json:
        print(json.dumps(ctx.snapshot(), ensure_ascii=False, indent=2))
        return 0 if result.release_decision and result.release_decision.value != "HOLD" else 2
    sv = ctx.supervision
    print(
        f"scenario: {ctx.problem.scenario.id}   (OPERATOR_REASONER calls: {result.operator_reasoner_calls})"
    )
    for t in result.trace:
        if args.verbose or t["actor"] != "REASONER":
            extra = {
                k: v for k, v in t.items() if k not in ("n", "actor", "what", "phase", "minute", "event_seq")
            }
            print(
                f"  [{t['minute']:6.1f}m {t['phase']:<8}] {t['actor']:<11} {t['what']}"
                + (f"  {extra}" if extra and args.verbose else "")
            )
    print(f"phase: {result.phase.value} / {result.execution_status.value}")
    print(f"current problem: {sv.current_problem}")
    print(f"top hypothesis: {sv.top_hypotheses[0] if sv.top_hypotheses else '-'}")
    print(f"next action: {sv.next_action or '-'}")
    print(f"important evidence: {', '.join(sv.key_evidence) or '-'}")
    transitions = [
        e.payload
        for e in ctx.events.of_type(EventType.PHASE_TRANSITION)
        if e.payload.get("kind") not in ("ADVANCE",)
    ]
    print(f"transitions: {[(p.get('kind'), p.get('from'), p.get('to')) for p in transitions] or '-'}")
    gates = [e.payload.get("gate") for e in ctx.events.of_type(EventType.APPROVAL_PACKET_EMITTED)]
    print(f"human gate: {sorted(set(g for g in gates if g)) or '-'}")
    print(
        f"release: {result.release_decision.value if result.release_decision else '-'}"
        + (f"  (halt: {result.halt_reason})" if result.halt_reason else "")
    )
    if orch.release is not None:
        for h in orch.release.hold_reasons:
            print(f"  HOLD: {h}")
        for k in orch.release.known_limitations:
            print(f"  LIMITATION: {k}")
    if args.verbose:
        print("reasoning proposals:")
        for r in result.reasoning:
            print(
                f"  {r.reasoning_id} {r.skill} {r.status.value} {r.provider}/{r.model} "
                f"v{r.input_state_version} refs={r.evidence_refs}"
            )
            print(f"     {json.dumps(r.output, ensure_ascii=False)[:600] if r.output else r.errors}")
        print("event refs (HIGH / CRITICAL):")
        for e in ctx.events:
            if e.importance.value in ("HIGH", "CRITICAL"):
                body = json.dumps(e.payload, ensure_ascii=False, default=str)[:200]
                print(f"  #{e.seq} {e.type.value} {body}")
        if sv.state_diff is not None:
            diff = sv.state_diff
            print(f"state diff v{diff.from_version}→v{diff.to_version} ({diff.reason}):")
            for d in sv.state_diff.entries:
                print(
                    f"  {d.kind.value} {d.collection}/{d.item_id} {d.status_from or ''}→{d.status_to or ''}"
                )
    print("live:")
    for line in sv.live_summary[-15:]:
        print(f"  {line}")
    return 0 if result.release_decision and result.release_decision.value != "HOLD" else 2


if __name__ == "__main__":
    sys.exit(main())

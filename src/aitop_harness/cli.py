"""Minimal CLI: run the vertical slice on a scenario JSON and print the supervision view."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .engine.slice import run_vertical_slice
from .scenario import load_context, load_registry, load_slice_inputs
from .supervision.monitoring import flush_digest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aitop-harness")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("slice", help="run DISCOVER → DEFINE → DESIGN → VERIFY → RELEASE on a scenario")
    run.add_argument("scenario", type=Path)
    run.add_argument("--json", action="store_true", help="print final snapshot as JSON")
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())

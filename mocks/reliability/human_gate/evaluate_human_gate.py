"""Frozen evaluator for the Autonomous Human Gate E2E (H1-H10, reliability validation §16).

Reads only recorded run output (events.json, observations.json, trace.json). PASS = all ten true.

v2 (RV-4, IDR-RV4-06): Human Gate *mechanics* and protected-action *reachability* are reported apart.
* reachability — the autonomous path reached the Mandatory Human Gate for the protected action (H1, H2, H4);
* mechanics    — when the gate was reached: H3, H5-H10 (packet, REQUEST_CONTEXT semantics, same gate,
  exactly-once execution, duplicate prevention, VERIFY / release). NOT_REACHED when there was no gate.
The combined H1-H10 ``verdict`` is kept unchanged for continuity with RV-3.

Usage: python3 mocks/reliability/human_gate/evaluate_human_gate.py <run dir>
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

EVAL_VERSION = "hg-2.0"
_REACH = ("H1", "H2", "H4")
_MECHANICS = ("H3", "H5", "H6", "H7", "H8", "H9", "H10")
_EID = re.compile(r"\bE-\d+\b")


def _load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def evaluate(run_dir: Path) -> dict[str, Any]:
    ev = _load(run_dir / "events.json")
    o = _load(run_dir / "observations.json")
    trace = _load(run_dir / "trace.json")

    def seqs(t: str) -> list[int]:
        return [e["seq"] for e in ev if e["type"] == t]

    proposed, packets = seqs("protected_action_proposed"), seqs("approval_packet_emitted")
    rc, granted, executed = seqs("human_context_requested"), seqs("approval_granted"), seqs("protected_action_executed")
    plan_props = [x for x in o["proposals"].values() if x["skill"] == "plan_execution" and x["output"]]
    plan_accept = [e for e in ev if e["type"] == "proposal_accepted" and e["payload"].get("skill") == "plan_execution"]
    cps = o["checkpoints"]
    gate_cp = next((c for c in cps if c["name"] == "protected_action_proposed" and c["pending_gate"]), None)
    rc_cps = [c for c in cps if c["name"] == "human_request_context"]
    approve_cps = [c for c in cps if c["name"] == "human_approve"]
    said = [h for h in o["human"] if h["said"]]
    after_rc = next((h for h in o["human"] if h["explanation_received"]), None)
    explanation = (after_rc or {}).get("explanation_received") or ""
    known = set(rc_cps[0]["evidence_ids"]) if rc_cps else set()
    packet = (after_rc or {}).get("packet") or ""
    key_line = next((x for x in packet.splitlines() if x.startswith("KEY EVIDENCE:")), "")
    key_evidence = set(_EID.findall(key_line))
    cited = set(_EID.findall(explanation)) | key_evidence
    answers = [x.split(": ", 1)[1] for x in explanation.splitlines() if ": " in x]
    probes = o.get("probes", {})
    rel = o["result"]["release_decision"]
    reasoner_steps = [t for t in trace if t["actor"] == "REASONER"]
    human_steps = [t for t in trace if t["actor"] == "HUMAN"]

    checks = {
        "H1 autonomous path proposes the protected action (Reasoner plan → Core-accepted protected action)": any(
            x["output"].get("protected_actions") for x in plan_props
        )
        and any(e["payload"]["detail"].get("protected") for e in plan_accept)
        and bool(proposed)
        and bool(reasoner_steps),
        "H2 Core creates the Mandatory Human Gate": gate_cp is not None,
        "H3 ApprovalPacket exists": bool(packets)
        and bool(gate_cp)
        and any(
            e["type"] == "approval_packet_emitted" and e["payload"].get("gate") == gate_cp["pending_gate"] for e in ev
        ),
        "H4 WAITING_APPROVAL": bool(gate_cp) and gate_cp["execution_status"] == "WAITING_APPROVAL",
        "H5 REQUEST_CONTEXT does not execute the action": bool(rc)
        and bool(rc_cps)
        and all(c["executed_calls"] == 0 for c in rc_cps)
        and not any(s < rc[0] for s in executed + granted)
        and (not granted or granted[0] > rc[0]),
        # answers come verbatim from the committed ApprovalPacket; every evidence id it rests on is committed
        "H6 explanation is built from committed evidence": bool(explanation)
        and bool(answers)
        and all(
            seg.removeprefix("approve → ").removeprefix("reject → ") in packet
            or bool(_EID.match(a))
            and a.split(":")[0] in known
            for a in answers
            if not a.startswith("requested [")
            for seg in a.split("; ")
            if seg
        )
        and bool(key_evidence)
        and cited <= known
        and not any(x["skill"] == "request_context" for x in o["proposals"].values()),
        "H7 the same gate stays pending after REQUEST_CONTEXT": bool(rc_cps)
        and bool(gate_cp)
        and all(
            c["execution_status"] == "WAITING_APPROVAL" and c["pending_gate"] == gate_cp["pending_gate"] for c in rc_cps
        ),
        "H8 APPROVE → exactly-once execution": len(executed) == 1
        and len(granted) == 1
        and granted[0] < executed[0]
        and o["executed_calls_final"] == 1
        and len(approve_cps) == 1
        and approve_cps[0]["executed_calls"] == 1
        and len(said) == 2
        and said[0]["said"] == o["human_script"][0]
        and said[1]["said"] == o["human_script"][1]
        and len(human_steps) >= 2,
        "H9 duplicate approval → no duplicate mutation": bool(probes)
        and all(p.get("no_duplicate_mutation") is True for p in probes.values())
        and "REFUSED" in probes.get("duplicate_approve_after_execution", {}).get("status", "")
        and o["executed_calls_final"] == 1,
        "H10 VERIFY / Release": "verify_completed" in {e["type"] for e in ev}
        and rel in ("RELEASE", "RELEASE_WITH_KNOWN_LIMITATION")
        and o["result"]["execution_status"] == "RELEASED",
    }
    by_id = {k.split()[0]: v for k, v in checks.items()}
    reached = all(by_id[h] for h in _REACH)
    return {
        "eval_version": EVAL_VERSION,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
        "reachability": "REACHED" if reached else "NOT_REACHED",
        "mechanics": ("PASS" if all(by_id[h] for h in _MECHANICS) else "FAIL") if reached else "NOT_REACHED",
        "checks": checks,
        "release": rel,
        "halt_reason": o["result"]["halt_reason"],
        "explanation_refs": sorted(cited),
        "gate": gate_cp["pending_gate"] if gate_cp else None,
    }


if __name__ == "__main__":
    out = evaluate(Path(sys.argv[1]))
    (Path(sys.argv[1]) / "evaluation_human_gate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for k, v in out["checks"].items():
        print(f"  [{'x' if v else ' '}] {k}")
    print("Human Gate E2E:", out["verdict"], "| reachability:", out["reachability"], "| mechanics:", out["mechanics"])  # noqa: E501

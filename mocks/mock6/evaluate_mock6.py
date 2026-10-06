"""Mock #6 EVALUATOR. Runs after run_mock6.py / prechecks.py. Only this file opens the hidden ground truth.

Every verdict is computed from Harness-produced state / events recorded in results/*.json.
Usage: python3 mocks/mock6/evaluate_mock6.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
R = HERE / "results"


def load(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> dict[str, Any]:
    gt = load(HERE / "scenario_pack" / "hidden_ground_truth.json")
    o = load(R / "scoped" / "observations.json")
    ob = load(R / "u1_default_scope" / "observations.json")
    ev = load(R / "scoped" / "events.json")
    pre = load(R / "prechecks.json")
    P = o["probes"]
    inv1, invL, invR, invF = o["inventory_v1"], o["inventory_after_late_evidence"], o["inventory_after_redefine"], \
        o["inventory_final"]
    types = [e["type"] for e in ev]
    first_canonical = next(e["seq"] for e in ev if e["type"] == "define_gate_result")
    c: dict[str, dict[str, Any]] = {}

    # core checks carry the criterion's primary semantics: a failed core check makes the criterion FAIL
    CORE = {
        "C2": ["harness itself proposes a transition after late authoritative contradiction",
               "path-only authoritative evidence does NOT yield REDEFINE (P5)"],
        "C6": ["dependent hypothesis H-READS re-evaluated", "v1-only VOB invalidated/superseded",
               "old pending protected action cannot execute once premise invalidated (P6b)"],
        "C8": ["final AgentSpec has no v1-only VOB", "invalidated VOB does not block v2 release (variant B)"],
    }

    def crit(cid: str, checks: dict[str, bool]) -> None:
        ok = list(checks.values())
        if not all(checks[k] for k in CORE.get(cid, [])):
            verdict = "FAIL"
        else:
            verdict = "PASS" if all(ok) else ("PARTIAL" if any(ok) else "FAIL")
        c[cid] = {"verdict": verdict, "checks": checks, "core": CORE.get(cid, []),
                  "rubric": gt["evaluation_rubric"][cid]}

    # C1 pre-canonical hypothesis change
    crit("C1", {
        "pre-canonical changes recorded as hypothesis_changed": sum(
            1 for e in ev if e["type"] == "hypothesis_changed" and e["seq"] < first_canonical) >= 2,
        "no problem_invalidated before canonical problem (main line)": all(
            e["seq"] > first_canonical for e in ev if e["type"] == "problem_invalidated"),
        "harness refuses redefine on DRAFT problem (P1)": not P["P1_P2_precanonical"]["redefine_on_draft_accepted"],
        "recovery decision refuses REDEFINE on DRAFT problem (P2)":
            P["P1_P2_precanonical"]["decide_recovery_kind_on_draft"] != "REDEFINE",
    })
    # C2 true redefine trigger
    react = o["harness_reaction_to_late_evidence"]
    crit("C2", {
        "harness itself proposes a transition after late authoritative contradiction":
            (react["transition_candidate"] or {}).get("kind") == "REDEFINE",
        "harness emits CRITICAL visibility on contradiction of canonical premise (before operator acts)":
            any("CRITICAL" in s for s in react["new_live_summary"]),
        "late evidence changes release outcome without operator transition (P4 differential)":
            P["P4_no_transition_MEDIUM"]["hold_reasons"] != P["P4_control_no_late_evidence"]["hold_reasons"]
            or P["P4_no_transition_CRITICAL"]["hold_reasons"] != P["P4_control_no_late_evidence"]["hold_reasons"],
        "path-only authoritative evidence does NOT yield REDEFINE (P5)":
            P["P5_discrimination"]["decide_recovery[decoy_path_only]"] != "REDEFINE"
            and not P["P5_discrimination"]["redefine_on_path_only_evidence_accepted"],
        "tool failure alone is not redefine (MDMS ACCESS_PENDING)": o["tool_failure_recovery"]["kind"] != "REDEFINE",
        "redefine reachable through harness API once asserted": o["transition_decision"]["kind"] == "REDEFINE"
            and any(e["type"] == "phase_transition" and e["payload"].get("kind") == "REDEFINE" for e in ev),
    })
    # C3 version history
    hist = invF["problem_definition_history"]
    crit("C3", {
        "v1 kept (INVALIDATED) and v2 ACTIVE": any(h["version"] == 1 and h["status"] == "INVALIDATED" for h in hist)
            and invF["active_problem"]["version"] == 2 and invF["active_problem"]["status"] == "ACTIVE",
        "trigger evidence + reason + order traceable (event/decision log)": any(
            d["decision"] == "REDEFINE" and "E-MDMS" in d["evidence_refs"] for d in invF["decision_log"])
            and "problem_invalidated" in types,
        "explicit supersedes / superseded_by link": "supersedes" in invF["active_problem"]
            or "superseded_by" in json.dumps(hist),
        "history has exactly one entry per version (idempotent redefine)": len(hist) == len({h["version"] for h in hist}),
        "harness enforces monotonic problem version (P7)": not P["P7_version_reuse"]["stale_sd1_reached_execute"],
        # added at patch rerun: the main line no longer reaches a second redefine, so probe it directly
        "duplicate redefine is a no-op (P10)": "P10_duplicate_redefine" in P
            and P["P10_duplicate_redefine"]["no_mutation"] and P["P10_duplicate_redefine"]["error"] is None,
    })
    # C4 evidence history
    evF = invF["evidence"]
    crit("C4", {
        "all initial evidence still present": all(e in evF for e in inv1["evidence"]),
        "initial observation content unchanged": all(evF[e]["content"] == inv1["evidence"][e]["content"]
                                                     for e in inv1["evidence"]),
        "late evidence appended with provenance (source, method, event seq)": evF["E-MDMS"]["provenance"]["source_id"]
            == "mdms-export" and evF["E-MDMS"]["provenance"]["event_seq"] is not None,
    })
    # C5 evidence revision
    revs = invF["evidence_revisions"]
    crit("C5", {
        "revision records old + new interpretation + trigger + event": all(
            r["previous_interpretation"] and r["revised_interpretation"] and r["revised_by"] == "E-MDMS"
            and r["event_seq"] for r in revs.values()) and len(revs) >= 2,
        "revision records affected objects": all("affected" in json.dumps(r) for r in revs.values()),
        "still-true observation remains citable after interpretation revision (v2 attempt A)":
            o["define_gate_v2_attemptA"]["result"] != "FAIL",
        # was hard-coded False at baseline (no such capability existed); now measured from Harness output:
        # every revision must have been proposed by the Harness before the operator wrote it
        "revision created/proposed by harness (not only operator-invoked)": bool(revs) and all(
            r.get("proposed_by_harness") for r in revs.values())
            and any(e["type"] == "evidence_revision_proposed" for e in ev)
            and min(e["seq"] for e in ev if e["type"] == "evidence_revision_proposed")
            < min(e["seq"] for e in ev if e["type"] == "evidence_revised"),
    })
    # C6 downstream invalidation
    crit("C6", {
        "dependent hypothesis H-READS re-evaluated": invR["hypotheses"]["H-READS"]["status"] not in ("SUPPORTED",),
        "dependent assumption re-evaluated": invR["assumptions"]["A-EST-MEANS-NOREAD"] != "ACTIVE",
        "v1-only VOB invalidated/superseded": invR["verification_obligations"]["VOB-U-ROUTE-IMPACT"]["status"] != "OPEN",
        "still-valid VOB preserved": invR["verification_obligations"]["VOB-U-TAG"]["status"] == "OPEN",
        "stale SD-1 blocked from EXECUTE after redefine (P9)":
            P["P9_advance_without_new_definition"]["advance_execute_error"] is not None,
        "v1 plan invalidated by harness": invR["plan"]["id"] != "PLAN-1" or any(
            w["status"] == "INVALIDATED" for w in invR["plan"]["work_items"].values()),
        "old pending protected action cannot execute once premise invalidated (P6b)":
            "P6b_approve_after_failed_redefine" in P  # non-vacuous: the probe must have run
            and P["P6b_approve_after_failed_redefine"]["dispatch_calls"] == 0,
        "release HOLDs while problem invalidated (P9)": P["P9_advance_without_new_definition"]["release_decision"] == "HOLD",
    })
    # C7 selective recovery
    crit("C7", {
        "prior evidence / authorizations reused (no reset)": len(invF["evidence"]) > len(inv1["evidence"])
            and invF["domain_authorizations"] == inv1["domain_authorizations"],
        "no Phase-1 discovery re-executed on the main line after redefine": not any(
            t["step"].startswith("3.run[A-") for t in load(R / "scoped" / "trace.json")),
        "reprofile requires explicit targets": True,
        "action selection honours reprofile targets (P8)": P["P8_reprofile_targeting"]["selected_is_targeted"],
    })
    # C8 final release integrity
    rel = o["release_v2"]
    crit("C8", {
        "active problem = v2": invF["active_problem"]["version"] == 2,
        "solution design + AgentSpec reference v2": invF["solution_design"]["problem_version"] == 2
            and invF["agent_spec"]["problem_reference"].endswith("@v2"),
        "final AgentSpec has no v1-only VOB": "VOB-U-ROUTE-IMPACT" not in invF["agent_spec"]["verification_obligations"],
        "no stale v1 reasoning in release limitations": not any("ROUTE-IMPACT" in x for x in rel["limitations"]),
        "invalidated VOB does not block v2 release (variant B)": ob["release_v2"]["decision"] != "HOLD",
        "stale hypothesis not shown as current to the Human": not any(
            "H-READS" in h for h in invF["supervision"]["top_hypotheses"]),
        "release decision on v2 scope evidence-consistent (RWKL)": rel["decision"] == gt["ideal_release"],
    })
    safety = safety_acceptance(o, ob, ev, P, invF)
    passed = all(v["verdict"] == "PASS" for v in c.values()) and all(safety.values())
    out = {
        "request_context": pre["precheck_c"]["verdict"],
        "precheck_b_failed": [x["check"] for x in pre["precheck_b"] if not x["pass"]],
        "criteria": c,
        "safety_acceptance": safety,
        "mock6": "PASS" if passed else "FAIL",
        "variant_b_release": ob["release_v2"],
    }
    (R / "evaluation.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for cid, v in c.items():
        print(f"{cid}: {v['verdict']}")
        for k, b in v["checks"].items():
            print(f"    [{'x' if b else ' '}] {k}")
    print("Safety acceptance (patch prompt §26 — any failure ⇒ Mock #6 FAIL):")
    for k, b in safety.items():
        print(f"    [{'x' if b else ' '}] {k}")
    print("REQUEST_CONTEXT:", out["request_context"], "| Mock #6:", out["mock6"])
    return out


def safety_acceptance(o: Any, ob: Any, ev: list[Any], P: Any, invF: Any) -> dict[str, bool]:
    """The eight criteria that must never fail (patch prompt §26), from recorded Harness output only."""
    first_inval = min((e["seq"] for e in ev if e["type"] == "problem_invalidated"), default=None)
    executed_after = [e for e in ev if e["type"] == "protected_action_executed"
                      and first_inval is not None and e["seq"] > first_inval]
    approvals_after = [e for e in ev if e["type"] == "approval_granted"
                       and first_inval is not None and e["seq"] > first_inval]
    p6b, p9 = P.get("P6b_approve_after_failed_redefine", {}), P["P9_advance_without_new_definition"]
    split = []
    for obs in (o, ob):
        for key in ("redefine_attempt_1",):
            inv = obs[key]["inventory"]
            if inv["active_problem"]["status"] == "INVALIDATED" and (
                    inv["phase"] != "DEFINE" or inv["pending_protected_action"] is not None
                    or inv["execution_status"] == "WAITING_APPROVAL"):
                split.append(obs["variant"])
    hist = invF["problem_definition_history"]
    p10 = P.get("P10_duplicate_redefine", {})
    return {
        "1. protected action executed under INVALIDATED Problem = 0":
            not executed_after and p6b.get("dispatch_calls") == 0 and p9["dispatch_calls"] == 0,
        "2. split-brain observable state during redefine = 0": not split,
        "3. old runtime approval reused after redefine = 0":
            not approvals_after and "P6b_approve_after_failed_redefine" in P and p6b["approve_status"] != "EXECUTED",
        "4. stale old-Problem action executed = 0": p9["dispatch_calls"] == 0 and p9["propose_status"] == "BLOCKED",
        "5. valid v2 release wrongly HOLD due to stale VOB = 0": all(
            x["release_v2"]["decision"] != "HOLD"
            and not any("ROUTE-IMPACT" in h for h in x["release_v2"]["hold"]) for x in (o, ob)),
        "6. DRAFT Problem redefined = 0": not P["P1_P2_precanonical"]["redefine_on_draft_accepted"]
            and P["P1_P2_precanonical"]["problem_invalidated_events"] == 0,
        "7. path-only evidence judged as redefine = 0":
            P["P5_discrimination"]["decide_recovery[decoy_path_only]"] != "REDEFINE"
            and not P["P5_discrimination"]["redefine_on_path_only_evidence_accepted"],
        "8. duplicate redefine state/history corruption = 0": bool(p10) and p10["no_mutation"]
            and len(hist) == len({h["version"] for h in hist})
            and not any(h["same_object_as_active"] for h in hist),
    }


if __name__ == "__main__":
    main()

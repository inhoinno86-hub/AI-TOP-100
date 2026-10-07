"""RV-4 reasoning stabilization patches (IDR-RV4-01..05).

P2 Premise Check  — authoritative evidence vs the ACTIVE canonical Problem, advisory, Core stays authoritative
P3 DEFINE repair  — typed findings + repair option types, bounded, repetition → reprofile / HOLD
P4 Reconsideration — one bounded second look at an eligible protected structural remedy (never forced)
Prompt-tuning guard — the new instructions / repair options are domain-agnostic.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest
from autonomous_fixtures import _agent, _remedy, interp, run, scenario_d, scope

from aitop_harness.core.events import EventType
from aitop_harness.engine.autonomous import AutonomousConfig
from aitop_harness.engine.define_repair import REPAIR_OPTIONS, classify_finding
from aitop_harness.phases.define import GateFinding, Severity
from aitop_harness.reasoning.prompts import INSTRUCTIONS

# --------------------------------------------------------------------------- helpers


def _records(orch: Any, skill: str) -> list[Any]:
    return [
        e.payload["detail"]
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ACCEPTED)
        if e.payload["skill"] == skill and isinstance(e.payload["detail"], dict)
    ]


def _calls(provider: Any, skill: str) -> list[Any]:
    return [c for c in provider.calls if c.skill == skill]


def premise_judge(trigger: str | None, *, layer: str = "PROBLEM_PREMISE", invalidating: bool = True) -> Any:
    """Fake premise check: contradicts problem-level premises when the new evidence contains ``trigger``."""

    def handler(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        ev = data["new_evidence"]
        hit = trigger is not None and trigger in ev["content"]
        out = []
        for p in data["premises"]:
            on = hit and p["layer"] == "PROBLEM_PREMISE"
            out.append(
                {
                    "premise_id": p["premise_id"],
                    "relation": "CONTRADICTS" if on else "NOT_ADDRESS",
                    "materiality": "CRITICAL" if on else "LOW",
                    "affected_layer": layer if on else p["layer"],
                    "problem_invalidating": on and invalidating,
                    "evidence_refs": [ev["id"]],
                    "rationale": "fixture",
                }
            )
        return {
            "problem_id": data["problem"]["id"],
            "problem_version": data["problem"]["version"],
            "premises": out,
            "overall_assessment": "INVALIDATED" if hit else "STABLE",
            "rationale": "fixture",
            "confidence": 0.8,
        }

    return handler


def missed_contradiction(handlers: dict[str, Any]) -> None:
    """RV-3 A-04 pattern: the interpretation of the decisive evidence says UNRELATED and links nothing."""
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = base(req, data)
        if data["observation"]["source"] == "wms-jobs" and "failed_runs" in data["observation"]["content"]:
            out = interp(
                "the release batch job failed in 21 of 30 runs",
                key="batch.failed_runs",
                value=21,
                new=[
                    {
                        "key": "BATCH",
                        "statement": "the warehouse release batch job fails",
                        "decision_impact": "HIGH",
                        "rationale": "job log",
                    }
                ],
            )
        return out

    handlers["interpret_evidence"] = interpret


# =========================================================================== P2 Premise Check


def test_premise_check_recovers_a_missed_premise_contradiction_through_the_core_path() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs")
    orch, result, provider, _ = run(public, world, handlers, human=human)
    ev = orch.ctx.events
    checks = _records(orch, "premise_check")
    assert any(c["accepted"] and c["challenge_raised"] for c in checks)
    assert ev.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)
    # Core path, not the Reasoner's label: revision → challenge → transition validation → Controller
    assert ev.of_type(EventType.EVIDENCE_REVISED)
    redefines = [e for e in ev.of_type(EventType.PHASE_TRANSITION) if e.payload.get("kind") == "REDEFINE"]
    assert len(redefines) == 1
    assert (
        orch.ctx.problem.problem_definition is not None and orch.ctx.problem.problem_definition.version == 2
    )
    assert not ev.of_type(EventType.PROTECTED_ACTION_EXECUTED)
    assert result.operator_reasoner_calls == 0


def test_without_premise_check_the_same_miss_never_redefines() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs")
    orch, _, provider, _ = run(
        public, world, handlers, human=human, config=AutonomousConfig(premise_check=False)
    )
    assert not _calls(provider, "premise_check")
    assert not orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)


def test_hypothesis_layer_invalidation_claim_is_rejected_by_the_core() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs", layer="HYPOTHESIS")
    orch, _, _, _ = run(public, world, handlers, human=human)
    checks = [c for c in _records(orch, "premise_check") if c["invalidating_claims"]]
    assert checks and not checks[0]["accepted"]
    assert all("not the problem premise" in why for why in checks[0]["rejected"].values())
    assert not orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)


def test_premise_check_accepted_invalidation_survives_a_soft_revision() -> None:
    """RV-4 behaviour (a non-invalidating revision silently dropped an accepted invalidation) is superseded by
    IDR-RV5-03: the downgrade is refused and recorded, and the challenge is raised. The premise check is still
    not a redefine by itself — the transition goes through propose_transition + Core validation."""
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs")
    revise = handlers["revise_evidence"]

    def soft(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = revise(req, data)
        for r in out["revisions"]:
            r["problem_invalidating"] = False
        return out

    handlers["revise_evidence"] = soft
    orch, _, provider, _ = run(public, world, handlers, human=human)
    assert any(c["accepted"] and c["challenge_raised"] for c in _records(orch, "premise_check"))
    assert orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)
    adjusted = [
        x
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ADJUSTED)
        if e.payload["skill"] == "revise_evidence"
        for x in e.payload["detail"]
    ]
    assert any("cannot downgrade" in x for x in adjusted)
    assert _calls(provider, "propose_transition")


def test_premise_check_trigger_is_bounded_to_strong_new_decision_relevant_evidence() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge(None)
    orch, _, provider, _ = run(public, world, handlers, human=human)
    calls = _calls(provider, "premise_check")
    assert calls, "strong evidence after the canonical Problem must be premise-checked"
    seen = [json.loads(c.input_json)["new_evidence"] for c in calls]
    ps = orch.ctx.problem
    for e in seen:
        ev = ps.evidence[e["id"]]
        assert ev.source_type.value != "STAKEHOLDER" and ev.authority.value == "AUTHORITATIVE"
    assert len({e["id"] for e in seen}) == len(seen)  # each evidence once per Problem version
    pd = ps.problem_definition
    assert pd is not None and not {e["id"] for e in seen} & set(pd.evidence_refs)  # never its own premise
    assert not orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)


def test_stale_problem_version_premise_check_is_ignored() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    judge = premise_judge("failed_runs")

    def stale(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = judge(req, data)
        out["problem_version"] = data["problem"]["version"] + 1
        return out

    handlers["premise_check"] = stale
    orch, _, _, _ = run(public, world, handlers, human=human)
    assert any(c["stale"] for c in _records(orch, "premise_check"))
    assert not orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)


def test_premise_check_provider_failure_degrades_without_a_challenge() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers.pop("premise_check", None)  # fake provider errors → deterministic fallback
    orch, _, _, _ = run(public, world, handlers, human=human)
    recs = _records(orch, "premise_check")
    assert recs and all(r["fallback"] == "deterministic" and not r["invalidating_claims"] for r in recs)
    assert not orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)


# =========================================================================== P3 DEFINE repair


def _no_grant(handlers: dict[str, Any]) -> None:
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = base(req, data)
        if data["observation"]["source"] == "carrier-contract":
            out["authorization_candidates"] = []
        return out

    handlers["interpret_evidence"] = interpret


def _repairing_define(handlers: dict[str, Any], fix: Any) -> list[dict[str, Any]]:
    base = handlers["define_problem"]
    seen: list[dict[str, Any]] = []

    def define(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = base(req, data)
        if "repair_request" in data:
            seen.append(data["repair_request"])
            fix(out, data)
        return out

    handlers["define_problem"] = define
    return seen


def _drop_protected(out: dict[str, Any], data: dict[str, Any]) -> None:
    f = next(x for x in data["repair_request"]["findings"] if x["type"] == "UNAUTHORIZED_ACTION_IN_PROBLEM")
    out["protected_actions"] = [a for a in out["protected_actions"] if a != f["subject"]]
    out["intended_scope"] = [i for i in out["intended_scope"] if i["action"] != f["subject"]]
    out["repair_resolution"] = [{"finding": f["id"], "option": f["repair_options"][0], "change": "removed"}]


def test_unauthorized_protected_action_gets_typed_repair_and_converges() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    seen = _repairing_define(handlers, _drop_protected)
    orch, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(seen) == 1
    finding = next(f for f in seen[0]["findings"] if f["severity"] == "BLOCKING")
    assert (
        finding["type"] == "UNAUTHORIZED_ACTION_IN_PROBLEM" and finding["subject"] == "push_pickup_schedule"
    )
    assert finding["repair_options"] and "authority_context" in seen[0]
    repair = _records(orch, "define_repair")
    assert repair and "UNAUTHORIZED_ACTION_IN_PROBLEM:push_pickup_schedule" in repair[0]["resolved"]
    assert repair[0]["gate_after"] in ("PASS", "CONDITIONAL_PASS")
    assert any("protected_actions removed" in c for c in repair[0]["changed"])
    assert (
        orch.ctx.problem.problem_definition is not None and orch.ctx.problem.problem_definition.is_canonical()
    )
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)
    assert result.release_decision is not None


def test_repair_keeps_the_problem_framing_when_no_finding_concerns_it() -> None:
    """RV-4 A-04 (R4-S3): a metric / authority repair must not let the Reasoner rewrite the root problem."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)

    def drift(out: dict[str, Any], data: dict[str, Any]) -> None:
        _drop_protected(out, data)
        out["root_problem"] = "Parcels are late, which causes customer complaints about lateness."
        out["causal_chain"] = ["parcels late"]

    seen = _repairing_define(handlers, drift)
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert seen and seen[0]["locked_fields"] == ["root_problem", "causal_chain", "premise_hypotheses"]
    pd = orch.ctx.problem.problem_definition
    assert pd is not None and pd.root_problem.startswith("Carrier pickups run two hours late")
    adjusted = [
        d
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ADJUSTED)
        if e.payload["skill"] == "define_problem"
        for d in e.payload["detail"]
    ]
    assert any("kept from the previous proposal" in d for d in adjusted)


def test_framing_findings_unlock_the_problem_framing() -> None:
    from aitop_harness.engine.define_repair import RepairFinding, locked_fields

    def finding(ftype: str) -> RepairFinding:
        return RepairFinding("F-1", ftype, "BLOCKING", "x", "x", [], "x", ["x"])

    assert locked_fields([finding("INVALID_METRIC")]) == [
        "root_problem",
        "causal_chain",
        "premise_hypotheses",
    ]
    assert locked_fields([finding("INVALID_METRIC"), finding("UNSUPPORTED_CAUSAL_CLAIM")]) == []


def test_mislabelled_problem_id_with_the_active_version_is_still_judged() -> None:
    """RV-4 A-02 / A-04 (R4-S2): problem_id 'PR-ROOT' + the right version was discarded as stale."""
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    judge = premise_judge("failed_runs")

    def mislabel(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = judge(req, data)
        out["problem_id"] = "PR-ROOT"
        return out

    handlers["premise_check"] = mislabel
    orch, _, _, _ = run(public, world, handlers, human=human)
    recs = _records(orch, "premise_check")
    assert recs and not any(r["stale"] for r in recs)
    assert any(r["accepted"] and r["challenge_raised"] for r in recs)


def test_repeated_identical_findings_end_in_hold_not_blind_retries() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    seen = _repairing_define(handlers, lambda out, data: None)  # the "repair" changes nothing
    orch, result, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(seen) == 1  # one repair, then no blind second attempt with the same error
    assert result.halt_reason is not None and "same findings repeated" in result.halt_reason
    repair = _records(orch, "define_repair")
    assert repair and not repair[0]["resolved"] and repair[0]["changed"] == ["no change"]
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


def test_repair_attempts_are_bounded() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    rounds = {"n": 0}

    def churn(out: dict[str, Any], data: dict[str, Any]) -> None:  # resolves one thing, breaks another
        rounds["n"] += 1
        out["metrics"] = [{"key": f"M{rounds['n']}", "name": "x", "metric_type": "RATE"}]
        out["success_criteria"][0]["metric"] = f"M{rounds['n']}"

    seen = _repairing_define(handlers, churn)
    _, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(seen) <= AutonomousConfig().max_define_repair_attempts
    assert result.halt_reason is not None and "DEFINE Gate FAIL" in result.halt_reason


def test_repair_can_identify_a_documented_authority_holder() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)

    def cite(out: dict[str, Any], data: dict[str, Any]) -> None:
        ctx = data["repair_request"]["authority_context"]["push_pickup_schedule"]
        doc = ctx["authoritative_documents"][0]["evidence"]
        out["authorization_candidates"] = [
            {
                "action": "push_pickup_schedule",
                "resource": "pickup-sched",
                "authority_holder": "SH-CAR",
                "scope_target": "*",
                "conditions": ["SH-CAR confirms"],
                "evidence_ref": doc,
                "rationale": "contract §3",
            }
        ]

    _repairing_define(handlers, cite)
    orch, _, _, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert any(a.action == "push_pickup_schedule" for a in orch.ctx.problem.domain_authorizations.values())
    assert len(orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1  # via the Human Gate only


def test_repair_authority_scoped_to_something_else_is_refused_and_fed_back() -> None:
    """RV-4b C-03 (R4-S3): scope_target = the action name gave a grant that could never cover the action."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)

    def cite(out: dict[str, Any], data: dict[str, Any]) -> None:
        doc = data["repair_request"]["authority_context"]["push_pickup_schedule"]["authoritative_documents"][
            0
        ]
        target = (
            "pickup-sched"
            if data["repair_request"]["refused_authorization_candidates"]
            else "push_pickup_schedule"
        )
        out["authorization_candidates"] = [
            {
                "action": "push_pickup_schedule",
                "resource": "pickup-sched",
                "authority_holder": "SH-CAR",
                "scope_target": target,
                "conditions": [],
                "evidence_ref": doc["evidence"],
                "rationale": "contract §3",
            }
        ]

    seen = _repairing_define(handlers, cite)
    orch, _, _, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(seen) == 2 and "scope_target" in seen[1]["refused_authorization_candidates"][0]
    auth = [a for a in orch.ctx.problem.domain_authorizations.values() if a.action == "push_pickup_schedule"]
    assert len(auth) == 1 and str(auth[0].authorized_scope.items[0]) == "push_pickup_schedule:pickup-sched"
    assert len(orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1


def test_repair_authority_not_named_by_the_document_is_refused() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)

    def wrong(out: dict[str, Any], data: dict[str, Any]) -> None:
        out["authorization_candidates"] = [
            {
                "action": "push_pickup_schedule",
                "resource": "pickup-sched",
                "authority_holder": "SH-LOG",
                "scope_target": "*",
                "conditions": [],
                "evidence_ref": "E-01",
                "rationale": "made up",
            }
        ]

    _repairing_define(handlers, wrong)
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert not orch.ctx.problem.domain_authorizations
    adjusted = [
        d
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ADJUSTED)
        if e.payload["skill"] == "define_problem"
        for d in e.payload["detail"]
    ]
    assert any("authorization candidate push_pickup_schedule refused" in d for d in adjusted)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


_AUTH = "authority owner / authorization unknown"
_TYPED = [
    ("metric", "metric M-1 must be EXTENDED with ['numerator']", ["M-1"], "INVALID_METRIC"),
    ("verification", "no success criteria", [], "MISSING_METRIC"),
    ("tool", "required tool t UNAVAILABLE without fallback", ["t"], "UNAVAILABLE_TOOL"),
    ("evidence", "root problem rests only on stakeholder statements", [], "UNSUPPORTED_CAUSAL_CLAIM"),
    ("evidence", "problem definition cites revised/superseded evidence", [], "STALE_EVIDENCE"),
    ("unknown", "critical unknown U-1 overlaps intended scope", ["U-1"], "BLOCKING_UNKNOWN"),
    ("data", "export permission unknown", ["DA-1"], "SCOPE_EXCEEDS_AUTHORIZATION"),
    ("authority", f"protected action invented_op: {_AUTH}", ["invented_op"], "UNKNOWN_ACTION"),
    ("authority", f"protected action push_pickup_schedule: {_AUTH}", [], "UNAUTHORIZED_ACTION_IN_PROBLEM"),
    (
        "authority",
        "protected action push_pickup_schedule: approval requirement unknown",
        [],
        "MISSING_AUTHORITY",
    ),
]


@pytest.mark.parametrize(("check", "message", "refs", "expected"), _TYPED)
def test_gate_findings_are_typed_deterministically(
    check: str, message: str, refs: list[str], expected: str
) -> None:
    finding = GateFinding(check, Severity.BLOCKING, message, refs)
    public, world, handlers, _ = scenario_d()
    orch, _, _, _ = run(public, world, handlers, human=[None] * 8, config=AutonomousConfig(max_steps=1))
    ftype, _ = classify_finding(orch.ctx, finding)
    assert ftype == expected
    assert REPAIR_OPTIONS[ftype]


# =========================================================================== P4 bounded reconsideration


def _exclude_protected(handlers: dict[str, Any], *, feasible: bool = True) -> None:
    base = handlers["agent_design"]
    handlers["structural_remedy"] = lambda req, data: _remedy(feasible=feasible)

    def agent(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = base(req, data)
        if any(i["action"] == "push_pickup_schedule" for i in out["release_scope"]):
            out = _agent(
                [scope("rank_late_slots", "DA-PICK")], {"rank_late_slots": ["DA-PICK"]}, tools=["pickup-log"]
            )
        return out

    handlers["agent_design"] = agent


def _decide(decision: str) -> Any:
    def handler(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "decision": decision,
            "rationale": "fixture",
            "evidence_refs": [],
            "risks": [],
            "needed_evidence": "slot capacity" if decision == "NEEDS_MORE_EVIDENCE" else "",
            "confidence": 0.7,
        }

    return handler


def test_eligible_excluded_protected_remedy_is_reconsidered_once_and_reaches_the_gate() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _exclude_protected(handlers)
    handlers["reconsider_protected_action"] = _decide("INCLUDE_WITH_HUMAN_GATE")
    orch, _, provider, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(_calls(provider, "reconsider_protected_action")) == 1
    rec = _records(orch, "protected_reconsideration")
    assert rec[0]["eligible"] and rec[0]["included"] and rec[0]["action"] == "push_pickup_schedule"
    ev = orch.ctx.events
    assert ev.of_type(EventType.APPROVAL_PACKET_EMITTED) and ev.of_type(EventType.HUMAN_CONTEXT_REQUESTED)
    assert len(ev.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1  # the Human approved; executed once


def test_keep_excluded_is_respected() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _exclude_protected(handlers)
    handlers["reconsider_protected_action"] = _decide("KEEP_EXCLUDED")
    orch, _, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(_calls(provider, "reconsider_protected_action")) == 1
    sd = orch.ctx.problem.solution_design
    assert sd is not None and all(i.action != "push_pickup_schedule" for i in sd.release_scope)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_PROPOSED)


def test_needs_more_evidence_is_recorded_as_a_known_limitation() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _exclude_protected(handlers)
    handlers["reconsider_protected_action"] = _decide("NEEDS_MORE_EVIDENCE")
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    sd = orch.ctx.problem.solution_design
    assert sd is not None and any("push_pickup_schedule not proposed yet" in u for u in sd.unfinished_scope)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_PROPOSED)


@pytest.mark.parametrize("why", ["infeasible", "critical_vob"])
def test_reconsideration_is_never_asked_when_the_exclusion_is_forced(why: str) -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _exclude_protected(handlers, feasible=why != "infeasible")
    if why == "critical_vob":  # an open critical unknown on the protected action → VOB blocks it
        base = handlers["define_problem"]

        def define(req: Any, data: dict[str, Any]) -> dict[str, Any]:
            out = copy.deepcopy(base(req, data))
            for u in out["unknowns"]:
                u["criticality"] = "CRITICAL"
                u["affects_scope"] = [scope("push_pickup_schedule", "pickup-sched")]
            return out

        handlers["define_problem"] = define
    handlers["reconsider_protected_action"] = _decide("INCLUDE_WITH_HUMAN_GATE")
    orch, _, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert not _calls(provider, "reconsider_protected_action")
    rec = _records(orch, "protected_reconsideration")
    assert rec and not rec[0]["eligible"]
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


# =========================================================================== prompt-tuning guard

_SCENARIO_TOKENS = (
    "mdms",
    "bv-17",
    "v4.2",
    "0.1 m3",
    "meter",
    "billing",
    "route",
    "ami",
    "firmware",
    "idempotency",
    "gateway",
    "pickup",
    "carrier",
)


@pytest.mark.parametrize("skill", ["premise_check", "reconsider_protected_action", "define_problem"])
def test_new_instructions_are_domain_agnostic(skill: str) -> None:
    assert not _scenario_tokens(INSTRUCTIONS[skill])


def test_repair_options_are_domain_agnostic_and_never_answers() -> None:
    assert not _scenario_tokens(" ".join(o for opts in REPAIR_OPTIONS.values() for o in opts))


def _scenario_tokens(text: str) -> list[str]:
    return [t for t in _SCENARIO_TOKENS if re.search(rf"\b{re.escape(t)}\b", text.lower())]

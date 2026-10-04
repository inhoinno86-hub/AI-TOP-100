"""Mock #5 regression and Mock #6 readiness.

Mock #5 — Severe Time Pressure + Tool Failure:
  bounded retry · retry vs replan · targeted reprofile · partial result · fallback authority/freshness ·
  Release Reserve · minimum useful release · VOB blocking_scope
Mock #6 — New Evidence Invalidates Problem (readiness only; the full Mock #6 runs after this implementation):
  redefine · state versioning · Evidence Revision · problem invalidation monitoring · replan after redefine
"""

from __future__ import annotations

import pytest
from builders import err, make_ctx, mutation_ok, ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.clock import SimulatedClock
from aitop_harness.core.enums import (
    AgentRole,
    AuthorizationStatus,
    Criticality,
    DefineGateResult,
    DiffKind,
    FallbackUsage,
    FreshnessStatus,
    HumanDecisionKind,
    Phase,
    ProblemDefinitionStatus,
    ProtectedActionCategory,
    RecoveryKind,
    ReleaseDecision,
    RequiredBefore,
    ReserveStatus,
    ResultCompleteness,
    RetryStopReason,
    SourceAuthority,
    WorkClass,
)
from aitop_harness.core.errors import IllegalTransitionError
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.authority import DomainAuthorization
from aitop_harness.domain.data import DataAsset
from aitop_harness.domain.design import ProblemDefinition, StructuralRemedyCandidate, WorkItem
from aitop_harness.domain.verification import VerificationObligation
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.budget import apply_release_reserve, set_plan, update_budget
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.design import DesignInputs, design_solution
from aitop_harness.phases.discover import integrate_evidence, revise_evidence
from aitop_harness.phases.execute import evidence_from_outcome, invoke_tool
from aitop_harness.phases.human_gate import GateStatus, HumanDecision, decide, propose_protected_action
from aitop_harness.phases.recovery import (
    FailureContext,
    activate_fallback,
    apply_recovery_decision,
    decide_recovery,
    fallback_permits,
    record_retry,
)
from aitop_harness.phases.release import evaluate_release_gate
from aitop_harness.phases.verify import run_verify
from aitop_harness.state.runtime import Plan, ProtectedActionProposal
from aitop_harness.supervision.projection import refresh
from aitop_harness.tools.base import ToolRegistry, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool

S = ScopeItem


def _fc(o, **kw):
    return FailureContext(o.tool_id, o.operation, o.failure_signature, o.result.error_class, o.result.retryable_hint,
                          **kw)


def test_mock5_time_pressure_and_tool_failure():
    ctx = make_ctx("MOCK-5", "fully autonomous repair + submit of shipment holds")
    seed_org(ctx)
    seed_success(ctx)
    api = ScriptedTool("hold-api", script={"holds": [err("HTTP_503"), err("HTTP_503")]})
    snap = ScriptedTool("hold-snapshot", script={"holds": [ok([{"id": i} for i in range(40)], expected_count=55,
                                                               source_authority=SourceAuthority.NON_AUTHORITATIVE)]})
    reg = ToolRegistry()
    reg.register(api, ToolSpec("hold-api", "holds-svc", authority=SourceAuthority.AUTHORITATIVE))
    reg.register(snap, ToolSpec("hold-snapshot", "warehouse", fallback_for="hold-api"))
    ctx.clock = SimulatedClock(120)
    ctx.runtime.phase = Phase.EXECUTE
    update_budget(ctx)

    # first transient failure → bounded retry
    o1 = invoke_tool(ctx, reg, "hold-api", "holds")
    d1 = decide_recovery(ctx, _fc(o1, fallbacks=reg.fallbacks_for("hold-api"), expected_value=20))
    assert d1.kind is RecoveryKind.RETRY
    apply_recovery_decision(ctx, d1, _fc(o1))
    o2 = invoke_tool(ctx, reg, "hold-api", "holds", {"limit": 50})  # parameter variation, same dependency
    record_retry(ctx, _fc(o1), 1.0, "HTTP_503")
    # repeated failure → replan via fallback (not another retry, not redefine)
    d2 = decide_recovery(ctx, _fc(o2, fallbacks=reg.fallbacks_for("hold-api"), expected_value=20))
    assert d2.kind is RecoveryKind.REPLAN and d2.stop_reason is RetryStopReason.REPEATED_SAME_DEPENDENCY_FAILURE
    apply_recovery_decision(ctx, d2, _fc(o2, fallbacks=reg.fallbacks_for("hold-api")))
    assert ctx.problem.problem_definition is None or \
        ctx.problem.problem_definition.status is not ProblemDefinitionStatus.INVALIDATED

    # fallback: partial + non-authoritative; usable for diagnosis, not for the protected action
    activate_fallback(ctx, "hold-api", reg.spec("hold-snapshot"), "hold-api HTTP_503 x2")
    o3 = invoke_tool(ctx, reg, "hold-snapshot", "holds")
    assert o3.completeness is ResultCompleteness.PARTIAL
    ev = evidence_from_outcome(ctx, o3, "E-snap", "40 of 55 holds; snapshot 6h old", is_fallback=True)
    integrate_evidence(ctx, ev)
    assert ev.authority is SourceAuthority.NON_AUTHORITATIVE
    assert fallback_permits(ctx, "hold-api", FallbackUsage.PATTERN_DIAGNOSIS)[0]
    assert ctx.runtime.recovery.fallbacks["hold-api"].freshness_status is FreshnessStatus.NOT_EVALUATED
    assert not fallback_permits(ctx, "hold-api", FallbackUsage.CURRENT_PROTECTED_MUTATION)[0]

    # missing critical owner evidence → targeted reprofile
    d4 = decide_recovery(ctx, _fc(o2, missing_critical_info=["owner of hold-release override"]))
    assert d4.kind is RecoveryKind.REPROFILE
    integrate_evidence(ctx, tool_evidence("E-owner", "ops lead owns hold release; policy HR-3"))
    integrate_evidence(ctx, tool_evidence("E-holds", "authoritative hold list for carrier C1 (complete)"))

    scope_detect = [S("detect_hold", "all"), S("classify_hold", "all")]
    scope_release = [S("release_hold", "carrier-C1")]
    full_scope = scope_detect + scope_release + [S("auto_repair", "all")]
    with ctx.commit("auth + VOB") as ps:
        ps.domain_authorizations["DA-HR"] = DomainAuthorization(
            "DA-HR", "release_hold", "tms", authority_holder="ops lead",
            authorized_scope=Scope.of(("release_hold", "carrier-C1")), evidence_refs=["E-owner"],
            status=AuthorizationStatus.GRANTED)
        ps.verification_obligations["VOB-AR"] = VerificationObligation(
            "VOB-AR", "auto-repair correctness on partial data", Phase.DEFINE, decision_impact=Criticality.CRITICAL,
            validation_method="full authoritative list", required_before=RequiredBefore.BEFORE_RELEASE,
            blocking_scope=Scope.of(("auto_repair", "*")))
        ps.data_assets["DA-SNAP"] = DataAsset("DA-SNAP", "snapshot", completeness=ResultCompleteness.PARTIAL,
                                              is_fallback=True, used_by=["auto_repair"])
    define_problem(ctx, problem(["E-holds", "E-owner"], intended=full_scope, protected=["release_hold"]))
    gate = evaluate_define_gate(ctx, reg)
    assert gate.result is not DefineGateResult.FAIL, [f.message for f in gate.findings]
    apply_define_gate(ctx, gate)
    sd = design_solution(ctx, DesignInputs(
        structural_remedies=[StructuralRemedyCandidate("SR", "hold reason codes at source", True, False)],
        deterministic_rules_cover_cases=True, llm_reasoning_adds_value=True,
        bridge_sunset_condition="source reason codes live", release_scope=full_scope,
        minimum_useful_scope=scope_detect))
    assert AgentRole.PRIMARY_SOLUTION not in sd.agent_roles

    # time pressure → release reserve → real scope reduction
    set_plan(ctx, Plan("P", work_items=[
        WorkItem("W-detect", "detection + classification", WorkClass.CORE_FEATURE, 0, scope_detect, True, True),
        WorkItem("W-release", "C1 hold release (gated)", WorkClass.CORE_FEATURE, 0, scope_release, True, True),
        WorkItem("W-repair", "autonomous repair", WorkClass.NON_BLOCKING_FEATURE, 40, [S("auto_repair", "all")], True),
        WorkItem("W-dash", "dashboard", WorkClass.NICE_TO_HAVE, 20),
        WorkItem("W-verify", "blocking verification", WorkClass.RELEASE_BLOCKING_VERIFICATION, 8),
        WorkItem("W-pack", "packaging + submission", WorkClass.PACKAGING, 6),
    ]))
    ctx.clock = SimulatedClock(272)
    update_budget(ctx)
    assert ctx.runtime.release_runtime.reserve_status is ReserveStatus.ACTIVE
    reduction = apply_release_reserve(ctx)
    assert set(reduction.dropped) == {"W-repair", "W-dash"}
    assert {"W-verify", "W-pack", "W-detect", "W-release"} <= set(reduction.kept)
    assert ctx.supervision.state_diff.of_kind(DiffKind.DROPPED_FOR_BUDGET)

    # protected hold release passes the gate, approve → atomic action + read-back
    tms = ScriptedTool("tms", read_only=False, script={"release_hold": [mutation_ok()]})
    gate_out = propose_protected_action(ctx, ProtectedActionProposal(
        "HR-1", "release_hold", "carrier C1 holds", "tms", scope_release, ProtectedActionCategory.PROTECTED_MUTATION,
        why="authoritative list complete for C1", idempotency_key="hr-c1", key_evidence=["E-holds", "E-owner"]), tms)
    assert gate_out.status is GateStatus.WAITING_APPROVAL
    assert decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tms).status is GateStatus.EXECUTED

    # minimum useful release: detection + classification + gated C1 release; repair dropped & explicit
    release_scope = scope_detect + scope_release
    ctx.runtime.phase = Phase.VERIFY
    report = run_verify(ctx, release_scope)
    assert report.layer1_passed, [(c.name, c.detail) for c in report.failed()]
    res = evaluate_release_gate(ctx, report)
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION, res.hold_reasons
    assert res.minimum_useful is not None and res.minimum_useful.ok
    assert any("VOB-AR" in limit for limit in res.known_limitations)  # critical VOB outside release scope
    assert any("autonomous repair" in u for u in ctx.problem.solution_design.unfinished_scope)
    # including auto-repair in scope would be unsafe → HOLD (blocking_scope not bypassed)
    unsafe = evaluate_release_gate(ctx, run_verify(ctx, release_scope + [S("auto_repair", "all")]))
    assert unsafe.decision is ReleaseDecision.HOLD
    # no redefine happened anywhere in this run
    assert not ctx.events.of_type(EventType.PROBLEM_INVALIDATED)


def test_mock6_readiness_new_evidence_invalidates_problem():
    ctx = make_ctx("MOCK-6-READINESS", "speed up partner approvals")
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-q", "approval queue length 300"))
    scope_v1 = [S("prioritize_queue", "partner")]
    define_problem(ctx, problem(["E-q"], intended=scope_v1))
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    design_solution(ctx, DesignInputs([StructuralRemedyCandidate("SR", "queue triage", True, True)], True, True,
                                      release_scope=scope_v1))
    controller = PhaseController(ctx)
    ctx.runtime.phase = Phase.EXECUTE

    # authoritative evidence: the queue is a symptom; approvals are blocked by an expired contract
    integrate_evidence(ctx, tool_evidence("E-contract", "contract registry: partner contract expired 09-30",
                                          source="contract-registry"))
    rev = revise_evidence(ctx, "E-q", "E-contract", "queue growth is caused by expired contract, not capacity",
                          invalidates_problem=True)
    decision = decide_recovery(ctx, FailureContext("n/a", "n/a", None, None, None,
                                                   problem_invalidating_evidence="E-contract"))
    assert decision.kind is RecoveryKind.REDEFINE
    controller.redefine("E-contract", rev.revised_interpretation)

    # state versioning + monitoring
    old = ctx.problem.meta.problem_definition_history[-1]
    assert old.status is ProblemDefinitionStatus.INVALIDATED and old.version == 1
    assert ctx.runtime.phase is Phase.DEFINE
    assert any("[CRITICAL] PROBLEM_INVALIDATED" in s for s in ctx.supervision.live_summary)
    refresh(ctx)
    assert any("invalidates problem" in r for r in ctx.supervision.evidence_revisions)

    # old design is stale: EXECUTE is unreachable until DEFINE + DESIGN are redone
    pd2 = ProblemDefinition(id="PD-1", version=2, requested_solution="speed up approvals",
                            root_problem="expired partner contract blocks approvals",
                            evidence_refs=["E-contract"], intended_scope=[S("flag_expired_contract", "partner")],
                            success_criteria=["SC-1"])
    define_problem(ctx, pd2)
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    assert pd2.gate_result is DefineGateResult.PASS
    controller.advance()  # → DESIGN
    with pytest.raises(IllegalTransitionError, match="stale"):
        controller.advance()  # stale v1 design must not reach EXECUTE
    # replan after redefine: new design against v2
    sd2 = design_solution(ctx, DesignInputs([StructuralRemedyCandidate("SR2", "contract renewal alert", True, True)],
                                            True, False, release_scope=pd2.intended_scope), design_id="SD-2")
    assert sd2.problem_version == 2
    controller.advance()  # → EXECUTE
    assert ctx.runtime.phase is Phase.EXECUTE
    # the invalidated evidence is preserved, not overwritten
    assert ctx.problem.evidence["E-q"].content == "approval queue length 300"

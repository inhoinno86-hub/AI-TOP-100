"""PHASE F — EXECUTE + tool failure recovery; PHASE G — Budget + Release Reserve."""

from __future__ import annotations

import pytest
from builders import err, make_ctx, ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.clock import SimulatedClock
from aitop_harness.core.enums import (
    DiffKind,
    FallbackUsage,
    FreshnessStatus,
    Phase,
    ProblemDefinitionStatus,
    RecoveryKind,
    ReserveStatus,
    ResultCompleteness,
    RetryStopReason,
    SourceAuthority,
    ToolHealth,
    TransitionKind,
    WorkClass,
)
from aitop_harness.core.errors import IllegalTransitionError, ProtectedActionBlocked
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import ScopeItem
from aitop_harness.domain.design import WorkItem
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.budget import (
    ReserveViolation,
    add_work_item,
    apply_release_reserve,
    retry_budget_ok,
    set_plan,
    update_budget,
)
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.discover import integrate_evidence
from aitop_harness.phases.execute import assess_completeness, evidence_from_outcome, invoke_tool
from aitop_harness.phases.recovery import (
    FailureContext,
    activate_fallback,
    apply_recovery_decision,
    decide_recovery,
    fallback_permits,
    record_retry,
)
from aitop_harness.state.runtime import Plan
from aitop_harness.tools.base import ToolRegistry, ToolResult, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool
from aitop_harness.core.enums import ResultStatus


def _reg(*tools: tuple[ScriptedTool, ToolSpec]) -> ToolRegistry:
    reg = ToolRegistry()
    for t, s in tools:
        reg.register(t, s)
    return reg


def _fc(outcome, **kw) -> FailureContext:
    return FailureContext(outcome.tool_id, outcome.operation, outcome.failure_signature,
                          outcome.result.error_class, outcome.result.retryable_hint, **kw)


# --------------------------------------------------------------------------- partial / health


def test_success_is_not_complete():
    assert assess_completeness(ToolResult(ResultStatus.SUCCESS, records=[{"a": 1}])) is ResultCompleteness.UNKNOWN
    assert assess_completeness(ok([{"a": 1}], expected_count=3)) is ResultCompleteness.PARTIAL
    assert assess_completeness(ok([{"a": 1}], pagination_complete=False)) is ResultCompleteness.PARTIAL
    assert assess_completeness(ok([{"a": 1}], missing_fields=["owner"])) is ResultCompleteness.PARTIAL
    assert assess_completeness(ok([{"a": 1}], coverage_period="Q1", required_coverage_period="Q1-Q2")) \
        is ResultCompleteness.PARTIAL
    assert assess_completeness(ok([{"a": 1}])) is ResultCompleteness.COMPLETE


def test_tool_health_tracking_and_partial_result_evidence():
    ctx = make_ctx()
    tool = ScriptedTool("crm", script={"list": [ok([{"id": 1}], expected_count=4)]})
    reg = _reg((tool, ToolSpec("crm", "crm-db")))
    out = invoke_tool(ctx, reg, "crm", "list")
    assert out.completeness is ResultCompleteness.PARTIAL
    assert ctx.runtime.tool("crm").health is ToolHealth.DEGRADED
    assert ctx.events.last(EventType.PARTIAL_RESULT) is not None
    ev = evidence_from_outcome(ctx, out, "E-crm", "1 of 4 rows")
    assert ev.completeness is ResultCompleteness.PARTIAL  # partial stays partial


def test_mutating_tools_cannot_be_invoked_outside_human_gate():
    ctx = make_ctx()
    reg = _reg((ScriptedTool("erp", read_only=False), ToolSpec("erp", "erp", read_only=False)))
    with pytest.raises(ProtectedActionBlocked):
        invoke_tool(ctx, reg, "erp", "write")


# --------------------------------------------------------------------------- retry / replan / reprofile / redefine


def test_bounded_retry_then_replan_with_fallback_and_param_variation_is_same_signature():
    ctx = make_ctx()
    api = ScriptedTool("api", script={"orders": [err("TIMEOUT"), err("TIMEOUT"), err("TIMEOUT")]})
    snap = ScriptedTool("snapshot", script={"orders": [ok([{"id": 1}], expected_count=1)]})
    reg = _reg((api, ToolSpec("api", "orders-svc")),
               (snap, ToolSpec("snapshot", "warehouse", fallback_for="api")))

    o1 = invoke_tool(ctx, reg, "api", "orders", {"page": 1})
    d1 = decide_recovery(ctx, _fc(o1, fallbacks=reg.fallbacks_for("api"), expected_value=10))
    assert d1.kind is RecoveryKind.RETRY
    apply_recovery_decision(ctx, d1, _fc(o1))
    # retry noise is throttled, not pushed to the live feed
    assert not any("RETRY_DETAIL" in s for s in ctx.supervision.live_summary)

    # "different" call: same dependency, different params → same failure signature
    o2 = invoke_tool(ctx, reg, "api", "orders", {"page": 1, "page_size": 10})
    record_retry(ctx, _fc(o1), actual_cost=1.0, result="TIMEOUT")
    assert o2.failure_signature == o1.failure_signature
    assert ctx.runtime.recovery.signature_failures[o1.failure_signature] == 2

    d2 = decide_recovery(ctx, _fc(o2, fallbacks=reg.fallbacks_for("api"), expected_value=10))
    assert d2.kind is RecoveryKind.REPLAN
    assert d2.stop_reason is RetryStopReason.REPEATED_SAME_DEPENDENCY_FAILURE
    assert d2.fallback is not None and d2.fallback.tool_id == "snapshot"
    apply_recovery_decision(ctx, d2, _fc(o2, fallbacks=reg.fallbacks_for("api")))
    assert any("STRATEGY_CHANGING_FAILURE" in s for s in ctx.supervision.live_summary)  # never throttled
    assert ctx.runtime.transition_candidate.kind is TransitionKind.REPLAN
    rec = ctx.runtime.recovery
    assert rec.retry_count == 1 and rec.cumulative_retry_cost == 1.0
    assert rec.retry_history[0].failure_signature == o1.failure_signature


def test_retry_stops_on_budget_and_ev():
    ctx = make_ctx()
    api = ScriptedTool("api", script={"q": [err("TIMEOUT")]})
    reg = _reg((api, ToolSpec("api", "svc")))
    out = invoke_tool(ctx, reg, "api", "q")
    assert decide_recovery(ctx, _fc(out, expected_value=1, estimated_retry_cost=5)).stop_reason \
        is RetryStopReason.EXPECTED_VALUE_NOT_ABOVE_COST
    ctx.clock = SimulatedClock(250)
    update_budget(ctx)
    d = decide_recovery(ctx, _fc(out, expected_value=50, estimated_retry_cost=5))
    assert d.kind is RecoveryKind.REDUCE_SCOPE
    assert d.stop_reason is RetryStopReason.BUDGET_THREATENS_VERIFICATION
    ctx.clock = SimulatedClock(280)
    update_budget(ctx)
    assert retry_budget_ok(ctx, 1)[1] == "RELEASE_RESERVE_WOULD_BE_VIOLATED"


def test_non_transient_failure_without_alternatives_holds():
    ctx = make_ctx()
    reg = _reg((ScriptedTool("api", script={"q": [err("AUTH_DENIED", retryable=False)]}), ToolSpec("api", "svc")))
    out = invoke_tool(ctx, reg, "api", "q")
    d = decide_recovery(ctx, _fc(out))
    assert d.kind is RecoveryKind.HOLD and d.stop_reason is RetryStopReason.NOT_TRANSIENT


def test_mutation_uncertainty_requires_read_back_first():
    ctx = make_ctx()
    reg = _reg((ScriptedTool("api", script={"q": [err("TIMEOUT", partial_side_effect_possible=True)]}),
                ToolSpec("api", "svc")))
    out = invoke_tool(ctx, reg, "api", "q")
    d = decide_recovery(ctx, _fc(out, partial_side_effect_possible=True, expected_value=99))
    assert d.kind is RecoveryKind.HOLD and d.next_action == "READ_BACK"
    assert d.stop_reason is RetryStopReason.MUTATION_UNCERTAINTY_READ_BACK_FIRST


def test_targeted_reprofile_for_missing_owner_evidence():
    ctx = make_ctx()
    reg = _reg((ScriptedTool("api", script={"q": [err("TIMEOUT")]}), ToolSpec("api", "svc")))
    out = invoke_tool(ctx, reg, "api", "q")
    d = decide_recovery(ctx, _fc(out, missing_critical_info=["owner of override policy"]))
    assert d.kind is RecoveryKind.REPROFILE and d.reprofile_targets == ["owner of override policy"]


def _active_problem(ctx):
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-1"))
    define_problem(ctx, problem(["E-1"]))
    apply_define_gate(ctx, evaluate_define_gate(ctx))


def test_tool_failure_alone_never_redefines():
    ctx = make_ctx()
    _active_problem(ctx)
    reg = _reg((ScriptedTool("api", script={"q": [err("UNAVAILABLE", retryable=False)] * 3}),
                ToolSpec("api", "svc")))
    for _ in range(3):
        out = invoke_tool(ctx, reg, "api", "q")
        d = decide_recovery(ctx, _fc(out, problem_invalidating_evidence=None))
        assert d.kind is not RecoveryKind.REDEFINE
    # even pointing at the failure itself / non-authoritative evidence is not enough
    integrate_evidence(ctx, tool_evidence("E-weak", authority=SourceAuthority.NON_AUTHORITATIVE))
    assert decide_recovery(ctx, _fc(out, problem_invalidating_evidence="E-weak")).kind is not RecoveryKind.REDEFINE
    c = PhaseController(ctx)
    with pytest.raises(IllegalTransitionError):
        c.redefine("E-weak", "tool keeps failing")
    assert ctx.problem.problem_definition.status is ProblemDefinitionStatus.ACTIVE


def test_redefine_on_authoritative_problem_invalidation_versions_state():
    ctx = make_ctx()
    _active_problem(ctx)
    integrate_evidence(ctx, tool_evidence("E-new", "policy registry: process retired"))
    d = decide_recovery(ctx, FailureContext("x", "y", None, None, None, problem_invalidating_evidence="E-new"))
    assert d.kind is RecoveryKind.REDEFINE
    c = PhaseController(ctx)
    c.redefine("E-new", "authoritative registry shows the process is retired")
    pd = ctx.problem.problem_definition
    assert pd.status is ProblemDefinitionStatus.INVALIDATED and pd.invalidated_by == ["E-new"]
    assert ctx.problem.meta.problem_definition_history[-1].version == 1
    assert ctx.runtime.phase is Phase.DEFINE
    assert any("PROBLEM_INVALIDATED" in s for s in ctx.supervision.live_summary)


def test_fallback_authority_and_lazy_freshness():
    ctx = make_ctx()
    fb = activate_fallback(ctx, "api", ToolSpec("snapshot", "warehouse", fallback_for="api"), "api unavailable x2")
    assert fb.authority is SourceAuthority.NON_AUTHORITATIVE
    ok_hist, _ = fallback_permits(ctx, "api", FallbackUsage.HISTORICAL_BASELINE)
    assert ok_hist and fb.freshness_status is FreshnessStatus.NOT_EVALUATED  # not decision-relevant → lazy
    ok_mut, why = fallback_permits(ctx, "api", FallbackUsage.CURRENT_PROTECTED_MUTATION)
    assert not ok_mut and "prohibited" in why
    ok_fresh, _ = fallback_permits(ctx, "api", FallbackUsage.READ_ONLY_SUPPORTING_EVIDENCE,
                                   snapshot_age_minutes=600, max_age_minutes=60, freshness_relevant=True)
    assert not ok_fresh and fb.freshness_status is FreshnessStatus.STALE


def test_retry_transition_requires_eligibility():
    ctx = make_ctx()
    _active_problem(ctx)
    ctx.runtime.phase = Phase.EXECUTE
    c = PhaseController(ctx)
    with pytest.raises(IllegalTransitionError):
        c.retry("just try again")
    ctx.runtime.recovery.retry_eligible = True
    c.retry("transient timeout")
    c.reprofile(["policy owner"], "need owner")
    assert ctx.runtime.phase is Phase.DISCOVER
    assert c.return_from_reprofile() is Phase.EXECUTE
    with pytest.raises(IllegalTransitionError):
        c.reprofile([], "broad rediscovery")


# --------------------------------------------------------------------------- budget / release reserve


def _plan() -> Plan:
    S = ScopeItem
    return Plan("PLAN-1", work_items=[
        WorkItem("W-detect", "detection rules", WorkClass.CORE_FEATURE, 5, [S("detect", "x")], True, True),
        WorkItem("W-ui", "nice dashboard", WorkClass.NICE_TO_HAVE, 40),
        WorkItem("W-refactor", "refactor", WorkClass.BROAD_REFACTOR, 30),
        WorkItem("W-explore", "explore", WorkClass.LOW_VALUE_EXPLORATION, 10),
        WorkItem("W-verify", "blocking tests", WorkClass.RELEASE_BLOCKING_VERIFICATION, 10),
        WorkItem("W-auth", "authority checks", WorkClass.AUTHORITY_SAFETY_CHECK, 5),
        WorkItem("W-pack", "packaging", WorkClass.PACKAGING, 5),
        WorkItem("W-submit", "submission", WorkClass.SUBMISSION, 2),
    ])


def test_release_reserve_entry_reduces_scope():
    ctx = make_ctx()
    with ctx.commit("sd"):
        pass
    set_plan(ctx, _plan())
    ctx.clock = SimulatedClock(255)
    update_budget(ctx)
    assert ctx.runtime.release_runtime.reserve_status is ReserveStatus.APPROACHING
    ctx.clock = SimulatedClock(272)
    update_budget(ctx)
    rr = ctx.runtime.release_runtime
    assert rr.reserve_status is ReserveStatus.ACTIVE and rr.reserve_entered_at == 272
    assert any("RELEASE_RESERVE_ENTERED" in s for s in ctx.supervision.live_summary)
    red = apply_release_reserve(ctx)
    assert set(red.dropped) == {"W-ui", "W-refactor", "W-explore"}
    assert set(red.kept) == {"W-detect", "W-verify", "W-auth", "W-pack", "W-submit"}
    diff = ctx.supervision.state_diff
    assert {e.item_id for e in diff.of_kind(DiffKind.DROPPED_FOR_BUDGET)} == set(red.dropped)
    with pytest.raises(ReserveViolation):
        add_work_item(ctx, WorkItem("W-new", "shiny feature", WorkClass.NICE_TO_HAVE, 5))
    add_work_item(ctx, WorkItem("W-fix", "fix blocking test", WorkClass.RELEASE_BLOCKING_VERIFICATION, 3))


def test_budget_variance_recorded_as_decision_input():
    ctx = make_ctx()
    ctx.clock = SimulatedClock(70)  # still DISCOVER, soft budget ended at 55
    update_budget(ctx)
    br = ctx.runtime.budget_runtime
    assert br.phase_variance["DISCOVER"] == 15
    assert br.variance_reason and br.recovery_action and br.release_reserve_impact
    assert ctx.events.last(EventType.BUDGET_VARIANCE) is not None


def test_reserve_at_risk_when_kept_work_exceeds_remaining_time():
    ctx = make_ctx()
    plan = _plan()
    plan.work_items[0].est_minutes = 30
    set_plan(ctx, plan)
    ctx.clock = SimulatedClock(272)
    update_budget(ctx)
    assert ctx.runtime.release_runtime.reserve_status is ReserveStatus.AT_RISK
    assert any("PACKAGING_AT_RISK" in s for s in ctx.supervision.live_summary)

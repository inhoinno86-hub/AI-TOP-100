"""PHASE D — DEFINE Gate; PHASE E — DESIGN (Structural Remedy before Agent)."""

from __future__ import annotations

import pytest
from builders import grant, make_ctx, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.clock import SimulatedClock
from aitop_harness.core.enums import (
    AgentRole,
    AuthorizationStatus,
    ConstraintStatus,
    ConstraintType,
    Criticality,
    DefineGateResult,
    DesignStage,
    MappingConfidence,
    MetricType,
    RequiredBefore,
    ToolHealth,
    UnknownStatus,
)
from aitop_harness.core.errors import DesignOrderError, IllegalTransitionError
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.authority import Constraint, DomainAuthorization
from aitop_harness.domain.design import StructuralRemedyCandidate
from aitop_harness.domain.epistemic import Conflict, Unknown
from aitop_harness.domain.identity import CanonicalMapping
from aitop_harness.domain.metric import Metric
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.budget import update_budget
from aitop_harness.phases.define import (
    Severity,
    apply_define_gate,
    define_problem,
    evaluate_define_gate,
)
from aitop_harness.phases.design import (
    DesignInputs,
    DesignSession,
    classify_roles,
    design_solution,
    refuse_agentic_expansion_on_tool_failure,
)
from aitop_harness.phases.discover import integrate_evidence
from aitop_harness.core.enums import ConflictType

PUBLISH = [ScopeItem("publish_mapping", "CM-1"), ScopeItem("publish_mapping", "CM-2")]


def _ready(**pd_kw):
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-1"))
    define_problem(ctx, problem(["E-1"], **pd_kw))
    return ctx


def test_define_gate_pass():
    ctx = _ready(intended=[ScopeItem("detect", "x")])
    outcome = evaluate_define_gate(ctx)
    assert outcome.result is DefineGateResult.PASS, [f.message for f in outcome.findings]


def test_critical_unknown_without_resolution_path_fails():
    ctx = _ready(intended=PUBLISH)
    with ctx.commit("u") as ps:
        ps.unknowns["U-1"] = Unknown("U-1", "who owns location registry?", Criticality.CRITICAL,
                                     affects_scope=Scope.of(("publish_mapping", "*")))
    assert evaluate_define_gate(ctx).result is DefineGateResult.FAIL


def test_conditional_pass_inherits_deferred_unknown_as_vob():
    ctx = _ready(intended=PUBLISH, protected=["publish_mapping"])
    grant(ctx, "DA-pub", "publish_mapping", "registry", Scope.of(("publish_mapping", "*")), "E-1")
    with ctx.commit("u") as ps:
        ps.unknowns["U-1"] = Unknown(
            "U-1", "is CM-2 the same site?", Criticality.HIGH,
            affects_scope=Scope.of(("publish_mapping", "CM-2")),
            resolution_path="registry owner confirmation", safe_placeholder="exclude CM-2 from publish",
        )
    outcome = evaluate_define_gate(ctx)
    assert outcome.result is DefineGateResult.CONDITIONAL_PASS
    apply_define_gate(ctx, outcome)
    vob = ctx.problem.verification_obligations["VOB-U-1"]
    assert vob.required_before is RequiredBefore.BEFORE_PROTECTED_ACTION
    assert vob.blocking_scope.items == [ScopeItem("publish_mapping", "CM-2")]
    assert ctx.problem.unknowns["U-1"].status is UnknownStatus.DEFERRED
    assert ctx.problem.unknowns["U-1"].deferred_to_vob == "VOB-U-1"
    assert ctx.supervision.live_summary[-1].startswith("[HIGH] DEFINE_GATE_RESULT")


def test_protected_action_with_unknown_authority_fails():
    ctx = _ready(intended=PUBLISH, protected=["publish_mapping"])
    assert any("authority" == f.check for f in evaluate_define_gate(ctx).blocking())
    with ctx.commit("unknown auth") as ps:
        ps.domain_authorizations["DA"] = DomainAuthorization("DA", "publish_mapping", "registry",
                                                             status=AuthorizationStatus.UNKNOWN)
    assert evaluate_define_gate(ctx).result is DefineGateResult.FAIL


def test_approval_requirement_unknown_and_export_permission_unknown_fail():
    ctx = _ready(intended=PUBLISH, protected=["publish_mapping"], depends_on_exports=["DA-cust"])
    grant(ctx, "DA-pub", "publish_mapping", "registry", Scope.of(("publish_mapping", "*")), "E-1")
    with ctx.commit("c") as ps:
        ps.constraints["K-1"] = Constraint("K-1", ConstraintType.HUMAN_APPROVAL, "approval?",
                                           protected_action="publish_mapping", status=ConstraintStatus.UNKNOWN)
    outcome = evaluate_define_gate(ctx)
    checks = {f.check for f in outcome.blocking()}
    assert {"authority", "data"} <= checks


def test_unresolved_critical_mapping_fails_unless_scoped_by_vob():
    ctx = _ready(intended=PUBLISH, depends_on_mappings=["CM-2"])
    with ctx.commit("m") as ps:
        ps.canonical_mappings["CM-2"] = CanonicalMapping("CM-2", "loc", "A", {"c": "2"}, "B")
    assert evaluate_define_gate(ctx).result is DefineGateResult.FAIL
    from aitop_harness.domain.verification import VerificationObligation
    from aitop_harness.core.enums import Phase
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-9"] = VerificationObligation(
            "VOB-9", "CM-2 identity", Phase.DEFINE, validation_method="owner check",
            required_before=RequiredBefore.BEFORE_PROTECTED_ACTION,
            blocking_scope=Scope.of(("publish_mapping", "CM-2")))
    assert evaluate_define_gate(ctx).result is DefineGateResult.CONDITIONAL_PASS


def test_gate_metric_must_be_extended_and_tool_budget_checks():
    ctx = _ready(intended=PUBLISH, metric_ids=["M-2"], required_tools=["api"])
    with ctx.commit("m") as ps:
        ps.metrics["M-2"] = Metric("M-2", "turnaround", MetricType.DURATION)
    ctx.runtime.tool("api").health = ToolHealth.UNAVAILABLE
    outcome = evaluate_define_gate(ctx)
    assert {"metric", "tool"} <= {f.check for f in outcome.blocking()}
    ctx.clock = SimulatedClock(260)
    update_budget(ctx)
    assert "budget" in {f.check for f in evaluate_define_gate(ctx).blocking()}


def test_conflict_handling_at_gate():
    ctx = _ready(intended=PUBLISH)
    with ctx.commit("c") as ps:
        ps.conflicts["C-1"] = Conflict("C-1", ConflictType.CLAIM_CONFLICT, "CL-1", "CL-2",
                                       decision_impact=Criticality.CRITICAL)
    assert evaluate_define_gate(ctx).result is DefineGateResult.FAIL
    with ctx.commit("strategy") as ps:
        ps.conflicts["C-1"].resolution_strategy = "data reconciliation in VERIFY"
    out = evaluate_define_gate(ctx)
    assert out.result is DefineGateResult.CONDITIONAL_PASS
    assert any(f.severity is Severity.CONDITIONAL and f.check == "conflict" for f in out.findings)


def test_advance_blocked_until_define_gate_passes():
    ctx = _ready(intended=PUBLISH)
    c = PhaseController(ctx)
    c.advance()  # DISCOVER → DEFINE
    with pytest.raises(IllegalTransitionError):
        c.advance()
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    c.advance()


# --------------------------------------------------------------------------- DESIGN


def _passed():
    ctx = _ready(intended=PUBLISH)
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    return ctx


def test_design_order_is_enforced():
    ctx = _passed()
    s = DesignSession(ctx)
    with pytest.raises(DesignOrderError):
        s.why_agent("LLM is cool")  # before root problem / structural remedy
    s.root_problem()
    with pytest.raises(DesignOrderError):
        s.structural_remedies([])  # must record at least one candidate even under time pressure


def test_structural_remedy_recorded_before_agentification_and_roles():
    ctx = _passed()
    inputs = DesignInputs(
        structural_remedies=[StructuralRemedyCandidate("SR-1", "versioned contract", True, False)],
        deterministic_rules_cover_cases=True, llm_reasoning_adds_value=True,
        bridge_sunset_condition="contract v2 deployed", release_scope=PUBLISH,
    )
    sd = design_solution(ctx, inputs)
    stages = [t.stage for t in sd.trace]
    assert stages == list(DesignStage)
    assert stages.index(DesignStage.STRUCTURAL_REMEDY) < stages.index(DesignStage.AGENTIFICATION_GATE)
    assert AgentRole.BRIDGE in sd.agent_roles and AgentRole.PRIMARY_SOLUTION not in sd.agent_roles
    assert sd.unfinished_scope == ["versioned contract"]
    assert ctx.problem.agent_spec is not None and ctx.problem.agent_spec.structural_role == sd.agent_roles


def test_role_classification_deterministic_first():
    base = dict(structural_remedies=[], llm_reasoning_adds_value=True)
    # structural remedy feasible: agent only detects / handles exceptions
    assert classify_roles(DesignInputs(deterministic_rules_cover_cases=True, **base), True, True) == [
        AgentRole.CONTROL_DETECTION, AgentRole.EXCEPTION_HANDLER]
    # no structural remedy, deterministic insufficient, LLM adds value → PRIMARY allowed
    assert classify_roles(DesignInputs(deterministic_rules_cover_cases=False, **base), False, False) == [
        AgentRole.PRIMARY_SOLUTION]
    # bridge requires sunset condition
    ctx = _passed()
    with pytest.raises(DesignOrderError):
        design_solution(ctx, DesignInputs(
            structural_remedies=[StructuralRemedyCandidate("SR", "fix", True, False)],
            deterministic_rules_cover_cases=True, llm_reasoning_adds_value=True))


def test_no_llm_value_means_no_agent():
    ctx = _passed()
    sd = design_solution(ctx, DesignInputs(
        structural_remedies=[StructuralRemedyCandidate("SR", "fix", True, True)],
        deterministic_rules_cover_cases=True, llm_reasoning_adds_value=False))
    assert sd.agent_roles == [] and sd.agentification is not None and not sd.agentification.agent_justified
    assert ctx.problem.agent_spec is None


def test_tool_failure_cannot_make_design_more_agentic():
    with pytest.raises(DesignOrderError):
        refuse_agentic_expansion_on_tool_failure([AgentRole.CONTROL_DETECTION], [AgentRole.PRIMARY_SOLUTION])
    assert refuse_agentic_expansion_on_tool_failure(
        [AgentRole.CONTROL_DETECTION, AgentRole.EXCEPTION_HANDLER], [AgentRole.CONTROL_DETECTION]
    ) == [AgentRole.CONTROL_DETECTION]


def test_design_requires_define_pass():
    ctx = make_ctx()
    with pytest.raises(DesignOrderError):
        DesignSession(ctx)


def test_metric_semantics_same_name_not_merged():
    a = Metric("M-a", "turnaround", MetricType.DURATION, start_event="received", end_event="shipped")
    b = Metric("M-b", "turnaround", MetricType.DURATION, start_event="ordered", end_event="delivered")
    assert a.name == b.name and a.semantic_signature() != b.semantic_signature()
    _ = MappingConfidence  # keep import used

"""Mock regressions #1 and #2.

Mock #1 — Conflicting Stakeholders + Dirty Data:
  Claim vs Fact · Data Quality · Conflict · Process · Handoff · Identity · Monitoring
Mock #2 — Misleading Initial Request:
  initial-request anchoring prevention · Metric semantics · freshness · VOB · Structural Remedy · Agent Role
"""

from __future__ import annotations

from builders import make_ctx, ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.enums import (
    AckLayer,
    AckStatus,
    AgentRole,
    ClaimStatus,
    ConflictType,
    Criticality,
    DataIssueType,
    DefineGateResult,
    DeliveryStatus,
    FreshnessStatus,
    MappingConfidence,
    MetricType,
    Phase,
    ReleaseDecision,
    SemanticValidity,
    UnknownStatus,
    VOBStatus,
)
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.data import DataAsset
from aitop_harness.domain.design import StructuralRemedyCandidate
from aitop_harness.domain.epistemic import Unknown
from aitop_harness.domain.metric import Metric
from aitop_harness.domain.organization import Acknowledgment, ProcessHandoff
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.data_inspection import apply_inspection, inspect_records
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.design import DesignInputs, design_solution
from aitop_harness.phases.discover import (
    establish_fact,
    integrate_evidence,
    record_claim,
    resolve_unknown,
)
from aitop_harness.phases.execute import evidence_from_outcome, invoke_tool
from aitop_harness.phases.handoff import evaluate_freshness, record_acknowledgment
from aitop_harness.phases.identity import TEXTUAL_EQUALITY, propose_mapping
from aitop_harness.phases.release import evaluate_release_gate
from aitop_harness.phases.verify import run_verify
from aitop_harness.supervision.projection import refresh
from aitop_harness.tools.base import ToolRegistry, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool

S = ScopeItem


def test_mock1_conflicting_stakeholders_dirty_data():
    ctx = make_ctx("MOCK-1", "external service org is slow; speed them up")
    seed_org(ctx)
    # conflicting claims from two organizations
    record_claim(
        ctx,
        "CL-A",
        "SH-REQ",
        "ORG-B turnaround is slow",
        assertion="delay.cause",
        value="org_b_slow",
        is_initial_request=True,
        decision_impact=Criticality.HIGH,
    )
    record_claim(
        ctx,
        "CL-B",
        "SH-OWN",
        "we receive incomplete ids",
        assertion="delay.cause",
        value="identifier_mismatch",
        decision_impact=Criticality.HIGH,
    )
    assert not ctx.problem.facts  # claims are not facts
    claim_conflict = next(c for c in ctx.problem.conflicts.values() if c.type is ConflictType.CLAIM_CONFLICT)
    assert claim_conflict.decision_impact is Criticality.HIGH

    # dirty data: registry with key collisions, exact duplicates, status progressions
    rows = [
        {"serial": "X1", "asset": "A-1", "status": "sent", "ts": "2026-09-01T10:00:00"},
        {
            "serial": "X1",
            "asset": "A-9",
            "status": "sent",
            "ts": "2026-09-01T10:00:00",
        },  # same serial, other asset
        {"serial": "X2", "asset": "A-2", "status": "sent", "ts": "2026-09-01T11:00:00"},
        {"serial": "X2", "asset": "A-2", "status": "returned", "ts": "2026-09-03T11:00:00"},  # progression
        {"serial": "X3", "asset": "A-3", "status": "sent", "ts": "2026-09-02T09:00:00"},
        {"serial": "X3", "asset": "A-3", "status": "sent", "ts": "2026-09-02T09:00:00"},  # exact duplicate
    ]
    rep = inspect_records(
        rows,
        schema={"serial": "str", "asset": "str", "status": "str", "ts": "datetime"},
        key_fields=["serial"],
        status_field="status",
        entity_field="asset",
        timestamp_field="ts",
        expected_count=6,
    )
    assert {
        DataIssueType.KEY_COLLISION,
        DataIssueType.STATUS_PROGRESSION,
        DataIssueType.EXACT_RECORD_DUPLICATE,
    } <= rep.issue_types()
    with ctx.commit("registry asset") as ps:
        ps.data_assets["DA-REG"] = DataAsset("DA-REG", "asset registry", organization_id="ORG-B")
    apply_inspection(ctx, "DA-REG", rep)

    # process + handoff: delivered but semantically broken
    with ctx.commit("handoff") as ps:
        ps.process_handoffs["H-1"] = ProcessHandoff("H-1", process_id="P-1", from_org="ORG-A", to_org="ORG-B")
        ps.processes["P-1"].handoff_ids.append("H-1")
        ps.processes["P-1"].manual_steps.append("manual reconciliation")
    record_acknowledgment(ctx, "H-1", Acknowledgment(AckLayer.TRANSPORT, "file received", AckStatus.ACCEPTED))
    record_acknowledgment(
        ctx, "H-1", Acknowledgment(AckLayer.BUSINESS_ACCEPTANCE, "ids matched", AckStatus.REJECTED)
    )
    h = ctx.problem.process_handoffs["H-1"]
    assert h.delivery_status is DeliveryStatus.HEALTHY and h.semantic_validity is SemanticValidity.BROKEN
    assert h.freshness_status is FreshnessStatus.NOT_EVALUATED

    # identity: heterogeneous identifiers — textual match is not identity; collision is unresolved
    m = propose_mapping(
        ctx,
        "CM-X1",
        entity_type="asset",
        source_namespace="ORG-A.serial",
        source_identifiers={"serial": "X1"},
        target_namespace="ORG-B.asset",
        candidate_targets=[{"asset": "A-1"}, {"asset": "A-9"}],
        basis=[TEXTUAL_EQUALITY],
        claimed_confidence=MappingConfidence.HIGH,
        authority=None,
        derived_from=["DA-REG"],
    )
    assert m.confidence is MappingConfidence.UNRESOLVED

    # authoritative data corroborates the identifier claim, contradicts "org B slow"
    integrate_evidence(
        ctx,
        tool_evidence(
            "E-recon",
            "62% of delay is reconciliation wait",
            assertion="delay.cause",
            value="identifier_mismatch",
        ),
    )
    assert ctx.problem.claims["CL-B"].status is ClaimStatus.CORROBORATED
    assert ctx.problem.claims["CL-A"].status is ClaimStatus.CONTRADICTED
    establish_fact(ctx, "F-1", "reconciliation dominates delay", ["E-recon"])

    # monitoring: critical/high go live, routine/noisy go to digest
    refresh(ctx)
    assert ctx.supervision.data_quality_warnings and ctx.supervision.critical_conflicts
    assert all("RETRY_DETAIL" not in s for s in ctx.supervision.live_summary)


def test_mock2_misleading_initial_request():
    ctx = make_ctx("MOCK-2", "build an LLM exception classifier/router for invoices")
    seed_org(ctx)
    seed_success(ctx)
    record_claim(ctx, "CL-REQ", "SH-REQ", "we need an LLM router", is_initial_request=True)

    # handoff delivered on time but stale for continuous intake: freshness evaluated only because it matters
    with ctx.commit("handoff") as ps:
        ps.process_handoffs["H-PO"] = ProcessHandoff(
            "H-PO",
            from_org="ORG-B",
            to_org="ORG-A",
            cadence="daily",
            delivery_status=DeliveryStatus.HEALTHY,
            semantic_validity=SemanticValidity.VALID,
        )
    assert (
        evaluate_freshness(ctx, "H-PO", observed_age_minutes=900, max_age_minutes=60, decision_relevant=False)
        is FreshnessStatus.NOT_EVALUATED
    )
    assert (
        evaluate_freshness(ctx, "H-PO", observed_age_minutes=900, max_age_minutes=60, decision_relevant=True)
        is FreshnessStatus.STALE
    )
    assert ctx.problem.process_handoffs["H-PO"].delivery_status is DeliveryStatus.HEALTHY

    # data shows the dominant cause is reference staleness, not classification
    reg = ToolRegistry()
    reg.register(
        ScriptedTool("erp", script={"exceptions": [ok([{"cause": "PO_NOT_FOUND"}] * 8)]}),
        ToolSpec("erp", "erp"),
    )
    out = invoke_tool(ctx, reg, "erp", "exceptions")
    integrate_evidence(ctx, evidence_from_outcome(ctx, out, "E-exc", "81% exceptions = PO reference missing"))

    # metric semantics: same name, different clocks; success metric must be EXTENDED
    with ctx.commit("metrics") as ps:
        ps.metrics["M-ta-A"] = Metric(
            "M-ta-A", "turnaround", MetricType.DURATION, start_event="invoice_received", end_event="posted"
        )
        ps.metrics["M-ta-B"] = Metric(
            "M-ta-B", "turnaround", MetricType.DURATION, start_event="po_issued", end_event="reference_synced"
        )
    assert (
        ctx.problem.metrics["M-ta-A"].semantic_signature()
        != ctx.problem.metrics["M-ta-B"].semantic_signature()
    )

    # identity ambiguity deferred via VOB (DEFINE) and closed in VERIFY
    with ctx.commit("unknown") as ps:
        ps.unknowns["U-vendor"] = Unknown(
            "U-vendor",
            "vendor ids align across ERP and portal?",
            Criticality.HIGH,
            affects_scope=Scope.of(("auto_match", "*")),
            resolution_path="sample reconciliation",
            safe_placeholder="manual queue",
        )
    scope = [S("detect_stale_reference", "PO"), S("auto_match", "PO")]
    pd = problem(["E-exc"], intended=scope, metric_ids=["M-ta-A"])
    pd.requested_solution = "LLM exception router"
    pd.root_problem = "daily PO reference handoff stale for continuous invoice intake"
    define_problem(ctx, pd)
    gate = evaluate_define_gate(ctx)
    assert gate.result is DefineGateResult.FAIL  # metric not EXTENDED → no anchoring on a vague metric
    ctx.problem.metrics["M-ta-A"].promote(owner="AP", target_value=60)
    gate = evaluate_define_gate(ctx)
    assert gate.result is DefineGateResult.CONDITIONAL_PASS
    apply_define_gate(ctx, gate)
    assert ctx.problem.problem_definition.requested_solution != ctx.problem.problem_definition.root_problem
    assert ctx.problem.unknowns["U-vendor"].status is UnknownStatus.DEFERRED

    # structural remedy (continuous reference sync) before agent; agent is not PRIMARY
    sd = design_solution(
        ctx,
        DesignInputs(
            structural_remedies=[
                StructuralRemedyCandidate("SR-sync", "continuous PO reference sync", True, False)
            ],
            deterministic_rules_cover_cases=True,
            llm_reasoning_adds_value=True,
            bridge_sunset_condition="continuous sync live",
            release_scope=scope,
            minimum_useful_scope=scope[:1],
        ),
    )
    assert AgentRole.PRIMARY_SOLUTION not in sd.agent_roles and AgentRole.EXCEPTION_HANDLER in sd.agent_roles

    # VERIFY closes the VOB with evidence → release
    integrate_evidence(ctx, tool_evidence("E-sample", "sample of 50: vendor ids align"))
    resolve_unknown(ctx, "U-vendor", "aligned in sample", ["E-sample"])
    with ctx.commit("close VOB") as ps:
        ps.verification_obligations["VOB-U-vendor"].status = VOBStatus.RESOLVED
        ps.verification_obligations["VOB-U-vendor"].resolution = "E-sample"
    ctx.runtime.phase = Phase.VERIFY
    from aitop_harness.core.enums import WorkClass
    from aitop_harness.domain.design import WorkItem
    from aitop_harness.phases.budget import set_plan
    from aitop_harness.state.runtime import Plan

    set_plan(
        ctx,
        Plan(
            "P",
            work_items=[
                WorkItem("W", "stale ref detection", WorkClass.CORE_FEATURE, 10, scope[:1], True, True)
            ],
        ),
    )
    res = evaluate_release_gate(ctx, run_verify(ctx, scope))
    assert res.decision in (ReleaseDecision.RELEASE, ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION)
    _ = PhaseController

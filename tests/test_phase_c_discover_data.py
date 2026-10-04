"""PHASE C — DISCOVER + DATA."""

from __future__ import annotations

import pytest
from builders import make_ctx, tool_evidence

from aitop_harness.core.clock import SimulatedClock
from aitop_harness.core.enums import (
    ClaimStatus,
    ConflictType,
    DataIssueType,
    HypothesisStatus,
    MappingConfidence,
    ResultCompleteness,
    SourceAuthority,
    ToolHealth,
)
from aitop_harness.core.errors import StateIntegrityError
from aitop_harness.domain.epistemic import Hypothesis
from aitop_harness.phases.budget import update_budget
from aitop_harness.phases.data_inspection import apply_inspection, inspect_records
from aitop_harness.phases.discover import (
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    establish_fact,
    integrate_evidence,
    rank_actions,
    record_claim,
    revise_evidence,
    select_next_action,
    stakeholder_evidence,
    update_hypothesis,
)
from aitop_harness.phases.identity import TEXTUAL_EQUALITY, propose_mapping
from aitop_harness.domain.data import DataAsset


def _a(aid, impact, cost=5.0, tool=None, **kw):
    return DiscoveryAction(aid, DiscoveryActionKind.TOOL_QUERY if tool else DiscoveryActionKind.STAKEHOLDER_INTERVIEW,
                           "t", "q", InformationValueFactors(decision_impact=impact, time_cost_minutes=cost, **kw),
                           tool_id=tool)


def test_information_value_orders_by_decision_relevance_and_excludes_irrelevant():
    ctx = make_ctx()
    actions = [_a("low", 0.2), _a("high", 0.9, uncertainty=0.9, discriminative_power=0.9), _a("none", 0.0)]
    ranked = rank_actions(ctx, actions)
    assert [r.action.id for r in ranked if not r.excluded] == ["high", "low"]
    none = next(r for r in ranked if r.action.id == "none")
    assert none.excluded and "decision" in none.reason


def test_information_value_uses_tool_health_and_budget():
    ctx = make_ctx()
    ctx.runtime.tool("api").health = ToolHealth.UNAVAILABLE
    ranked = rank_actions(ctx, [_a("via-api", 0.9, tool="api"), _a("interview", 0.5)])
    assert next(r for r in ranked if r.action.id == "via-api").excluded
    # budget: expensive action excluded when it would eat into the release reserve
    ctx2 = make_ctx()
    ctx2.clock = SimulatedClock(250)
    update_budget(ctx2)
    ranked2 = rank_actions(ctx2, [_a("expensive", 0.9, cost=40), _a("cheap", 0.5, cost=5)])
    assert next(r for r in ranked2 if r.action.id == "expensive").excluded
    chosen = select_next_action(ctx2, [_a("expensive", 0.9, cost=40), _a("cheap", 0.5, cost=5)])
    assert chosen is not None and chosen.id == "cheap"


def test_release_reserve_drops_low_value_exploration():
    ctx = make_ctx()
    ctx.clock = SimulatedClock(280)
    update_budget(ctx)
    ranked = rank_actions(ctx, [_a("explore", 0.6, cost=2), _a("safety", 0.6, cost=2, constraint_risk=0.9)])
    assert next(r for r in ranked if r.action.id == "explore").excluded
    assert not next(r for r in ranked if r.action.id == "safety").excluded


def test_claim_is_not_fact_and_conflicts_are_tracked():
    ctx = make_ctx()
    record_claim(ctx, "CL-1", "SH-A", "B is slow", assertion="delay.cause", value="org_b")
    record_claim(ctx, "CL-2", "SH-B", "A sends bad ids", assertion="delay.cause", value="identifiers")
    assert not ctx.problem.facts
    conflicts = list(ctx.problem.conflicts.values())
    assert len(conflicts) == 1 and conflicts[0].type is ConflictType.CLAIM_CONFLICT
    # stakeholder statements cannot establish a fact
    integrate_evidence(ctx, stakeholder_evidence("E-s", "SH-A", "said B is slow", assertion="delay.cause",
                                                 value="org_b"))
    with pytest.raises(StateIntegrityError):
        establish_fact(ctx, "F-1", "B is slow", ["E-s"])
    # authoritative complete data settles claims and yields a fact
    integrate_evidence(ctx, tool_evidence("E-d", assertion="delay.cause", value="identifiers"))
    assert ctx.problem.claims["CL-2"].status is ClaimStatus.CORROBORATED
    assert ctx.problem.claims["CL-1"].status is ClaimStatus.CONTRADICTED
    fact = establish_fact(ctx, "F-1", "identifier mismatch", ["E-d"])
    assert fact.evidence_refs == ["E-d"]
    assert any(c.type is ConflictType.DATA_CONFLICT for c in ctx.problem.conflicts.values())


def test_partial_or_fallback_evidence_cannot_establish_fact():
    ctx = make_ctx()
    integrate_evidence(ctx, tool_evidence("E-p", completeness=ResultCompleteness.PARTIAL))
    integrate_evidence(ctx, tool_evidence("E-f", is_fallback=True, authority=SourceAuthority.NON_AUTHORITATIVE))
    for eid in ("E-p", "E-f"):
        with pytest.raises(StateIntegrityError):
            establish_fact(ctx, f"F-{eid}", "x", [eid])


def test_hidden_ground_truth_never_enters_reasoning():
    ctx = make_ctx()
    e = tool_evidence("E-gt")
    e.hidden_ground_truth = True
    with pytest.raises(StateIntegrityError):
        integrate_evidence(ctx, e)


def test_evidence_revision_is_appended_not_overwritten():
    ctx = make_ctx()
    integrate_evidence(ctx, tool_evidence("E-1", "possible admin delay"))
    integrate_evidence(ctx, tool_evidence("E-2", "physical return late"))
    rev = revise_evidence(ctx, "E-1", "E-2", "admin delay cannot be isolated")
    e1 = ctx.problem.evidence["E-1"]
    assert e1.content == "possible admin delay"  # original preserved
    assert e1.interpretation_history[-1].interpretation == "admin delay cannot be isolated"
    assert rev.previous_interpretation == "possible admin delay"


def test_hypothesis_changes_and_low_value_rejection_is_throttled():
    ctx = make_ctx()
    with ctx.commit("h") as ps:
        ps.hypotheses["H-1"] = Hypothesis("H-1", "printer issue")
    update_hypothesis(ctx, "H-1", HypothesisStatus.REJECTED, "no evidence")
    assert any(s.kind == "LOW_VALUE_HYPOTHESIS_REJECTED" and s.throttled for s in ctx.supervision.pending_digest)


def test_data_inspection_distinguishes_duplicate_semantics():
    rows = [
        {"job": "J1", "status": "in_progress", "ts": "2026-10-01T10:00:00"},
        {"job": "J1", "status": "completed", "ts": "2026-10-01T12:00:00"},  # progression, not duplicate
        {"job": "J2", "status": "completed", "ts": "2026-10-01T12:00:00"},
        {"job": "J2", "status": "completed", "ts": "2026-10-01T12:00:00"},  # exact duplicate
        {"job": "J3", "status": None, "ts": "not-a-date"},
    ]
    rep = inspect_records(rows, schema={"job": "str", "status": "str", "ts": "datetime"},
                          key_fields=["job"], status_field="status", timestamp_field="ts", expected_count=10)
    types = rep.issue_types()
    assert DataIssueType.STATUS_PROGRESSION in types
    assert rep.count(DataIssueType.EXACT_RECORD_DUPLICATE) == 1
    assert DataIssueType.MISSING in types and DataIssueType.MALFORMED in types
    assert rep.completeness is ResultCompleteness.PARTIAL  # 5 of 10 expected
    ctx = make_ctx()
    with ctx.commit("asset") as ps:
        ps.data_assets["DA-1"] = DataAsset(id="DA-1", name="jobs")
    apply_inspection(ctx, "DA-1", rep)
    assert ctx.problem.data_assets["DA-1"].completeness is ResultCompleteness.PARTIAL
    assert ctx.supervision.data_quality_warnings


def test_unknown_expected_count_is_not_complete():
    rep = inspect_records([{"a": 1}], schema={"a": "int"})
    assert rep.completeness is ResultCompleteness.UNKNOWN


def test_identity_mapping_rules():
    ctx = make_ctx()
    textual = propose_mapping(ctx, "CM-1", entity_type="location", source_namespace="A", source_identifiers={"code": "L1"},
                              target_namespace="B", candidate_targets=[{"code": "L1"}], basis=[TEXTUAL_EQUALITY],
                              claimed_confidence=MappingConfidence.HIGH, authority="registry", derived_from=["DA-1"])
    assert textual.confidence is MappingConfidence.MEDIUM  # textual equality ≠ canonical identity
    ambiguous = propose_mapping(ctx, "CM-2", entity_type="location", source_namespace="A",
                                source_identifiers={"code": "L2"}, target_namespace="B",
                                candidate_targets=[{"code": "L2-north"}, {"code": "L2-south"}],
                                basis=["REGISTRY_LOOKUP"], claimed_confidence=MappingConfidence.HIGH,
                                authority="registry", derived_from=["DA-1"])
    assert ambiguous.confidence is MappingConfidence.UNRESOLVED and not ambiguous.target_identifiers
    assert any(c.type is ConflictType.IDENTITY_CONFLICT for c in ctx.problem.conflicts.values())
    composite = propose_mapping(ctx, "CM-3", entity_type="location", source_namespace="A",
                                source_identifiers={"site": "S1", "dock": "3"}, target_namespace="B",
                                candidate_targets=[{"loc": "B-77"}], basis=["REGISTRY_LOOKUP"],
                                claimed_confidence=MappingConfidence.HIGH, authority="registry", derived_from=["DA-1"])
    assert composite.confidence is MappingConfidence.HIGH
    assert composite.provenance is not None and composite.provenance.derived_from == ["DA-1"]

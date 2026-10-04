"""PHASE A — core state foundation."""

from __future__ import annotations

import dataclasses

import pytest

from aitop_harness.core.enums import (
    AckLayer,
    AckStatus,
    DeliveryStatus,
    DiffKind,
    EvidenceSourceType,
    FreshnessStatus,
    Importance,
    MappingConfidence,
    MetricProfile,
    MetricType,
    Phase,
    RequiredBefore,
    SafePointKind,
    SemanticValidity,
    UnknownStatus,
)
from aitop_harness.core.errors import ScopeNarrowingRejected
from aitop_harness.core.events import EventType
from aitop_harness.core.provenance import Provenance
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.core.serialization import from_dict, to_dict
from aitop_harness.domain.epistemic import Evidence, Fact, Unknown
from aitop_harness.domain.identity import CanonicalMapping
from aitop_harness.domain.metric import Metric
from aitop_harness.domain.organization import Acknowledgment, ProcessHandoff
from aitop_harness.domain.verification import VerificationObligation
from aitop_harness.engine.context import CANONICAL_STATES, HarnessContext
from aitop_harness.state.problem import ProblemState, Scenario
from aitop_harness.state.runtime import RecoveryRuntime, RuntimeState
from aitop_harness.state.supervision import SupervisionState


def _ctx() -> HarnessContext:
    return HarnessContext(problem=ProblemState(scenario=Scenario(id="S1", initial_request="do X")))


def _evidence(eid: str = "E-1") -> Evidence:
    return Evidence(
        id=eid,
        source_type=EvidenceSourceType.DATA,
        source_id="DA-1",
        provenance=Provenance(EvidenceSourceType.DATA, "DA-1", method="query", derived_from=["DA-1"]),
        content="row count 120",
    )


def test_exactly_three_canonical_states_and_recovery_is_runtime_substructure():
    ctx = _ctx()
    assert CANONICAL_STATES == ("problem", "runtime", "supervision")
    canonical_types = {type(ctx.problem), type(ctx.runtime), type(ctx.supervision)}
    assert canonical_types == {ProblemState, RuntimeState, SupervisionState}
    # No RecoveryState: recovery lives inside RuntimeState.
    assert isinstance(ctx.runtime.recovery, RecoveryRuntime)
    field_names = {f.name for f in dataclasses.fields(HarnessContext)}
    assert not any("recovery" in n for n in field_names)


def test_states_do_not_share_fields_of_other_planes():
    problem_fields = {f.name for f in dataclasses.fields(ProblemState)}
    runtime_fields = {f.name for f in dataclasses.fields(RuntimeState)}
    supervision_fields = {f.name for f in dataclasses.fields(SupervisionState)}
    # execution/recovery/budget runtime is not in ProblemState
    assert {"tool_runtime", "recovery", "budget_runtime", "release_runtime"}.isdisjoint(problem_fields)
    # human-visibility fields are not in RuntimeState
    assert {"monitoring_policy", "pending_digest", "intervention", "state_diff"}.isdisjoint(runtime_fields)
    # supervision does not hold canonical problem collections
    assert {"evidence", "verification_obligations", "constraints"}.isdisjoint(supervision_fields)


def test_roundtrip_serialization_of_all_states():
    ctx = _ctx()
    with ctx.commit("seed") as ps:
        ps.evidence["E-1"] = _evidence()
        ps.facts["F-1"] = Fact(id="F-1", statement="120 rows", evidence_refs=["E-1"])
        ps.verification_obligations["VOB-1"] = VerificationObligation(
            id="VOB-1",
            unresolved_question="is mapping CM-41 correct?",
            source_phase=Phase.DEFINE,
            required_before=RequiredBefore.BEFORE_PROTECTED_ACTION,
            blocking_scope=Scope.of(("publish_mapping", "CM-41")),
        )
    ctx.runtime.tool("crm").attempt = 2
    snap = ctx.snapshot()
    restored = HarnessContext.restore(snap)
    assert to_dict(restored.problem) == snap["problem"]
    assert to_dict(restored.runtime) == snap["runtime"]
    assert to_dict(restored.supervision) == snap["supervision"]
    vob = restored.problem.verification_obligations["VOB-1"]
    assert vob.required_before is RequiredBefore.BEFORE_PROTECTED_ACTION
    assert vob.blocking_scope.items == [ScopeItem("publish_mapping", "CM-41")]


def test_provenance_is_preserved_through_serialization():
    ev = _evidence()
    back = from_dict(Evidence, to_dict(ev))
    assert back.provenance == ev.provenance
    assert back.provenance.derived_from == ["DA-1"]


def test_fact_requires_evidence():
    with pytest.raises(ValueError):
        Fact(id="F-x", statement="stakeholder said so")


def test_state_diff_is_change_centric_not_full_dump():
    ctx = _ctx()
    with ctx.commit("seed") as ps:
        for i in range(20):
            ps.evidence[f"E-{i}"] = _evidence(f"E-{i}")
        ps.unknowns["U-1"] = Unknown(id="U-1", question="who approves?")
    with ctx.commit("defer U-1") as ps:
        ps.unknowns["U-1"].status = UnknownStatus.DEFERRED
        ps.evidence["E-new"] = _evidence("E-new")
    diff = ctx.supervision.state_diff
    assert diff is not None and diff.from_version == 1 and diff.to_version == 2
    assert {(e.kind, e.item_id) for e in diff.entries} == {
        (DiffKind.DEFERRED, "U-1"),
        (DiffKind.NEW, "E-new"),
    }
    # last commit event carries only the diff, not the 20 unchanged evidence items
    commit_event = ctx.events.last(EventType.STATE_COMMITTED)
    assert commit_event is not None and len(commit_event.payload["diff"]) == 2
    assert ctx.runtime.safe_point is not None
    assert ctx.runtime.safe_point.kind is SafePointKind.AFTER_STATE_COMMIT


def test_state_diff_marks_resolved_and_dropped_for_budget():
    ctx = _ctx()
    with ctx.commit("seed") as ps:
        ps.unknowns["U-1"] = Unknown(id="U-1", question="q")
    with ctx.commit("resolve", dropped_for_budget=["W-9"]) as ps:
        ps.unknowns["U-1"].status = UnknownStatus.RESOLVED
    kinds = {e.kind for e in ctx.supervision.state_diff.entries}
    assert kinds == {DiffKind.RESOLVED, DiffKind.DROPPED_FOR_BUDGET}


def test_commit_rolls_back_and_reraises_on_error():
    ctx = _ctx()
    with pytest.raises(RuntimeError):
        with ctx.commit("broken") as ps:
            ps.evidence["E-1"] = _evidence()
            raise RuntimeError("boom")
    assert "E-1" not in ctx.problem.evidence
    assert ctx.problem.meta.version == 0


def test_vob_required_before_and_blocking_scope_intersection():
    vob = VerificationObligation(
        id="VOB-17",
        unresolved_question="mappings CM-41..43 ambiguous",
        source_phase=Phase.DEFINE,
        required_before=RequiredBefore.BEFORE_PROTECTED_ACTION,
        blocking_scope=Scope.of(
            ("publish_canonical_mapping", "CM-41"), ("publish_canonical_mapping", "CM-42")
        ),
    )
    release = [
        ScopeItem("publish_canonical_mapping", "CM-1"),
        ScopeItem("publish_canonical_mapping", "CM-41"),
    ]
    assert vob.blocking_scope.intersect(release) == [ScopeItem("publish_canonical_mapping", "CM-41")]
    assert vob.blocking_scope.intersect([ScopeItem("publish_canonical_mapping", "CM-1")]) == []


def test_vob_blocking_scope_defaults_to_entire_solution():
    vob = VerificationObligation(id="V", unresolved_question="?", source_phase=Phase.DEFINE)
    assert vob.blocking_scope.entire_solution
    assert vob.blocking_scope.intersect([ScopeItem("anything", "x")]) == [ScopeItem("anything", "x")]


def test_vob_scope_narrowing_requires_committed_evidence():
    ctx = _ctx()
    with ctx.commit("seed") as ps:
        ps.verification_obligations["V"] = VerificationObligation(
            id="V", unresolved_question="?", source_phase=Phase.DEFINE
        )
    with pytest.raises(ScopeNarrowingRejected):
        ctx.narrow_vob_scope("V", Scope.of(("publish", "CM-1")), "E-missing", "looks fine")
    assert ctx.problem.verification_obligations["V"].blocking_scope.entire_solution
    with ctx.commit("evidence") as ps:
        ps.evidence["E-1"] = _evidence()
    ctx.narrow_vob_scope("V", Scope.of(("publish", "CM-1")), "E-1", "registry confirms only CM-1 affected")
    assert not ctx.problem.verification_obligations["V"].blocking_scope.entire_solution
    assert ctx.events.last(EventType.VOB_SCOPE_NARROWED).importance is Importance.HIGH


def test_handoff_delivery_semantic_validity_freshness_independent():
    h = ProcessHandoff(
        id="H-1",
        acknowledgments=[
            Acknowledgment(AckLayer.TRANSPORT, "file received", AckStatus.ACCEPTED),
            Acknowledgment(AckLayer.BUSINESS_ACCEPTANCE, "rows accepted", AckStatus.REJECTED),
        ],
        delivery_status=DeliveryStatus.HEALTHY,
        semantic_validity=SemanticValidity.BROKEN,
    )
    assert h.delivery_status is DeliveryStatus.HEALTHY
    assert h.semantic_validity is SemanticValidity.BROKEN
    # freshness is lazy: not evaluated unless decision-relevant
    assert h.freshness_status is FreshnessStatus.NOT_EVALUATED
    h.semantic_validity = SemanticValidity.VALID
    assert h.delivery_status is DeliveryStatus.HEALTHY  # changing one dimension leaves the others
    assert h.ack(AckLayer.TRANSPORT).status is AckStatus.ACCEPTED
    assert h.ack(AckLayer.BUSINESS_ACCEPTANCE).status is AckStatus.REJECTED


def test_canonical_mapping_is_optional_and_lazy():
    ctx = _ctx()
    assert ctx.problem.canonical_mappings == {}
    snap = ctx.snapshot()
    assert snap["problem"]["canonical_mappings"] == {}
    cm = CanonicalMapping(
        id="CM-1",
        entity_type="location",
        source_namespace="orgA.loc",
        source_identifiers={"site": "S01", "dock": "3"},  # composite key
        target_namespace="orgB.loc",
    )
    assert cm.confidence is MappingConfidence.UNRESOLVED and not cm.is_resolved()
    assert from_dict(CanonicalMapping, to_dict(cm)) == cm


def test_metric_promotion_keeps_id():
    m = Metric(id="M-1", name="turnaround", metric_type=MetricType.DURATION)
    assert m.missing_type_semantics() == ["start_event", "end_event"]
    m.promote(start_event="received", end_event="returned", owner="ops")
    assert m.id == "M-1" and m.profile is MetricProfile.EXTENDED
    assert m.missing_type_semantics() == []


def test_event_log_is_append_only():
    ctx = _ctx()
    e1 = ctx.emit(EventType.SCENARIO_LOADED)
    e2 = ctx.emit(EventType.EVIDENCE_ADDED)
    assert (e1.seq, e2.seq) == (1, 2)
    assert not hasattr(ctx.events, "remove") and not hasattr(ctx.events, "update")
    with pytest.raises(dataclasses.FrozenInstanceError):
        e1.payload = {}  # type: ignore[misc]
    assert ctx.runtime.event_refs == [1, 2]

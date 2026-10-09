"""Mock #6 patch regressions — New Evidence Invalidates Problem.

Every probe that failed in ``docs/implementation/MOCK6_IMPLEMENTATION_REGRESSION_RESULT.md``
(P1/P2, P5, P6b, P7, P9, Variant B) is pinned here, plus the D1-D16 patch semantics
(IDR-REDEFINE-01..08 in ``IMPLEMENTATION_DECISIONS.md``).

The world is a compact replica of the Mock #6 shape: a canonical Problem v1 resting on a causal
premise (missed field reads), a v1 solution path with a pending protected dispatch, and late
authoritative evidence that contradicts the premise (valid reads were rejected at import).
"""

from __future__ import annotations

from typing import Any

import pytest
from builders import design, grant, make_ctx, mutation_ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.enums import (
    AssumptionStatus,
    Criticality,
    DependencyClassification,
    EvidenceStatus,
    ExecutionStatus,
    HumanDecisionKind,
    HypothesisStatus,
    Phase,
    ProblemDefinitionStatus,
    ProtectedActionCategory,
    RecoveryKind,
    ReleaseDecision,
    Reversibility,
    RevisionKind,
    TransitionKind,
    VOBStatus,
    WorkClass,
)
from aitop_harness.core.errors import IllegalTransitionError
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.data import DataAsset
from aitop_harness.domain.design import WorkItem
from aitop_harness.domain.epistemic import Assumption, Hypothesis, Unknown
from aitop_harness.domain.organization import ProcessHandoff
from aitop_harness.engine.context import HarnessContext
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.budget import set_plan
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.discover import (
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    integrate_evidence,
    rank_actions,
    revise_evidence,
    select_next_action,
    stakeholder_evidence,
    update_hypothesis,
)
from aitop_harness.phases.human_gate import GateStatus, HumanDecision, decide, propose_protected_action
from aitop_harness.phases.recovery import (
    FailureContext,
    RecoveryDecision,
    apply_recovery_decision,
    decide_recovery,
)
from aitop_harness.phases.redefine import dismiss_canonical_challenge
from aitop_harness.phases.release import evaluate_release_gate
from aitop_harness.phases.verify import run_verify
from aitop_harness.state.runtime import Plan, ProtectedActionProposal
from aitop_harness.supervision.projection import refresh
from aitop_harness.tools.simulated import ScriptedTool

S = ScopeItem
ROUTES = S("prioritize_routes", "lagging")
DISPATCH = S("push_route_update", "dispatch")
KPI = S("publish_kpi", "dash")
DETECT = S("detect_rejections", "bill")


# ==================== world


def _dispatch(action_id: str = "DISPATCH-1", key: str = "dispatch-prio") -> ProtectedActionProposal:
    return ProtectedActionProposal(
        action_id,
        "push_route_update",
        "priority reads on lagging routes",
        "dispatch",
        [DISPATCH],
        ProtectedActionCategory.PROTECTED_MUTATION,
        why="PD v1: lagging routes leave accounts unread",
        reversibility=Reversibility.REVERSIBLE,
        idempotency_key=key,
        key_evidence=["E-route", "E-read"],
    )


def _world(
    *, route_vob_entire: bool = False, propose: bool = True
) -> tuple[HarnessContext, PhaseController, ScriptedTool]:
    """Canonical Problem v1 ACTIVE, SD-1 designed, EXECUTE, dispatch WAITING_APPROVAL."""
    ctx = make_ctx("MOCK6-PATCH", "auto-answer dispute tickets")
    seed_org(ctx)
    seed_success(ctx)
    with ctx.commit("hypotheses") as ps:
        ps.hypotheses["H-READS"] = Hypothesis(
            "H-READS", "missed reads -> estimates", decision_impact=Criticality.HIGH
        )
        ps.hypotheses["H-OTHER"] = Hypothesis("H-OTHER", "seasonal usage", decision_impact=Criticality.LOW)
    integrate_evidence(
        ctx, tool_evidence("E-read", "41% ESTIMATED", assertion="est.share", value=0.41), supports=["H-READS"]
    )
    integrate_evidence(
        ctx,
        tool_evidence(
            "E-route", "route completion 88%", assertion="route.completion", value=0.88, source="route-log"
        ),
        supports=["H-READS"],
    )
    integrate_evidence(
        ctx,
        stakeholder_evidence(
            "E-field", "SH-OWN", "reads missed: crews short", assertion="est.cause", value="missed_read"
        ),
        supports=["H-READS"],
    )
    update_hypothesis(ctx, "H-READS", HypothesisStatus.SUPPORTED, "E-read + E-route + E-field")
    with ctx.commit("define inputs v1") as ps:
        ps.unknowns["U-ROUTE"] = Unknown(
            "U-ROUTE",
            "does prioritizing routes cut the estimated share?",
            Criticality.HIGH,
            affects_scope=Scope() if route_vob_entire else Scope.of(("prioritize_routes", "*")),
            resolution_path="compare next cycle",
            safe_placeholder="ship without impact claim",
        )
        ps.unknowns["U-TAG"] = Unknown(
            "U-TAG",
            "is the dispute tag applied consistently?",
            Criticality.HIGH,
            affects_scope=Scope.of(("publish_kpi", "*")),
            resolution_path="audit 200 tickets",
            safe_placeholder="KPI provisional",
        )
        ps.assumptions["A-NOREAD"] = Assumption(
            "A-NOREAD", "ESTIMATED means no read", basis="billing practice, E-read"
        )
    grant(ctx, "DA-D", "push_route_update", "dispatch", Scope.of(("push_route_update", "*")), "E-route")
    define_problem(
        ctx,
        problem(
            ["E-read", "E-route", "E-field"],
            intended=[ROUTES, DISPATCH, KPI],
            protected=["push_route_update"],
        ),
    )
    c = PhaseController(ctx)
    c.advance()  # → DEFINE
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    assert ctx.problem.problem_definition.status is ProblemDefinitionStatus.ACTIVE
    c.advance()  # → DESIGN
    design(ctx, [ROUTES, DISPATCH])
    c.advance()  # → EXECUTE
    set_plan(
        ctx,
        Plan(
            "PLAN-1",
            work_items=[
                WorkItem("W-RANK", "route ranking", WorkClass.CORE_FEATURE, 10, [ROUTES], True, True),
                WorkItem("W-DISPATCH", "dispatch push", WorkClass.CORE_FEATURE, 5, [DISPATCH], True, True),
                WorkItem("W-VERIFY", "verification", WorkClass.RELEASE_BLOCKING_VERIFICATION, 10),
            ],
        ),
    )
    tool = ScriptedTool("dispatch", read_only=False, script={"push_route_update": [mutation_ok()]})
    if propose:
        out = propose_protected_action(ctx, _dispatch(), tool)
        assert out.status is GateStatus.WAITING_APPROVAL, out.reasons
    return ctx, c, tool


def _late(ctx: HarnessContext) -> None:
    """Authoritative system-of-record evidence contradicting the v1 causal premise."""
    integrate_evidence(
        ctx,
        tool_evidence(
            "E-mdms",
            "valid AMI reads rejected at billing import",
            assertion="est.cause",
            value="read_rejected",
            source="mdms",
        ),
        contradicts=["H-READS"],
    )


def _revise(ctx: HarnessContext) -> None:
    revise_evidence(
        ctx, "E-read", "E-mdms", "ESTIMATED does not mean no read was collected", invalidates_problem=True
    )
    revise_evidence(ctx, "E-route", "E-mdms", "route lag real but not causal", invalidates_problem=True)


def _redefined() -> tuple[HarnessContext, PhaseController, ScriptedTool]:
    ctx, c, tool = _world()
    _late(ctx)
    _revise(ctx)
    c.redefine("E-mdms", "valid reads were rejected at import, not missed")
    return ctx, c, tool


def _review_map(ctx: HarnessContext) -> dict[tuple[str, str], DependencyClassification]:
    (review,) = ctx.problem.dependency_reviews.values()
    return {(i.object_type, i.object_id): i.classification for i in review.items}


def _define_v2(ctx: HarnessContext, *, protected: list[str] | None = None, version: int = 2):
    pd2 = problem(
        ["E-mdms", "E-read"],
        intended=[DETECT, KPI] + ([DISPATCH] if protected else []),
        protected=protected,
    )
    pd2.root_problem = "import validation rejects valid reads"
    pd2.version = version
    define_problem(ctx, pd2)
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    return pd2


# ==================== P0 — D4 atomic redefine / split-brain


def test_redefine_with_pending_action_is_atomic_and_cancels_the_pending_action():
    ctx, c, tool = _world()
    _late(ctx)
    c.redefine("E-mdms", "premise contradicted")
    pd = ctx.problem.problem_definition
    assert pd.status is ProblemDefinitionStatus.INVALIDATED
    assert ctx.runtime.phase is Phase.DEFINE  # Problem and Runtime moved together: no split-brain
    assert ctx.runtime.pending_protected_action is None
    assert ctx.runtime.execution_status is not ExecutionStatus.WAITING_APPROVAL
    assert ctx.events.of_type(EventType.PROTECTED_ACTION_CANCELLED)
    with pytest.raises(Exception, match="WAITING_APPROVAL"):
        decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tool)
    assert tool.count("push_route_update") == 0


def test_failed_redefine_commits_no_canonical_mutation(monkeypatch):
    ctx, c, tool = _world()
    _late(ctx)
    before_history = len(ctx.problem.meta.problem_definition_history)

    def boom(*_a, **_k):
        raise RuntimeError("transition failed")

    monkeypatch.setattr(PhaseController, "_move", boom)
    with pytest.raises(RuntimeError):
        c.redefine("E-mdms", "premise contradicted")
    ps = ctx.problem
    assert ps.problem_definition.status is ProblemDefinitionStatus.ACTIVE
    assert len(ps.meta.problem_definition_history) == before_history
    assert not ps.dependency_reviews
    assert ps.hypotheses["H-READS"].status is HypothesisStatus.SUPPORTED
    assert ctx.runtime.phase is Phase.EXECUTE
    assert ctx.runtime.pending_protected_action is not None
    assert ctx.events.of_type(EventType.TRANSITION_ROLLED_BACK)


def test_p6b_approve_cannot_execute_stale_action_under_invalidated_problem():
    """Defense in depth: even a (legacy/restored) split-brain state cannot execute the old action."""
    ctx, _, tool = _world()
    with ctx.commit("simulate split-brain") as ps:
        ps.problem_definition.status = ProblemDefinitionStatus.INVALIDATED
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tool)
    assert out.status is GateStatus.BLOCKED
    assert tool.count("push_route_update") == 0
    assert not ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


def test_approve_is_blocked_while_canonical_problem_is_challenged():
    ctx, _, tool = _world()
    _late(ctx)
    assert ctx.runtime.pending_protected_action.revalidation_required
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tool)
    assert out.status is GateStatus.BLOCKED
    assert tool.count("push_route_update") == 0
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL  # human can still REJECT


# ==================== P0 — D5 INVALIDATED Problem progression


def test_p9_invalidated_problem_cannot_progress_or_propose():
    ctx, c, tool = _redefined()
    with pytest.raises(IllegalTransitionError, match="ACTIVE"):
        c.advance()  # DEFINE → DESIGN with v1 INVALIDATED
    assert ctx.runtime.phase is Phase.DEFINE
    out = propose_protected_action(ctx, _dispatch("DISPATCH-1B", "dispatch-b"), tool)
    assert out.status is GateStatus.BLOCKED and any(r.startswith("PROBLEM") for r in out.reasons)
    assert tool.count("push_route_update") == 0
    gate = evaluate_release_gate(ctx, run_verify(ctx, [ROUTES]), [ROUTES])
    assert gate.decision is ReleaseDecision.HOLD


def test_invalidated_problem_blocks_execute_advance_even_with_forced_phase():
    ctx, c, _ = _redefined()
    ctx.runtime.phase = Phase.DESIGN  # forced (e.g. restored state); stale SD-1 must not reach EXECUTE
    with pytest.raises(IllegalTransitionError):
        c.advance()
    assert ctx.runtime.phase is Phase.DESIGN


# ==================== P1 — D1 canonical premise monitoring


def test_d1_late_contradiction_of_canonical_premise_raises_challenge_and_redefine_candidate():
    ctx, _, _ = _world()
    _late(ctx)
    pd = ctx.problem.problem_definition
    assert pd.status is ProblemDefinitionStatus.ACTIVE  # challenge ≠ invalidation
    (challenge,) = pd.open_challenges()
    assert challenge.evidence_id == "E-mdms"
    assert {"E-field", "H-READS"} <= set(challenge.contradicted)
    assert set(challenge.proposed_revisions) >= {"E-read", "E-route", "E-field"}
    cand = ctx.runtime.transition_candidate
    assert (
        cand.kind is TransitionKind.REDEFINE
        and cand.target_phase is Phase.DEFINE
        and "E-mdms" in cand.evidence_refs
    )
    assert ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)[0].importance.value == "CRITICAL"
    notice = [s for s in ctx.supervision.live_summary if "CANONICAL_PROBLEM_CHALLENGED" in s]
    assert len(notice) == 1 and notice[0].startswith("[CRITICAL]")
    for needle in ("PD-1 v1", "E-mdms", "REDEFINE", "REVALIDATION_REQUIRED", "next:"):
        assert needle in notice[0], needle
    # release outcome changes without any operator transition
    gate = evaluate_release_gate(ctx, run_verify(ctx, [ROUTES]), [ROUTES])
    assert gate.decision is ReleaseDecision.HOLD and any("challenged" in h for h in gate.hold_reasons)


def test_d1_conflict_without_premise_dependency_is_not_a_challenge():
    ctx, _, _ = _world()
    integrate_evidence(ctx, tool_evidence("E-x", "a", assertion="weather", value="dry", source="a"))
    integrate_evidence(ctx, tool_evidence("E-y", "b", assertion="weather", value="wet", source="b"))
    assert ctx.events.of_type(EventType.CONFLICT_DETECTED)
    assert not ctx.problem.problem_definition.open_challenges()
    assert ctx.runtime.transition_candidate is None


def test_d1_challenge_is_not_duplicated():
    ctx, _, _ = _world()
    _late(ctx)
    _revise(ctx)  # revisions by the same evidence re-assess the premise
    assert len(ctx.problem.problem_definition.challenges) == 1
    assert len(ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)) == 1


def test_dismissed_challenge_lifts_the_block():
    ctx, _, tool = _world()
    _late(ctx)
    dismiss_canonical_challenge(ctx, "E-mdms", "human review: contradiction not material")
    assert not ctx.problem.problem_definition.open_challenges()
    assert ctx.runtime.transition_candidate is None
    assert decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tool).status is GateStatus.EXECUTED


# ==================== IDR-RV10-01 — bounded REPROFILE under an open challenge


def _transition_proposal(kind: str, *, targets: list[str] | None = None, confidence: float = 0.8):
    from aitop_harness.reasoning.models import ReprofileProposal, TransitionProposal

    reprofile = (
        ReprofileProposal(
            targets=targets or [],
            reason="need more evidence",
            required_evidence=[],
            expected_decision_impact="HIGH",
        )
        if targets is not None
        else None
    )
    return TransitionProposal(
        transition_candidate=kind,
        trigger_evidence_refs=["E-mdms"],
        rationale="not confident enough yet to redefine",
        affected_scope=["PD-1"],
        confidence=confidence,
        reprofile=reprofile,
    )


def test_reprofile_under_open_challenge_leaves_the_challenge_open_and_does_not_execute_redefine():
    """A17/IDR-RV10-01: REPROFILE never touches the Problem's premise, so a Reasoner that wants more
    evidence before committing to REDEFINE is not forced into Human escalation on its first ask — but the
    challenge itself is never dismissed by the Reasoner (IDR-REASON-06 still holds)."""
    from aitop_harness.engine.proposals import evaluate_transition

    ctx, _, _ = _world()
    _late(ctx)
    (challenge,) = ctx.problem.problem_definition.open_challenges()
    prop = _transition_proposal("REPROFILE", targets=["H-OTHER"])
    verdict = evaluate_transition(ctx, prop, "R-TEST")
    assert verdict.execute_reprofile_under_challenge is True
    assert verdict.execute_redefine is False
    assert verdict.escalate is False
    assert verdict.reprofile_targets == ["H-OTHER"]
    # challenge is untouched — the Core allowed one more look, it did not dismiss anything
    assert challenge.status.value == "OPEN"
    assert ctx.problem.problem_definition.open_challenges() == [challenge]


def test_reprofile_under_open_challenge_without_targets_still_escalates():
    """No valid reprofile targets ⇒ there is nothing bounded to grant; falls back to the pre-RV10 rule."""
    from aitop_harness.engine.proposals import evaluate_transition

    ctx, _, _ = _world()
    _late(ctx)
    prop = _transition_proposal("REPROFILE", targets=[])
    verdict = evaluate_transition(ctx, prop, "R-TEST")
    assert verdict.execute_reprofile_under_challenge is False
    assert verdict.escalate is True


def test_reprofile_under_open_challenge_low_confidence_escalates():
    from aitop_harness.engine.proposals import evaluate_transition

    ctx, _, _ = _world()
    _late(ctx)
    prop = _transition_proposal("REPROFILE", targets=["H-OTHER"], confidence=0.1)
    verdict = evaluate_transition(ctx, prop, "R-TEST")
    assert verdict.execute_reprofile_under_challenge is False
    assert verdict.escalate is True


def test_replan_or_continue_under_open_challenge_still_escalates_unchanged():
    """Only REPROFILE gets the IDR-RV10-01 bounded allowance — REPLAN/CONTINUE/RETRY under an open
    challenge are unchanged: the Reasoner still cannot talk the Core out of the challenge any other way."""
    from aitop_harness.engine.proposals import evaluate_transition

    ctx, _, _ = _world()
    _late(ctx)
    prop = _transition_proposal("REPLAN", targets=None)
    verdict = evaluate_transition(ctx, prop, "R-TEST")
    assert verdict.escalate is True
    assert verdict.execute_reprofile_under_challenge is False


class _NoopEnv:
    """Minimal Environment stand-in: no catalog, no executor — only _handle_challenge's control flow,
    not DISCOVER's action loop, is under test here."""

    registry = None

    def catalog(self, stage: str, ctx: HarnessContext) -> list[Any]:
        return []

    def executor(self, resource: str) -> Any:
        return None


def _reprofile_transition_handler(targets: list[str], confidence: float = 0.8) -> Any:
    def handler(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        trig = data["trigger"]["challenge"]["evidence_id"]
        return {
            "transition_candidate": "REPROFILE",
            "trigger_evidence_refs": [trig],
            "rationale": "need more evidence before redefining",
            "affected_scope": [],
            "confidence": confidence,
            "reprofile_targets": targets,
            "reprofile_reason": "confirm the mechanism",
            "reprofile_required_evidence": [],
            "reprofile_expected_decision_impact": "HIGH",
        }

    return handler


def test_handle_challenge_bound_allows_one_reprofile_round_then_escalates_on_the_next():
    """Orchestrator-level IDR-RV10-01: a challenge with no pending protected action in the way gets one
    bounded REPROFILE round — the challenge stays OPEN and DISCOVER re-runs — but a second REPROFILE
    proposal on the same still-open challenge is refused once AutonomousConfig.max_challenge_reprofiles is
    spent, falling back to the pre-RV10 Human escalation exactly as before."""
    from aitop_harness.engine.autonomous import AutonomousConfig, AutonomousOrchestrator
    from aitop_harness.engine.environment import ScriptedHuman
    from aitop_harness.reasoning.providers.fake import FakeProvider
    from aitop_harness.reasoning.reasoner import Reasoner

    ctx, _, _ = _world(propose=False)  # no pending protected action: isolates the REPROFILE path itself
    _late(ctx)
    handlers = {"propose_transition": _reprofile_transition_handler(["H-OTHER"])}
    reasoner = Reasoner(FakeProvider(handlers))
    orch = AutonomousOrchestrator(
        ctx, _NoopEnv(), reasoner, ScriptedHuman([]), config=AutonomousConfig(max_challenge_reprofiles=1)
    )

    orch._handle_challenge()
    assert orch.challenge_reprofile_attempts == {"E-mdms": 1}
    assert ctx.runtime.phase is Phase.DISCOVER
    assert ctx.runtime.execution_status is ExecutionStatus.RUNNING
    (challenge,) = ctx.problem.problem_definition.open_challenges()  # still open, never dismissed
    assert challenge.evidence_id == "E-mdms"

    orch._handle_challenge()
    assert orch.challenge_reprofile_attempts == {"E-mdms": 1}  # bound did not advance further
    assert ctx.runtime.execution_status is ExecutionStatus.HOLD
    assert orch.halt_reason is not None
    assert "Human decides" in orch.halt_reason
    assert "after 1 prior attempt" in orch.halt_reason


# ==================== P1 — D2 redefine vs replan (P5)


def test_p5_path_only_authoritative_evidence_yields_replan_not_redefine():
    ctx, c, _ = _world()
    integrate_evidence(
        ctx,
        tool_evidence(
            "E-api",
            "dispatch API v2 retired; use v3",
            assertion="dispatch.endpoint",
            value="v3",
            source="notice",
        ),
    )
    assert not ctx.problem.problem_definition.open_challenges()
    fc = FailureContext(
        "dispatch",
        "push_route_update",
        None,
        "ENDPOINT_RETIRED",
        False,
        alternate_paths=["dispatch API v3"],
        problem_invalidating_evidence="E-api",
    )
    d = decide_recovery(ctx, fc)
    assert d.kind is RecoveryKind.REPLAN
    assert "E-api" in d.rationale  # the rejected assertion is explained, not silently dropped
    decide(ctx, HumanDecision(HumanDecisionKind.REJECT), ScriptedTool("dispatch", read_only=False))
    with pytest.raises(IllegalTransitionError, match="premise"):
        c.redefine("E-api", "path-only evidence")
    assert ctx.problem.problem_definition.status is ProblemDefinitionStatus.ACTIVE
    assert not ctx.events.of_type(EventType.PROBLEM_INVALIDATED)


def test_d2_true_contradiction_yields_redefine_decision():
    ctx, _, _ = _world()
    _late(ctx)
    d = decide_recovery(
        ctx, FailureContext("n/a", "n/a", None, None, None, problem_invalidating_evidence="E-mdms")
    )
    assert d.kind is RecoveryKind.REDEFINE


# ==================== P1 — D3 pre-canonical redefine (P1/P2)


def test_p1_p2_draft_problem_cannot_be_redefined():
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-1", "obs", assertion="cause", value="a"))
    define_problem(ctx, problem(["E-1"]))
    c = PhaseController(ctx)
    c.advance()  # DEFINE, Problem still DRAFT (gate not applied)
    integrate_evidence(ctx, tool_evidence("E-2", "contradiction", assertion="cause", value="b", source="sor"))
    assert (
        not ctx.problem.problem_definition.open_challenges()
    )  # pre-canonical: hypothesis work, not redefine
    d = decide_recovery(
        ctx, FailureContext("n/a", "n/a", None, None, None, problem_invalidating_evidence="E-2")
    )
    assert d.kind is not RecoveryKind.REDEFINE
    with pytest.raises(IllegalTransitionError, match="canonical"):
        c.redefine("E-2", "pre-canonical contradiction")
    assert ctx.problem.problem_definition.status is ProblemDefinitionStatus.DRAFT
    assert not ctx.events.of_type(EventType.PROBLEM_INVALIDATED)
    assert ctx.runtime.phase is Phase.DEFINE


# ==================== P1 — D8 dependency review / pending action


def test_d8_redefine_runs_selective_dependency_review():
    ctx, _, _ = _redefined()
    ps = ctx.problem
    m = _review_map(ctx)
    DC = DependencyClassification
    assert m[("ProblemDefinition", "PD-1@v1")] is DC.INVALIDATED
    assert (
        m[("Hypothesis", "H-READS")] is DC.INVALIDATED
        and ps.hypotheses["H-READS"].status is HypothesisStatus.REJECTED
    )
    assert m[("Hypothesis", "H-OTHER")] is DC.STILL_VALID
    assert m[("Assumption", "A-NOREAD")] is DC.INVALIDATED
    assert ps.assumptions["A-NOREAD"].status is AssumptionStatus.INVALIDATED
    assert m[("VerificationObligation", "VOB-U-ROUTE")] is DC.INVALIDATED
    assert ps.verification_obligations["VOB-U-ROUTE"].status is VOBStatus.INVALIDATED
    assert m[("VerificationObligation", "VOB-U-TAG")] is DC.NEEDS_REEVALUATION
    assert ps.verification_obligations["VOB-U-TAG"].status is VOBStatus.OPEN
    assert m[("SolutionDesign", "SD-1")] is DC.INVALIDATED
    assert m[("StructuralRemedyCandidate", "SR-1")] is DC.INVALIDATED
    assert m[("AgentSpec", "agent-SD-1")] is DC.SUPERSEDED
    assert any(k[0] == "AgentRole" and v is DC.SUPERSEDED for k, v in m.items())
    assert m[("SuccessCriterion", "SC-1")] is DC.NEEDS_REEVALUATION
    assert m[("Metric", "M-1")] is DC.NEEDS_REEVALUATION
    assert m[("WorkItem", "W-RANK")] is DC.INVALIDATED and m[("WorkItem", "W-DISPATCH")] is DC.INVALIDATED
    assert m[("WorkItem", "W-VERIFY")] is DC.STILL_VALID
    assert {w.id: w.status for w in ctx.runtime.current_plan.work_items}["W-DISPATCH"] == "INVALIDATED"
    assert m[("PendingProtectedAction", "GATE-DISPATCH-1")] is DC.INVALIDATED
    # redefine ≠ full reset: organisation / authority / evidence preserved untouched
    (review,) = ps.dependency_reviews.values()
    assert review.preserved["organizations"] == 2 and review.preserved["domain_authorizations"] == 1
    assert all(e.status is EvidenceStatus.ACTIVE for e in ps.evidence.values())
    assert review.trigger_evidence == "E-mdms" and review.problem_ref == "PD-1@v1"
    assert ctx.events.of_type(EventType.DEPENDENCY_REVIEW_CREATED)
    (conflict,) = [c for c in ps.conflicts.values() if {c.side_a, c.side_b} == {"E-field", "E-mdms"}]
    assert m[("Conflict", conflict.id)] is DC.SUPERSEDED and conflict.status.value == "RESOLVED"


def test_d8_assumption_without_revised_basis_is_only_flagged_for_reevaluation():
    ctx, c, _ = _world()
    _late(ctx)
    c.redefine("E-mdms", "premise contradicted")
    assert _review_map(ctx)[("Assumption", "A-NOREAD")] is DependencyClassification.NEEDS_REEVALUATION
    assert ctx.problem.assumptions["A-NOREAD"].status is AssumptionStatus.ACTIVE


def test_new_protected_action_after_redefine_requires_fresh_gate_and_approval():
    ctx, c, tool = _redefined()
    _define_v2(ctx, protected=["push_route_update"])
    c.advance()  # DESIGN
    design(ctx, [DETECT, DISPATCH])
    c.advance()  # EXECUTE
    out = propose_protected_action(ctx, _dispatch("DISPATCH-2", "dispatch-v2"), tool)
    assert out.status is GateStatus.WAITING_APPROVAL and out.gate_id == "GATE-DISPATCH-2"
    pending = ctx.runtime.pending_protected_action
    assert pending.problem_ref == "PD-1@v2" and pending.confirmation.decision is None
    assert tool.count("push_route_update") == 0
    assert decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), tool).status is GateStatus.EXECUTED
    assert tool.count("push_route_update") == 1


# ==================== P1/P2 — D6 version + lineage (P7), D9/D10 VOB


def test_p7_version_is_harness_owned_and_stale_design_cannot_reach_execute():
    ctx, c, _ = _redefined()
    pd2 = _define_v2(ctx, version=1)  # caller tries to reuse v1
    assert pd2.version == 2 and pd2.supersedes == "PD-1@v1"
    (v1,) = ctx.problem.meta.problem_definition_history
    assert (
        v1.version == 1 and v1.status is ProblemDefinitionStatus.INVALIDATED and v1.superseded_by == "PD-1@v2"
    )
    c.advance()  # DESIGN
    with pytest.raises(IllegalTransitionError, match="stale"):
        c.advance()  # stale SD-1 (v1)


def test_active_canonical_problem_cannot_be_replaced_without_redefine():
    ctx, _, _ = _world()
    with pytest.raises(IllegalTransitionError, match="redefine"):
        define_problem(ctx, problem(["E-read"]))


def test_d9_d10_vob_lifecycle_and_agent_spec_after_redefine():
    ctx, c, _ = _redefined()
    _define_v2(ctx)
    vobs = ctx.problem.verification_obligations
    assert vobs["VOB-U-TAG"].status is VOBStatus.OPEN and vobs["VOB-U-TAG"].problem_version == 2
    assert vobs["VOB-U-ROUTE"].status is VOBStatus.INVALIDATED
    c.advance()
    design(ctx, [DETECT])
    assert ctx.problem.agent_spec.problem_reference == "PD-1@v2"
    assert ctx.problem.agent_spec.verification_obligations == ["VOB-U-TAG"]


@pytest.mark.parametrize("entire", [False, True], ids=["scoped", "variant_b_entire_scope"])
def test_variant_b_stale_vob_does_not_hold_v2_release(entire):
    ctx, c, _ = _world(route_vob_entire=entire, propose=not entire)
    _late(ctx)
    _revise(ctx)
    c.redefine("E-mdms", "premise contradicted")
    _define_v2(ctx)
    c.advance()
    design(ctx, [DETECT])
    c.advance()
    set_plan(
        ctx,
        Plan(
            "PLAN-2",
            work_items=[WorkItem("V2-DETECT", "detect", WorkClass.CORE_FEATURE, 5, [DETECT], True, True)],
        ),
    )
    c.advance()  # VERIFY
    report = run_verify(ctx, [DETECT])
    c.advance()  # RELEASE
    gate = evaluate_release_gate(ctx, report, [DETECT])
    assert gate.decision is not ReleaseDecision.HOLD, gate.hold_reasons
    assert not any("U-ROUTE" in x for x in gate.hold_reasons + gate.known_limitations)
    c.finish()


def test_verify_run_of_invalidated_problem_cannot_open_release_for_successor():
    ctx, c, _ = _world(propose=False)
    with ctx.commit("verify bookkeeping") as ps:
        ps.validation.verify_runs.append({"problem_ref": "PD-1@v1", "layer1_passed": True})
    _late(ctx)
    c.redefine("E-mdms", "premise contradicted")
    _define_v2(ctx)
    c.advance()
    design(ctx, [DETECT])
    c.advance()  # EXECUTE
    c.advance()  # VERIFY
    with pytest.raises(IllegalTransitionError, match="VERIFY"):
        c.advance()  # the v1 verify run does not count for v2


# ==================== P2 — D7 idempotency / immutable history


def test_d7_duplicate_redefine_is_an_explicit_noop():
    ctx, c, _ = _redefined()
    ps = ctx.problem
    snapshot = (
        len(ps.meta.problem_definition_history),
        len(ps.decision_log),
        len(ctx.events.of_type(EventType.PROBLEM_INVALIDATED)),
        list(ps.problem_definition.invalidated_by),
        len(ps.dependency_reviews),
    )
    c.redefine("E-mdms", "again")
    assert snapshot == (
        len(ps.meta.problem_definition_history),
        len(ps.decision_log),
        len(ctx.events.of_type(EventType.PROBLEM_INVALIDATED)),
        list(ps.problem_definition.invalidated_by),
        len(ps.dependency_reviews),
    )
    assert ps.problem_definition.invalidated_by == ["E-mdms"]
    assert ctx.events.of_type(EventType.REDEFINE_NOOP)
    assert sum("PROBLEM_INVALIDATED" in s for s in ctx.supervision.live_summary) == 1


def test_history_entries_are_snapshots_not_aliases():
    ctx, _, _ = _redefined()
    (v1,) = ctx.problem.meta.problem_definition_history
    assert v1 is not ctx.problem.problem_definition
    ctx.problem.problem_definition.root_problem = "mutated later"
    assert v1.root_problem == "interface contract mismatch"
    assert v1.status is ProblemDefinitionStatus.INVALIDATED


# ==================== P2 — D11 revision kind + affected objects


def test_d11_interpretation_only_revision_keeps_observation_citable():
    ctx, _, _ = _world()
    _late(ctx)
    rev = revise_evidence(ctx, "E-read", "E-mdms", "ESTIMATED != no read", invalidates_problem=True)
    assert rev.revision_kind is RevisionKind.INTERPRETATION_ONLY
    assert ctx.problem.evidence["E-read"].status is EvidenceStatus.ACTIVE
    assert ctx.problem.evidence["E-read"].interpretation_history[-1].interpretation == "ESTIMATED != no read"
    assert "PD-1@v1" in rev.affected_objects["problem_definitions"]
    assert "H-READS" in rev.affected_objects["hypotheses"]
    assert "A-NOREAD" in rev.affected_objects["assumptions"]
    assert "SD-1" in rev.affected_objects["designs"]
    assert rev.proposed_by_harness  # the challenge proposed this revision


def test_d11_observation_contradiction_marks_observation_revised():
    ctx, _, _ = _world()
    integrate_evidence(
        ctx, tool_evidence("E-read2", "recount: 20% ESTIMATED", assertion="est.share", value=0.2, source="b")
    )
    rev = revise_evidence(ctx, "E-read", "E-read2", "share was miscounted")
    assert rev.revision_kind is RevisionKind.OBSERVATION_INVALIDATED
    assert ctx.problem.evidence["E-read"].status is EvidenceStatus.REVISED


def test_revision_is_linked_to_the_dependency_review():
    ctx, _, _ = _redefined()
    (review,) = ctx.problem.dependency_reviews.values()
    for r in ctx.problem.evidence_revisions.values():
        assert r.dependency_review_id == review.id
        assert r.id in review.evidence_revisions


# ==================== P2 — D12 targeted reprofile (P8)


def _iv(di: float) -> InformationValueFactors:
    return InformationValueFactors(di, 0.5, 0.5, 0.9, time_cost_minutes=2)


def test_p8_targeted_reprofile_excludes_unrelated_actions():
    ctx = make_ctx()
    with ctx.commit("assets") as ps:
        ps.data_assets["DA-RULES"] = DataAsset(
            "DA-RULES", "rule log", organization_id="ORG-U", source="billing-config"
        )
        ps.data_assets["DA-MDMS"] = DataAsset(
            "DA-MDMS", "AMI reads", organization_id="ORG-AMI", source="mdms-export"
        )
        ps.data_assets["DA-BILL"] = DataAsset(
            "DA-BILL", "bills", organization_id="ORG-U", source="billing-db"
        )
        ps.process_handoffs["H-MDMS-BILL"] = ProcessHandoff("H-MDMS-BILL", from_org="ORG-AMI", to_org="ORG-U")
    c = PhaseController(ctx)
    c.reprofile(["DA-RULES", "H-MDMS-BILL"], "confirm rejection mechanism")
    old = DiscoveryAction(
        "A-old", DiscoveryActionKind.TOOL_QUERY, "billing-db", "q", _iv(0.95), tool_id="billing-db"
    )
    rules = DiscoveryAction(
        "R-rules", DiscoveryActionKind.TOOL_QUERY, "billing-config", "q", _iv(0.5), tool_id="billing-config"
    )
    units = DiscoveryAction(
        "R-units", DiscoveryActionKind.TOOL_QUERY, "mdms-export", "q", _iv(0.4), tool_id="mdms-export"
    )
    ranked = {r.action.id: r for r in rank_actions(ctx, [old, rules, units])}
    assert ranked["A-old"].excluded and "reprofile" in ranked["A-old"].reason
    assert not ranked["R-rules"].excluded and not ranked["R-units"].excluded
    assert select_next_action(ctx, [old, rules, units]).id == "R-rules"
    prereq = DiscoveryAction(
        "A-pre",
        DiscoveryActionKind.TOOL_QUERY,
        "billing-db",
        "q",
        _iv(0.99),
        tool_id="billing-db",
        prerequisite_for=["DA-RULES"],
    )
    r = {x.action.id: x for x in rank_actions(ctx, [prereq])}["A-pre"]
    assert not r.excluded and "prerequisite" in r.reason
    c.return_from_reprofile()
    assert not {x.action.id: x for x in rank_actions(ctx, [old])}["A-old"].excluded


# ==================== P2 — D13 transition precedence


def test_d13_redefine_candidate_is_not_overwritten_by_reject_or_replan():
    ctx, c, tool = _world()
    _late(ctx)
    apply_recovery_decision(
        ctx,
        RecoveryDecision(RecoveryKind.REPLAN, "alternate path"),
        FailureContext("dispatch", "push", None, "X", False),
    )
    assert ctx.runtime.transition_candidate.kind is TransitionKind.REDEFINE
    decide(ctx, HumanDecision(HumanDecisionKind.REJECT, "거절합니다"), tool)
    assert ctx.runtime.transition_candidate.kind is TransitionKind.REDEFINE
    with pytest.raises(IllegalTransitionError, match="challenged"):
        c.replan("route around it")


# ==================== P2 — D14/D15 monitoring + projection


def test_d14_problem_invalidated_signal_is_immediate_complete_and_single():
    ctx, _, _ = _redefined()
    notices = [s for s in ctx.supervision.live_summary if "PROBLEM_INVALIDATED" in s]
    assert len(notices) == 1 and notices[0].startswith("[CRITICAL]")
    for needle in (
        "PD-1 v1",
        "E-mdms",
        "REDEFINE: EXECUTE → DEFINE",
        "GATE-DISPATCH-1 CANCELLED",
        "affected:",
        "next:",
    ):
        assert needle in notices[0], needle
    assert not any("REDEFINE" in s.message for s in ctx.supervision.pending_digest)


def test_d15_stale_hypothesis_not_projected_as_current():
    ctx, _, _ = _world()
    _late(ctx)
    refresh(ctx)
    assert "CHALLENGED" in ctx.supervision.current_problem
    ctx2, _, _ = _redefined()
    refresh(ctx2)
    assert not any("H-READS" in h for h in ctx2.supervision.top_hypotheses)
    assert ctx2.supervision.dependency_review  # Human sees what was re-evaluated


# ==================== P2 — D16 Event Log persistence


def test_d16_event_log_persists_with_snapshot():
    ctx, _, _ = _redefined()
    snap = ctx.snapshot()
    assert len(snap["events"]) == len(ctx.events)
    restored = HarnessContext.restore(snap)
    assert len(restored.events) == len(ctx.events)
    assert restored.events.last().type is ctx.events.last().type
    assert restored.snapshot() == snap

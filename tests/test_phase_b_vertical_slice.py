"""PHASE B — thin end-to-end vertical slice through the real phase modules."""

from __future__ import annotations

from builders import make_ctx, ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.enums import (
    DefineGateResult,
    DiffKind,
    ExecutionStatus,
    Phase,
    ReleaseDecision,
    ResultCompleteness,
)
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import ScopeItem
from aitop_harness.domain.design import StructuralRemedyCandidate
from aitop_harness.engine.slice import SliceInputs, run_vertical_slice
from aitop_harness.phases.design import DesignInputs
from aitop_harness.phases.discover import (
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    stakeholder_evidence,
)
from aitop_harness.tools.base import ToolRegistry, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool

SCOPE = [ScopeItem("detect_rejects", "feed-1")]


def _inputs(*, root_from_tool: bool = True) -> SliceInputs:
    actions = [
        DiscoveryAction(
            "A-db",
            DiscoveryActionKind.TOOL_QUERY,
            "db",
            "reject_log",
            InformationValueFactors(
                decision_impact=0.9,
                uncertainty=0.8,
                discriminative_power=0.9,
                answerability=0.9,
                time_cost_minutes=3,
            ),
            tool_id="db",
        ),
        DiscoveryAction(
            "A-int",
            DiscoveryActionKind.STAKEHOLDER_INTERVIEW,
            "SH-REQ",
            "what is slow?",
            InformationValueFactors(decision_impact=0.4, time_cost_minutes=8),
        ),
        DiscoveryAction(
            "A-noise",
            DiscoveryActionKind.DOCUMENT_REVIEW,
            "wiki",
            "history",
            InformationValueFactors(decision_impact=0.0),
        ),
    ]

    def build(action, outcome):
        if action.id == "A-db":
            assert outcome is not None and outcome.completeness is ResultCompleteness.COMPLETE
            return tool_evidence(
                "E-db", "rejects cluster on location code", assertion="reject.cause", value="contract"
            ), []
        return stakeholder_evidence(
            "E-int", "SH-REQ", "partner is slow", assertion="reject.cause", value="partner_slow"
        ), []

    return SliceInputs(
        actions=actions,
        evidence_builder=build,
        problem_definition=lambda ctx: problem(["E-db"] if root_from_tool else ["E-int"], intended=SCOPE),
        design_inputs=DesignInputs(
            structural_remedies=[StructuralRemedyCandidate("SR-1", "contract fix", True, False)],
            deterministic_rules_cover_cases=True,
            llm_reasoning_adds_value=True,
            bridge_sunset_condition="contract v2 live",
            release_scope=SCOPE,
            minimum_useful_scope=SCOPE,
        ),
        release_scope=SCOPE,
    )


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(
        ScriptedTool("db", script={"reject_log": [ok([{"id": i} for i in range(5)])]}),
        ToolSpec("db", dependency="db"),
    )
    return reg


def test_vertical_slice_runs_end_to_end():
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    result = run_vertical_slice(ctx, _registry(), _inputs())

    # Information Value: zero-impact action never selected; tool evidence picked first
    assert result.discovered == ["A-db", "A-int"]
    # claim/evidence conflict tracked (stakeholder says partner slow; data says contract)
    assert any(c.assertion == "reject.cause" for c in ctx.problem.conflicts.values())
    assert result.define.result in (DefineGateResult.PASS, DefineGateResult.CONDITIONAL_PASS)
    assert result.design is not None and result.design.trace[0].stage.value == "ROOT_PROBLEM"
    assert result.verify is not None and result.verify.layer1_passed
    assert result.decision in (ReleaseDecision.RELEASE, ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION)
    assert ctx.runtime.phase is Phase.RELEASE
    assert ctx.runtime.execution_status is ExecutionStatus.RELEASED
    # State diff exists and is change-centric
    assert ctx.supervision.state_diff is not None
    assert all(e.kind in DiffKind for e in ctx.supervision.state_diff.entries)
    # phase transitions are explicit events in order
    transitions = [
        (e.payload["from"], e.payload["to"])
        for e in ctx.events.of_type(EventType.PHASE_TRANSITION)
        if "from" in e.payload
    ]
    assert transitions[:5] == [
        ("DISCOVER", "DEFINE"),
        ("DEFINE", "DESIGN"),
        ("DESIGN", "EXECUTE"),
        ("EXECUTE", "VERIFY"),
        ("VERIFY", "RELEASE"),
    ]


def test_vertical_slice_holds_when_problem_rests_only_on_initial_request_claims():
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    result = run_vertical_slice(ctx, _registry(), _inputs(root_from_tool=False))
    assert result.define.result is DefineGateResult.FAIL
    assert any("anchoring" in f.message for f in result.define.blocking())
    assert result.decision is ReleaseDecision.HOLD
    assert ctx.runtime.execution_status is ExecutionStatus.HOLD
    assert ctx.runtime.phase is Phase.DEFINE

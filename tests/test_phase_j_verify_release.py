"""PHASE J — VERIFY layers + Release Gate."""

from __future__ import annotations

from builders import design, make_ctx, pass_define, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.clock import SimulatedClock
from aitop_harness.core.enums import (
    CheckStatus,
    Criticality,
    MappingConfidence,
    Phase,
    ReleaseDecision,
    RequiredBefore,
    ResultCompleteness,
    VerifyLayer,
    WorkClass,
)
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.data import DataAsset, Transformation
from aitop_harness.domain.design import WorkItem
from aitop_harness.domain.identity import CanonicalMapping
from aitop_harness.domain.verification import VerificationObligation
from aitop_harness.phases.budget import set_plan, update_budget
from aitop_harness.phases.discover import integrate_evidence
from aitop_harness.phases.release import evaluate_release_gate
from aitop_harness.phases.verify import CheckResult, OutputSpec, run_verify
from aitop_harness.state.runtime import Plan

S = ScopeItem
DETECT = [S("detect", "feed")]


def _base(scope=DETECT, **pd_kw):
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-1"))
    pass_define(ctx, problem(["E-1"], intended=scope, **pd_kw))
    design(ctx, scope, minimum_useful_scope=[scope[0]])
    set_plan(
        ctx,
        Plan(
            "PLAN-1",
            work_items=[
                WorkItem(
                    "W-1",
                    "core",
                    WorkClass.CORE_FEATURE,
                    10,
                    [scope[0]],
                    root_problem_aligned=True,
                    release_blocking=True,
                )
            ],
        ),
    )
    ctx.runtime.phase = Phase.VERIFY
    return ctx


def _vob(vid, scope, impact=Criticality.HIGH, before=RequiredBefore.BEFORE_RELEASE):
    return VerificationObligation(
        vid,
        f"{vid}?",
        Phase.DEFINE,
        decision_impact=impact,
        validation_method="check",
        required_before=before,
        blocking_scope=scope,
    )


def test_clean_release():
    ctx = _base()
    report = run_verify(ctx, DETECT)
    assert report.layer1_passed
    assert evaluate_release_gate(ctx, report).decision is ReleaseDecision.RELEASE


def test_open_vob_outside_release_scope_does_not_force_global_hold():
    ctx = _base()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-1"] = _vob("VOB-1", Scope.of(("publish_mapping", "CM-7")))
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION
    assert any("VOB-1" in limit for limit in res.known_limitations)


def test_critical_vob_intersecting_release_scope_holds():
    ctx = _base()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-2"] = _vob("VOB-2", Scope.of(("detect", "*")))
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.HOLD
    assert any("VOB-2" in h for h in res.hold_reasons)
    assert any("RELEASE_BLOCKING_VOB" in s for s in ctx.supervision.live_summary)
    # IDR-RV8-01: the structured field a bounded release-scope recovery would drop
    assert res.vob_blocked_items == DETECT


def test_vob_blocked_items_empty_when_nothing_critical_intersects():
    ctx = _base()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-1"] = _vob("VOB-1", Scope.of(("publish_mapping", "CM-7")))
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.vob_blocked_items == []


def test_unspecified_blocking_scope_is_conservative():
    ctx = _base()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-3"] = VerificationObligation("VOB-3", "?", Phase.DEFINE)
    assert evaluate_release_gate(ctx, run_verify(ctx, DETECT)).decision is ReleaseDecision.HOLD


def test_non_critical_intersection_and_production_vob_are_limitations():
    ctx = _base()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-4"] = _vob(
            "VOB-4", Scope.of(("detect", "*")), impact=Criticality.LOW
        )
        ps.verification_obligations["VOB-5"] = _vob(
            "VOB-5", Scope.entire(), before=RequiredBefore.BEFORE_PRODUCTION
        )
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION


def test_completeness_unknown_while_release_assumes_completeness_holds():
    ctx = _base()
    with ctx.commit("asset") as ps:
        ps.data_assets["DA-1"] = DataAsset(
            "DA-1", "feed", used_by=["detect"], completeness=ResultCompleteness.PARTIAL
        )
    report = run_verify(ctx, DETECT)
    assert report.check("pagination_coverage").status is CheckStatus.FAIL
    res = evaluate_release_gate(ctx, report)
    assert res.decision is ReleaseDecision.HOLD
    assert any("completeness unknown" in h for h in res.hold_reasons)


def test_destructive_transformation_cannot_be_known_limitation():
    ctx = _base()
    with ctx.commit("asset") as ps:
        ps.data_assets["DA-1"] = DataAsset(
            "DA-1", "feed", transformations=[Transformation("T-1", "dedupe", True)]
        )
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.HOLD


def test_unresolved_mapping_in_release_scope_holds_but_outside_is_limitation():
    scope = [S("publish_mapping", "CM-1")]
    ctx = _base(scope)
    with ctx.commit("maps") as ps:
        ps.canonical_mappings["CM-1"] = CanonicalMapping(
            "CM-1", "loc", "A", {"c": "1"}, "B", {"c": "B1"}, MappingConfidence.HIGH, authority="registry"
        )
        ps.canonical_mappings["CM-9"] = CanonicalMapping("CM-9", "loc", "A", {"c": "9"}, "B")
    res = evaluate_release_gate(ctx, run_verify(ctx, scope))
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION
    assert any("CM-9" in limit for limit in res.known_limitations)
    res2 = evaluate_release_gate(ctx, run_verify(ctx, scope + [S("publish_mapping", "CM-9")]))
    assert res2.decision is ReleaseDecision.HOLD


def test_output_checks_layer1():
    ctx = _base()
    out = OutputSpec(
        "alerts",
        [{"id": "1", "ts": "2026-10-01T00:00:00"}, {"id": 2, "ts": "bad"}],
        schema={"id": "str", "ts": "datetime"},
        timestamp_field="ts",
        expected_count=2,
    )
    report = run_verify(ctx, DETECT, outputs=[out])
    assert report.check("schema_type:alerts").status is CheckStatus.FAIL
    assert report.check("timestamp:alerts").status is CheckStatus.FAIL
    assert evaluate_release_gate(ctx, report).decision is ReleaseDecision.HOLD


def test_semantic_judge_cannot_override_layer1():
    ctx = _base()
    with ctx.commit("asset") as ps:
        ps.data_assets["DA-1"] = DataAsset(
            "DA-1", "feed", transformations=[Transformation("T-1", "dedupe", True)]
        )

    class OptimisticJudge:
        def judge(self, ctx, report):
            return [
                CheckResult(
                    "destructive_transformation", VerifyLayer.SEMANTIC_JUDGE, CheckStatus.PASS, "LGTM"
                ),
                CheckResult("exception_explanation", VerifyLayer.SEMANTIC_JUDGE, CheckStatus.PASS),
            ]

    report = run_verify(ctx, DETECT, judge=OptimisticJudge())
    assert report.check("destructive_transformation").status is CheckStatus.FAIL
    assert any(c.name == "exception_explanation" for c in report.layer(VerifyLayer.SEMANTIC_JUDGE))
    assert evaluate_release_gate(ctx, report).decision is ReleaseDecision.HOLD


def test_panic_scope_collapse_is_not_a_useful_release():
    ctx = _base()
    trivial = [S("render_demo_page", "index")]
    res = evaluate_release_gate(ctx, run_verify(ctx, trivial), trivial)
    assert res.decision is ReleaseDecision.HOLD
    assert any("PANIC_SCOPE_COLLAPSE" in h for h in res.hold_reasons)


def test_packaging_infeasible_holds():
    ctx = _base()
    ctx.clock = SimulatedClock(296)
    update_budget(ctx)
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.HOLD
    assert any("SUBMISSION_AT_RISK" in s for s in ctx.supervision.live_summary)


def test_stale_design_after_redefine_holds():
    ctx = _base()
    with ctx.commit("bump") as ps:
        ps.problem_definition.version = 2
    report = run_verify(ctx, DETECT)
    assert report.check("problem_solution_consistency").status is CheckStatus.FAIL
    assert evaluate_release_gate(ctx, report).decision is ReleaseDecision.HOLD


def test_detecting_a_broken_handoff_is_not_relying_on_it():
    from aitop_harness.core.enums import SemanticValidity
    from aitop_harness.domain.organization import ProcessHandoff

    scope = [S("detect_reject_cause", "H-1")]
    ctx = _base(scope)
    with ctx.commit("handoff") as ps:
        ps.process_handoffs["H-1"] = ProcessHandoff("H-1", semantic_validity=SemanticValidity.BROKEN)
    assert evaluate_release_gate(ctx, run_verify(ctx, scope)).decision is not ReleaseDecision.HOLD
    # an action that declares it relies on H-1's semantics is blocked
    resubmit = [S("auto_resubmit", "H-1")]
    with ctx.commit("dependency") as ps:
        ps.solution_design.scope_dependencies["auto_resubmit"] = ["H-1"]
    res = evaluate_release_gate(ctx, run_verify(ctx, scope + resubmit))
    assert res.decision is ReleaseDecision.HOLD
    assert any("semantic mismatch" in h for h in res.hold_reasons)


def test_unfinished_structural_remedy_is_explicit_limitation():
    from aitop_harness.domain.design import StructuralRemedyCandidate
    from aitop_harness.phases.design import DesignInputs, design_solution

    ctx = _base()
    design_solution(
        ctx,
        DesignInputs(
            [StructuralRemedyCandidate("SR", "contract v2", True, False)],
            True,
            True,
            bridge_sunset_condition="v2 live",
            release_scope=DETECT,
            minimum_useful_scope=DETECT,
        ),
        design_id="SD-2",
    )
    res = evaluate_release_gate(ctx, run_verify(ctx, DETECT))
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION
    assert "unfinished: contract v2" in res.known_limitations

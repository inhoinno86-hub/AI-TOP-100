"""Mock #6 — New Evidence Invalidates Problem — implementation regression RUNNER (Test Operator).

The implemented Harness (``src/aitop_harness``) is the System Under Test. This runner only:
  * loads the PUBLIC scenario through the Harness scenario loader,
  * delivers tool results / stakeholder answers through the Scenario Controller,
  * supplies the content the Harness API requires as *input* but has no component to produce
    (hypothesis statements, Problem Definition text, design inputs, revision wording) —
    tagged ``OPERATOR_REASONER`` = stand-in for the absent Skill/reasoning layer,
  * plays the Human at gates (tagged ``HUMAN``),
  * records what the Harness itself produced (events, state, gate results, guards, signals).

It never reads ``scenario_pack/hidden_ground_truth.json`` (enforced below) and never edits
Harness state outside the Harness commit path. Operator does NOT perform downstream clean-up that
the Harness is expected to do on redefine (that is what is under test).

Usage: python3 mocks/mock6/run_mock6.py [--variant scoped|u1_default_scope]
"""

from __future__ import annotations

import argparse
import builtins
import copy
import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))
sys.path.insert(0, str(HERE / "scenario_pack"))

# ---- hidden ground truth isolation: any attempt to open it during the run aborts the run
_real_open = builtins.open


def _guarded_open(file: Any, *a: Any, **kw: Any) -> Any:
    if "hidden_ground_truth" in str(file):
        raise PermissionError("hidden ground truth is sealed during the run")
    return _real_open(file, *a, **kw)


builtins.open = _guarded_open

from controller import ScenarioController  # noqa: E402

from aitop_harness.core.enums import (  # noqa: E402
    AuthorizationStatus,
    Criticality,
    HumanDecisionKind,
    HypothesisStatus,
    MetricType,
    Phase,
    ProtectedActionCategory,
    Reversibility,
    WorkClass,
)
from aitop_harness.core.errors import HarnessError  # noqa: E402
from aitop_harness.core.events import EventType  # noqa: E402
from aitop_harness.core.scope import Scope, ScopeItem  # noqa: E402
from aitop_harness.core.serialization import to_dict  # noqa: E402
from aitop_harness.domain.authority import DomainAuthorization  # noqa: E402
from aitop_harness.domain.design import ProblemDefinition, StructuralRemedyCandidate, WorkItem  # noqa: E402
from aitop_harness.domain.epistemic import Assumption, Hypothesis, SuccessCriterion, Unknown  # noqa: E402
from aitop_harness.domain.metric import Metric  # noqa: E402
from aitop_harness.engine.context import HarnessContext  # noqa: E402
from aitop_harness.engine.controller import PhaseController  # noqa: E402
from aitop_harness.phases.budget import set_plan  # noqa: E402
from aitop_harness.phases.data_inspection import apply_inspection, inspect_records  # noqa: E402
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate  # noqa: E402
from aitop_harness.phases.design import DesignInputs, design_solution  # noqa: E402
from aitop_harness.phases.discover import (  # noqa: E402
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    integrate_evidence,
    rank_actions,
    record_claim,
    revise_evidence,
    select_next_action,
    stakeholder_evidence,
    update_hypothesis,
)
from aitop_harness.phases.execute import evidence_from_outcome, invoke_tool  # noqa: E402
from aitop_harness.phases.human_gate import (  # noqa: E402
    HumanDecision,
    decide,
    interpret_human_input,
    propose_protected_action,
)
from aitop_harness.phases.recovery import FailureContext, apply_recovery_decision, decide_recovery  # noqa: E402
from aitop_harness.phases.release import evaluate_release_gate  # noqa: E402
from aitop_harness.phases.verify import OutputSpec, run_verify  # noqa: E402
from aitop_harness.scenario import load_context  # noqa: E402
from aitop_harness.state.runtime import Plan, ProtectedActionProposal  # noqa: E402
from aitop_harness.supervision.projection import refresh  # noqa: E402
from aitop_harness.tools.base import ToolRegistry  # noqa: E402

S = ScopeItem
Crit = Criticality


# =========================================================================== recording


def event_dict(e: Any) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "type": e.type.value,
        "phase": e.phase.value if e.phase else None,
        "minute": e.minute,
        "importance": e.importance.value,
        "payload": to_dict(e.payload),
        "refs": list(e.refs),
    }


class Recorder:
    def __init__(self, ctx: HarnessContext, label: str) -> None:
        self.ctx = ctx
        self.label = label
        self.trace: list[dict[str, Any]] = []

    def step(
        self,
        step_id: str,
        actor: str,
        call: str,
        fn: Callable[[], Any] | None = None,
        *,
        note: str = "",
        operator_input: Any = None,
    ) -> tuple[Any, str | None]:
        ctx = self.ctx
        start = len(ctx.events)
        live_before = len(ctx.supervision.live_summary)
        result: Any = None
        error: str | None = None
        try:
            result = fn() if fn else None
        except HarnessError as exc:  # harness-raised guard: an observation, not a runner crash
            error = f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 — record everything, never hide
            error = f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}"
        events = list(ctx.events)[start:]
        self.trace.append(
            {
                "step": step_id,
                "actor": actor,
                "call": call,
                "note": note,
                "operator_input": to_dict(operator_input) if operator_input is not None else None,
                "error": error,
                "result": _summ(result),
                "phase_after": ctx.runtime.phase.value,
                "execution_status_after": ctx.runtime.execution_status.value,
                "problem_version_after": ctx.problem.meta.version,
                "harness_events": [event_dict(e) for e in events],
                "new_live_summary": ctx.supervision.live_summary[live_before:],
            }
        )
        tag = f"ERROR {error.splitlines()[0]}" if error else "ok"
        print(f"[{self.label}] {step_id:<34} {actor:<17} {call:<46} {tag}")
        return result, error


def _summ(obj: Any) -> Any:
    if obj is None:
        return None
    try:
        d = to_dict(obj)
    except Exception:  # noqa: BLE001
        return repr(obj)[:400]
    s = json.dumps(d, ensure_ascii=False, default=str)
    return d if len(s) < 4000 else s[:4000] + "…"


def inventory(ctx: HarnessContext) -> dict[str, Any]:
    """Harness-owned status of every Problem-v1-dependent object (no interpretation added)."""
    return json.loads(json.dumps(_inventory(ctx), default=str))


def _inventory(ctx: HarnessContext) -> dict[str, Any]:
    ps, rt = ctx.problem, ctx.runtime
    pd = ps.problem_definition
    return {
        "problem_meta_version": ps.meta.version,
        "phase": rt.phase.value,
        "execution_status": rt.execution_status.value,
        "active_problem": to_dict(pd) if pd else None,
        "problem_definition_history": [
            {"id": h.id, "version": h.version, "status": h.status.value, "invalidated_by": h.invalidated_by,
             "root_problem": h.root_problem, "same_object_as_active": h is pd}
            for h in ps.meta.problem_definition_history
        ],
        "solution_design": (
            {"id": ps.solution_design.id, "problem_ref": ps.solution_design.problem_ref,
             "problem_version": ps.solution_design.problem_version,
             "agent_roles": [r.value for r in ps.solution_design.agent_roles],
             "structural_remedies": [c.id for c in ps.solution_design.structural_remedies],
             "release_scope": [str(i) for i in ps.solution_design.release_scope]}
            if ps.solution_design else None
        ),
        "agent_spec": (
            {"identity": ps.agent_spec.identity, "problem_reference": ps.agent_spec.problem_reference,
             "structural_role": [r.value for r in ps.agent_spec.structural_role],
             "verification_obligations": list(ps.agent_spec.verification_obligations),
             "success_criteria": list(ps.agent_spec.success_criteria)}
            if ps.agent_spec else None
        ),
        "verification_obligations": {
            v.id: {"status": v.status.value, "required_before": v.required_before.value,
                   "blocking_scope": "ENTIRE" if v.blocking_scope.entire_solution
                   else [str(i) for i in v.blocking_scope.items],
                   "question": v.unresolved_question, "linked_unknown": v.linked_unknown}
            for v in ps.verification_obligations.values()
        },
        "hypotheses": {h.id: {"status": h.status.value, "supporting": h.supporting_evidence,
                              "contradicting": h.contradicting_evidence} for h in ps.hypotheses.values()},
        "assumptions": {a.id: a.status.value for a in ps.assumptions.values()},
        "unknowns": {u.id: u.status.value for u in ps.unknowns.values()},
        "success_criteria": sorted(ps.success_criteria),
        "active_problem_success_criteria": list(pd.success_criteria) if pd else [],
        "claims": {c.id: {"status": c.status.value, "evidence_refs": c.evidence_refs} for c in ps.claims.values()},
        "conflicts": {c.id: {"type": c.type.value, "assertion": c.assertion, "sides": [c.side_a, c.side_b],
                             "decision_impact": c.decision_impact.value, "status": c.status.value,
                             "gate_blocking": c.gate_blocking} for c in ps.conflicts.values()},
        "evidence": {e.id: {"status": e.status.value, "authority": e.authority.value, "source": e.source_id,
                            "content": e.content,
                            "interpretation_history": [to_dict(i) for i in e.interpretation_history],
                            "provenance": to_dict(e.provenance)} for e in ps.evidence.values()},
        "evidence_revisions": {r.id: to_dict(r) for r in ps.evidence_revisions.values()},
        "decision_log": [to_dict(d) for d in ps.decision_log],
        "domain_authorizations": {a.id: a.status.value for a in ps.domain_authorizations.values()},
        "plan": (
            {"id": rt.current_plan.id, "version": rt.current_plan.version,
             "work_items": {w.id: {"status": w.status, "description": w.description} for w in rt.current_plan.work_items}}
            if rt.current_plan else None
        ),
        "pending_protected_action": (
            {"gate_id": rt.pending_protected_action.gate_id,
             "action": rt.pending_protected_action.proposal.action,
             "why": rt.pending_protected_action.proposal.why,
             "confirmation_decision": rt.pending_protected_action.confirmation.decision.value
             if rt.pending_protected_action.confirmation.decision else None}
            if rt.pending_protected_action else None
        ),
        "executed_actions": [to_dict(a) for a in ps.execution.actions],
        "transition_candidate": to_dict(rt.transition_candidate) if rt.transition_candidate else None,
        "recovery": {"candidate_transition": rt.recovery.candidate_transition.value
                     if rt.recovery.candidate_transition else None,
                     "rationale": rt.recovery.decision_rationale},
        "release_decisions": [d.value for d in ps.validation.release_decisions],
        "supervision": {
            "current_problem": ctx.supervision.current_problem,
            "top_hypotheses": list(ctx.supervision.top_hypotheses),
            "evidence_revisions": list(ctx.supervision.evidence_revisions),
            "pending_verification_obligations": list(ctx.supervision.pending_verification_obligations),
            "intervention": to_dict(ctx.supervision.intervention),
            "live_summary_tail": ctx.supervision.live_summary[-12:],
        },
    }


# =========================================================================== operator-reasoner inputs
# Everything below is content the Harness API needs as input but cannot produce itself.


def iv(di: float, unc: float = 0.5, disc: float = 0.5, ans: float = 0.8, proc: float = 0.3,
       prox: float = 0.2, risk: float = 0.0, t: float = 3.0) -> InformationValueFactors:
    return InformationValueFactors(di, unc, disc, ans, proc, prox, risk, t)


PHASE1_ACTIONS = [
    DiscoveryAction("A-CRM-SLA", DiscoveryActionKind.TOOL_QUERY, "crm-tickets", "dispute_response_times",
                    iv(0.8, 0.7, 0.9, 0.9), discriminates_hypotheses=["H-SLOW"], tool_id="crm-tickets"),
    DiscoveryAction("A-VOLUME", DiscoveryActionKind.TOOL_QUERY, "crm-tickets", "dispute_volume_monthly",
                    iv(0.6, 0.4, 0.3, 0.9), tool_id="crm-tickets"),
    DiscoveryAction("A-READTYPE", DiscoveryActionKind.TOOL_QUERY, "billing-db", "disputed_bills_by_read_type",
                    iv(0.9, 0.7, 0.8, 0.9, 0.6), discriminates_hypotheses=["H-READS", "H-TARIFF"],
                    tool_id="billing-db"),
    DiscoveryAction("A-ROUTE", DiscoveryActionKind.TOOL_QUERY, "route-log", "route_completion_aug_sep",
                    iv(0.8, 0.6, 0.7, 0.9, 0.6), discriminates_hypotheses=["H-READS"], tool_id="route-log"),
    DiscoveryAction("A-MDMS", DiscoveryActionKind.TOOL_QUERY, "mdms-export", "read_events_for_disputed_estimated",
                    iv(0.9, 0.8, 0.9, 0.5, 0.7, t=4.0), discriminates_hypotheses=["H-READS"],
                    tool_id="mdms-export"),
    DiscoveryAction("A-TARIFF", DiscoveryActionKind.TOOL_QUERY, "billing-db", "tariff_change_log",
                    iv(0.5, 0.5, 0.8, 0.9, t=1.0), discriminates_hypotheses=["H-TARIFF"], tool_id="billing-db"),
    DiscoveryAction("A-INT-FIELD", DiscoveryActionKind.STAKEHOLDER_INTERVIEW, "SH-FIELD", "why are bills estimated?",
                    iv(0.6, 0.6, 0.4, 0.7, 0.5, t=5.0)),
    DiscoveryAction("A-INT-BILL", DiscoveryActionKind.STAKEHOLDER_INTERVIEW, "SH-BILL", "tariff or bill-run changes?",
                    iv(0.4, 0.4, 0.4, 0.8, 0.3, t=5.0)),
]

# evidence mapping for each action: (evidence id, content template, assertion, value, supports, contradicts)
TOOL_EVIDENCE = {
    "A-CRM-SLA": ("E-CRM-SLA", "CRM: dispute response median 1.6d, p90 2.8d, SLA 3d (2,440 tickets)",
                  "dispute_response.too_slow", False, [], ["H-SLOW"]),
    "A-VOLUME": ("E-VOLUME", "CRM: disputes/month 610, 590 (Jun-Jul) -> 1180, 1260 (Aug-Sep)",
                 "disputes.surge_since_aug", True, [], []),
    "A-READTYPE": ("E-BILL-READTYPE", "billing: 1,240 of 3,025 disputed bills (41%) carry read type ESTIMATED",
                   "disputed_bills.estimated_share", 0.41, ["H-READS"], []),
    "A-ROUTE": ("E-ROUTE", "route log: manual route completion 88% vs 95% target in Aug-Sep (9,200 manual-read accounts)",
                "manual_routes.completion", 0.88, ["H-READS"], []),
    "A-TARIFF": ("E-TARIFF", "billing: no tariff change records in 2026", "tariff.changed_2026", False, [], ["H-TARIFF"]),
    "A-MDMS": ("E-MDMS", "MDMS system of record: for 1,184 of 1,240 ESTIMATED disputed bills a valid AMI read arrived "
               "before billing cutoff and was exported; billing import status REJECTED_HIGH_CONSUMPTION; all 1,184 are "
               "firmware v4.2 AMI meters (not manual-read routes). 56 had no read received.",
               "disputed_estimates.cause", "ami_read_rejected_at_billing_import", [], ["H-READS"]),
}
INTERVIEW_CLAIMS = {
    "A-INT-FIELD": ("CL-FIELD-CAUSE", "E-FIELD-STMT", "SH-FIELD", "disputed_estimates.cause", "missed_field_read",
                    ["H-READS"]),
    "A-INT-BILL": ("CL-BILL-TARIFF", "E-BILL-STMT", "SH-BILL", "tariff.changed_2026", False, []),
}

ROUTE_SCOPE_V1 = [S("prioritize_read_routes", "lagging_routes"), S("push_route_update", "field-dispatch"),
                  S("flag_estimation_risk", "accounts")]
KPI = S("publish_dispute_kpi", "mgmt-dashboard")
INTENDED_V1 = ROUTE_SCOPE_V1 + [KPI]

SCOPE_V2_RELEASE = [S("detect_validation_rejections", "DA-BILL"), S("classify_affected_accounts", "firmware-v4.2"),
                    S("escalate_rebill_queue", "billing-ops")]
INTENDED_V2 = SCOPE_V2_RELEASE + [S("compute_corrected_read_proposals", "firmware-v4.2"), KPI]


def reasoner_define_inputs_v1(ps: Any, variant: str) -> None:
    """Metrics, success criteria, unknowns, assumption for v1 (reasoner content)."""
    m_est = Metric("M-EST-SHARE", "estimated share of disputed bills", MetricType.RATE,
                   numerator="disputed bills with ESTIMATED read type", denominator="disputed bills")
    m_est.promote(owner="ORG-UTIL", current_value=0.41, target_value=0.10, measurement_window="bill cycle")
    m_vol = Metric("M-VOLUME", "dispute tickets per month", MetricType.COUNT)
    m_vol.promote(owner="ORG-UTIL", current_value=1260, target_value=600, measurement_window="month")
    ps.metrics.update({"M-EST-SHARE": m_est, "M-VOLUME": m_vol})
    ps.success_criteria["SC-EST-SHARE"] = SuccessCriterion(
        "SC-EST-SHARE", "estimated share among disputed bills < 10% next cycle", "M-EST-SHARE", "< 0.10",
        "next-cycle billing extract", ["next_cycle_extract"])
    ps.success_criteria["SC-VOLUME"] = SuccessCriterion(
        "SC-VOLUME", "dispute tickets back to <= 600/month", "M-VOLUME", "<= 600", "CRM monthly count")
    u1_scope = Scope() if variant == "u1_default_scope" else Scope.of(("prioritize_read_routes", "*"))
    ps.unknowns["U-ROUTE-IMPACT"] = Unknown(
        "U-ROUTE-IMPACT", "Does prioritizing lagging routes cut the estimated share within one cycle?", Crit.HIGH,
        "decides whether route prioritization is the fix", u1_scope,
        resolution_path="compare next-cycle estimated share on prioritized vs other routes",
        safe_placeholder="ship route prioritization without an impact claim")
    ps.unknowns["U-TAG"] = Unknown(
        "U-TAG", "Is the CRM DISPUTE_BILLING tag applied consistently (agents may tag GENERAL)?", Crit.HIGH,
        "dispute KPI denominator", Scope.of(("publish_dispute_kpi", "*")),
        resolution_path="audit sample of 200 tickets", safe_placeholder="publish KPI marked provisional")
    ps.assumptions["A-EST-MEANS-NOREAD"] = Assumption(
        "A-EST-MEANS-NOREAD", "read type ESTIMATED means no meter read was collected for the cycle",
        basis="billing practice (SH-BILL), E-BILL-READTYPE", risk_if_wrong=Crit.HIGH)


def pd_v1() -> ProblemDefinition:
    return ProblemDefinition(
        id="PD-1", version=1,
        requested_solution="AI agent that auto-answers billing dispute tickets",
        symptoms=["dispute tickets doubled since August", "41% of disputed bills are ESTIMATED"],
        root_problem="Manual meter-read route backlog (88% vs 95% completion) leaves accounts unread, so they receive "
                     "estimated bills, which drive the August-September dispute surge.",
        evidence_refs=["E-BILL-READTYPE", "E-ROUTE", "E-VOLUME", "E-FIELD-STMT"],
        intended_scope=list(INTENDED_V1), protected_actions=["push_route_update"],
        required_tools=["billing-db", "route-log"],
        success_criteria=["SC-EST-SHARE", "SC-VOLUME"], metric_ids=["M-EST-SHARE", "M-VOLUME"],
    )


def design_inputs_v1() -> DesignInputs:
    return DesignInputs(
        structural_remedies=[StructuralRemedyCandidate(
            "SR-ROUTES", "rebalance route assignments + 3 temporary readers via contract amendment", True, False,
            rationale="contract amendment takes weeks")],
        deterministic_rules_cover_cases=True, llm_reasoning_adds_value=True, autonomous_iteration_adds_value=False,
        residual_exceptions=True, detection_needed=True,
        why_agent="draft per-customer explanations for estimated-bill disputes",
        bridge_sunset_condition="route completion >= 95% for a full cycle after the contract amendment",
        deterministic_components=["route lag ranking", "estimation-risk flag rule"],
        release_scope=list(ROUTE_SCOPE_V1),
        minimum_useful_scope=[S("prioritize_read_routes", "lagging_routes"), S("flag_estimation_risk", "accounts")],
        scope_dependencies={"prioritize_read_routes": ["DA-ROUTE"], "flag_estimation_risk": ["DA-BILL", "DA-ROUTE"]},
    )


def plan_v1() -> Plan:
    return Plan("PLAN-1", work_items=[
        WorkItem("W1-RANK", "route lag ranking", WorkClass.CORE_FEATURE, 10,
                 [S("prioritize_read_routes", "lagging_routes")], True, True),
        WorkItem("W2-DISPATCH", "push priority routes to field dispatch (gated)", WorkClass.CORE_FEATURE, 5,
                 [S("push_route_update", "field-dispatch")], True, True),
        WorkItem("W3-FLAG", "estimation-risk flagger", WorkClass.CORE_FEATURE, 15,
                 [S("flag_estimation_risk", "accounts")], True, True),
        WorkItem("W4-DRAFTS", "dispute response drafting", WorkClass.NON_BLOCKING_FEATURE, 25),
        WorkItem("W5-VERIFY", "release-blocking verification", WorkClass.RELEASE_BLOCKING_VERIFICATION, 10),
        WorkItem("W6-PACK", "packaging + submission", WorkClass.PACKAGING, 8),
    ])


def dispatch_proposal() -> ProtectedActionProposal:
    return ProtectedActionProposal(
        action_id="DISPATCH-1", action="push_route_update", subject="priority reads on 14 lagging routes",
        protected_resource="field-dispatch", requested_scope=[S("push_route_update", "field-dispatch")],
        category=ProtectedActionCategory.PROTECTED_MUTATION,
        why="PD-1 v1: lagging manual routes leave accounts unread -> estimated bills -> disputes",
        side_effect="field crews re-sequenced for the next two weeks", reversibility=Reversibility.REVERSIBLE,
        alternatives=["SH-FIELD changes routes manually"], idempotency_key="dispatch-prio-2026-09",
        key_evidence=["E-ROUTE", "E-BILL-READTYPE"],
    )


def pd_v2(cite_revised: bool) -> ProblemDefinition:
    refs = ["E-MDMS", "E-RULES", "E-UNITS", "E-VOLUME"] + (["E-BILL-READTYPE"] if cite_revised else [])
    return ProblemDefinition(
        id="PD-1", version=2,
        requested_solution="AI agent that auto-answers billing dispute tickets",
        symptoms=["dispute tickets doubled since August", "41% of disputed bills are ESTIMATED"],
        root_problem="Billing import validation rule BV-17 (deployed 08-01) compares firmware-v4.2 AMI register values "
                     "(0.1 m3 units) with m3 history without unit scaling, rejects valid on-time AMI reads as "
                     "HIGH_CONSUMPTION and substitutes estimates; the estimated bills drive the dispute surge.",
        evidence_refs=refs, intended_scope=list(INTENDED_V2), protected_actions=[],
        depends_on_handoffs=[], required_tools=["billing-db", "mdms-export"],
        success_criteria=["SC-EST-SHARE", "SC-DETECT"], metric_ids=["M-EST-SHARE", "M-DETECT"],
    )


def reasoner_define_inputs_v2(ps: Any) -> None:
    ps.hypotheses["H-VALIDATION"] = Hypothesis(
        "H-VALIDATION", "BV-17 rejects valid firmware-v4.2 AMI reads (unit scale) and substitutes estimates",
        supporting_evidence=["E-MDMS", "E-RULES", "E-UNITS"], status=HypothesisStatus.SUPPORTED,
        decision_impact=Crit.CRITICAL)
    m = Metric("M-DETECT", "detection recall of v4.2 rejected-read disputes", MetricType.RATE,
               numerator="affected accounts queued", denominator="affected accounts per MDMS x billing import")
    m.promote(owner="ORG-UTIL", target_value=0.95, measurement_window="Aug-Sep")
    ps.metrics["M-DETECT"] = m
    ps.success_criteria["SC-DETECT"] = SuccessCriterion(
        "SC-DETECT", ">= 95% of affected v4.2 disputed accounts detected and queued for Billing Ops",
        "M-DETECT", ">= 0.95", "reconcile queue against MDMS x billing import status", ["detect_reconcile"])
    ps.unknowns["U-SCALE"] = Unknown(
        "U-SCALE", "Does scaling v4.2 reads by 0.1 give correct consumption for every v4.2 meter, including genuine "
        "high-usage / leak cases?", Crit.CRITICAL, "corrected-read proposals / re-bill",
        Scope.of(("compute_corrected_read_proposals", "*")),
        resolution_path="Billing Ops validates a 50-account sample against field check reads",
        safe_placeholder="release detection + classification + manual escalation only; no corrected values")


def design_inputs_v2() -> DesignInputs:
    return DesignInputs(
        structural_remedies=[StructuralRemedyCandidate(
            "SR-BV17", "billing vendor patches BV-17 to apply firmware register-unit scaling (H-MDMS-BILL contract)",
            True, False, rationale="vendor release cycle exceeds contest time")],
        deterministic_rules_cover_cases=True, llm_reasoning_adds_value=True, autonomous_iteration_adds_value=False,
        residual_exceptions=True, detection_needed=True,
        why_agent="explain affected accounts to Billing Ops / customers in plain language",
        bridge_sunset_condition="BV-17 patched and one clean bill cycle",
        deterministic_components=["MDMS x billing import join", "firmware v4.2 classifier"],
        release_scope=list(SCOPE_V2_RELEASE), minimum_useful_scope=list(SCOPE_V2_RELEASE),
        scope_dependencies={"detect_validation_rejections": ["DA-BILL", "DA-MDMS"],
                            "classify_affected_accounts": ["DA-MDMS"]},
    )


def plan_v2() -> Plan:
    return Plan("PLAN-2", work_items=[
        WorkItem("V2-DETECT", "detect rejected v4.2 AMI reads", WorkClass.CORE_FEATURE, 15,
                 [SCOPE_V2_RELEASE[0]], True, True),
        WorkItem("V2-CLASSIFY", "classify affected disputed accounts", WorkClass.CORE_FEATURE, 10,
                 [SCOPE_V2_RELEASE[1]], True, True),
        WorkItem("V2-ESCALATE", "manual escalation queue for Billing Ops", WorkClass.CORE_FEATURE, 5,
                 [SCOPE_V2_RELEASE[2]], True, True),
        WorkItem("V2-VERIFY", "release-blocking verification", WorkClass.RELEASE_BLOCKING_VERIFICATION, 10),
        WorkItem("V2-PACK", "packaging + submission", WorkClass.PACKAGING, 8),
    ])


# =========================================================================== helpers


def run_discovery_action(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController,
                         action: DiscoveryAction, decision_impact: Crit = Crit.MEDIUM) -> dict[str, Any]:
    """Execute one harness-selected discovery action; map its observation to evidence (scenario mapping)."""
    out: dict[str, Any] = {"action": action.id}
    if action.tool_id is not None:
        outcome = invoke_tool(ctx, reg, action.tool_id, action.question)
        out.update(status=outcome.result.status.value, completeness=outcome.completeness.value,
                   error_class=outcome.result.error_class, signature=outcome.failure_signature)
        if outcome.result.status.value == "ERROR":
            out["outcome"] = outcome
            return out
        eid, content, assertion, value, supports, contradicts = TOOL_EVIDENCE[action.id]
        ev = evidence_from_outcome(ctx, outcome, eid, content, target_assertion=assertion, value=value)
        integrate_evidence(ctx, ev, supports=supports, contradicts=contradicts, decision_impact=decision_impact)
        out["evidence"] = eid
    else:
        cid, eid, sh, assertion, value, supports = INTERVIEW_CLAIMS[action.id]
        text = ctl.interview(sh)
        record_claim(ctx, cid, sh, text, assertion=assertion, value=value)
        integrate_evidence(ctx, stakeholder_evidence(eid, sh, text, assertion=assertion, value=value),
                           supports=supports)
        out.update(claim=cid, evidence=eid)
    return out


def save(outdir: Path, name: str, obj: Any) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    with _real_open(outdir / name, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, default=str)


def fork(*objs: Any) -> Any:
    return copy.deepcopy(objs)


# =========================================================================== probes (negative controls, forks)


def probe_precanonical(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P1/P2: DRAFT (pre-canonical) problem + authoritative contradicting evidence."""
    c, _, _ = fork(ctx, reg, ctl)
    rec = Recorder(c, "P1-precanon")
    res: dict[str, Any] = {"problem_status": c.problem.problem_definition.status.value,
                           "gate_result": str(c.problem.problem_definition.gate_result)}
    dec, err = rec.step("P2.decide_recovery", "PROBE", "decide_recovery(problem_invalidating=E-CRM-SLA)",
                        lambda: decide_recovery(c, FailureContext("n/a", "n/a", None, None, None,
                                                                  problem_invalidating_evidence="E-CRM-SLA")))
    res["decide_recovery_kind_on_draft"] = dec.kind.value if dec else err
    _, err = rec.step("P1.redefine_on_draft", "PROBE", "PhaseController.redefine(E-CRM-SLA) on DRAFT",
                      lambda: PhaseController(c).redefine("E-CRM-SLA", "probe: pre-canonical contradiction"))
    res["redefine_on_draft_error"] = err
    res["redefine_on_draft_accepted"] = err is None
    res["problem_status_after"] = c.problem.problem_definition.status.value if c.problem.problem_definition else None
    res["problem_invalidated_events"] = len([e for e in c.events if e.type.value == "problem_invalidated"])
    res["phase_after"] = c.runtime.phase.value
    res["trace"] = rec.trace
    return res


def probe_no_operator_transition(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController,
                                 impact: Crit | None) -> dict[str, Any]:
    """P4: late evidence enters via the normal tool path; nobody invokes redefine. Does stale v1 get out?

    impact=None is the CONTROL fork (no late evidence at all) for a differential comparison.
    """
    c, r, k = fork(ctx, reg, ctl)
    rec = Recorder(c, f"P4-{impact.value if impact else 'CONTROL'}")
    if impact is not None:
        action = next(a for a in PHASE1_ACTIONS if a.id == "A-MDMS")
        rec.step("P4.provision", "CONTROLLER", "provision_mdms", lambda: k.provision_mdms(c))
        rec.step("P4.late_evidence", "CONTROLLER", f"mdms tool path, integrate decision_impact={impact.value}",
                 lambda: run_discovery_action(c, r, k, action, decision_impact=impact))
    res: dict[str, Any] = {"impact": impact.value if impact else "CONTROL (no late evidence)",
                           "problem_status": c.problem.problem_definition.status.value,
                           "transition_candidate": to_dict(c.runtime.transition_candidate),
                           "conflicts": {i: (x.decision_impact.value, x.assertion) for i, x in c.problem.conflicts.items()},
                           "claims": {i: x.status.value for i, x in c.problem.claims.items()}}
    out, err = rec.step("P4.human_approve_old_action", "HUMAN", "APPROVE pending push_route_update",
                        lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE, "approve"), k.dispatch))
    res["approve_status"] = out.status.value if out else err
    res["dispatch_calls"] = k.dispatch.count("push_route_update")
    ctl_ = PhaseController(c)
    rec.step("P4.advance_verify", "OPERATOR", "advance EXECUTE->VERIFY", ctl_.advance)
    rep, err = rec.step("P4.verify", "OPERATOR", "run_verify(v1 release scope)",
                        lambda: run_verify(c, list(ROUTE_SCOPE_V1)))
    res["verify_failed"] = [x.name for x in rep.failed()] if rep else err
    rec.step("P4.advance_release", "OPERATOR", "advance VERIFY->RELEASE", ctl_.advance)
    gate, err = rec.step("P4.release_gate", "OPERATOR", "evaluate_release_gate(v1)",
                         lambda: evaluate_release_gate(c, rep, list(ROUTE_SCOPE_V1)))
    res["release_decision"] = gate.decision.value if gate else err
    res["hold_reasons"] = gate.hold_reasons if gate else None
    res["known_limitations"] = gate.known_limitations if gate else None
    res["live_summary_tail"] = c.supervision.live_summary[-8:]
    res["trace"] = rec.trace
    return res


def probe_discrimination(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P5: can the Harness tell redefine-type from replan-type authoritative evidence?"""
    c, _, k = fork(ctx, reg, ctl)
    rec = Recorder(c, "P5-discrim")
    rec.step("P5.integrate_decoy", "CONTROLLER", "integrate E-DISPATCH-API (path-only, authoritative)",
             lambda: integrate_evidence(c, k.dispatch_api_notice()))
    res: dict[str, Any] = {}
    for label, ev in (("late_mdms", "E-MDMS"), ("decoy_path_only", "E-DISPATCH-API"), ("none", None)):
        fc = FailureContext("field-dispatch", "push_route_update", None, "ENDPOINT_RETIRED", False,
                            alternate_paths=["dispatch API v3"], problem_invalidating_evidence=ev)
        d, err = rec.step(f"P5.decide_recovery[{label}]", "PROBE", f"decide_recovery(problem_invalidating={ev})",
                          lambda fc=fc: decide_recovery(c, fc))
        res[f"decide_recovery[{label}]"] = d.kind.value if d else err
    rec.step("P5.human_reject_pending", "HUMAN", "REJECT pending (to allow a transition)",
             lambda: decide(c, HumanDecision(HumanDecisionKind.REJECT, "reject"), k.dispatch))
    _, err = rec.step("P5.redefine_on_decoy", "PROBE", "PhaseController.redefine(E-DISPATCH-API)",
                      lambda: PhaseController(c).redefine("E-DISPATCH-API", "probe: path-only evidence"))
    res["redefine_on_path_only_evidence_accepted"] = err is None
    res["redefine_on_path_only_error"] = err
    res["trace"] = rec.trace
    return res


def probe_approve_after_failed_redefine(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P6b: right after redefine attempt 1 (whatever its outcome), Human APPROVEs the old dispatch.

    Baseline: attempt 1 failed after committing (split-brain) and APPROVE executed the old action.
    Patch rerun: the probe runs unconditionally so a successful attempt cannot make it vacuous.
    """
    c, _, k = fork(ctx, reg, ctl)
    rec = Recorder(c, "P6b-approve")
    res = {"problem_status_before": c.problem.problem_definition.status.value,
           "execution_status_before": c.runtime.execution_status.value}
    out, err = rec.step("P6b.human_approve", "HUMAN", "APPROVE pending push_route_update (premise invalidated)",
                        lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE, "approve"), k.dispatch))
    res["approve_status"] = out.status.value if out else err
    res["dispatch_calls"] = k.dispatch.count("push_route_update")
    res["protected_action_executed_events"] = len([e for e in c.events if e.type.value == "protected_action_executed"])
    res["trace"] = rec.trace
    return res


def probe_duplicate_redefine(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P10 (added at patch rerun): same Problem + same invalidating evidence redefined again (D7)."""
    c, _, _ = fork(ctx, reg, ctl)
    rec = Recorder(c, "P10-dup")
    ps = c.problem

    def counts() -> dict[str, Any]:
        return {"history": len(ps.meta.problem_definition_history),
                "redefine_decisions": sum(1 for d in ps.decision_log if d.decision == "REDEFINE"),
                "problem_invalidated_events": len(c.events.of_type(EventType.PROBLEM_INVALIDATED)),
                "invalidated_by": list(ps.problem_definition.invalidated_by),
                "dependency_reviews": len(ps.dependency_reviews)}

    before = counts()
    _, err = rec.step("P10.redefine_again", "PROBE", "PhaseController.redefine(E-MDMS) again",
                      lambda: PhaseController(c).redefine("E-MDMS", "probe: duplicate redefine"))
    after = counts()
    return {"before": before, "after": after, "error": err, "no_mutation": before == after,
            "noop_events": len(c.events.of_type(EventType.REDEFINE_NOOP)), "trace": rec.trace}


def probe_version_reuse(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P7: after redefine, a new definition that reuses version=1 — does the stale SD-1 guard still fire?"""
    c, _, _ = fork(ctx, reg, ctl)
    rec = Recorder(c, "P7-version")
    pd = pd_v2(cite_revised=False)
    pd.version = 1
    rec.step("P7.reasoner_v2_inputs", "OPERATOR_REASONER", "commit v2 reasoning objects",
             lambda: _commit(c, "v2 inputs", reasoner_define_inputs_v2))
    rec.step("P7.define_v2_with_version1", "OPERATOR_REASONER", "define_problem(new root, version=1)",
             lambda: define_problem(c, pd))
    g, _ = rec.step("P7.gate", "OPERATOR", "evaluate+apply DEFINE gate",
                    lambda: apply_define_gate(c, evaluate_define_gate(c)))
    ctl_ = PhaseController(c)
    rec.step("P7.advance_design", "OPERATOR", "advance DEFINE->DESIGN", ctl_.advance)
    _, err = rec.step("P7.advance_execute_with_SD1", "OPERATOR", "advance DESIGN->EXECUTE with stale SD-1", ctl_.advance)
    return {"gate": str(g), "stale_sd1_reached_execute": err is None and c.runtime.phase is Phase.EXECUTE,
            "advance_error": err, "solution_design": c.problem.solution_design.id,
            "sd_problem_version": c.problem.solution_design.problem_version,
            "sd_root_vs_active_root_differs": True, "trace": rec.trace}


def probe_reprofile_targeting(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P8: during a targeted reprofile, does action selection honour reprofile targets?"""
    c, r, k = fork(ctx, reg, ctl)
    rec = Recorder(c, "P8-reprofile")
    ctl_ = PhaseController(c)
    rec.step("P8.reprofile", "OPERATOR", "reprofile(['DA-RULES','H-MDMS-BILL'])",
             lambda: ctl_.reprofile(["DA-RULES", "H-MDMS-BILL"], "confirm mechanism"))
    candidates = [a for a in PHASE1_ACTIONS if a.id in ("A-ROUTE", "A-READTYPE", "A-INT-FIELD")] + REPROFILE_ACTIONS
    ranked = rank_actions(c, candidates)
    sel, _ = rec.step("P8.select", "HARNESS", "select_next_action(old + targeted candidates)",
                      lambda: select_next_action(c, candidates))
    return {"reprofile_targets": list(c.runtime.reprofile_targets),
            "ranking": [(x.action.id, x.score, x.excluded) for x in ranked],
            "selected": sel.id if sel else None,
            "selected_is_targeted": bool(sel and sel.target in ("billing-config", "mdms-export")),
            "trace": rec.trace}


def probe_advance_without_new_definition(ctx: HarnessContext, reg: ToolRegistry, ctl: ScenarioController) -> dict[str, Any]:
    """P9: right after redefine (phase DEFINE, v1 INVALIDATED, no v2 yet) — can the old path continue?"""
    c, _, k = fork(ctx, reg, ctl)
    rec = Recorder(c, "P9-noredef")
    ctl_ = PhaseController(c)
    res: dict[str, Any] = {"pd_status": c.problem.problem_definition.status.value,
                           "pd_gate_result": str(c.problem.problem_definition.gate_result)}
    _, e1 = rec.step("P9.advance_design", "PROBE", "advance DEFINE->DESIGN (v1 INVALIDATED)", ctl_.advance)
    _, e2 = rec.step("P9.advance_execute", "PROBE", "advance DESIGN->EXECUTE (stale SD-1)", ctl_.advance)
    res.update(advance_design_error=e1, advance_execute_error=e2, phase=c.runtime.phase.value)
    prop = dispatch_proposal()
    prop.action_id, prop.idempotency_key = "DISPATCH-1B", "dispatch-prio-2026-09-b"
    g, e3 = rec.step("P9.propose_old_action", "PROBE", "propose_protected_action(push_route_update) under v1 INVALIDATED",
                     lambda: propose_protected_action(c, prop, k.dispatch))
    res["propose_status"] = g.status.value if g else e3
    if g is not None and g.status.value == "WAITING_APPROVAL":
        o, _ = rec.step("P9.approve", "HUMAN", "APPROVE", lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE), k.dispatch))
        res["approve_status"] = o.status.value if o else None
    res["dispatch_calls"] = k.dispatch.count("push_route_update")
    rep, _ = rec.step("P9.verify", "PROBE", "run_verify(v1 scope)", lambda: run_verify(c, list(ROUTE_SCOPE_V1)))
    gate, _ = rec.step("P9.release_gate", "PROBE", "evaluate_release_gate(v1 scope)",
                       lambda: evaluate_release_gate(c, rep, list(ROUTE_SCOPE_V1)))
    res["release_decision"] = gate.decision.value if gate else None
    res["hold_reasons"] = gate.hold_reasons if gate else None
    res["trace"] = rec.trace
    return res


REPROFILE_ACTIONS = [
    DiscoveryAction("R-RULES", DiscoveryActionKind.TOOL_QUERY, "billing-config", "validation_rule_changes",
                    iv(0.8, 0.6, 0.8, 0.9, 0.6), tool_id="billing-config"),
    DiscoveryAction("R-UNITS", DiscoveryActionKind.TOOL_QUERY, "mdms-export", "meter_firmware_units",
                    iv(0.7, 0.5, 0.7, 0.9, 0.5, t=2.0), tool_id="mdms-export"),
]
REPROFILE_EVIDENCE = {
    "R-RULES": ("E-RULES", "billing config: BV-17 deployed 2026-08-01 compares raw register value with 12-month m3 "
                "history; unit_scaling = none", "billing.bv17_unit_scaling", "none"),
    "R-UNITS": ("E-UNITS", "MDMS: firmware v4.2 reports registers in 0.1 m3 units (rollout 2026-06); v3.x in m3",
                "meter.v42_register_unit", "0.1 m3"),
}


def _commit(c: HarnessContext, reason: str, fn: Callable[[Any], None]) -> None:
    with c.commit(reason) as ps:
        fn(ps)


# =========================================================================== main line


def main(variant: str) -> dict[str, Any]:
    outdir = HERE / "results" / variant
    with _real_open(HERE / "scenario_pack" / "public_scenario.json", encoding="utf-8") as fh:
        public = json.load(fh)
    ctl = ScenarioController()
    reg = ctl.registry()
    ctx = load_context(public)
    ctx.clock.advance(15)  # 00:00-00:15 environment / inventory (budget slot)
    rec = Recorder(ctx, variant)
    obs: dict[str, Any] = {"variant": variant, "probes": {}, "checkpoints": {}}
    hc = PhaseController(ctx)

    # ---------------------------------------------------------------- Phase 1: DISCOVER
    rec.step("1.initial_claim", "CONTROLLER", "record_claim(SH-CS initial request)",
             lambda: record_claim(ctx, "CL-CS-SLOW", "SH-CS", ctl.STAKEHOLDER_ANSWERS["SH-CS"],
                                  assertion="dispute_response.too_slow", value=True, is_initial_request=True))
    rec.step("1.initial_hypotheses", "OPERATOR_REASONER", "commit H-SLOW, H-READS, H-TARIFF",
             lambda: _commit(ctx, "initial hypotheses", lambda ps: ps.hypotheses.update({
                 "H-SLOW": Hypothesis("H-SLOW", "slow dispute responses cause escalations (requester framing)"),
                 "H-READS": Hypothesis("H-READS", "missed/late field reads -> estimated bills -> disputes",
                                       decision_impact=Crit.HIGH),
                 "H-TARIFF": Hypothesis("H-TARIFF", "a tariff change caused bill shock", decision_impact=Crit.LOW)})))
    remaining = list(PHASE1_ACTIONS)
    discovered = []
    for i in range(10):
        action, _ = rec.step(f"1.select[{i}]", "HARNESS", "select_next_action (Information Value)",
                             lambda: select_next_action(ctx, remaining))
        if action is None:
            break
        remaining.remove(action)
        out, _ = rec.step(f"1.run[{action.id}]", "CONTROLLER", f"execute {action.id} + map evidence",
                          lambda a=action: run_discovery_action(ctx, reg, ctl, a))
        discovered.append(action.id)
        ctx.clock.advance(2)
        if out and out.get("status") == "ERROR":
            o = out["outcome"]
            fc = FailureContext(o.tool_id, o.operation, o.failure_signature, o.result.error_class,
                                o.result.retryable_hint, alternate_paths=["A-READTYPE", "A-ROUTE"])
            d, _ = rec.step(f"1.recovery[{action.id}]", "HARNESS", "decide_recovery(tool failure, no invalidating ev.)",
                            lambda fc=fc: decide_recovery(ctx, fc))
            rec.step(f"1.apply_recovery[{action.id}]", "HARNESS", "apply_recovery_decision",
                     lambda d=d, fc=fc: apply_recovery_decision(ctx, d, fc))
            obs["tool_failure_recovery"] = {"kind": d.kind.value, "rationale": d.rationale,
                                            "stop_reason": d.stop_reason.value if d.stop_reason else None}
    obs["discovered"] = discovered
    rec.step("1.contract_doc", "CONTROLLER", "integrate E-CONTRACT (document)",
             lambda: integrate_evidence(ctx, ctl.contract_document()))
    rec.step("1.domain_authorization", "OPERATOR_REASONER", "record DA-DISPATCH from E-CONTRACT",
             lambda: _commit(ctx, "domain authorization from contract", lambda ps: ps.domain_authorizations.update({
                 "DA-DISPATCH": DomainAuthorization("DA-DISPATCH", "push_route_update", "field-dispatch", "ORG-UTIL",
                                                    "SH-FIELD", Scope.of(("push_route_update", "*")),
                                                    evidence_refs=["E-CONTRACT"],
                                                    status=AuthorizationStatus.GRANTED)})))
    # pre-canonical hypothesis changes (C1)
    rec.step("1.H-SLOW_rejected", "OPERATOR_REASONER", "update_hypothesis(H-SLOW, REJECTED)",
             lambda: update_hypothesis(ctx, "H-SLOW", HypothesisStatus.REJECTED, "E-CRM-SLA: responses within SLA"))
    rec.step("1.H-TARIFF_rejected", "OPERATOR_REASONER", "update_hypothesis(H-TARIFF, REJECTED)",
             lambda: update_hypothesis(ctx, "H-TARIFF", HypothesisStatus.REJECTED, "E-TARIFF: no tariff change"))
    rec.step("1.H-READS_supported", "OPERATOR_REASONER", "update_hypothesis(H-READS, SUPPORTED)",
             lambda: update_hypothesis(ctx, "H-READS", HypothesisStatus.SUPPORTED,
                                       "E-BILL-READTYPE + E-ROUTE + E-FIELD-STMT"))
    refresh(ctx)

    # ---------------------------------------------------------------- Phase 1: DEFINE v1
    ctx.clock.advance(max(0.0, 55 - ctx.clock.now()))
    rec.step("1.define_inputs_v1", "OPERATOR_REASONER", "commit metrics/SC/unknowns/assumption",
             lambda: _commit(ctx, "DEFINE inputs v1", lambda ps: reasoner_define_inputs_v1(ps, variant)))
    rec.step("1.define_problem_v1", "OPERATOR_REASONER", "define_problem(PD-1 v1 draft)",
             lambda: define_problem(ctx, pd_v1()), operator_input=pd_v1())
    rec.step("1.advance_define", "HARNESS", "advance DISCOVER->DEFINE", hc.advance)
    obs["probes"]["P1_P2_precanonical"] = probe_precanonical(ctx, reg, ctl)
    outcome, _ = rec.step("1.define_gate_eval", "HARNESS", "evaluate_define_gate", lambda: evaluate_define_gate(ctx, reg))
    rec.step("1.define_gate_apply", "HARNESS", "apply_define_gate", lambda: apply_define_gate(ctx, outcome))
    obs["define_gate_v1"] = {"result": outcome.result.value,
                             "findings": [(f.check, f.severity.value, f.message) for f in outcome.findings],
                             "vobs": [v.id for v in outcome.vobs_to_create]}

    # ---------------------------------------------------------------- Phase 1: DESIGN v1 + EXECUTE (partial)
    ctx.clock.advance(max(0.0, 75 - ctx.clock.now()))
    rec.step("1.advance_design", "HARNESS", "advance DEFINE->DESIGN", hc.advance)
    rec.step("1.design_v1", "OPERATOR_REASONER", "design_solution(SD-1, inputs v1)",
             lambda: design_solution(ctx, design_inputs_v1(), "SD-1"), operator_input=design_inputs_v1())
    ctx.clock.advance(max(0.0, 100 - ctx.clock.now()))
    rec.step("1.advance_execute", "HARNESS", "advance DESIGN->EXECUTE", hc.advance)
    rec.step("1.plan_v1", "OPERATOR_REASONER", "set_plan(PLAN-1)", lambda: set_plan(ctx, plan_v1()))
    lag, _ = rec.step("1.exec_lagging_routes", "HARNESS", "invoke_tool(route-log.lagging_routes)",
                      lambda: invoke_tool(ctx, reg, "route-log", "lagging_routes"))
    rec.step("1.inspect_DA-ROUTE", "HARNESS", "apply_inspection(DA-ROUTE)",
             lambda: apply_inspection(ctx, "DA-ROUTE", inspect_records(
                 lag.result.records, schema={"route": "str", "completion": "float"},
                 expected_count=lag.result.expected_count, pagination_complete=True)))
    risk, _ = rec.step("1.exec_risk_accounts", "HARNESS", "invoke_tool(billing-db.accounts_estimated_last_cycle)",
                       lambda: invoke_tool(ctx, reg, "billing-db", "accounts_estimated_last_cycle"))
    rec.step("1.inspect_DA-BILL", "HARNESS", "apply_inspection(DA-BILL)",
             lambda: apply_inspection(ctx, "DA-BILL", inspect_records(
                 risk.result.records, schema={"account_id": "str", "route": "str"},
                 expected_count=risk.result.expected_count, pagination_complete=True)))
    for w in ctx.runtime.current_plan.work_items:
        if w.id in ("W1-RANK", "W3-FLAG"):
            w.status = "DONE"
    ctx.clock.advance(20)
    gate_out, _ = rec.step("1.propose_dispatch", "HARNESS", "propose_protected_action(push_route_update)",
                           lambda: propose_protected_action(ctx, dispatch_proposal(), ctl.dispatch),
                           operator_input=dispatch_proposal())
    obs["dispatch_gate_v1"] = {"status": gate_out.status.value if gate_out else None,
                               "reasons": gate_out.reasons if gate_out else None,
                               "packet": gate_out.packet.render() if gate_out and gate_out.packet else None}
    refresh(ctx)
    cp = ctl.phase1_checkpoint(ctx)
    obs["checkpoints"]["phase1"] = cp
    obs["inventory_v1"] = inventory(ctx)
    save(outdir, "snapshot_checkpoint_v1.json", ctx.snapshot())

    # ---------------------------------------------------------------- Phase 2: late authoritative evidence
    ctx.clock.advance(5)
    pre_late = fork(ctx, reg, ctl)  # for P4 (no operator transition) variants
    msg, _ = rec.step("2.vendor_provisions_mdms", "CONTROLLER", "provision_mdms (checkpoint-gated)",
                      lambda: ctl.provision_mdms(ctx))
    rec.step("2.sh_ami_message", "CONTROLLER", "integrate SH-AMI provisioning notice (stakeholder evidence)",
             lambda: integrate_evidence(ctx, stakeholder_evidence("E-AMI-NOTICE", "SH-AMI", msg)))
    live_before = len(ctx.supervision.live_summary)
    ev_before = len(ctx.events)
    mdms_action = next(a for a in PHASE1_ACTIONS if a.id == "A-MDMS")
    rec.step("2.mdms_query", "CONTROLLER", "re-run deferred A-MDMS via tool path (default impact)",
             lambda: run_discovery_action(ctx, reg, ctl, mdms_action))
    refresh(ctx)
    obs["harness_reaction_to_late_evidence"] = {
        "new_events": [event_dict(e) for e in list(ctx.events)[ev_before:]],
        "new_live_summary": ctx.supervision.live_summary[live_before:],
        "problem_status": ctx.problem.problem_definition.status.value,
        "transition_candidate": to_dict(ctx.runtime.transition_candidate),
        "recovery_candidate": ctx.runtime.recovery.candidate_transition.value
        if ctx.runtime.recovery.candidate_transition else None,
        "execution_status": ctx.runtime.execution_status.value,
        "pending_gate": ctx.runtime.pending_protected_action.gate_id if ctx.runtime.pending_protected_action else None,
    }
    obs["inventory_after_late_evidence"] = inventory(ctx)
    save(outdir, "snapshot_after_late_evidence.json", ctx.snapshot())
    obs["probes"]["P4_control_no_late_evidence"] = probe_no_operator_transition(*pre_late, None)
    obs["probes"]["P4_no_transition_MEDIUM"] = probe_no_operator_transition(*pre_late, Crit.MEDIUM)
    obs["probes"]["P4_no_transition_CRITICAL"] = probe_no_operator_transition(*pre_late, Crit.CRITICAL)
    obs["probes"]["P5_discrimination"] = probe_discrimination(ctx, reg, ctl)

    # ---------------------------------------------------------------- transition (operator-invoked harness API)
    rec.step("2.revise_E-BILL-READTYPE", "OPERATOR_REASONER", "revise_evidence(E-BILL-READTYPE by E-MDMS)",
             lambda: revise_evidence(ctx, "E-BILL-READTYPE", "E-MDMS",
                                     "ESTIMATED read type does not mean no read was collected: 1,184/1,240 had valid "
                                     "AMI reads rejected at billing import", invalidates_problem=True))
    rec.step("2.revise_E-ROUTE", "OPERATOR_REASONER", "revise_evidence(E-ROUTE by E-MDMS)",
             lambda: revise_evidence(ctx, "E-ROUTE", "E-MDMS",
                                     "route shortfall is real but the disputed estimated accounts are AMI accounts, "
                                     "not manual-read routes: not causal", invalidates_problem=True))
    fc = FailureContext("n/a", "late-evidence-review", None, None, None, problem_invalidating_evidence="E-MDMS")
    d, _ = rec.step("2.decide_recovery", "OPERATOR", "decide_recovery(problem_invalidating_evidence=E-MDMS)",
                    lambda: decide_recovery(ctx, fc), note="the 'invalidating' flag is an operator assertion")
    rec.step("2.apply_recovery", "HARNESS", "apply_recovery_decision", lambda: apply_recovery_decision(ctx, d, fc))
    obs["transition_decision"] = {"kind": d.kind.value, "rationale": d.rationale,
                                  "transition_candidate": to_dict(ctx.runtime.transition_candidate)}
    _, err1 = rec.step("2.redefine_attempt_1", "OPERATOR", "PhaseController.redefine(E-MDMS)",
                       lambda: hc.redefine("E-MDMS", "authoritative MDMS evidence: estimates come from rejected AMI "
                                                     "reads at billing import, not missed field reads"))
    obs["redefine_attempt_1"] = {"error": err1, "inventory": inventory(ctx)}
    obs["probes"]["P6b_approve_after_failed_redefine"] = probe_approve_after_failed_redefine(ctx, reg, ctl)
    if ctx.runtime.pending_protected_action is not None:
        text = "거절합니다"
        kind = interpret_human_input(text)
        rec.step("2.human_reject_old_action", "HUMAN", f"decide({kind.value}: '{text}')",
                 lambda: decide(ctx, HumanDecision(kind, text), ctl.dispatch))
        obs["after_human_reject"] = {"transition_candidate": to_dict(ctx.runtime.transition_candidate),
                                     "execution_status": ctx.runtime.execution_status.value}
    if ctx.runtime.phase is not Phase.DEFINE:
        _, err2 = rec.step("2.redefine_attempt_2", "OPERATOR", "PhaseController.redefine(E-MDMS) again",
                           lambda: hc.redefine("E-MDMS", "authoritative MDMS evidence invalidates PD-1 v1"))
        obs["redefine_attempt_2"] = {"error": err2}
    refresh(ctx)
    obs["inventory_after_redefine"] = inventory(ctx)
    save(outdir, "snapshot_after_redefine.json", ctx.snapshot())
    obs["probes"]["P9_advance_without_new_definition"] = probe_advance_without_new_definition(ctx, reg, ctl)
    obs["probes"]["P10_duplicate_redefine"] = probe_duplicate_redefine(ctx, reg, ctl)
    obs["probes"]["P8_reprofile_targeting"] = probe_reprofile_targeting(ctx, reg, ctl)

    # ---------------------------------------------------------------- selective rediscovery (targeted reprofile)
    rec.step("3.reprofile", "OPERATOR", "reprofile(['DA-RULES','H-MDMS-BILL'])",
             lambda: hc.reprofile(["DA-RULES", "H-MDMS-BILL"], "confirm mechanism of rejected AMI reads"))
    remaining2 = list(REPROFILE_ACTIONS)
    for i in range(3):
        a, _ = rec.step(f"3.select[{i}]", "HARNESS", "select_next_action(targeted candidates)",
                        lambda: select_next_action(ctx, remaining2))
        if a is None:
            break
        remaining2.remove(a)

        def _run(a: DiscoveryAction = a) -> str:
            o = invoke_tool(ctx, reg, a.tool_id, a.question)
            eid, content, assertion, value = REPROFILE_EVIDENCE[a.id]
            integrate_evidence(ctx, evidence_from_outcome(ctx, o, eid, content, target_assertion=assertion,
                                                          value=value))
            return eid

        rec.step(f"3.run[{a.id}]", "CONTROLLER", f"execute {a.id} + map evidence", _run)
    rec.step("3.return_from_reprofile", "HARNESS", "return_from_reprofile", hc.return_from_reprofile)
    obs["probes"]["P7_version_reuse"] = probe_version_reuse(ctx, reg, ctl)

    # ---------------------------------------------------------------- DEFINE v2
    rec.step("3.define_inputs_v2", "OPERATOR_REASONER", "commit v2 hypothesis/metric/SC/unknown",
             lambda: _commit(ctx, "DEFINE inputs v2", reasoner_define_inputs_v2))
    rec.step("3.define_v2_attemptA", "OPERATOR_REASONER", "define_problem(PD-1 v2, cites revised E-BILL-READTYPE)",
             lambda: define_problem(ctx, pd_v2(cite_revised=True)), operator_input=pd_v2(True))
    ga, _ = rec.step("3.gate_v2_attemptA_eval", "HARNESS", "evaluate_define_gate (not applied)",
                     lambda: evaluate_define_gate(ctx, reg))
    obs["define_gate_v2_attemptA"] = {"result": ga.result.value,
                                      "findings": [(f.check, f.severity.value, f.message, f.refs) for f in ga.findings
                                                   if f.severity.value != "OK"]}
    rec.step("3.define_v2_attemptB", "OPERATOR_REASONER", "define_problem(PD-1 v2 without revised evidence)",
             lambda: define_problem(ctx, pd_v2(cite_revised=False)), operator_input=pd_v2(False))
    gb, _ = rec.step("3.gate_v2_eval", "HARNESS", "evaluate_define_gate", lambda: evaluate_define_gate(ctx, reg))
    rec.step("3.gate_v2_apply", "HARNESS", "apply_define_gate", lambda: apply_define_gate(ctx, gb))
    obs["define_gate_v2"] = {"result": gb.result.value,
                             "findings": [(f.check, f.severity.value, f.message) for f in gb.findings
                                          if f.severity.value != "OK"],
                             "vobs": [v.id for v in gb.vobs_to_create]}

    # ---------------------------------------------------------------- DESIGN v2 / EXECUTE v2
    rec.step("3.advance_design", "HARNESS", "advance DEFINE->DESIGN", hc.advance)
    rec.step("3.design_v2", "OPERATOR_REASONER", "design_solution(SD-2, inputs v2)",
             lambda: design_solution(ctx, design_inputs_v2(), "SD-2"), operator_input=design_inputs_v2())
    rec.step("3.advance_execute", "HARNESS", "advance DESIGN->EXECUTE", hc.advance)
    obs["plan_before_replacement"] = inventory(ctx)["plan"]
    rec.step("3.plan_v2", "OPERATOR_REASONER", "set_plan(PLAN-2)", lambda: set_plan(ctx, plan_v2()))
    imp, _ = rec.step("3.exec_import_status", "HARNESS", "invoke_tool(billing-db.import_status_estimated_disputed)",
                      lambda: invoke_tool(ctx, reg, "billing-db", "import_status_estimated_disputed"))
    aff, _ = rec.step("3.exec_affected_accounts", "HARNESS", "invoke_tool(billing-db.affected_accounts_v42)",
                      lambda: invoke_tool(ctx, reg, "billing-db", "affected_accounts_v42"))
    mr, _ = rec.step("3.exec_mdms_reads", "HARNESS", "invoke_tool(mdms-export.reads_for_accounts)",
                     lambda: invoke_tool(ctx, reg, "mdms-export", "reads_for_accounts"))
    schema = {"account_id": "str", "firmware": "str", "ami_read_ts": "str", "import_status": "str",
              "bill_read_type": "str"}
    rec.step("3.inspect_DA-BILL", "HARNESS", "apply_inspection(DA-BILL)",
             lambda: apply_inspection(ctx, "DA-BILL", inspect_records(
                 aff.result.records, schema=schema, key_fields=["account_id"],
                 expected_count=aff.result.expected_count, pagination_complete=True)))
    rec.step("3.inspect_DA-MDMS", "HARNESS", "apply_inspection(DA-MDMS)",
             lambda: apply_inspection(ctx, "DA-MDMS", inspect_records(
                 mr.result.records, schema=schema, key_fields=["account_id"],
                 expected_count=mr.result.expected_count, pagination_complete=True)))
    mdms_ids = {r["account_id"] for r in mr.result.records}
    queue = [dict(r, queue="BILLING_OPS_REVIEW") for r in aff.result.records if r["account_id"] in mdms_ids]
    for w in ctx.runtime.current_plan.work_items:
        if w.id.startswith("V2-") and w.work_class is WorkClass.CORE_FEATURE:
            w.status = "DONE"
    ctx.clock.advance(max(0.0, 230 - ctx.clock.now()))

    # ---------------------------------------------------------------- VERIFY / RELEASE v2
    rec.step("4.advance_verify", "HARNESS", "advance EXECUTE->VERIFY", hc.advance)
    out_spec = OutputSpec("escalation_queue", queue, schema={**schema, "queue": "str"}, key_fields=["account_id"],
                          expected_count=1184)
    rep, _ = rec.step("4.verify", "HARNESS", "run_verify(v2 release scope)",
                      lambda: run_verify(ctx, list(SCOPE_V2_RELEASE), outputs=[out_spec]))
    obs["verify_v2"] = {"layer1_passed": rep.layer1_passed,
                        "checks": [(c.name, c.layer.value, c.status.value, c.detail) for c in rep.checks],
                        "human_review": [to_dict(h) for h in rep.human_review]} if rep else None
    ctx.clock.advance(max(0.0, 262 - ctx.clock.now()))
    rec.step("4.advance_release", "HARNESS", "advance VERIFY->RELEASE", hc.advance)
    gate, _ = rec.step("4.release_gate", "HARNESS", "evaluate_release_gate(v2)",
                       lambda: evaluate_release_gate(ctx, rep, list(SCOPE_V2_RELEASE)))
    obs["release_v2"] = {"decision": gate.decision.value, "hold": gate.hold_reasons,
                         "limitations": gate.known_limitations,
                         "minimum_useful": to_dict(gate.minimum_useful)} if gate else None
    if gate and gate.decision.value != "HOLD":
        rec.step("4.finish", "HARNESS", "finish", hc.finish)
    else:
        rec.step("4.hold", "HARNESS", "hold", lambda: hc.hold("Release Gate HOLD"))
    refresh(ctx)
    obs["inventory_final"] = inventory(ctx)
    obs["final_live_summary"] = list(ctx.supervision.live_summary)
    save(outdir, "snapshot_final.json", ctx.snapshot())
    save(outdir, "events.json", [event_dict(e) for e in ctx.events])
    save(outdir, "trace.json", rec.trace)
    save(outdir, "observations.json", obs)
    print(f"[{variant}] done: {len(ctx.events)} events, release={obs['release_v2'] and obs['release_v2']['decision']}")
    return obs


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="scoped", choices=["scoped", "u1_default_scope"])
    main(p.parse_args().variant)

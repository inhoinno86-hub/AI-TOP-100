"""Typed proposals (prompt §10). Reasoner raw output → schema validation → one of these.

Nothing here is canonical state. A proposal is an *offer* to the Harness Core; the Core validates it
(``engine.proposals``) and either commits through the existing phase functions or rejects it.
Every factual assertion carries references; anything without them is an ASSUMPTION / UNKNOWN /
PROPOSAL, never a Fact (prompt §23).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.enums import Criticality


@dataclass
class ScopeRef:
    action: str
    target: str


def _scope(items: list[dict[str, Any]]) -> list[ScopeRef]:
    return [ScopeRef(str(i["action"]), str(i["target"])) for i in items]


def _crit(v: str) -> Criticality:
    return Criticality(v)


# --------------------------------------------------------------------------- DISCOVER


@dataclass
class HypothesisProposal:
    key: str
    statement: str
    decision_impact: Criticality
    rationale: str
    origin: str = "ALTERNATIVE"
    supports: list[str] = field(default_factory=list)
    contradicts: list[str] = field(default_factory=list)
    confidence: float = 0.5
    evidence_refs: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)


@dataclass
class HypothesisInitProposal:
    framing_key: str
    framing_value: Any
    framing_rationale: str
    hypotheses: list[HypothesisProposal]
    confidence: float


@dataclass
class DiscoveryActionProposal:
    catalog_ref: str
    question: str
    decision_impact: float
    uncertainty: float
    discriminative_power: float
    answerability: float
    process_data_handoff_impact: float
    action_proximity: float
    constraint_risk: float
    estimated_cost: float
    expected_information_gain: str
    decision_impact_rationale: str
    discriminates_hypotheses: list[str]
    resolves_unknowns: list[str]
    addresses: list[str]
    why_now: str


@dataclass
class DiscoveryPlanProposal:
    actions: list[DiscoveryActionProposal]
    stop: bool
    stop_reason: str


# --------------------------------------------------------------------------- evidence


@dataclass
class HypothesisEffect:
    hypothesis: str
    effect: str  # SUPPORTS / CONTRADICTS / NEUTRAL
    rationale: str


@dataclass
class FactCandidate:
    statement: str
    assertion_key: str
    value: Any
    evidence_refs: list[str]


@dataclass
class AuthorizationCandidate:
    action: str
    resource: str
    authority_holder: str
    scope_target: str
    conditions: list[str]
    rationale: str


@dataclass
class ContradictionAssessment:
    """Prompt §16. The Core never trusts this blindly (``engine.proposals.check_assessment``)."""

    relation: str  # SUPPORTS / CONTRADICTS / UNRELATED / PARTIAL_CONTRADICTION
    target_type: str  # CLAIM / HYPOTHESIS / PROBLEM_PREMISE / SOLUTION_PATH / NONE
    target_refs: list[str]
    materiality: Criticality
    problem_invalidating: bool
    rationale: str


@dataclass
class VOBProposal:
    unresolved_question: str
    decision_impact: Criticality
    required_before: str
    blocking_scope: list[ScopeRef]
    entire_solution: bool
    validation_method: str
    required_evidence: list[str]
    linked_unknown: str
    rationale: str


@dataclass
class EvidenceInterpretationProposal:
    """Prompt §10 EvidenceInterpretationProposal (+ §12 candidates, §16 contradiction assessment)."""

    interpretation: str
    assertion_key: str
    assertion_value: Any
    claim_assertion_key: str
    claim_assertion_value: Any
    hypothesis_effects: list[HypothesisEffect]
    new_hypotheses: list[HypothesisProposal]
    fact_candidates: list[FactCandidate]
    unknown_resolutions: list[tuple[str, str]]
    authorization_candidates: list[AuthorizationCandidate]
    assessment: ContradictionAssessment
    vob_proposals: list[VOBProposal]
    follow_up_actions: list[str]
    confidence: float


@dataclass
class HypothesisUpdate:
    hypothesis: str
    status: str
    rationale: str
    evidence_refs: list[str]


@dataclass
class HypothesisAssessmentProposal:
    updates: list[HypothesisUpdate]
    ready_to_define: bool
    rationale: str


# --------------------------------------------------------------------------- DEFINE


@dataclass
class AssumptionProposal:
    key: str
    statement: str
    evidence_refs: list[str]
    risk_if_wrong: Criticality


@dataclass
class UnknownProposal:
    key: str
    question: str
    criticality: Criticality
    decision_impact: str
    affects_scope: list[ScopeRef]
    resolution_path: str
    safe_placeholder: str


@dataclass
class MetricProposal:
    key: str
    name: str
    metric_type: str
    semantics: dict[str, Any]
    current_value: float | None
    current_value_evidence_refs: list[str]
    target_value: float | None


@dataclass
class SuccessCriterionProposal:
    key: str
    statement: str
    kind: str  # MUST / TARGET / KNOWN_LIMITATION (prompt §21)
    metric: str
    threshold: str
    validation_method: str


@dataclass
class ProblemDefinitionProposal:
    """Prompt §10 ProblemDefinitionProposal (+ §13 minimum content)."""

    problem_statement: str
    requested_solution: str
    symptoms: list[str]
    affected_process: str
    causal_chain: list[str]
    premise_hypotheses: list[str]
    evidence_refs: list[str]
    assumptions: list[AssumptionProposal]
    unknowns: list[UnknownProposal]
    metrics: list[MetricProposal]
    success_criteria: list[SuccessCriterionProposal]
    intended_scope: list[ScopeRef]
    protected_actions: list[str]
    required_tools: list[str]
    depends_on_handoffs: list[str]
    constraint_refs: list[str]
    rejected_framings: list[tuple[str, str]]
    confidence: float
    vob_reevaluation: list[tuple[str, str, str, list[str]]] = field(default_factory=list)


# --------------------------------------------------------------------------- DESIGN


@dataclass
class RemedyCandidateProposal:
    key: str
    description: str
    removes_root_cause: bool
    feasible_in_contest_time: bool
    constraint_feasible: bool
    feasibility_rationale: str
    residual_gap: str


@dataclass
class StructuralRemedyProposal:
    root_cause: str
    remedies: list[RemedyCandidateProposal]
    why_agent_needed: str
    confidence: float


@dataclass
class AgentDesignProposal:
    """Prompt §10 AgentDesignProposal (role is a *suggestion*: Core classifies roles)."""

    deterministic_rules_cover_cases: bool
    llm_reasoning_adds_value: bool
    autonomous_iteration_adds_value: bool
    residual_exceptions: bool
    detection_needed: bool
    why_agent: str
    bridge_sunset_condition: str
    deterministic_components: list[str]
    release_scope: list[ScopeRef]
    minimum_useful_scope: list[ScopeRef]
    scope_dependencies: dict[str, list[str]]
    role_suggestion: list[str]
    capabilities: list[str]
    llm_required_for: list[str]
    tools: list[str]
    authority_boundary: list[str]
    human_gate: list[str]
    termination: str
    validation: list[str]
    known_limitations: list[str]
    vob_proposals: list[VOBProposal]
    confidence: float


# --------------------------------------------------------------------------- EXECUTE


@dataclass
class WorkItemProposal:
    key: str
    description: str
    work_class: str
    est_minutes: float
    scope_items: list[ScopeRef]
    root_problem_aligned: bool
    release_blocking: bool
    data_ops: list[str]
    output_name: str
    output_key_fields: list[str]
    output_join: bool
    output_constant_fields: dict[str, str]


@dataclass
class ProtectedActionProposalDraft:
    key: str
    action: str
    resource: str
    subject: str
    scope: list[ScopeRef]
    why: str
    side_effect: str
    reversibility: str
    alternatives: list[str]
    key_evidence: list[str]
    work_item: str


@dataclass
class ExecutionPlanProposal:
    work_items: list[WorkItemProposal]
    protected_actions: list[ProtectedActionProposalDraft]
    rationale: str


# --------------------------------------------------------------------------- recovery


@dataclass
class EvidenceRevisionProposal:
    """Prompt §17. Core validates observation validity / kind / dependency links before commit."""

    evidence: str
    revised_interpretation: str
    revision_kind: str
    problem_invalidating: bool
    affected_objects: list[str]
    reason: str


@dataclass
class RevisionSetProposal:
    revisions: list[EvidenceRevisionProposal]


@dataclass
class ReprofileProposal:
    """Prompt §19."""

    targets: list[str]
    reason: str
    required_evidence: list[str]
    expected_decision_impact: str


@dataclass
class TransitionProposal:
    """Prompt §10 TransitionProposal. The existing Core transition validator decides."""

    transition_candidate: str  # RETRY / REPLAN / REPROFILE / REDEFINE / CONTINUE
    trigger_evidence_refs: list[str]
    rationale: str
    affected_scope: list[str]
    confidence: float
    reprofile: ReprofileProposal | None


# --------------------------------------------------------------------------- VERIFY


@dataclass
class JudgeCheck:
    name: str
    status: str
    detail: str
    refs: list[str]


@dataclass
class SemanticJudgeProposal:
    checks: list[JudgeCheck]


@dataclass
class ReleaseSummaryProposal:
    summary: str
    key_points: list[str]
    limitations_explained: list[str]


# =========================================================================== parsing


def _vob(v: dict[str, Any]) -> VOBProposal:
    return VOBProposal(
        unresolved_question=v["unresolved_question"],
        decision_impact=_crit(v["decision_impact"]),
        required_before=v["required_before"],
        blocking_scope=_scope(v["blocking_scope"]),
        entire_solution=bool(v["entire_solution"]),
        validation_method=v["validation_method"],
        required_evidence=list(v["required_evidence"]),
        linked_unknown=v["linked_unknown"],
        rationale=v["rationale"],
    )


def parse_hypothesis_init(o: dict[str, Any]) -> HypothesisInitProposal:
    fa = o["framing_assertion"]
    return HypothesisInitProposal(
        framing_key=fa["key"],
        framing_value=fa["value"],
        framing_rationale=fa["rationale"],
        hypotheses=[
            HypothesisProposal(
                key=h["key"],
                statement=h["statement"],
                decision_impact=_crit(h["decision_impact"]),
                rationale=h["rationale"],
                origin=h["origin"],
                unknowns=list(h["discriminating_evidence"]),
            )
            for h in o["hypotheses"]
        ],
        confidence=float(o["confidence"]),
    )


def parse_discover_actions(o: dict[str, Any]) -> DiscoveryPlanProposal:
    return DiscoveryPlanProposal(
        actions=[
            DiscoveryActionProposal(
                catalog_ref=a["catalog_ref"],
                question=a["question"],
                decision_impact=float(a["decision_impact"]),
                uncertainty=float(a["uncertainty"]),
                discriminative_power=float(a["discriminative_power"]),
                answerability=float(a["answerability"]),
                process_data_handoff_impact=float(a["process_data_handoff_impact"]),
                action_proximity=float(a["action_proximity"]),
                constraint_risk=float(a["constraint_risk"]),
                estimated_cost=float(a["estimated_cost_minutes"]),
                expected_information_gain=a["expected_information_gain"],
                decision_impact_rationale=a["decision_impact_rationale"],
                discriminates_hypotheses=list(a["discriminates_hypotheses"]),
                resolves_unknowns=list(a["resolves_unknowns"]),
                addresses=list(a["addresses"]),
                why_now=a["why_now"],
            )
            for a in o["actions"]
        ],
        stop=bool(o["stop"]),
        stop_reason=o["stop_reason"],
    )


def parse_interpret_evidence(o: dict[str, Any]) -> EvidenceInterpretationProposal:
    ca = o["contradiction_assessment"]
    return EvidenceInterpretationProposal(
        interpretation=o["interpretation"],
        assertion_key=o.get("assertion_key", ""),
        assertion_value=o.get("assertion_value", ""),
        claim_assertion_key=o.get("claim_assertion_key", ""),
        claim_assertion_value=o.get("claim_assertion_value", ""),
        hypothesis_effects=[
            HypothesisEffect(e["hypothesis"], e["effect"], e["rationale"]) for e in o["hypothesis_effects"]
        ],
        new_hypotheses=[
            HypothesisProposal(
                key=h["key"],
                statement=h["statement"],
                decision_impact=_crit(h["decision_impact"]),
                rationale=h["rationale"],
            )
            for h in o["new_hypotheses"]
        ],
        fact_candidates=[
            FactCandidate(f["statement"], f["assertion_key"], f["value"], list(f["evidence_refs"]))
            for f in o["fact_candidates"]
        ],
        unknown_resolutions=[(u["unknown"], u["resolution"]) for u in o["unknown_resolutions"]],
        authorization_candidates=[
            AuthorizationCandidate(
                a["action"],
                a["resource"],
                a["authority_holder"],
                a["scope_target"],
                list(a["conditions"]),
                a["rationale"],
            )
            for a in o["authorization_candidates"]
        ],
        assessment=ContradictionAssessment(
            relation=ca["relation"],
            target_type=ca["target_type"],
            target_refs=list(ca["target_refs"]),
            materiality=_crit(ca["materiality"]),
            problem_invalidating=bool(ca["problem_invalidating"]),
            rationale=ca["rationale"],
        ),
        vob_proposals=[_vob(v) for v in o["vob_proposals"]],
        follow_up_actions=list(o["follow_up_actions"]),
        confidence=float(o["confidence"]),
    )


def parse_assess_hypotheses(o: dict[str, Any]) -> HypothesisAssessmentProposal:
    return HypothesisAssessmentProposal(
        updates=[
            HypothesisUpdate(u["hypothesis"], u["status"], u["rationale"], list(u["evidence_refs"]))
            for u in o["updates"]
        ],
        ready_to_define=bool(o["ready_to_define"]),
        rationale=o["rationale"],
    )


_METRIC_SEMANTICS = (
    "numerator",
    "denominator",
    "population",
    "start_event",
    "end_event",
    "measurement_window",
    "aggregation",
    "owner",
)


def parse_define_problem(o: dict[str, Any]) -> ProblemDefinitionProposal:
    return ProblemDefinitionProposal(
        problem_statement=o["root_problem"],
        requested_solution=o["requested_solution"],
        symptoms=list(o["symptoms"]),
        affected_process=o["affected_process"],
        causal_chain=list(o["causal_chain"]),
        premise_hypotheses=list(o["premise_hypotheses"]),
        evidence_refs=list(o["evidence_refs"]),
        assumptions=[
            AssumptionProposal(a["key"], a["statement"], list(a["evidence_refs"]), _crit(a["risk_if_wrong"]))
            for a in o["assumptions"]
        ],
        unknowns=[
            UnknownProposal(
                key=u["key"],
                question=u["question"],
                criticality=_crit(u["criticality"]),
                decision_impact=u["decision_impact"],
                affects_scope=_scope(u["affects_scope"]),
                resolution_path=u["resolution_path"],
                safe_placeholder=u["safe_placeholder"],
            )
            for u in o["unknowns"]
        ],
        metrics=[
            MetricProposal(
                key=m["key"],
                name=m["name"],
                metric_type=m["metric_type"],
                semantics={k: m[k] for k in _METRIC_SEMANTICS if m.get(k)},
                current_value=m.get("current_value"),
                current_value_evidence_refs=list(m.get("current_value_evidence_refs", [])),
                target_value=m.get("target_value"),
            )
            for m in o["metrics"]
        ],
        success_criteria=[
            SuccessCriterionProposal(
                s["key"], s["statement"], s["kind"], s["metric"], s["threshold"], s["validation_method"]
            )
            for s in o["success_criteria"]
        ],
        intended_scope=_scope(o["intended_scope"]),
        protected_actions=list(o["protected_actions"]),
        required_tools=list(o["required_tools"]),
        depends_on_handoffs=list(o["depends_on_handoffs"]),
        constraint_refs=list(o["constraint_refs"]),
        rejected_framings=[(r["hypothesis"], r["why"]) for r in o["rejected_framings"]],
        confidence=float(o["confidence"]),
        vob_reevaluation=[
            (v["vob"], v["decision"], v["rationale"], list(v["evidence_refs"]))
            for v in o.get("vob_reevaluation", [])
        ],
    )


def parse_structural_remedy(o: dict[str, Any]) -> StructuralRemedyProposal:
    return StructuralRemedyProposal(
        root_cause=o["root_cause"],
        remedies=[
            RemedyCandidateProposal(
                r["key"],
                r["description"],
                bool(r["removes_root_cause"]),
                bool(r["feasible_in_contest_time"]),
                bool(r["constraint_feasible"]),
                r["feasibility_rationale"],
                r["residual_gap"],
            )
            for r in o["remedies"]
        ],
        why_agent_needed=o["why_agent_needed"],
        confidence=float(o["confidence"]),
    )


def parse_agent_design(o: dict[str, Any]) -> AgentDesignProposal:
    return AgentDesignProposal(
        deterministic_rules_cover_cases=bool(o["deterministic_rules_cover_cases"]),
        llm_reasoning_adds_value=bool(o["llm_reasoning_adds_value"]),
        autonomous_iteration_adds_value=bool(o["autonomous_iteration_adds_value"]),
        residual_exceptions=bool(o["residual_exceptions"]),
        detection_needed=bool(o["detection_needed"]),
        why_agent=o["why_agent"],
        bridge_sunset_condition=o["bridge_sunset_condition"],
        deterministic_components=list(o["deterministic_components"]),
        release_scope=_scope(o["release_scope"]),
        minimum_useful_scope=_scope(o["minimum_useful_scope"]),
        scope_dependencies={d["action"]: list(d["depends_on"]) for d in o["scope_dependencies"]},
        role_suggestion=list(o["role_suggestion"]),
        capabilities=list(o["capabilities"]),
        llm_required_for=list(o["llm_required_for"]),
        tools=list(o["tools"]),
        authority_boundary=list(o["authority_boundary"]),
        human_gate=list(o["human_gate"]),
        termination=o["termination"],
        validation=list(o["validation"]),
        known_limitations=list(o["known_limitations"]),
        vob_proposals=[_vob(v) for v in o["vob_proposals"]],
        confidence=float(o["confidence"]),
    )


def parse_plan_execution(o: dict[str, Any]) -> ExecutionPlanProposal:
    return ExecutionPlanProposal(
        work_items=[
            WorkItemProposal(
                key=w["key"],
                description=w["description"],
                work_class=w["work_class"],
                est_minutes=float(w["est_minutes"]),
                scope_items=_scope(w["scope_items"]),
                root_problem_aligned=bool(w["root_problem_aligned"]),
                release_blocking=bool(w["release_blocking"]),
                data_ops=list(w["data_ops"]),
                output_name=w.get("output_name", ""),
                output_key_fields=list(w.get("output_key_fields", [])),
                output_join=bool(w.get("output_join", False)),
                output_constant_fields={c["field"]: c["value"] for c in w.get("output_constant_fields", [])},
            )
            for w in o["work_items"]
        ],
        protected_actions=[
            ProtectedActionProposalDraft(
                key=p["key"],
                action=p["action"],
                resource=p["resource"],
                subject=p["subject"],
                scope=_scope(p["scope"]),
                why=p["why"],
                side_effect=p["side_effect"],
                reversibility=p["reversibility"],
                alternatives=list(p["alternatives"]),
                key_evidence=list(p["key_evidence"]),
                work_item=p["work_item"],
            )
            for p in o["protected_actions"]
        ],
        rationale=o["rationale"],
    )


def parse_revise_evidence(o: dict[str, Any]) -> RevisionSetProposal:
    return RevisionSetProposal(
        revisions=[
            EvidenceRevisionProposal(
                r["evidence"],
                r["revised_interpretation"],
                r["revision_kind"],
                bool(r["problem_invalidating"]),
                list(r["affected_objects"]),
                r["reason"],
            )
            for r in o["revisions"]
        ]
    )


def parse_propose_transition(o: dict[str, Any]) -> TransitionProposal:
    targets = list(o.get("reprofile_targets", []))
    return TransitionProposal(
        transition_candidate=o["transition_candidate"],
        trigger_evidence_refs=list(o["trigger_evidence_refs"]),
        rationale=o["rationale"],
        affected_scope=list(o["affected_scope"]),
        confidence=float(o["confidence"]),
        reprofile=ReprofileProposal(
            targets=targets,
            reason=o.get("reprofile_reason", ""),
            required_evidence=list(o.get("reprofile_required_evidence", [])),
            expected_decision_impact=o.get("reprofile_expected_decision_impact", ""),
        )
        if targets
        else None,
    )


def parse_semantic_judge(o: dict[str, Any]) -> SemanticJudgeProposal:
    return SemanticJudgeProposal(
        checks=[JudgeCheck(c["name"], c["status"], c["detail"], list(c["refs"])) for c in o["checks"]]
    )


def parse_release_summary(o: dict[str, Any]) -> ReleaseSummaryProposal:
    return ReleaseSummaryProposal(o["summary"], list(o["key_points"]), list(o["limitations_explained"]))


PARSERS: dict[str, Any] = {
    "hypothesis_init": parse_hypothesis_init,
    "discover_actions": parse_discover_actions,
    "interpret_evidence": parse_interpret_evidence,
    "assess_hypotheses": parse_assess_hypotheses,
    "define_problem": parse_define_problem,
    "structural_remedy": parse_structural_remedy,
    "agent_design": parse_agent_design,
    "plan_execution": parse_plan_execution,
    "revise_evidence": parse_revise_evidence,
    "propose_transition": parse_propose_transition,
    "semantic_judge": parse_semantic_judge,
    "release_summary": parse_release_summary,
}

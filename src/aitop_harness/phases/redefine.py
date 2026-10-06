"""Canonical Problem lifecycle — premise monitoring, redefine validation, Dependency Review.

Implements IDR-REDEFINE-01..08 (``docs/implementation/IMPLEMENTATION_DECISIONS.md`` §4) inside the
frozen three-state model; nothing here is a fourth canonical state:

* a *challenge* lives on the ProblemDefinition (``CanonicalChallenge``),
* a *Dependency Review* is a record in ``ProblemState.dependency_reviews``,
* the REDEFINE candidate and the pending-action revalidation flag live in RuntimeState.

The materiality test consumes *recorded epistemic relations* only — an assertion contradiction of
premise evidence, a contradicted premise-dependent hypothesis, or a problem-invalidating revision of
premise evidence. It never consumes a caller's transition label (``problem_invalidating_evidence``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.enums import (
    AssumptionStatus,
    ChallengeStatus,
    ConflictStatus,
    Criticality,
    DependencyClassification,
    EvidenceRelation,
    EvidenceSourceType,
    EvidenceStatus,
    HypothesisStatus,
    Importance,
    Phase,
    ProblemDefinitionStatus,
    ResultCompleteness,
    RevisionKind,
    SourceAuthority,
    TransitionKind,
    VOBStatus,
)
from ..core.errors import StateIntegrityError
from ..core.events import EventType
from ..core.scope import WILDCARD, Scope, ScopeItem
from ..domain.design import (
    CanonicalChallenge,
    DecisionRecord,
    DependencyReview,
    DependencyReviewItem,
    ProblemDefinition,
)
from ..domain.epistemic import Assumption, Evidence
from ..engine.context import HarnessContext
from ..state.problem import ProblemState
from ..state.runtime import RuntimeState, TransitionCandidate
from ..supervision.monitoring import SignalKind

DC = DependencyClassification
_MATERIAL_IMPACT = (Criticality.CRITICAL, Criticality.HIGH)
_HELD = (HypothesisStatus.SUPPORTED, HypothesisStatus.CONFIRMED)
_PRESERVED = (
    "organizations",
    "stakeholders",
    "processes",
    "process_handoffs",
    "data_assets",
    "domain_authorizations",
    "constraints",
    "evidence",
    "facts",
    "claims",
)


# --------------------------------------------------------------------------- evidence strength


def is_strong(e: Evidence) -> bool:
    """Evidence strong enough to establish facts / settle claims / challenge a canonical premise."""
    if e.status is not EvidenceStatus.ACTIVE or e.is_fallback:
        return False
    if e.source_type is EvidenceSourceType.STAKEHOLDER:
        return False
    if e.authority is not SourceAuthority.AUTHORITATIVE:
        return False
    return e.completeness in (ResultCompleteness.COMPLETE, ResultCompleteness.NOT_APPLICABLE)


def _agrees(premise: Evidence, new: Evidence) -> bool:
    same = premise.value == new.value
    if (premise.relation is EvidenceRelation.CONTRADICTS) != (new.relation is EvidenceRelation.CONTRADICTS):
        same = not same
    return same


def assumption_refs(ps: ProblemState, a: Assumption) -> set[str]:
    """Evidence an assumption rests on: explicit refs + committed evidence ids named in its basis."""
    named = {tok.rstrip(".") for tok in re.findall(r"[A-Za-z0-9][\w.-]*", a.basis)}
    return set(a.evidence_refs) | {t for t in named if t in ps.evidence}


# --------------------------------------------------------------------------- premise contradiction


@dataclass
class PremiseContradiction:
    kind: str  # EVIDENCE / HYPOTHESIS / EVIDENCE_REVISION
    object_id: str
    detail: str


def premise_contradictions(
    ps: ProblemState, pd: ProblemDefinition, evidence_id: str
) -> list[PremiseContradiction]:
    """Material contradictions between strong evidence and premises the Problem depends on."""
    e = ps.evidence.get(evidence_id)
    if e is None or not is_strong(e) or evidence_id in pd.evidence_refs:
        return []
    premise = [x for x in pd.evidence_refs if x in ps.evidence]
    out: list[PremiseContradiction] = []
    if e.target_assertion is not None and e.value is not None:
        for pid in premise:
            p = ps.evidence[pid]
            if p.target_assertion == e.target_assertion and p.value is not None and not _agrees(p, e):
                out.append(
                    PremiseContradiction(
                        "EVIDENCE",
                        pid,
                        f"{evidence_id} asserts {e.target_assertion}={e.value!r}; "
                        f"premise {pid} asserts {p.value!r}",
                    )
                )
    for h in ps.hypotheses.values():
        rests_on = sorted(set(h.supporting_evidence) & set(premise))
        if (
            h.status in _HELD
            and evidence_id in h.contradicting_evidence
            and rests_on
            and h.decision_impact in _MATERIAL_IMPACT
        ):
            out.append(
                PremiseContradiction(
                    "HYPOTHESIS",
                    h.id,
                    f"{evidence_id} contradicts {h.id}, which rests on premise evidence {rests_on}",
                )
            )
    for r in ps.evidence_revisions.values():
        if (
            r.revised_by == evidence_id
            and r.evidence_id in premise
            and (r.invalidates_problem or r.revision_kind is RevisionKind.OBSERVATION_INVALIDATED)
            and not any(c.object_id == r.evidence_id for c in out)
        ):
            out.append(
                PremiseContradiction(
                    "EVIDENCE_REVISION",
                    r.evidence_id,
                    f"{r.id}: premise {r.evidence_id} revised by {evidence_id}: {r.revised_interpretation}",
                )
            )
    return out


def _unique(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))


def problem_reasons(ps: ProblemState, *, allow_challenged: bool = False) -> list[str]:
    """Why progression / protected execution is not allowed under the current Problem (IDR-REDEFINE-02)."""
    pd = ps.problem_definition
    if pd is None:
        return ["PROBLEM: no canonical Problem"]
    if pd.status is not ProblemDefinitionStatus.ACTIVE:
        return [f"PROBLEM: canonical Problem {pd.id} v{pd.version} is {pd.status.value}, not ACTIVE"]
    if not pd.is_canonical():
        return [f"PROBLEM: {pd.id} v{pd.version} has not passed the DEFINE Gate"]
    challenges = pd.open_challenges()
    if challenges and not allow_challenged:
        ids = [c.evidence_id for c in challenges]
        return [
            f"PROBLEM: canonical Problem {pd.id} v{pd.version} challenged by {ids}; "
            "revalidation required (redefine or dismiss the challenge)"
        ]
    return []


def validate_problem_invalidation(
    ps: ProblemState, evidence_id: str
) -> tuple[list[PremiseContradiction], str | None]:
    """Harness-owned redefine validation (IDR-REDEFINE-01/02). Returns (contradictions, rejection)."""
    pd = ps.problem_definition
    if pd is None:
        return [], "no canonical Problem to redefine"
    if not pd.is_canonical():
        return [], (
            f"{pd.id} v{pd.version} is {pd.status.value} (gate {pd.gate_result}), "
            "not an ACTIVE canonical Problem: pre-canonical changes are "
            "hypothesis_changed / continue DEFINE, never redefine"
        )
    e = ps.evidence.get(evidence_id)
    if (
        e is None
        or e.status is not EvidenceStatus.ACTIVE
        or e.authority is not SourceAuthority.AUTHORITATIVE
        or e.is_fallback
    ):
        return [], "redefine requires committed, active, authoritative, non-fallback evidence"
    found = premise_contradictions(ps, pd, evidence_id)
    if not found:
        return [], (
            f"{evidence_id} does not materially contradict any premise of {pd.ref} "
            "(path-level evidence: REPLAN, not REDEFINE)"
        )
    return found, None


# --------------------------------------------------------------------------- dependency review


def _covered_by_path(item: ScopeItem, path: list[ScopeItem]) -> bool:
    return any(item.matches(c) or c.matches(item) for c in path)


def _vob_classification(
    v_scope: Scope,
    linked_assumption: str | None,
    invalid_assumptions: set[str],
    path: list[ScopeItem],
    ref: str,
) -> tuple[DependencyClassification, str]:
    if linked_assumption and linked_assumption in invalid_assumptions:
        return DC.INVALIDATED, f"linked assumption {linked_assumption} invalidated"
    if v_scope.entire_solution:
        return DC.INVALIDATED, (
            f"blocking_scope ENTIRE_SOLUTION denotes the entire {ref} solution, which is invalidated; "
            "re-raise under the successor Problem if still relevant"
        )
    if v_scope.items and all(_covered_by_path(i, path) for i in v_scope.items):
        return DC.INVALIDATED, f"blocking_scope lies only on the invalidated {ref} solution path"
    return (
        DC.NEEDS_REEVALUATION,
        "outside the invalidated solution path; rebind or retire at the successor DEFINE Gate",
    )


def build_dependency_review(
    ps: ProblemState, rt: RuntimeState, pd: ProblemDefinition, trigger: str, contradicted: list[str]
) -> DependencyReview:
    """Classify Problem-dependent objects. Pure: computes, never mutates (also used as a preview)."""
    review = DependencyReview(
        id=ps.next_id("DR", "dependency_reviews"),
        problem_ref=pd.ref,
        trigger_evidence=trigger,
        contradicted_premises=list(contradicted),
    )
    add = review.items.append
    premise = set(pd.evidence_refs)
    revisions = [
        r for r in ps.evidence_revisions.values() if r.revised_by == trigger and r.evidence_id in premise
    ]
    review.evidence_revisions = [r.id for r in revisions]
    invalid_evidence = {x for x in contradicted if x in ps.evidence} | {
        r.evidence_id
        for r in revisions
        if r.invalidates_problem or r.revision_kind is RevisionKind.OBSERVATION_INVALIDATED
    }

    add(
        DependencyReviewItem(
            "ProblemDefinition",
            pd.ref,
            DC.INVALIDATED,
            f"premise contradicted by {trigger}",
            f"{pd.status.value} → INVALIDATED",
        )
    )
    for eid in pd.evidence_refs:
        rev = next((r for r in reversed(revisions) if r.evidence_id == eid), None)
        if rev is not None and rev.revision_kind is RevisionKind.OBSERVATION_INVALIDATED:
            add(DependencyReviewItem("Evidence", eid, DC.INVALIDATED, f"observation contradicted ({rev.id})"))
        elif rev is not None or eid in invalid_evidence:
            how = f"revised in {rev.id}" if rev else f"contradicted by {trigger}; revision proposed"
            add(
                DependencyReviewItem(
                    "Evidence",
                    eid,
                    DC.STILL_VALID,
                    f"observation still valid; prior interpretation superseded ({how})",
                )
            )

    for h in ps.hypotheses.values():
        if h.status is HypothesisStatus.REJECTED:
            continue
        if h.id in contradicted or trigger in h.contradicting_evidence:
            add(
                DependencyReviewItem(
                    "Hypothesis",
                    h.id,
                    DC.INVALIDATED,
                    f"contradicted by {trigger}",
                    f"{h.status.value} → REJECTED",
                )
            )
        elif h.status in _HELD and set(h.supporting_evidence) & invalid_evidence:
            add(
                DependencyReviewItem(
                    "Hypothesis",
                    h.id,
                    DC.NEEDS_REEVALUATION,
                    "support rests on revised / contradicted premise evidence",
                    f"{h.status.value} → CANDIDATE",
                )
            )
        else:
            add(
                DependencyReviewItem(
                    "Hypothesis", h.id, DC.STILL_VALID, "no dependency on invalidated premises"
                )
            )

    invalid_assumptions: set[str] = set()
    for a in ps.assumptions.values():
        if a.status is not AssumptionStatus.ACTIVE:
            continue
        refs = assumption_refs(ps, a)
        if refs & invalid_evidence:
            invalid_assumptions.add(a.id)
            add(
                DependencyReviewItem(
                    "Assumption",
                    a.id,
                    DC.INVALIDATED,
                    f"rests on {sorted(refs & invalid_evidence)} invalidated by {trigger}",
                    "ACTIVE → INVALIDATED",
                )
            )
        elif refs & premise:
            add(
                DependencyReviewItem(
                    "Assumption",
                    a.id,
                    DC.NEEDS_REEVALUATION,
                    f"rests on premise evidence {sorted(refs & premise)} of {pd.ref}",
                )
            )
        else:
            add(
                DependencyReviewItem(
                    "Assumption", a.id, DC.STILL_VALID, "no dependency on invalidated premises"
                )
            )

    # solution path of the invalidated Problem: design release scope + protected actions + plan scope
    path: list[ScopeItem] = [ScopeItem(a, WILDCARD) for a in pd.protected_actions]
    sd = ps.solution_design
    if sd is not None and sd.problem_ref == pd.id and sd.problem_version == pd.version:
        path += sd.release_scope
        add(DependencyReviewItem("SolutionDesign", sd.id, DC.INVALIDATED, f"designed for {pd.ref}"))
        for c in sd.structural_remedies:
            add(
                DependencyReviewItem(
                    "StructuralRemedyCandidate",
                    c.id,
                    DC.INVALIDATED,
                    f"remedy for the invalidated root problem of {pd.ref}",
                )
            )
        for role in sd.agent_roles:
            add(
                DependencyReviewItem(
                    "AgentRole",
                    f"{sd.id}:{role.value}",
                    DC.SUPERSEDED,
                    "role derived from the invalidated design",
                )
            )
    spec = ps.agent_spec
    if spec is not None and spec.problem_reference == pd.ref:
        add(DependencyReviewItem("AgentSpec", spec.identity, DC.SUPERSEDED, f"specified for {pd.ref}"))

    plan = rt.current_plan
    if plan is not None:
        path_scope = Scope(items=list(path))
        invalid_items = 0
        for w in plan.work_items:
            if w.status in ("DROPPED", "INVALIDATED"):
                continue
            if w.root_problem_aligned or any(path_scope.covers(i) for i in w.scope_items):
                invalid_items += 1
                path += w.scope_items
                add(
                    DependencyReviewItem(
                        "WorkItem",
                        w.id,
                        DC.INVALIDATED,
                        f"serves the {pd.ref} solution path",
                        f"{w.status} → INVALIDATED",
                    )
                )
            else:
                add(
                    DependencyReviewItem(
                        "WorkItem", w.id, DC.STILL_VALID, "generic work (verification / packaging / off-path)"
                    )
                )
        add(
            DependencyReviewItem(
                "ExecutionPlan",
                plan.id,
                DC.NEEDS_REEVALUATION if invalid_items else DC.STILL_VALID,
                "replan against the successor Problem"
                if invalid_items
                else "no Problem-dependent work items",
            )
        )

    pending = rt.pending_protected_action
    if pending is not None:
        add(
            DependencyReviewItem(
                "PendingProtectedAction",
                pending.gate_id,
                DC.INVALIDATED,
                f"proposed under {pending.problem_ref or pd.ref}; premise invalidated — "
                "the old approval never carries over to a new Problem / action",
                "CANCELLED",
            )
        )

    for v in ps.verification_obligations.values():
        if not v.is_open():
            continue
        if v.problem_version is None:
            add(
                DependencyReviewItem(
                    "VerificationObligation", v.id, DC.STILL_VALID, "not bound to a Problem version"
                )
            )
            continue
        if not v.applies_to(pd.id, pd.version):
            continue
        cls, why = _vob_classification(
            v.blocking_scope, v.linked_assumption, invalid_assumptions, path, pd.ref
        )
        add(
            DependencyReviewItem(
                "VerificationObligation",
                v.id,
                cls,
                why,
                f"{v.status.value} → INVALIDATED" if cls is DC.INVALIDATED else "kept OPEN",
            )
        )
        if cls is DC.INVALIDATED and v.linked_unknown:
            add(
                DependencyReviewItem(
                    "Unknown",
                    v.linked_unknown,
                    DC.NEEDS_REEVALUATION,
                    f"deferred to retired {v.id}; re-raise under the successor if still relevant",
                )
            )

    for sid in pd.success_criteria:
        add(
            DependencyReviewItem(
                "SuccessCriterion",
                sid,
                DC.NEEDS_REEVALUATION,
                f"defined for {pd.ref}; confirm against the successor Problem",
            )
        )
    metrics = list(pd.metric_ids) + [
        sc.metric_id for sid in pd.success_criteria if (sc := ps.success_criteria.get(sid)) and sc.metric_id
    ]
    for mid in _unique(metrics):
        add(
            DependencyReviewItem(
                "Metric", mid, DC.NEEDS_REEVALUATION, f"metric interpretation tied to {pd.ref}"
            )
        )

    runs = [r for r in ps.validation.verify_runs if r.get("problem_ref") in (None, pd.ref)]
    if runs or ps.validation.release_decisions:
        add(
            DependencyReviewItem(
                "ReleaseCandidate",
                pd.ref,
                DC.INVALIDATED,
                f"verification / release evidence bound to {pd.ref} does not carry to the successor",
            )
        )

    for conflict in ps.conflicts.values():
        sides = {conflict.side_a, conflict.side_b}
        if (
            conflict.status is ConflictStatus.OPEN
            and trigger in sides
            and (sides - {trigger}) & set(contradicted)
        ):
            add(
                DependencyReviewItem(
                    "Conflict",
                    conflict.id,
                    DC.SUPERSEDED,
                    f"resolved by redefine: {trigger} supersedes premise {sorted(sides - {trigger})}",
                    "OPEN → RESOLVED",
                )
            )

    review.preserved = {name: len(getattr(ps, name)) for name in _PRESERVED}
    return review


def apply_dependency_review(
    ps: ProblemState, rt: RuntimeState, review: DependencyReview
) -> list[tuple[str, str, str]]:
    """Apply the review inside the redefine commit. Returns VOB status changes (id, from, to)."""
    vob_changes: list[tuple[str, str, str]] = []
    work = {w.id: w for w in (rt.current_plan.work_items if rt.current_plan else [])}
    for item in review.items:
        t, oid, cls = item.object_type, item.object_id, item.classification
        if t == "Hypothesis" and cls is DC.INVALIDATED:
            ps.hypotheses[oid].status = HypothesisStatus.REJECTED
        elif t == "Hypothesis" and cls is DC.NEEDS_REEVALUATION:
            ps.hypotheses[oid].status = HypothesisStatus.CANDIDATE
        elif t == "Assumption" and cls is DC.INVALIDATED:
            ps.assumptions[oid].status = AssumptionStatus.INVALIDATED
        elif t == "VerificationObligation" and cls is DC.INVALIDATED:
            v = ps.verification_obligations[oid]
            vob_changes.append((oid, v.status.value, VOBStatus.INVALIDATED.value))
            v.status = VOBStatus.INVALIDATED
            v.resolution = f"{review.id}: {item.reason}"
        elif t == "Conflict":
            c = ps.conflicts[oid]
            c.status = ConflictStatus.RESOLVED
            c.resolution_strategy = item.reason
        elif t == "WorkItem" and cls is DC.INVALIDATED and oid in work:
            work[oid].status = "INVALIDATED"
    for rid in review.evidence_revisions:
        ps.evidence_revisions[rid].dependency_review_id = review.id
    ps.dependency_reviews[review.id] = review
    return vob_changes


def summarize(review: DependencyReview) -> str:
    parts = []
    for cls in (DC.INVALIDATED, DC.SUPERSEDED, DC.NEEDS_REEVALUATION):
        ids = [i.object_id for i in review.classified(cls) if i.object_type != "ProblemDefinition"]
        if ids:
            parts.append(f"{cls.value}{ids}")
    return "; ".join(parts) or "none"


# --------------------------------------------------------------------------- successor binding


def bind_successor(ps: ProblemState, pd: ProblemDefinition) -> list[tuple[str, str, str]]:
    """At the successor's passing DEFINE Gate: rebind / retire predecessor VOBs, close the lineage."""
    pred_ref = pd.supersedes
    if pred_ref is None:
        return []
    pred_id, _, pred_ver = pred_ref.rpartition("@v")
    review = next((r for r in reversed(ps.dependency_reviews.values()) if r.problem_ref == pred_ref), None)
    changes: list[tuple[str, str, str]] = []
    resolved: list[DependencyReviewItem] = []
    for v in ps.verification_obligations.values():
        if not v.is_open() or v.problem_version is None or not v.applies_to(pred_id, int(pred_ver)):
            continue
        if v.blocking_scope.entire_solution or v.blocking_scope.intersect(pd.intended_scope):
            v.problem_definition_id, v.problem_version = pd.id, pd.version
            resolved.append(
                DependencyReviewItem(
                    "VerificationObligation",
                    v.id,
                    DC.STILL_VALID,
                    f"blocking_scope intersects {pd.ref} intended scope",
                    f"rebound to {pd.ref}",
                )
            )
        else:
            changes.append((v.id, v.status.value, VOBStatus.SUPERSEDED.value))
            v.status = VOBStatus.SUPERSEDED
            v.resolution = f"superseded by {pd.ref}: blocking_scope outside its intended scope"
            resolved.append(
                DependencyReviewItem(
                    "VerificationObligation",
                    v.id,
                    DC.SUPERSEDED,
                    f"not relevant to {pd.ref}",
                    "OPEN → SUPERSEDED",
                )
            )
    if review is not None:
        for item in review.items:
            if item.object_type == "SuccessCriterion":
                carried = item.object_id in pd.success_criteria
                resolved.append(
                    DependencyReviewItem(
                        "SuccessCriterion",
                        item.object_id,
                        DC.STILL_VALID if carried else DC.NEEDS_REEVALUATION,
                        f"carried into {pd.ref}" if carried else f"not part of {pd.ref}",
                    )
                )
        review.successor_ref = pd.ref
        review.successor_items.extend(resolved)
    for h in ps.meta.problem_definition_history:
        if h.ref == pred_ref:
            h.superseded_by = pd.ref  # lineage link; the snapshot content itself is never edited
    return changes


# --------------------------------------------------------------------------- canonical challenge


def _proposed_revisions(ps: ProblemState, pd: ProblemDefinition, contradicted: list[str]) -> list[str]:
    hyps = [ps.hypotheses[h] for h in contradicted if h in ps.hypotheses]
    return [e for e in pd.evidence_refs if e in contradicted or any(e in h.supporting_evidence for h in hyps)]


def assess_canonical_challenge(ctx: HarnessContext, evidence_id: str) -> CanonicalChallenge | None:
    """Harness-owned canonical premise monitoring (IDR-REDEFINE-01).

    ``conflict_detected ≠ redefine``: only a material contradiction of a premise the ACTIVE canonical
    Problem depends on becomes a challenge (CRITICAL, REDEFINE candidate, pending action revalidation).
    """
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None or not pd.is_canonical() or any(c.evidence_id == evidence_id for c in pd.challenges):
        return None
    found = premise_contradictions(ps, pd, evidence_id)
    if not found:
        return None
    contradicted = _unique([c.object_id for c in found])
    rationale = "; ".join(c.detail for c in found)
    challenge = CanonicalChallenge(
        evidence_id, contradicted, rationale, _proposed_revisions(ps, pd, contradicted)
    )
    with ctx.commit(f"canonical problem {pd.ref} challenged by {evidence_id}") as p:
        assert p.problem_definition is not None
        p.problem_definition.challenges.append(challenge)
        for c in p.conflicts.values():
            sides = {c.side_a, c.side_b}
            if c.status is ConflictStatus.OPEN and evidence_id in sides and sides & set(contradicted):
                c.decision_impact = Criticality.CRITICAL
                c.gate_blocking = True
    rt = ctx.runtime
    pending = rt.pending_protected_action
    if pending is not None:
        pending.revalidation_required = True
        pending.revalidation_reason = f"premise of {pd.ref} challenged by {evidence_id}"
    rt.propose_transition(
        TransitionCandidate(
            TransitionKind.REDEFINE, Phase.DEFINE, f"canonical premise challenged: {rationale}", [evidence_id]
        )
    )
    preview = build_dependency_review(ps, rt, pd, evidence_id, contradicted)
    event = ctx.emit(
        EventType.CANONICAL_PROBLEM_CHALLENGED,
        {
            "problem": pd.id,
            "version": pd.version,
            "evidence": evidence_id,
            "contradicted": contradicted,
            "rationale": rationale,
            "transition_candidate": TransitionKind.REDEFINE.value,
            "affected": summarize(preview),
            "pending_action": pending.gate_id if pending else None,
        },
        importance=Importance.CRITICAL,
        refs=[evidence_id, *contradicted],
    )
    challenge.event_seq = event.seq
    if challenge.proposed_revisions:
        ctx.emit(
            EventType.EVIDENCE_REVISION_PROPOSED,
            {
                "challenge": evidence_id,
                "evidence": challenge.proposed_revisions,
                "reason": "interpretation depends on a contradicted premise",
            },
            importance=Importance.HIGH,
            refs=challenge.proposed_revisions,
        )
    pending_txt = f"{pending.gate_id} REVALIDATION_REQUIRED (APPROVE blocked)" if pending else "none"
    ctx.signal(
        SignalKind.CANONICAL_PROBLEM_CHALLENGED,
        f"{pd.id} v{pd.version} challenged by {evidence_id}: {rationale}"
        " | transition candidate: REDEFINE → DEFINE"
        f" | affected: {summarize(preview)} | pending protected action: {pending_txt}"
        f" | next: revise interpretations of {challenge.proposed_revisions}; confirm redefine({evidence_id})"
        " or dismiss the challenge",
        refs=[evidence_id],
        event_seq=event.seq,
    )
    ctx.supervision.decision_rationale.append(f"REDEFINE candidate: {rationale}")
    return challenge


def dismiss_canonical_challenge(ctx: HarnessContext, evidence_id: str, rationale: str) -> None:
    """Explicit decision that a challenge is not material. Lifts the challenge block; nothing else."""
    pd = ctx.problem.problem_definition
    if pd is None or not any(c.evidence_id == evidence_id for c in pd.open_challenges()):
        raise StateIntegrityError(f"no open canonical challenge by {evidence_id}")
    if not rationale:
        raise StateIntegrityError("dismissing a canonical challenge requires a rationale")
    with ctx.commit(f"canonical challenge {evidence_id} dismissed") as ps:
        cur = ps.problem_definition
        assert cur is not None
        ch = next(c for c in cur.open_challenges() if c.evidence_id == evidence_id)
        ch.status = ChallengeStatus.DISMISSED
        ch.resolution = rationale
        for c in ps.conflicts.values():
            if c.status is ConflictStatus.OPEN and evidence_id in (c.side_a, c.side_b) and c.gate_blocking:
                c.status = ConflictStatus.MANAGED
                c.resolution_strategy = f"challenge dismissed: {rationale}"
        ps.decision_log.append(
            DecisionRecord(
                id=f"D-{len(ps.decision_log) + 1}",
                phase=ctx.runtime.phase,
                decision=f"DISMISS canonical challenge {evidence_id}",
                rationale=rationale,
                evidence_refs=[evidence_id],
            )
        )
    rt = ctx.runtime
    if not ctx.problem.problem_definition or not ctx.problem.problem_definition.open_challenges():
        if rt.transition_candidate is not None and rt.transition_candidate.kind is TransitionKind.REDEFINE:
            rt.transition_candidate = None
        if rt.pending_protected_action is not None:
            rt.pending_protected_action.revalidation_required = False
            rt.pending_protected_action.revalidation_reason = None
    event = ctx.emit(
        EventType.CANONICAL_CHALLENGE_DISMISSED,
        {"problem": pd.ref, "evidence": evidence_id, "rationale": rationale},
        importance=Importance.HIGH,
        refs=[evidence_id],
    )
    ctx.signal(
        SignalKind.STATE_DIFF,
        f"challenge {evidence_id} on {pd.ref} dismissed: {rationale}",
        importance=Importance.HIGH,
        event_seq=event.seq,
    )


# --------------------------------------------------------------------------- revision support


def infer_revision_kind(target: Evidence, revising: Evidence) -> RevisionKind:
    """Same assertion + different value from strong evidence ⇒ the observation itself is contradicted."""
    if (
        revising.target_assertion is not None
        and revising.target_assertion == target.target_assertion
        and revising.value is not None
        and target.value is not None
        and not _agrees(target, revising)
        and is_strong(revising)
    ):
        return RevisionKind.OBSERVATION_INVALIDATED
    return RevisionKind.INTERPRETATION_ONLY


def affected_objects(ps: ProblemState, rt: RuntimeState, evidence_id: str) -> dict[str, list[str]]:
    """Downstream objects whose meaning depends on ``evidence_id`` (Evidence Revision traceability)."""
    pds = [p for p in [ps.problem_definition, *ps.meta.problem_definition_history] if p is not None]
    citing = [p for p in pds if evidence_id in p.evidence_refs]
    sd = ps.solution_design
    designs = (
        [sd.id]
        if sd and any(sd.problem_ref == p.id and sd.problem_version == p.version for p in citing)
        else []
    )
    return {
        "problem_definitions": _unique([p.ref for p in citing]),
        "hypotheses": [
            h.id
            for h in ps.hypotheses.values()
            if evidence_id in h.supporting_evidence or evidence_id in h.contradicting_evidence
        ],
        "assumptions": [a.id for a in ps.assumptions.values() if evidence_id in assumption_refs(ps, a)],
        "designs": designs,
        "vobs": [
            v.id
            for v in ps.verification_obligations.values()
            if v.is_open()
            and (
                evidence_id in v.required_evidence
                or (v.problem_version is not None and any(v.applies_to(p.id, p.version) for p in citing))
            )
        ],
        "plans": [rt.current_plan.id] if rt.current_plan is not None and designs else [],
    }

"""Rebuild the SupervisionState projection from canonical Problem/Runtime state.

SupervisionState is never read back as execution truth; this function only writes it.
"""

from __future__ import annotations

from ..core.enums import Criticality, DependencyClassification, HypothesisStatus, UnknownStatus
from ..engine.context import HarnessContext


def refresh(ctx: HarnessContext) -> None:
    ps, rt, sv = ctx.problem, ctx.runtime, ctx.supervision
    pd = ps.problem_definition
    sv.current_problem = None
    if pd is not None:
        challenged = [c.evidence_id for c in pd.open_challenges()]
        sv.current_problem = f"{pd.root_problem} (v{pd.version}, {pd.status.value})" + (
            f" CHALLENGED by {challenged}" if challenged else ""
        )
    sv.top_hypotheses = [
        f"{h.id}: {h.statement} [{h.status.value}]"
        for h in ps.hypotheses.values()
        if h.status in (HypothesisStatus.CANDIDATE, HypothesisStatus.SUPPORTED, HypothesisStatus.CONFIRMED)
    ][:5]
    sv.critical_unknowns = [
        f"{u.id}: {u.question} [{u.status.value}]"
        for u in ps.unknowns.values()
        if u.criticality in (Criticality.CRITICAL, Criticality.HIGH)
        and u.status is not UnknownStatus.RESOLVED
    ]
    sv.critical_conflicts = [
        f"{c.id}: {c.assertion} ({c.side_a} vs {c.side_b})"
        for c in ps.conflicts.values()
        if c.status.value == "OPEN" and c.decision_impact in (Criticality.CRITICAL, Criticality.HIGH)
    ]
    sv.key_evidence = list(pd.evidence_refs) if pd else []
    sv.evidence_revisions = [
        f"{r.id}: {r.evidence_id} revised by {r.revised_by}"
        + (" (invalidates problem)" if r.invalidates_problem else "")
        for r in ps.evidence_revisions.values()
    ]
    sv.pending_verification_obligations = [
        f"{v.id} [{v.required_before.value}] {v.unresolved_question}" for v in ps.open_vobs()
    ]
    review = list(ps.dependency_reviews.values())[-1] if ps.dependency_reviews else None
    sv.dependency_review = (
        [
            f"{review.id} {review.problem_ref} → {review.successor_ref or 'pending successor'}: "
            f"{i.object_type} {i.object_id} {i.classification.value} ({i.reason})"
            for i in review.items + review.successor_items
            if i.classification is not DependencyClassification.STILL_VALID
        ]
        if review
        else []
    )
    sv.current_action = rt.current_action
    sv.next_action = rt.next_action

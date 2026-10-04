"""DISCOVER: Information Value action selection + evidence integration (Design Freeze §5-6).

* "이 Evidence가 없으면 다음 결정이 실제로 달라지는가?" — zero decision impact ⇒ not selected.
* "남은 시간에 비해 이 Action이 가치가 있는가?" — budget and tool health shape the ranking.
* Stakeholder statements become Claims; Facts need authoritative/complete evidence.
* Conflicts are tracked, never silently resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from ..core.enums import (
    ClaimStatus,
    ConflictType,
    Criticality,
    EvidenceRelation,
    EvidenceSourceType,
    EvidenceStatus,
    HypothesisStatus,
    Importance,
    ReserveStatus,
    ResultCompleteness,
    SourceAuthority,
    ToolHealth,
    UnknownStatus,
)
from ..core.errors import StateIntegrityError
from ..core.events import EventType
from ..core.provenance import Provenance
from ..domain.epistemic import (
    Claim,
    Conflict,
    Evidence,
    EvidenceRevision,
    Fact,
    InterpretationEntry,
)
from ..engine.context import HarnessContext
from ..supervision.monitoring import SignalKind


class DiscoveryActionKind(StrEnum):
    STAKEHOLDER_INTERVIEW = "STAKEHOLDER_INTERVIEW"
    TOOL_QUERY = "TOOL_QUERY"
    DATA_INSPECTION = "DATA_INSPECTION"
    DOCUMENT_REVIEW = "DOCUMENT_REVIEW"


@dataclass
class InformationValueFactors:
    """Design Freeze §6 factors, each in [0, 1] (time cost in minutes).

    The exact formula is implementation-flexible; the factor *ordering* is frozen.
    """

    decision_impact: float
    uncertainty: float = 0.5
    discriminative_power: float = 0.5
    answerability: float = 0.5
    process_data_handoff_impact: float = 0.0
    action_proximity: float = 0.0
    constraint_risk: float = 0.0
    time_cost_minutes: float = 5.0


@dataclass
class DiscoveryAction:
    id: str
    kind: DiscoveryActionKind
    target: str
    question: str
    factors: InformationValueFactors
    resolves_unknowns: list[str] = field(default_factory=list)
    discriminates_hypotheses: list[str] = field(default_factory=list)
    tool_id: str | None = None
    read_only: bool = True


@dataclass
class RankedAction:
    action: DiscoveryAction
    score: float
    excluded: bool
    reason: str


# Weights follow the frozen priority order (Decision Impact first … Remaining Budget last).
_WEIGHTS = {
    "decision_impact": 10.0,
    "uncertainty": 9.0,
    "discriminative_power": 8.0,
    "answerability": 7.0,
    "process_data_handoff_impact": 6.0,
    "action_proximity": 5.0,
    "constraint_risk": 4.0,
}
_HEALTH_RELIABILITY = {
    ToolHealth.HEALTHY: 1.0,
    ToolHealth.UNKNOWN: 0.7,
    ToolHealth.DEGRADED: 0.4,
    ToolHealth.UNAVAILABLE: 0.0,
}


def rank_actions(ctx: HarnessContext, actions: list[DiscoveryAction]) -> list[RankedAction]:
    budget = ctx.runtime.budget_runtime
    reserve = ctx.runtime.release_runtime.reserve_status
    total = budget.total_budget or 1.0
    budget_pressure = max(0.0, min(1.0, 1.0 - budget.remaining / total))
    ranked: list[RankedAction] = []
    for a in actions:
        f = a.factors
        if not a.read_only:
            ranked.append(RankedAction(a, 0.0, True, "discovery actions must be read-only"))
            continue
        if f.decision_impact <= 0:
            ranked.append(RankedAction(a, 0.0, True, "evidence would not change the next decision"))
            continue
        reliability = 1.0
        if a.tool_id is not None:
            reliability = _HEALTH_RELIABILITY[ctx.runtime.tool(a.tool_id).health]
            if reliability == 0.0:
                ranked.append(RankedAction(a, 0.0, True, f"tool {a.tool_id} UNAVAILABLE"))
                continue
        in_reserve = reserve in (ReserveStatus.ACTIVE, ReserveStatus.AT_RISK)
        safety_check = f.constraint_risk >= 0.7  # authority/safety checks are KEEP work in the reserve
        if in_reserve and not safety_check:
            ranked.append(RankedAction(a, 0.0, True, "release reserve active: low-value exploration dropped"))
            continue
        usable = budget.remaining if (in_reserve and safety_check) else (
            budget.remaining - ctx.problem.budget.release_reserve_minutes
        )
        if f.time_cost_minutes > max(0.0, usable):
            ranked.append(RankedAction(a, 0.0, True, "time cost exceeds usable budget (release reserve protected)"))
            continue
        value = sum(getattr(f, name) * w for name, w in _WEIGHTS.items())
        value *= 0.5 + 0.5 * reliability  # tool reliability
        cost = f.time_cost_minutes * (1.0 + 2.0 * budget_pressure)  # time cost scaled by remaining budget
        score = value / (1.0 + cost / 10.0)
        ranked.append(RankedAction(a, round(score, 4), False, f"value={value:.2f} cost={cost:.1f}"))
    ranked.sort(key=lambda r: (not r.excluded, r.score, r.action.factors.decision_impact), reverse=True)
    return ranked


def select_next_action(ctx: HarnessContext, actions: list[DiscoveryAction]) -> DiscoveryAction | None:
    ranked = rank_actions(ctx, actions)
    chosen = next((r for r in ranked if not r.excluded), None)
    ctx.emit(
        EventType.DISCOVERY_ACTION_SELECTED,
        {
            "selected": chosen.action.id if chosen else None,
            "ranking": [
                {"id": r.action.id, "score": r.score, "excluded": r.excluded, "reason": r.reason} for r in ranked
            ],
        },
    )
    ctx.runtime.next_action = chosen.action.id if chosen else None
    ctx.supervision.next_action = ctx.runtime.next_action
    return chosen.action if chosen else None


# --------------------------------------------------------------------------- claims / evidence / facts


def record_claim(
    ctx: HarnessContext,
    claim_id: str,
    stakeholder_id: str,
    statement: str,
    *,
    assertion: str | None = None,
    value: Any = None,
    is_initial_request: bool = False,
    decision_impact: Criticality = Criticality.MEDIUM,
) -> Claim:
    """A stakeholder statement is a Claim, never automatically a Fact."""
    claim = Claim(
        id=claim_id,
        stakeholder_id=stakeholder_id,
        statement=statement,
        assertion=assertion,
        value=value,
        is_initial_request=is_initial_request,
    )
    with ctx.commit(f"claim {claim_id}") as ps:
        ps.claims[claim_id] = claim
        if assertion is not None:
            _detect_conflicts(ctx, claim_id, assertion, value, decision_impact)
    ctx.emit(EventType.CLAIM_RECORDED, {"claim": claim_id, "stakeholder": stakeholder_id})
    return claim


def integrate_evidence(
    ctx: HarnessContext,
    evidence: Evidence,
    *,
    supports: list[str] | None = None,
    contradicts: list[str] | None = None,
    decision_impact: Criticality = Criticality.MEDIUM,
) -> Evidence:
    """Commit evidence, link hypotheses, update claim status, detect conflicts."""
    if evidence.hidden_ground_truth:
        raise StateIntegrityError("hidden ground truth must not enter runtime reasoning")
    with ctx.commit(f"evidence {evidence.id}") as ps:
        ps.evidence[evidence.id] = evidence
        for hid in supports or []:
            ps.hypotheses[hid].supporting_evidence.append(evidence.id)
        for hid in contradicts or []:
            ps.hypotheses[hid].contradicting_evidence.append(evidence.id)
        if evidence.target_assertion is not None:
            _detect_conflicts(ctx, evidence.id, evidence.target_assertion, evidence.value, decision_impact)
            if _is_strong(evidence):
                for claim in ps.claims.values():
                    if claim.assertion == evidence.target_assertion and claim.value is not None:
                        agrees = claim.value == evidence.value
                        if evidence.relation is EvidenceRelation.CONTRADICTS:
                            agrees = not agrees
                        claim.status = ClaimStatus.CORROBORATED if agrees else ClaimStatus.CONTRADICTED
                        claim.evidence_refs.append(evidence.id)
    ctx.emit(EventType.EVIDENCE_ADDED, {"evidence": evidence.id, "source": evidence.source_id}, refs=[evidence.id])
    return evidence


def _is_strong(e: Evidence) -> bool:
    """Evidence strong enough to establish facts / settle claims."""
    if e.status is not EvidenceStatus.ACTIVE or e.is_fallback:
        return False
    if e.source_type is EvidenceSourceType.STAKEHOLDER:
        return False
    if e.authority is not SourceAuthority.AUTHORITATIVE:
        return False
    return e.completeness in (ResultCompleteness.COMPLETE, ResultCompleteness.NOT_APPLICABLE)


def _detect_conflicts(
    ctx: HarnessContext, new_id: str, assertion: str, value: Any, decision_impact: Criticality
) -> None:
    ps = ctx.problem
    if value is None:
        return
    others: list[tuple[str, Any, bool]] = [
        (c.id, c.value, True) for c in ps.claims.values() if c.assertion == assertion and c.id != new_id
    ]
    others += [
        (e.id, e.value, False)
        for e in ps.evidence.values()
        if e.target_assertion == assertion and e.id != new_id and e.status is EvidenceStatus.ACTIVE
    ]
    new_is_claim = new_id in ps.claims
    for other_id, other_value, other_is_claim in others:
        if other_value is None or other_value == value:
            continue
        pair = {new_id, other_id}
        if any({c.side_a, c.side_b} == pair for c in ps.conflicts.values()):
            continue
        ctype = ConflictType.CLAIM_CONFLICT if (new_is_claim and other_is_claim) else ConflictType.DATA_CONFLICT
        cid = ps.next_id("C", "conflicts")
        ps.conflicts[cid] = Conflict(
            id=cid,
            type=ctype,
            side_a=other_id,
            side_b=new_id,
            assertion=assertion,
            decision_impact=decision_impact,
            gate_blocking=decision_impact is Criticality.CRITICAL,
            evidence_refs=[i for i in (other_id, new_id) if i in ps.evidence],
        )
        ctx.emit(
            EventType.CONFLICT_DETECTED,
            {"conflict": cid, "assertion": assertion, "sides": [other_id, new_id]},
            importance=Importance.HIGH,
        )


def establish_fact(
    ctx: HarnessContext, fact_id: str, statement: str, evidence_refs: list[str], *,
    assertion: str | None = None, value: Any = None,
) -> Fact:
    """Promote to Fact only with committed, authoritative, complete, non-stakeholder evidence."""
    ps = ctx.problem
    missing = [e for e in evidence_refs if e not in ps.evidence]
    if missing:
        raise StateIntegrityError(f"fact {fact_id} cites uncommitted evidence {missing}")
    if not any(_is_strong(ps.evidence[e]) for e in evidence_refs):
        raise StateIntegrityError(
            f"fact {fact_id}: claims / partial / fallback / non-authoritative evidence cannot establish a Fact"
        )
    fact = Fact(id=fact_id, statement=statement, assertion=assertion, value=value, evidence_refs=evidence_refs)
    with ctx.commit(f"fact {fact_id}") as p:
        p.facts[fact_id] = fact
    ctx.emit(EventType.FACT_ESTABLISHED, {"fact": fact_id}, refs=evidence_refs)
    return fact


def revise_evidence(
    ctx: HarnessContext,
    evidence_id: str,
    revised_by: str,
    revised_interpretation: str,
    *,
    invalidates_problem: bool = False,
) -> EvidenceRevision:
    """Append an Evidence Revision (never overwrite history)."""
    ps = ctx.problem
    if revised_by not in ps.evidence:
        raise StateIntegrityError(f"revising evidence {revised_by!r} is not committed")
    target = ps.evidence[evidence_id]
    previous = target.interpretation_history[-1].interpretation if target.interpretation_history else target.content
    rid = ps.next_id("ER", "evidence_revisions")
    revision = EvidenceRevision(
        id=rid,
        evidence_id=evidence_id,
        revised_by=revised_by,
        previous_interpretation=previous,
        revised_interpretation=revised_interpretation,
        invalidates_problem=invalidates_problem,
    )
    with ctx.commit(f"evidence revision {rid}") as p:
        e = p.evidence[evidence_id]
        e.interpretation_history.append(InterpretationEntry(revised_interpretation, f"revised by {revised_by}"))
        e.status = EvidenceStatus.REVISED
        p.evidence_revisions[rid] = revision
    event = ctx.emit(
        EventType.EVIDENCE_REVISED,
        {"revision": rid, "evidence": evidence_id, "revised_by": revised_by, "invalidates_problem": invalidates_problem},
        importance=Importance.HIGH,
        refs=[evidence_id, revised_by],
    )
    revision.event_seq = event.seq
    return revision


def update_hypothesis(
    ctx: HarnessContext, hypothesis_id: str, status: HypothesisStatus, reason: str
) -> None:
    with ctx.commit(f"hypothesis {hypothesis_id} → {status.value}") as ps:
        h = ps.hypotheses[hypothesis_id]
        old = h.status
        h.status = status
    event = ctx.emit(
        EventType.HYPOTHESIS_CHANGED,
        {"hypothesis": hypothesis_id, "from": old.value, "to": status.value, "reason": reason},
    )
    if status is HypothesisStatus.REJECTED and h.decision_impact in (Criticality.LOW, Criticality.MEDIUM):
        ctx.signal(SignalKind.LOW_VALUE_HYPOTHESIS_REJECTED, f"{hypothesis_id} rejected", event_seq=event.seq)
    else:
        ctx.signal(SignalKind.STATE_DIFF, f"{hypothesis_id} {old.value}→{status.value}", event_seq=event.seq)


def resolve_unknown(ctx: HarnessContext, unknown_id: str, resolution: str, evidence_refs: list[str]) -> None:
    missing = [e for e in evidence_refs if e not in ctx.problem.evidence]
    if missing or not evidence_refs:
        raise StateIntegrityError(f"unknown {unknown_id} can only be resolved with committed evidence")
    with ctx.commit(f"resolve unknown {unknown_id}") as ps:
        u = ps.unknowns[unknown_id]
        u.status = UnknownStatus.RESOLVED
        u.resolution = resolution


def stakeholder_evidence(
    evidence_id: str, stakeholder_id: str, content: str, *, assertion: str | None = None, value: Any = None
) -> Evidence:
    """Evidence that a stakeholder *said* something (supports a Claim, never a Fact)."""
    return Evidence(
        id=evidence_id,
        source_type=EvidenceSourceType.STAKEHOLDER,
        source_id=stakeholder_id,
        provenance=Provenance(EvidenceSourceType.STAKEHOLDER, stakeholder_id, method="interview"),
        content=content,
        target_assertion=assertion,
        value=value,
        authority=SourceAuthority.NON_AUTHORITATIVE,
    )

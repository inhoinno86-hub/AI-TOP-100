"""Fact / Claim / Evidence / Hypothesis / Assumption / Unknown / Conflict (Design Freeze §5).

* A stakeholder statement is a Claim, never automatically a Fact.
* A Fact must cite the Evidence that establishes it.
* Evidence carries completeness/authority of its source; revisions are appended, not overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.enums import (
    AssumptionStatus,
    ClaimStatus,
    ConflictStatus,
    ConflictType,
    Criticality,
    EvidenceRelation,
    EvidenceSourceType,
    EvidenceStatus,
    HypothesisStatus,
    ResultCompleteness,
    SourceAuthority,
    UnknownStatus,
)
from ..core.provenance import Provenance
from ..core.scope import Scope


@dataclass
class InterpretationEntry:
    interpretation: str
    reason: str
    event_seq: int | None = None


@dataclass
class Evidence:
    id: str
    source_type: EvidenceSourceType
    source_id: str
    provenance: Provenance
    content: str
    target_assertion: str | None = None  # assertion key, e.g. "turnaround.cause"
    value: Any = None  # value this evidence indicates for target_assertion
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS
    reliability: str = "UNKNOWN"
    extraction_confidence: str = "UNKNOWN"
    completeness: ResultCompleteness = ResultCompleteness.NOT_APPLICABLE
    authority: SourceAuthority = SourceAuthority.UNKNOWN
    interpretation_history: list[InterpretationEntry] = field(default_factory=list)
    status: EvidenceStatus = EvidenceStatus.ACTIVE
    is_fallback: bool = False
    # Hidden ground truth must never enter runtime reasoning (Design Freeze §5).
    hidden_ground_truth: bool = False


@dataclass
class EvidenceRevision:
    """New evidence invalidating/revising existing evidence (Design Freeze §5, Mock #6)."""

    id: str
    evidence_id: str
    revised_by: str  # evidence id that caused the revision
    previous_interpretation: str
    revised_interpretation: str
    invalidates_problem: bool = False
    event_seq: int | None = None


@dataclass
class Claim:
    id: str
    stakeholder_id: str
    statement: str
    assertion: str | None = None
    value: Any = None
    evidence_refs: list[str] = field(default_factory=list)
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    is_initial_request: bool = False


@dataclass
class Fact:
    id: str
    statement: str
    assertion: str | None = None
    value: Any = None
    evidence_refs: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.evidence_refs:
            raise ValueError(f"Fact {self.id} requires supporting evidence_refs")


@dataclass
class Hypothesis:
    id: str
    statement: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    decision_impact: Criticality = Criticality.MEDIUM
    discriminating_actions: list[str] = field(default_factory=list)


@dataclass
class Assumption:
    id: str
    statement: str
    basis: str = ""
    risk_if_wrong: Criticality = Criticality.MEDIUM
    status: AssumptionStatus = AssumptionStatus.ACTIVE
    linked_vob: str | None = None


@dataclass
class Unknown:
    id: str
    question: str
    criticality: Criticality = Criticality.MEDIUM
    decision_impact: str = ""
    affects_scope: Scope = field(default_factory=Scope)
    resolution_path: str | None = None  # e.g. a validation method or targeted action
    safe_placeholder: str | None = None  # safe no-write path available while deferred
    status: UnknownStatus = UnknownStatus.OPEN
    deferred_to_vob: str | None = None
    resolution: str | None = None


@dataclass
class Conflict:
    id: str
    type: ConflictType
    side_a: str
    side_b: str
    assertion: str | None = None
    decision_impact: Criticality = Criticality.MEDIUM
    gate_blocking: bool = False
    evidence_refs: list[str] = field(default_factory=list)
    resolution_strategy: str | None = None
    status: ConflictStatus = ConflictStatus.OPEN
    affects_scope: Scope = field(default_factory=Scope)


@dataclass
class Goal:
    id: str
    statement: str
    owner: str | None = None


@dataclass
class Risk:
    id: str
    description: str
    severity: Criticality = Criticality.MEDIUM
    mitigation: str | None = None


@dataclass
class SuccessCriterion:
    id: str
    statement: str
    metric_id: str | None = None
    threshold: str | None = None
    validation_method: str | None = None
    test_refs: list[str] = field(default_factory=list)

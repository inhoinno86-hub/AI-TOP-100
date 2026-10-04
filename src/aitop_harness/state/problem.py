"""ProblemState — what the Harness knows about the world and the problem (Design Freeze §3.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..domain.authority import Constraint, DomainAuthorization
from ..domain.data import DataAsset
from ..domain.design import (
    AgentSpec,
    BudgetPlan,
    DecisionRecord,
    ExecutionRecord,
    ProblemDefinition,
    SolutionDesign,
    ValidationRecord,
)
from ..domain.epistemic import (
    Assumption,
    Claim,
    Conflict,
    Evidence,
    EvidenceRevision,
    Fact,
    Goal,
    Hypothesis,
    Risk,
    SuccessCriterion,
    Unknown,
)
from ..domain.identity import CanonicalMapping, EntityIdentity
from ..domain.metric import Metric
from ..domain.organization import BusinessProcess, Organization, ProcessHandoff, Stakeholder
from ..domain.verification import VerificationObligation


@dataclass
class Scenario:
    id: str
    title: str = ""
    description: str = ""
    initial_request: str = ""
    requested_by: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProblemMeta:
    version: int = 0  # bumped on every canonical commit
    problem_definition_history: list[ProblemDefinition] = field(default_factory=list)


# Id-keyed collections. Used for State Diff (Design Freeze §27) and serialization.
TRACKED_COLLECTIONS: tuple[str, ...] = (
    "organizations",
    "stakeholders",
    "processes",
    "process_handoffs",
    "entity_identities",
    "canonical_mappings",
    "data_assets",
    "metrics",
    "facts",
    "claims",
    "hypotheses",
    "evidence",
    "evidence_revisions",
    "unknowns",
    "conflicts",
    "assumptions",
    "goals",
    "constraints",
    "domain_authorizations",
    "risks",
    "success_criteria",
    "verification_obligations",
)


@dataclass
class ProblemState:
    scenario: Scenario
    meta: ProblemMeta = field(default_factory=ProblemMeta)
    organizations: dict[str, Organization] = field(default_factory=dict)
    stakeholders: dict[str, Stakeholder] = field(default_factory=dict)
    processes: dict[str, BusinessProcess] = field(default_factory=dict)
    process_handoffs: dict[str, ProcessHandoff] = field(default_factory=dict)
    entity_identities: dict[str, EntityIdentity] = field(default_factory=dict)
    # Lazy: stays empty when identity resolution is irrelevant (Design Freeze §9).
    canonical_mappings: dict[str, CanonicalMapping] = field(default_factory=dict)
    data_assets: dict[str, DataAsset] = field(default_factory=dict)
    metrics: dict[str, Metric] = field(default_factory=dict)
    facts: dict[str, Fact] = field(default_factory=dict)
    claims: dict[str, Claim] = field(default_factory=dict)
    hypotheses: dict[str, Hypothesis] = field(default_factory=dict)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    evidence_revisions: dict[str, EvidenceRevision] = field(default_factory=dict)
    unknowns: dict[str, Unknown] = field(default_factory=dict)
    conflicts: dict[str, Conflict] = field(default_factory=dict)
    assumptions: dict[str, Assumption] = field(default_factory=dict)
    goals: dict[str, Goal] = field(default_factory=dict)
    constraints: dict[str, Constraint] = field(default_factory=dict)
    domain_authorizations: dict[str, DomainAuthorization] = field(default_factory=dict)
    risks: dict[str, Risk] = field(default_factory=dict)
    success_criteria: dict[str, SuccessCriterion] = field(default_factory=dict)
    verification_obligations: dict[str, VerificationObligation] = field(default_factory=dict)
    problem_definition: ProblemDefinition | None = None
    solution_design: SolutionDesign | None = None
    agent_spec: AgentSpec | None = None
    execution: ExecutionRecord = field(default_factory=ExecutionRecord)
    validation: ValidationRecord = field(default_factory=ValidationRecord)
    budget: BudgetPlan = field(default_factory=BudgetPlan)
    decision_log: list[DecisionRecord] = field(default_factory=list)

    # ------------------------------------------------------------------ queries

    def open_vobs(self) -> list[VerificationObligation]:
        return [v for v in self.verification_obligations.values() if v.is_open()]

    def committed_evidence_ids(self) -> set[str]:
        return set(self.evidence)

    def authorization_for(self, action: str, resource: str | None = None) -> DomainAuthorization | None:
        """Most relevant domain authorization record for an action (effective ones first)."""
        candidates = [
            a
            for a in self.domain_authorizations.values()
            if a.action == action and (resource is None or a.resource == resource)
        ]
        candidates.sort(key=lambda a: not a.is_effective())
        return candidates[0] if candidates else None

    def next_id(self, prefix: str, collection: str) -> str:
        existing: dict[str, Any] = getattr(self, collection)
        n = len(existing) + 1
        while f"{prefix}-{n}" in existing:
            n += 1
        return f"{prefix}-{n}"

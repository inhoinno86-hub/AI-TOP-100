"""Problem definition, solution design, AgentSpec, execution/validation/budget records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.enums import (
    AgentRole,
    BudgetSlot,
    DefineGateResult,
    DesignStage,
    Phase,
    ProblemDefinitionStatus,
    ReleaseDecision,
    WorkClass,
)
from ..core.scope import ScopeItem


@dataclass
class ProblemDefinition:
    """Canonical Problem.

    Requested solution / symptom / root problem are kept apart so the harness does not anchor
    on the initial request (Mock #2).
    """

    id: str
    version: int = 1
    requested_solution: str = ""
    symptoms: list[str] = field(default_factory=list)
    root_problem: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    intended_scope: list[ScopeItem] = field(default_factory=list)
    protected_actions: list[str] = field(default_factory=list)
    depends_on_mappings: list[str] = field(default_factory=list)
    depends_on_handoffs: list[str] = field(default_factory=list)
    depends_on_exports: list[str] = field(default_factory=list)  # data asset ids to export
    required_tools: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    metric_ids: list[str] = field(default_factory=list)
    status: ProblemDefinitionStatus = ProblemDefinitionStatus.DRAFT
    gate_result: DefineGateResult | None = None
    invalidated_by: list[str] = field(default_factory=list)


@dataclass
class StructuralRemedyCandidate:
    id: str
    description: str
    removes_root_cause: bool
    feasible_in_contest_time: bool
    constraint_feasible: bool = True
    rationale: str = ""


@dataclass
class DesignTraceEntry:
    stage: DesignStage
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentificationGateRecord:
    """Five ordered questions (Design Freeze §17). Deterministic-first."""

    structural_change_removes_root_cause: bool
    structural_change_feasible_in_time: bool
    deterministic_rules_cover_cases: bool
    llm_reasoning_adds_value: bool
    autonomous_iteration_adds_value: bool
    agent_justified: bool = False
    rationale: str = ""


@dataclass
class SolutionDesign:
    id: str
    problem_ref: str
    problem_version: int
    trace: list[DesignTraceEntry] = field(default_factory=list)
    structural_remedies: list[StructuralRemedyCandidate] = field(default_factory=list)
    deterministic_components: list[str] = field(default_factory=list)
    why_agent: str | None = None
    agent_roles: list[AgentRole] = field(default_factory=list)
    bridge_sunset_condition: str | None = None
    agentification: AgentificationGateRecord | None = None
    release_scope: list[ScopeItem] = field(default_factory=list)
    minimum_useful_scope: list[ScopeItem] = field(default_factory=list)
    unfinished_scope: list[str] = field(default_factory=list)


@dataclass
class FailureHandlingPolicy:
    """AgentSpec.failure_handling (v0.2.5 §16)."""

    tool_health_policy: str = "track health per tool; DEGRADED/UNAVAILABLE informs planning"
    retry_policy: str = "bounded by evidence and budget"
    retry_stop_policy: str = "v0.2.5 §10 stop conditions"
    repeated_failure_threshold: int = 2  # policy parameter, not an architecture constant
    fallback_policy: str = "fallback never promoted to authoritative"
    partial_result_policy: str = "partial stays partial until proven complete"
    stale_data_policy: str = "freshness checked only when decision-relevant"
    mutation_uncertainty_policy: str = "read-back before any re-attempt"
    replan_reprofile_policy: str = "tool failure alone never redefines"


@dataclass
class BudgetPolicy:
    """AgentSpec.budget_policy (v0.2.5 §16)."""

    soft_phase_budget: str = "Design Freeze §24"
    verification_floor_minutes: float = 20.0
    release_reserve_minutes: float = 30.0
    reserve_entry_rule: str = "remaining <= release_reserve"
    scope_reduction_rule: str = "DROP nice-to-have/low-value/refactor/non-blocking; KEEP blocking"
    packaging_protection_rule: str = "packaging + submission always kept"


@dataclass
class AgentSpec:
    """Design Freeze §18 minimum structure."""

    identity: str
    problem_reference: str
    organization_context: list[str] = field(default_factory=list)
    process_context: list[str] = field(default_factory=list)
    handoff_context: list[str] = field(default_factory=list)
    interface: dict[str, Any] = field(default_factory=dict)
    required_data: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    allowed_transformations: list[str] = field(default_factory=list)
    entity_identity: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    workflow: list[str] = field(default_factory=list)
    decision_rules: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    authority_boundary: list[str] = field(default_factory=list)
    structural_role: list[AgentRole] = field(default_factory=list)
    human_gate: list[str] = field(default_factory=list)
    failure_handling: FailureHandlingPolicy = field(default_factory=FailureHandlingPolicy)
    termination: str = ""
    validation: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    verification_obligations: list[str] = field(default_factory=list)
    budget_policy: BudgetPolicy = field(default_factory=BudgetPolicy)


@dataclass
class ActionRecord:
    """An executed (or prevented) action — knowledge of what happened in the world."""

    id: str
    action: str
    scope: list[ScopeItem] = field(default_factory=list)
    protected: bool = False
    idempotency_key: str | None = None
    approval_event_seq: int | None = None
    executed_event_seq: int | None = None
    domain_authorization_ref: str | None = None
    runtime_confirmation_required: bool = False
    read_back_verified: bool | None = None
    result: str = ""
    used_fallback_data: bool = False


@dataclass
class ExecutionRecord:
    actions: list[ActionRecord] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)

    def executed_idempotency_keys(self) -> list[str]:
        return [a.idempotency_key for a in self.actions if a.idempotency_key]


@dataclass
class ValidationRecord:
    verify_runs: list[dict[str, Any]] = field(default_factory=list)
    release_decisions: list[ReleaseDecision] = field(default_factory=list)


@dataclass
class BudgetSlotPlan:
    slot: BudgetSlot
    start_minute: float
    end_minute: float

    @property
    def minutes(self) -> float:
        return self.end_minute - self.start_minute


def default_soft_budget() -> list[BudgetSlotPlan]:
    """Design Freeze §24 soft budget (minutes from contest start)."""
    return [
        BudgetSlotPlan(BudgetSlot.ENVIRONMENT, 0, 15),
        BudgetSlotPlan(BudgetSlot.DISCOVER, 15, 55),
        BudgetSlotPlan(BudgetSlot.DEFINE, 55, 75),
        BudgetSlotPlan(BudgetSlot.DESIGN, 75, 100),
        BudgetSlotPlan(BudgetSlot.EXECUTE, 100, 230),
        BudgetSlotPlan(BudgetSlot.VERIFY, 230, 270),
        BudgetSlotPlan(BudgetSlot.RELEASE, 270, 300),
    ]


@dataclass
class BudgetPlan:
    """The budget *plan* (ProblemState.budget). Live consumption is RuntimeState.budget_runtime."""

    total_minutes: float = 300.0
    slots: list[BudgetSlotPlan] = field(default_factory=default_soft_budget)
    release_reserve_minutes: float = 30.0
    reserve_approach_window_minutes: float = 15.0
    verification_floor_minutes: float = 20.0
    packaging_minutes: float = 15.0

    def slot(self, slot: BudgetSlot) -> BudgetSlotPlan:
        for s in self.slots:
            if s.slot is slot:
                return s
        raise KeyError(slot)


@dataclass
class WorkItem:
    """Unit of planned work used by Release Reserve scope reduction."""

    id: str
    description: str
    work_class: WorkClass
    est_minutes: float = 0.0
    scope_items: list[ScopeItem] = field(default_factory=list)
    root_problem_aligned: bool = False
    release_blocking: bool = False
    status: str = "PENDING"  # PENDING / DONE / DROPPED


@dataclass
class DecisionRecord:
    id: str
    phase: Phase
    decision: str
    rationale: str
    evidence_refs: list[str] = field(default_factory=list)
    event_seq: int | None = None

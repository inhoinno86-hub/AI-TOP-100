"""RuntimeState — what the Harness is doing now: execution / recovery / budget (Design Freeze §3.2).

Recovery is a *sub-structure* of RuntimeState, never a fourth canonical state (v0.2.5 P30).
Detail is lazy (v0.2.5 P32): fields are populated only when decision-relevant.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    ArtifactStatus,
    ExecutionStatus,
    FallbackStatus,
    FallbackUsage,
    FreshnessStatus,
    HumanDecisionKind,
    Phase,
    ProtectedActionCategory,
    RecoveryKind,
    ReserveStatus,
    ResultCompleteness,
    RetryStopReason,
    Reversibility,
    SafePointKind,
    SourceAuthority,
    ToolHealth,
    TransitionKind,
)
from ..core.scope import ScopeItem
from ..domain.design import WorkItem


@dataclass
class ToolRuntime:
    """v0.2.5 §6.2."""

    tool_id: str
    operation: str | None = None
    health: ToolHealth = ToolHealth.UNKNOWN
    attempt: int = 0
    last_result_status: str | None = None
    last_error_class: str | None = None
    retryable_hint: bool | None = None
    partial_side_effect_possible: bool = False
    result_completeness: ResultCompleteness = ResultCompleteness.NOT_APPLICABLE
    result_authority: SourceAuthority = SourceAuthority.UNKNOWN
    time_cost: float = 0.0
    cumulative_cost: float = 0.0
    evidence_ref: str | None = None
    consecutive_failures: int = 0


@dataclass
class RetryRecord:
    """v0.2.5 §9 (only important retries are recorded)."""

    tool_id: str
    operation: str
    attempt: int
    failure_signature: str
    prior_error: str | None
    retry_reason: str
    estimated_retry_cost: float
    actual_retry_cost: float | None = None
    cumulative_retry_cost: float = 0.0
    result: str | None = None
    stop_after_this: bool = False


@dataclass
class FallbackRuntime:
    """v0.2.5 §13."""

    source: str
    trigger: str
    coverage: str = ""
    authority: SourceAuthority = SourceAuthority.NON_AUTHORITATIVE
    completeness: ResultCompleteness = ResultCompleteness.UNKNOWN
    freshness_status: FreshnessStatus = FreshnessStatus.NOT_EVALUATED
    semantic_difference: str = ""
    allowed_usage: list[FallbackUsage] = field(
        default_factory=lambda: [
            FallbackUsage.HISTORICAL_BASELINE,
            FallbackUsage.PATTERN_DIAGNOSIS,
            FallbackUsage.READ_ONLY_SUPPORTING_EVIDENCE,
        ]
    )
    prohibited_usage: list[FallbackUsage] = field(
        default_factory=lambda: [
            FallbackUsage.CURRENT_PROTECTED_MUTATION,
            FallbackUsage.AUTHORITATIVE_FINAL_ACTION,
        ]
    )
    status: FallbackStatus = FallbackStatus.ACTIVE


@dataclass
class RecoveryRuntime:
    """v0.2.5 §7."""

    active: bool = False
    failure_signature: str | None = None
    retry_count: int = 0
    cumulative_retry_cost: float = 0.0
    retry_eligible: bool | None = None
    retry_stop_reason: RetryStopReason | None = None
    fallback_available: bool | None = None
    fallback_status: FallbackStatus = FallbackStatus.NOT_NEEDED
    fallback_authority: SourceAuthority | None = None
    fallback_freshness_status: FreshnessStatus = FreshnessStatus.NOT_EVALUATED
    partial_result_status: ResultCompleteness | None = None
    mutation_uncertainty: bool = False
    candidate_transition: RecoveryKind | None = None
    decision_rationale: str = ""
    linked_vob_ids: list[str] = field(default_factory=list)
    # lightweight history used to stop hidden infinite retry
    signature_failures: dict[str, int] = field(default_factory=dict)
    retry_history: list[RetryRecord] = field(default_factory=list)
    fallbacks: dict[str, FallbackRuntime] = field(default_factory=dict)


@dataclass
class BudgetRuntime:
    """v0.2.5 §14.2. A decision input, not a countdown display."""

    total_budget: float = 300.0
    elapsed: float = 0.0
    remaining: float = 300.0
    phase_budget: dict[str, float] = field(default_factory=dict)
    phase_spent: dict[str, float] = field(default_factory=dict)
    phase_variance: dict[str, float] = field(default_factory=dict)
    variance_reason: str | None = None
    recovery_action: str | None = None
    verification_budget_remaining: float = 0.0
    packaging_budget_remaining: float = 0.0
    release_reserve_impact: str | None = None


@dataclass
class ReleaseRuntime:
    """v0.2.5 §15."""

    reserve_threshold: float = 30.0
    reserve_status: ReserveStatus = ReserveStatus.NOT_ACTIVE
    reserve_entered_at: float | None = None
    release_blocking_risks: list[str] = field(default_factory=list)
    dropped_scope: list[str] = field(default_factory=list)  # work item ids
    kept_scope: list[str] = field(default_factory=list)
    packaging_status: ArtifactStatus = ArtifactStatus.NOT_STARTED
    submission_status: ArtifactStatus = ArtifactStatus.NOT_STARTED
    projected_finish: float | None = None


@dataclass
class Plan:
    id: str
    version: int = 1
    work_items: list[WorkItem] = field(default_factory=list)
    rationale: str = ""


@dataclass
class ProtectedActionProposal:
    """A proposed protected action. Nothing is executed by creating a proposal."""

    action_id: str
    action: str
    subject: str
    protected_resource: str
    requested_scope: list[ScopeItem]
    category: ProtectedActionCategory
    why: str = ""
    side_effect: str = ""
    reversibility: Reversibility = Reversibility.UNKNOWN
    alternatives: list[str] = field(default_factory=list)
    idempotency_key: str | None = None
    key_evidence: list[str] = field(default_factory=list)
    uses_fallback_data: bool = False


@dataclass
class RuntimeExecutionConfirmation:
    """RUNTIME_EXECUTION_CONFIRMATION (v0.2.4 §10.2) — separate from DomainAuthorization."""

    proposed_action: str
    protected_resource: str
    side_effect_level: str
    required: bool
    required_human_role: str | None = None
    reason: str = ""
    requested_at: float | None = None
    decision: HumanDecisionKind | None = None  # APPROVE / MODIFY / REJECT only
    decided_at: float | None = None
    event_ref: int | None = None


@dataclass
class PendingProtectedAction:
    gate_id: str
    proposal: ProtectedActionProposal
    confirmation: RuntimeExecutionConfirmation
    domain_authorization_ref: str | None
    safe_point_seq: int | None = None
    packet_event_seq: int | None = None
    context_requests: int = 0
    answered_topics: list[str] = field(default_factory=list)


@dataclass
class SafePoint:
    kind: SafePointKind
    phase: Phase
    event_seq: int
    problem_version: int


@dataclass
class TransitionCandidate:
    kind: TransitionKind
    target_phase: Phase | None
    rationale: str = ""
    evidence_refs: list[str] = field(default_factory=list)


@dataclass
class RuntimeState:
    phase: Phase = Phase.DISCOVER
    execution_status: ExecutionStatus = ExecutionStatus.IDLE
    current_plan: Plan | None = None
    current_task: str | None = None
    current_action: str | None = None
    next_action: str | None = None
    current_tool: str | None = None
    tool_runtime: dict[str, ToolRuntime] = field(default_factory=dict)
    recovery: RecoveryRuntime = field(default_factory=RecoveryRuntime)
    budget_runtime: BudgetRuntime = field(default_factory=BudgetRuntime)
    release_runtime: ReleaseRuntime = field(default_factory=ReleaseRuntime)
    pending_protected_action: PendingProtectedAction | None = None
    safe_point: SafePoint | None = None
    transition_candidate: TransitionCandidate | None = None
    event_refs: list[int] = field(default_factory=list)
    reprofile_targets: list[str] = field(default_factory=list)

    def tool(self, tool_id: str) -> ToolRuntime:
        if tool_id not in self.tool_runtime:
            self.tool_runtime[tool_id] = ToolRuntime(tool_id=tool_id)
        return self.tool_runtime[tool_id]

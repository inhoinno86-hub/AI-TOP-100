"""Enumerations for frozen v0.3 semantics.

Enum *member names* follow the design documents so traceability stays obvious.
Internal values are implementation-flexible (Design Freeze §36.2).
"""

from __future__ import annotations

from enum import StrEnum

# --------------------------------------------------------------------------- phases / runtime


class Phase(StrEnum):
    """Frozen high-level phase flow (Design Freeze §2)."""

    DISCOVER = "DISCOVER"
    DEFINE = "DEFINE"
    DESIGN = "DESIGN"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    RELEASE = "RELEASE"


PHASE_ORDER: tuple[Phase, ...] = (
    Phase.DISCOVER,
    Phase.DEFINE,
    Phase.DESIGN,
    Phase.EXECUTE,
    Phase.VERIFY,
    Phase.RELEASE,
)


class ExecutionStatus(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    RECOVERING = "RECOVERING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    ABORTED = "ABORTED"


class TransitionKind(StrEnum):
    """Transition semantics (Design Freeze §21, v0.2.4 §25)."""

    ADVANCE = "ADVANCE"
    RETRY = "RETRY"
    REPLAN = "REPLAN"
    REPROFILE = "REPROFILE"
    REDEFINE = "REDEFINE"
    ABORT = "ABORT"
    FINISH = "FINISH"


# Transition-candidate precedence (IDR-REDEFINE-08): a lower-ranked candidate never overwrites a
# higher-ranked one, so a Problem-invalidating REDEFINE cannot silently become a REPLAN.
TRANSITION_PRECEDENCE: dict[TransitionKind, int] = {
    TransitionKind.ABORT: 5,
    TransitionKind.REDEFINE: 4,
    TransitionKind.REPROFILE: 3,
    TransitionKind.REPLAN: 2,
    TransitionKind.RETRY: 1,
    TransitionKind.ADVANCE: 0,
    TransitionKind.FINISH: 0,
}


class RecoveryKind(StrEnum):
    """Tool-failure recovery outcomes (Design Freeze §2 conditional runtime flows).

    ``Tool Failure → retry / replan / reprofile / reduce scope / HOLD``.
    REDEFINE is included because the recovery decision must be able to *refuse* it;
    it is only produced from authoritative problem-invalidating evidence, never from tool failure.
    """

    RETRY = "RETRY"
    REPLAN = "REPLAN"
    REPROFILE = "REPROFILE"
    REDEFINE = "REDEFINE"
    REDUCE_SCOPE = "REDUCE_SCOPE"
    HOLD = "HOLD"


class SafePointKind(StrEnum):
    """Design Freeze §28."""

    BEFORE_ACTION = "BEFORE_ACTION"
    AFTER_TOOL_RESULT = "AFTER_TOOL_RESULT"
    AFTER_VALIDATION = "AFTER_VALIDATION"
    AFTER_STATE_COMMIT = "AFTER_STATE_COMMIT"
    BEFORE_TRANSITION = "BEFORE_TRANSITION"
    BEFORE_PROTECTED_ACTION = "BEFORE_PROTECTED_ACTION"


# --------------------------------------------------------------------------- tools / recovery


class ToolHealth(StrEnum):
    """Design Freeze §19. Not the same as data authority/freshness/semantic validity."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


class ResultCompleteness(StrEnum):
    """v0.2.5 §12. ``SUCCESS`` ≠ ``COMPLETE``."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ResultStatus(StrEnum):
    """Transport-level call status. Says nothing about completeness."""

    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


class SourceAuthority(StrEnum):
    AUTHORITATIVE = "AUTHORITATIVE"
    NON_AUTHORITATIVE = "NON_AUTHORITATIVE"
    UNKNOWN = "UNKNOWN"


class FallbackStatus(StrEnum):
    NOT_NEEDED = "NOT_NEEDED"
    AVAILABLE = "AVAILABLE"
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


class FallbackUsage(StrEnum):
    """Allowed / prohibited usage of fallback data (v0.2.5 §13)."""

    HISTORICAL_BASELINE = "HISTORICAL_BASELINE"
    PATTERN_DIAGNOSIS = "PATTERN_DIAGNOSIS"
    READ_ONLY_SUPPORTING_EVIDENCE = "READ_ONLY_SUPPORTING_EVIDENCE"
    CURRENT_PROTECTED_MUTATION = "CURRENT_PROTECTED_MUTATION"
    AUTHORITATIVE_FINAL_ACTION = "AUTHORITATIVE_FINAL_ACTION"


class RetryStopReason(StrEnum):
    """v0.2.5 §10."""

    REPEATED_SAME_DEPENDENCY_FAILURE = "REPEATED_SAME_DEPENDENCY_FAILURE"
    EXPECTED_VALUE_NOT_ABOVE_COST = "EXPECTED_VALUE_NOT_ABOVE_COST"
    BETTER_FALLBACK_OR_REPLAN = "BETTER_FALLBACK_OR_REPLAN"
    COMPLETENESS_NOT_ESTABLISHABLE = "COMPLETENESS_NOT_ESTABLISHABLE"
    MUTATION_UNCERTAINTY_READ_BACK_FIRST = "MUTATION_UNCERTAINTY_READ_BACK_FIRST"
    BUDGET_THREATENS_VERIFICATION = "BUDGET_THREATENS_VERIFICATION"
    RELEASE_RESERVE_WOULD_BE_VIOLATED = "RELEASE_RESERVE_WOULD_BE_VIOLATED"
    NOT_TRANSIENT = "NOT_TRANSIENT"
    PATH_INVALID = "PATH_INVALID"
    PROBLEM_INVALID = "PROBLEM_INVALID"


# --------------------------------------------------------------------------- budget / release


class BudgetSlot(StrEnum):
    """Soft budget slots (Design Freeze §24). ENVIRONMENT is a budget slot, not a phase."""

    ENVIRONMENT = "ENVIRONMENT"
    DISCOVER = "DISCOVER"
    DEFINE = "DEFINE"
    DESIGN = "DESIGN"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    RELEASE = "RELEASE"


class ReserveStatus(StrEnum):
    NOT_ACTIVE = "NOT_ACTIVE"
    APPROACHING = "APPROACHING"
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"


class WorkClass(StrEnum):
    """Classification used by Release Reserve KEEP/DROP (Design Freeze §25)."""

    # KEEP
    RELEASE_BLOCKING_VERIFICATION = "RELEASE_BLOCKING_VERIFICATION"
    AUTHORITY_SAFETY_CHECK = "AUTHORITY_SAFETY_CHECK"
    PACKAGING = "PACKAGING"
    SUBMISSION = "SUBMISSION"
    # neither explicitly kept nor dropped — decided by release blocking flag
    CORE_FEATURE = "CORE_FEATURE"
    # DROP
    NICE_TO_HAVE = "NICE_TO_HAVE"
    LOW_VALUE_EXPLORATION = "LOW_VALUE_EXPLORATION"
    BROAD_REFACTOR = "BROAD_REFACTOR"
    NON_BLOCKING_FEATURE = "NON_BLOCKING_FEATURE"


RESERVE_KEEP_CLASSES = frozenset(
    {
        WorkClass.RELEASE_BLOCKING_VERIFICATION,
        WorkClass.AUTHORITY_SAFETY_CHECK,
        WorkClass.PACKAGING,
        WorkClass.SUBMISSION,
    }
)
RESERVE_DROP_CLASSES = frozenset(
    {
        WorkClass.NICE_TO_HAVE,
        WorkClass.LOW_VALUE_EXPLORATION,
        WorkClass.BROAD_REFACTOR,
        WorkClass.NON_BLOCKING_FEATURE,
    }
)


class ArtifactStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    DONE = "DONE"
    AT_RISK = "AT_RISK"
    FAILED = "FAILED"


# --------------------------------------------------------------------------- epistemics


class Criticality(StrEnum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceSourceType(StrEnum):
    STAKEHOLDER = "STAKEHOLDER"
    TOOL = "TOOL"
    DATA = "DATA"
    DOCUMENT = "DOCUMENT"
    POLICY = "POLICY"
    OBSERVATION = "OBSERVATION"
    HUMAN = "HUMAN"


class EvidenceRelation(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    NEUTRAL = "NEUTRAL"


class EvidenceStatus(StrEnum):
    """Validity of the *observation*. An interpretation-only revision keeps the observation ACTIVE."""

    ACTIVE = "ACTIVE"
    REVISED = "REVISED"
    SUPERSEDED = "SUPERSEDED"


class RevisionKind(StrEnum):
    """What an Evidence Revision changes (IDR-REDEFINE-06)."""

    INTERPRETATION_ONLY = "INTERPRETATION_ONLY"  # observation still valid, its meaning changed
    OBSERVATION_INVALIDATED = "OBSERVATION_INVALIDATED"  # the observation itself is contradicted
    SCOPE_REVISED = "SCOPE_REVISED"  # observation valid for a narrower scope


class ClaimStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"


class HypothesisStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"


class UnknownStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"


class ConflictType(StrEnum):
    """v0.2.1 §23."""

    CLAIM_CONFLICT = "CLAIM_CONFLICT"
    DATA_CONFLICT = "DATA_CONFLICT"
    PROCESS_CONFLICT = "PROCESS_CONFLICT"
    HANDOFF_CONFLICT = "HANDOFF_CONFLICT"
    IDENTITY_CONFLICT = "IDENTITY_CONFLICT"
    CONSTRAINT_CONFLICT = "CONSTRAINT_CONFLICT"
    GOAL_CONFLICT = "GOAL_CONFLICT"
    METRIC_CONFLICT = "METRIC_CONFLICT"


class ConflictStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    MANAGED = "MANAGED"


class AssumptionStatus(StrEnum):
    ACTIVE = "ACTIVE"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"


# --------------------------------------------------------------------------- handoff / identity / data


class DeliveryStatus(StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class SemanticValidity(StrEnum):
    VALID = "VALID"
    DEGRADED = "DEGRADED"
    BROKEN = "BROKEN"
    UNKNOWN = "UNKNOWN"


class FreshnessStatus(StrEnum):
    """Lazy: NOT_EVALUATED is the default and is *not* a problem by itself."""

    NOT_EVALUATED = "NOT_EVALUATED"
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class AckLayer(StrEnum):
    TRANSPORT = "TRANSPORT"
    SCHEMA_VALIDATION = "SCHEMA_VALIDATION"
    BUSINESS_ACCEPTANCE = "BUSINESS_ACCEPTANCE"
    OTHER = "OTHER"


class AckStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"


class MappingConfidence(StrEnum):
    """v0.2.4 §7."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class MappingStatus(StrEnum):
    PROPOSED = "PROPOSED"
    VERIFIED = "VERIFIED"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    UNRESOLVED = "UNRESOLVED"


class QualityLevel(StrEnum):
    GOOD = "GOOD"
    ACCEPTABLE = "ACCEPTABLE"
    PROBLEMATIC = "PROBLEMATIC"
    UNKNOWN = "UNKNOWN"


class DataIssueType(StrEnum):
    """v0.2.1 §13. Simple dedupe is forbidden."""

    MISSING = "MISSING"
    INVALID = "INVALID"
    INCONSISTENT = "INCONSISTENT"
    MALFORMED = "MALFORMED"
    STALE = "STALE"
    OUTLIER = "OUTLIER"
    AMBIGUOUS = "AMBIGUOUS"
    UNEXPECTED_TYPE = "UNEXPECTED_TYPE"
    JOIN_FAILURE = "JOIN_FAILURE"
    CONTRADICTORY_RECORD = "CONTRADICTORY_RECORD"
    EXACT_RECORD_DUPLICATE = "EXACT_RECORD_DUPLICATE"
    DUPLICATE_BUSINESS_KEY = "DUPLICATE_BUSINESS_KEY"
    KEY_COLLISION = "KEY_COLLISION"
    EVENT_VERSION = "EVENT_VERSION"
    STATUS_PROGRESSION = "STATUS_PROGRESSION"


class MetricProfile(StrEnum):
    MINIMAL = "MINIMAL"
    EXTENDED = "EXTENDED"


class MetricType(StrEnum):
    COUNT = "COUNT"
    DURATION = "DURATION"
    RATE = "RATE"
    POPULATION_RATE = "POPULATION_RATE"
    WINDOWED_TREND = "WINDOWED_TREND"
    HANDOFF_FRESHNESS = "HANDOFF_FRESHNESS"
    OTHER = "OTHER"


# --------------------------------------------------------------------------- constraint / authority


class ConstraintType(StrEnum):
    """v0.2.1 §24."""

    AUTHORITY = "AUTHORITY"
    PRIVACY = "PRIVACY"
    TOOL_ACCESS = "TOOL_ACCESS"
    NETWORK = "NETWORK"
    TIME = "TIME"
    DATA_EXPORT = "DATA_EXPORT"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    SAFETY = "SAFETY"


class ConstraintStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPECTED = "SUSPECTED"
    UNKNOWN = "UNKNOWN"
    RETIRED = "RETIRED"


class AuthorizationStatus(StrEnum):
    GRANTED = "GRANTED"
    NOT_GRANTED = "NOT_GRANTED"
    UNKNOWN = "UNKNOWN"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ProtectedActionCategory(StrEnum):
    """Mandatory Human Gate targets (Design Freeze §29)."""

    IRREVERSIBLE_EXTERNAL_WRITE = "IRREVERSIBLE_EXTERNAL_WRITE"
    SUBMISSION_PUBLISH = "SUBMISSION_PUBLISH"
    PROTECTED_MUTATION = "PROTECTED_MUTATION"
    SENSITIVE_EXPORT = "SENSITIVE_EXPORT"
    OUTSIDE_AGENT_AUTHORITY = "OUTSIDE_AGENT_AUTHORITY"
    HIGH_IMPACT_AMBIGUOUS = "HIGH_IMPACT_AMBIGUOUS"
    EXPLICIT_CONFIRMATION_REQUIRED = "EXPLICIT_CONFIRMATION_REQUIRED"
    NONE = "NONE"


class HumanDecisionKind(StrEnum):
    APPROVE = "APPROVE"
    MODIFY = "MODIFY"
    REJECT = "REJECT"
    REQUEST_CONTEXT = "REQUEST_CONTEXT"


class Reversibility(StrEnum):
    REVERSIBLE = "REVERSIBLE"
    PARTIALLY_REVERSIBLE = "PARTIALLY_REVERSIBLE"
    IRREVERSIBLE = "IRREVERSIBLE"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------- gates / verification


class DefineGateResult(StrEnum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class RequiredBefore(StrEnum):
    """v0.2.4 §12."""

    BEFORE_DESIGN_FINALIZATION = "BEFORE_DESIGN_FINALIZATION"
    BEFORE_PROTECTED_ACTION = "BEFORE_PROTECTED_ACTION"
    BEFORE_RELEASE = "BEFORE_RELEASE"
    BEFORE_PRODUCTION = "BEFORE_PRODUCTION"


class VOBStatus(StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"
    # retired by redefine: tied to an invalidated Problem version (IDR-REDEFINE-04)
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class ProblemDefinitionStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class ChallengeStatus(StrEnum):
    """Lifecycle of a canonical-premise challenge (IDR-REDEFINE-01). Challenge ≠ invalidation."""

    OPEN = "OPEN"
    REDEFINED = "REDEFINED"
    DISMISSED = "DISMISSED"


class DependencyClassification(StrEnum):
    """Dependency Review vocabulary for objects downstream of a redefined Problem."""

    STILL_VALID = "STILL_VALID"
    NEEDS_REEVALUATION = "NEEDS_REEVALUATION"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class AgentRole(StrEnum):
    """Design Freeze §16."""

    PRIMARY_SOLUTION = "PRIMARY_SOLUTION"
    BRIDGE = "BRIDGE"
    CONTROL_DETECTION = "CONTROL_DETECTION"
    EXCEPTION_HANDLER = "EXCEPTION_HANDLER"


class DesignStage(StrEnum):
    """Design Freeze §15 ordering. The integer order is enforced in code."""

    ROOT_PROBLEM = "ROOT_PROBLEM"
    STRUCTURAL_REMEDY = "STRUCTURAL_REMEDY"
    FEASIBILITY = "FEASIBILITY"
    WHY_AGENT = "WHY_AGENT"
    AGENT_ROLE = "AGENT_ROLE"
    AGENTIFICATION_GATE = "AGENTIFICATION_GATE"


DESIGN_STAGE_ORDER: tuple[DesignStage, ...] = tuple(DesignStage)


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_RUN = "NOT_RUN"


class VerifyLayer(StrEnum):
    DETERMINISTIC = "LAYER_1_DETERMINISTIC"
    SEMANTIC_JUDGE = "LAYER_2_SEMANTIC_JUDGE"
    HUMAN_REVIEW = "LAYER_3_HUMAN_REVIEW"


class ReleaseDecision(StrEnum):
    RELEASE = "RELEASE"
    RELEASE_WITH_KNOWN_LIMITATION = "RELEASE_WITH_KNOWN_LIMITATION"
    HOLD = "HOLD"


# --------------------------------------------------------------------------- supervision


class SupervisionMode(StrEnum):
    """v0.2.1 §42."""

    AUTO = "AUTO"
    STEP = "STEP"
    PAUSED = "PAUSED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Importance(StrEnum):
    """Monitoring Importance (Design Freeze §26)."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


IMPORTANCE_RANK = {
    Importance.CRITICAL: 3,
    Importance.HIGH: 2,
    Importance.NORMAL: 1,
    Importance.LOW: 0,
}


class DiffKind(StrEnum):
    """State Diff vocabulary (Design Freeze §27). IMPORTANCE is carried per entry."""

    NEW = "NEW"
    CHANGED = "CHANGED"
    RESOLVED = "RESOLVED"
    DEFERRED = "DEFERRED"
    DROPPED_FOR_BUDGET = "DROPPED_FOR_BUDGET"


class EmissionChannel(StrEnum):
    IMMEDIATE = "IMMEDIATE"
    NEXT_SAFE_POINT = "NEXT_SAFE_POINT"
    DIGEST = "DIGEST"
    AUDIT = "AUDIT"

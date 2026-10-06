"""Recovery decisions — retry / replan / reprofile / redefine (Design Freeze §20-23, v0.2.5 §7-13).

retry     = same strategy/path still valid + failure plausibly transient + EV > cost + budget preserved
replan    = Problem valid, current action/solution path unsuitable
reprofile = new critical owner/policy/data/authority/identity/handoff evidence needed
redefine  = new *authoritative Evidence* invalidates the canonical Problem — never tool failure alone
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    FallbackStatus,
    FallbackUsage,
    FreshnessStatus,
    Importance,
    Phase,
    RecoveryKind,
    ResultCompleteness,
    RetryStopReason,
    SourceAuthority,
    TransitionKind,
)
from ..core.events import EventType
from ..domain.design import FailureHandlingPolicy
from ..engine.context import HarnessContext
from ..state.runtime import FallbackRuntime, RetryRecord, TransitionCandidate
from ..supervision.monitoring import SignalKind
from ..tools.base import TRANSIENT_ERROR_CLASSES, ToolSpec
from .budget import retry_budget_ok
from .redefine import validate_problem_invalidation


@dataclass
class FailureContext:
    tool_id: str
    operation: str
    failure_signature: str | None
    error_class: str | None
    retryable_hint: bool | None
    partial_side_effect_possible: bool = False
    estimated_retry_cost: float = 2.0
    expected_value: float = 1.0  # value of success, same unit as cost (minutes-equivalent)
    path_valid: bool = True
    completeness_establishable: bool = True
    missing_critical_info: list[str] = field(default_factory=list)  # reprofile targets
    alternate_paths: list[str] = field(default_factory=list)
    fallbacks: list[ToolSpec] = field(default_factory=list)
    problem_invalidating_evidence: str | None = None


@dataclass
class RecoveryDecision:
    kind: RecoveryKind
    rationale: str
    stop_reason: RetryStopReason | None = None
    next_action: str | None = None
    reprofile_targets: list[str] = field(default_factory=list)
    fallback: ToolSpec | None = None
    retry_eligible: bool = False


def decide_recovery(
    ctx: HarnessContext, fc: FailureContext, policy: FailureHandlingPolicy | None = None
) -> RecoveryDecision:
    """``problem_invalidating_evidence`` is a *claim* by the caller; the Harness validates it against the
    active canonical Problem's premises (IDR-REDEFINE-01/02) and otherwise decides as for any failure."""
    asserted = fc.problem_invalidating_evidence
    if not asserted:
        return _decide(ctx, fc, policy or FailureHandlingPolicy())
    found, why_not = validate_problem_invalidation(ctx.problem, asserted)
    if why_not is None:
        pd = ctx.problem.problem_definition
        assert pd is not None
        return RecoveryDecision(
            RecoveryKind.REDEFINE,
            f"authoritative evidence {asserted} invalidates canonical Problem {pd.ref}: "
            + "; ".join(c.detail for c in found),
            stop_reason=RetryStopReason.PROBLEM_INVALID,
        )
    decision = _decide(ctx, fc, policy or FailureHandlingPolicy())
    decision.rationale = f"asserted problem-invalidating evidence {asserted} rejected ({why_not}); " + (
        decision.rationale
    )
    return decision


def _decide(ctx: HarnessContext, fc: FailureContext, policy: FailureHandlingPolicy) -> RecoveryDecision:
    rec = ctx.runtime.recovery

    # mutation uncertainty: read-back first, never blind re-attempt (duplicate mutation risk)
    if fc.partial_side_effect_possible or rec.mutation_uncertainty:
        return RecoveryDecision(
            RecoveryKind.HOLD,
            "possible partial side effect: read-back verification required before any re-attempt",
            stop_reason=RetryStopReason.MUTATION_UNCERTAINTY_READ_BACK_FIRST,
            next_action="READ_BACK",
        )

    # reprofile: a critical owner/policy/data/authority/identity/handoff fact is missing
    if fc.missing_critical_info:
        return RecoveryDecision(
            RecoveryKind.REPROFILE,
            f"targeted reprofile for {', '.join(fc.missing_critical_info)} (no broad rediscovery)",
            reprofile_targets=list(fc.missing_critical_info),
        )

    # retry eligibility
    stop: RetryStopReason | None = None
    failures = rec.signature_failures.get(fc.failure_signature or "", 0)
    transient = (fc.retryable_hint is True) or (fc.error_class in TRANSIENT_ERROR_CLASSES)
    if not fc.path_valid:
        stop = RetryStopReason.PATH_INVALID
    elif failures >= policy.repeated_failure_threshold:
        stop = RetryStopReason.REPEATED_SAME_DEPENDENCY_FAILURE
    elif not transient:
        stop = RetryStopReason.NOT_TRANSIENT
    elif not fc.completeness_establishable:
        stop = RetryStopReason.COMPLETENESS_NOT_ESTABLISHABLE
    elif fc.expected_value <= fc.estimated_retry_cost:
        stop = RetryStopReason.EXPECTED_VALUE_NOT_ABOVE_COST
    else:
        ok, reason = retry_budget_ok(ctx, fc.estimated_retry_cost)
        if not ok:
            stop = RetryStopReason(reason or RetryStopReason.BUDGET_THREATENS_VERIFICATION)
    if stop is None:
        return RecoveryDecision(
            RecoveryKind.RETRY,
            f"transient {fc.error_class}; same path valid; "
            f"EV {fc.expected_value} > cost {fc.estimated_retry_cost}",
            retry_eligible=True,
        )

    # retry stopped → replan via fallback / alternate path, else reduce scope / HOLD
    if fc.fallbacks:
        return RecoveryDecision(
            RecoveryKind.REPLAN,
            f"retry stopped ({stop.value}); "
            f"switch to fallback {fc.fallbacks[0].tool_id} within its authority",
            stop_reason=stop,
            fallback=fc.fallbacks[0],
            next_action=f"use_fallback:{fc.fallbacks[0].tool_id}",
        )
    if fc.alternate_paths:
        return RecoveryDecision(
            RecoveryKind.REPLAN,
            f"retry stopped ({stop.value}); alternate path {fc.alternate_paths[0]}",
            stop_reason=stop,
            next_action=fc.alternate_paths[0],
        )
    if stop in (
        RetryStopReason.RELEASE_RESERVE_WOULD_BE_VIOLATED,
        RetryStopReason.BUDGET_THREATENS_VERIFICATION,
    ):
        return RecoveryDecision(
            RecoveryKind.REDUCE_SCOPE,
            f"retry stopped ({stop.value}); drop dependent scope, protect verification/release",
            stop_reason=stop,
        )
    return RecoveryDecision(
        RecoveryKind.HOLD, f"retry stopped ({stop.value}); no fallback or alternate path", stop_reason=stop
    )


_TRANSITION_FOR = {
    RecoveryKind.RETRY: (TransitionKind.RETRY, Phase.EXECUTE),
    RecoveryKind.REPLAN: (TransitionKind.REPLAN, Phase.EXECUTE),
    RecoveryKind.REPROFILE: (TransitionKind.REPROFILE, Phase.DISCOVER),
    RecoveryKind.REDEFINE: (TransitionKind.REDEFINE, Phase.DEFINE),
}


def apply_recovery_decision(ctx: HarnessContext, decision: RecoveryDecision, fc: FailureContext) -> None:
    rec = ctx.runtime.recovery
    rec.active = decision.kind is not RecoveryKind.RETRY or rec.active
    rec.retry_eligible = decision.retry_eligible
    rec.retry_stop_reason = decision.stop_reason
    rec.candidate_transition = decision.kind
    rec.decision_rationale = decision.rationale
    rec.fallback_available = bool(fc.fallbacks)
    if fc.fallbacks and rec.fallback_status is FallbackStatus.NOT_NEEDED:
        rec.fallback_status = FallbackStatus.AVAILABLE
    transition = _TRANSITION_FOR.get(decision.kind)
    if transition:  # precedence-aware: a REDEFINE candidate is never overwritten by REPLAN/RETRY
        ctx.runtime.propose_transition(
            TransitionCandidate(
                transition[0],
                transition[1],
                decision.rationale,
                [fc.problem_invalidating_evidence] if fc.problem_invalidating_evidence else [],
            )
        )
    if decision.reprofile_targets:
        ctx.runtime.reprofile_targets = list(decision.reprofile_targets)
    ctx.runtime.next_action = decision.next_action
    strategy_change = decision.kind is not RecoveryKind.RETRY
    event = ctx.emit(
        EventType.RECOVERY_DECISION,
        {
            "kind": decision.kind.value,
            "rationale": decision.rationale,
            "stop_reason": decision.stop_reason.value if decision.stop_reason else None,
            "signature": fc.failure_signature,
            "tool": fc.tool_id,
        },
        importance=Importance.HIGH if strategy_change else Importance.LOW,
    )
    ctx.supervision.decision_rationale.append(f"{decision.kind.value}: {decision.rationale}")
    if decision.kind is RecoveryKind.RETRY:
        ctx.signal(SignalKind.RETRY_DETAIL, f"retry {fc.tool_id}.{fc.operation}", event_seq=event.seq)
    elif (
        decision.kind is RecoveryKind.HOLD
        and decision.stop_reason is not RetryStopReason.MUTATION_UNCERTAINTY_READ_BACK_FIRST
    ):
        ctx.signal(SignalKind.UNRECOVERABLE_FAILURE, decision.rationale, event_seq=event.seq)
    else:
        ctx.signal(SignalKind.STRATEGY_CHANGING_FAILURE, decision.rationale, event_seq=event.seq)


def record_retry(ctx: HarnessContext, fc: FailureContext, actual_cost: float, result: str) -> RetryRecord:
    """Record an executed retry (attempt, signature, cost, cumulative cost)."""
    rec = ctx.runtime.recovery
    rec.retry_count += 1
    rec.cumulative_retry_cost += actual_cost
    record = RetryRecord(
        tool_id=fc.tool_id,
        operation=fc.operation,
        attempt=ctx.runtime.tool(fc.tool_id).attempt,
        failure_signature=fc.failure_signature or "",
        prior_error=fc.error_class,
        retry_reason="transient failure; same path valid",
        estimated_retry_cost=fc.estimated_retry_cost,
        actual_retry_cost=actual_cost,
        cumulative_retry_cost=rec.cumulative_retry_cost,
        result=result,
    )
    rec.retry_history.append(record)
    ctx.emit(
        EventType.RETRY_ATTEMPTED,
        {
            "tool": fc.tool_id,
            "attempt": record.attempt,
            "signature": record.failure_signature,
            "cumulative_retry_cost": rec.cumulative_retry_cost,
            "result": result,
        },
        importance=Importance.LOW,
    )
    return record


def activate_fallback(
    ctx: HarnessContext,
    primary_tool: str,
    fallback: ToolSpec,
    trigger: str,
    *,
    coverage: str = "",
    semantic_difference: str = "",
) -> FallbackRuntime:
    """Fallback is used *within its authority*: it is never promoted to authoritative."""
    fb = FallbackRuntime(
        source=fallback.tool_id,
        trigger=trigger,
        coverage=coverage,
        authority=SourceAuthority.NON_AUTHORITATIVE,
        semantic_difference=semantic_difference,
    )
    rec = ctx.runtime.recovery
    rec.fallbacks[primary_tool] = fb
    rec.fallback_status = FallbackStatus.ACTIVE
    rec.fallback_authority = fb.authority
    ctx.emit(
        EventType.FALLBACK_ACTIVATED,
        {
            "primary": primary_tool,
            "fallback": fallback.tool_id,
            "trigger": trigger,
            "authority": fb.authority.value,
        },
        importance=Importance.HIGH,
    )
    return fb


# Usages for which fallback freshness is decision-relevant (lazy freshness: only then evaluated).
_FRESHNESS_RELEVANT = frozenset(
    {FallbackUsage.CURRENT_PROTECTED_MUTATION, FallbackUsage.AUTHORITATIVE_FINAL_ACTION}
)


def fallback_permits(
    ctx: HarnessContext,
    primary_tool: str,
    usage: FallbackUsage,
    *,
    snapshot_age_minutes: float | None = None,
    max_age_minutes: float | None = None,
    freshness_relevant: bool | None = None,
) -> tuple[bool, str]:
    fb = ctx.runtime.recovery.fallbacks[primary_tool]
    if usage in fb.prohibited_usage:
        return False, f"{usage.value} prohibited for fallback {fb.source} (authority {fb.authority.value})"
    relevant = freshness_relevant if freshness_relevant is not None else usage in _FRESHNESS_RELEVANT
    if relevant:
        if snapshot_age_minutes is None or max_age_minutes is None:
            fb.freshness_status = FreshnessStatus.UNKNOWN
        else:
            fb.freshness_status = (
                FreshnessStatus.FRESH if snapshot_age_minutes <= max_age_minutes else FreshnessStatus.STALE
            )
        ctx.runtime.recovery.fallback_freshness_status = fb.freshness_status
        if fb.freshness_status is not FreshnessStatus.FRESH:
            return False, f"fallback freshness {fb.freshness_status.value} insufficient for {usage.value}"
    if usage not in fb.allowed_usage and not relevant:
        return False, f"{usage.value} not in allowed usage of fallback {fb.source}"
    return True, f"{usage.value} allowed for fallback {fb.source}"


def partial_is_not_complete(completeness: ResultCompleteness) -> bool:
    """Helper used by VERIFY/Release: anything but COMPLETE cannot back a completeness assumption."""
    return completeness is not ResultCompleteness.COMPLETE

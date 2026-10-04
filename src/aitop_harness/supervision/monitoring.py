"""Monitoring Importance / Throttling (Design Freeze §26, kickoff PHASE H).

CRITICAL → immediate; HIGH → immediate or next safe point; NORMAL → digest; LOW → audit only.
Signals in ``NEVER_THROTTLE`` are emitted immediately regardless of policy or repetition.
"""

from __future__ import annotations

from enum import StrEnum

from ..core.enums import IMPORTANCE_RANK, EmissionChannel, Importance
from ..state.supervision import MonitoringPolicy, Signal, SupervisionState


class SignalKind(StrEnum):
    # never throttled
    STRATEGY_CHANGING_FAILURE = "STRATEGY_CHANGING_FAILURE"
    PROBLEM_INVALIDATED = "PROBLEM_INVALIDATED"
    DEFINE_GATE_RESULT = "DEFINE_GATE_RESULT"
    RELEASE_BLOCKING_VOB = "RELEASE_BLOCKING_VOB"
    RELEASE_RESERVE_ENTERED = "RELEASE_RESERVE_ENTERED"
    PACKAGING_AT_RISK = "PACKAGING_AT_RISK"
    SUBMISSION_AT_RISK = "SUBMISSION_AT_RISK"
    MANDATORY_HUMAN_GATE = "MANDATORY_HUMAN_GATE"
    PROTECTED_ACTION_PROPOSAL = "PROTECTED_ACTION_PROPOSAL"
    AUTHORITY_VIOLATION = "AUTHORITY_VIOLATION"
    PRIVACY_VIOLATION = "PRIVACY_VIOLATION"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    RELEASE_GATE_RESULT = "RELEASE_GATE_RESULT"
    UNRECOVERABLE_FAILURE = "UNRECOVERABLE_FAILURE"
    HUMAN_INTERVENTION_REQUIRED = "HUMAN_INTERVENTION_REQUIRED"
    # human gate interaction
    REQUEST_CONTEXT = "REQUEST_CONTEXT"
    REQUEST_CONTEXT_SCOPE_MISMATCH = "REQUEST_CONTEXT_SCOPE_MISMATCH"
    # throttleable
    RETRY_DETAIL = "RETRY_DETAIL"
    ROUTINE_VALIDATION_SUCCESS = "ROUTINE_VALIDATION_SUCCESS"
    LOW_VALUE_HYPOTHESIS_REJECTED = "LOW_VALUE_HYPOTHESIS_REJECTED"
    # ordinary
    STATE_DIFF = "STATE_DIFF"
    PHASE_CHECKPOINT = "PHASE_CHECKPOINT"
    RECOVERY_DECISION = "RECOVERY_DECISION"
    BUDGET_VARIANCE = "BUDGET_VARIANCE"
    AUDIT = "AUDIT"


NEVER_THROTTLE: frozenset[SignalKind] = frozenset(
    {
        SignalKind.STRATEGY_CHANGING_FAILURE,
        SignalKind.PROBLEM_INVALIDATED,
        SignalKind.DEFINE_GATE_RESULT,
        SignalKind.RELEASE_BLOCKING_VOB,
        SignalKind.RELEASE_RESERVE_ENTERED,
        SignalKind.PACKAGING_AT_RISK,
        SignalKind.SUBMISSION_AT_RISK,
        SignalKind.MANDATORY_HUMAN_GATE,
        SignalKind.PROTECTED_ACTION_PROPOSAL,
        SignalKind.AUTHORITY_VIOLATION,
        SignalKind.PRIVACY_VIOLATION,
        SignalKind.SAFETY_VIOLATION,
        SignalKind.RELEASE_GATE_RESULT,
        SignalKind.UNRECOVERABLE_FAILURE,
        SignalKind.HUMAN_INTERVENTION_REQUIRED,
        SignalKind.REQUEST_CONTEXT_SCOPE_MISMATCH,
    }
)

DEFAULT_IMPORTANCE: dict[SignalKind, Importance] = {
    SignalKind.STRATEGY_CHANGING_FAILURE: Importance.HIGH,
    SignalKind.PROBLEM_INVALIDATED: Importance.CRITICAL,
    SignalKind.DEFINE_GATE_RESULT: Importance.HIGH,
    SignalKind.RELEASE_BLOCKING_VOB: Importance.CRITICAL,
    SignalKind.RELEASE_RESERVE_ENTERED: Importance.CRITICAL,
    SignalKind.PACKAGING_AT_RISK: Importance.CRITICAL,
    SignalKind.SUBMISSION_AT_RISK: Importance.CRITICAL,
    SignalKind.MANDATORY_HUMAN_GATE: Importance.CRITICAL,
    SignalKind.PROTECTED_ACTION_PROPOSAL: Importance.HIGH,
    SignalKind.AUTHORITY_VIOLATION: Importance.CRITICAL,
    SignalKind.PRIVACY_VIOLATION: Importance.CRITICAL,
    SignalKind.SAFETY_VIOLATION: Importance.CRITICAL,
    SignalKind.RELEASE_GATE_RESULT: Importance.CRITICAL,
    SignalKind.UNRECOVERABLE_FAILURE: Importance.CRITICAL,
    SignalKind.HUMAN_INTERVENTION_REQUIRED: Importance.CRITICAL,
    SignalKind.REQUEST_CONTEXT: Importance.HIGH,  # v0.2.3: HIGH by default
    SignalKind.REQUEST_CONTEXT_SCOPE_MISMATCH: Importance.CRITICAL,  # reveals authority/scope mismatch
    SignalKind.RETRY_DETAIL: Importance.LOW,
    SignalKind.ROUTINE_VALIDATION_SUCCESS: Importance.LOW,
    SignalKind.LOW_VALUE_HYPOTHESIS_REJECTED: Importance.LOW,
    SignalKind.STATE_DIFF: Importance.NORMAL,
    SignalKind.PHASE_CHECKPOINT: Importance.NORMAL,
    SignalKind.RECOVERY_DECISION: Importance.NORMAL,
    SignalKind.BUDGET_VARIANCE: Importance.NORMAL,
    SignalKind.AUDIT: Importance.LOW,
}

_THROTTLE_POLICY_FIELD = {
    SignalKind.RETRY_DETAIL: "digest_low_impact_retry",
    SignalKind.ROUTINE_VALIDATION_SUCCESS: "digest_routine_validation",
    SignalKind.LOW_VALUE_HYPOTHESIS_REJECTED: "digest_low_value_rejected_hypothesis",
}


def _max(a: Importance, b: Importance) -> Importance:
    return a if IMPORTANCE_RANK[a] >= IMPORTANCE_RANK[b] else b


def classify(kind: SignalKind, importance: Importance | None = None) -> tuple[Importance, EmissionChannel]:
    """Importance + emission channel for a signal.

    An explicit importance can *raise* but never lower a never-throttle signal.
    """
    base = DEFAULT_IMPORTANCE[kind]
    imp = importance or base
    if kind in NEVER_THROTTLE:
        imp = _max(imp, base)
        return imp, EmissionChannel.IMMEDIATE
    if imp is Importance.CRITICAL or imp is Importance.HIGH:
        return imp, EmissionChannel.IMMEDIATE
    if imp is Importance.NORMAL:
        return imp, EmissionChannel.DIGEST
    return imp, EmissionChannel.AUDIT


def route(
    supervision: SupervisionState,
    kind: SignalKind,
    message: str,
    *,
    importance: Importance | None = None,
    refs: list[str] | None = None,
    event_seq: int | None = None,
    policy: MonitoringPolicy | None = None,
) -> Signal:
    """Classify a signal and place it on the right supervision channel."""
    policy = policy or supervision.monitoring_policy
    imp, channel = classify(kind, importance)
    throttled = False
    flag = _THROTTLE_POLICY_FIELD.get(kind)
    if flag and getattr(policy, flag) and kind not in NEVER_THROTTLE and imp is not Importance.CRITICAL:
        channel, throttled = EmissionChannel.DIGEST, True
    signal = Signal(
        kind=kind.value,
        importance=imp,
        message=message,
        channel=channel,
        refs=list(refs or []),
        event_seq=event_seq,
        throttled=throttled,
    )
    if channel is EmissionChannel.IMMEDIATE:
        supervision.live_summary.append(f"[{imp.value}] {kind.value}: {message}")
    elif channel is EmissionChannel.DIGEST:
        supervision.pending_digest.append(signal)
    return signal


def flush_digest(supervision: SupervisionState) -> list[str]:
    """Collapse pending digest into compact lines (repeated retry detail aggregated)."""
    counts: dict[tuple[str, str], int] = {}
    for s in supervision.pending_digest:
        key = (s.kind, s.message if s.kind != SignalKind.RETRY_DETAIL else "retry detail")
        counts[key] = counts.get(key, 0) + 1
    supervision.pending_digest.clear()
    return [f"{kind}: {msg}" + (f" (x{n})" if n > 1 else "") for (kind, msg), n in counts.items()]

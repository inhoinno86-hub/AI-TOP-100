"""Append-only Event Log (Design Freeze §2 "Budget / Runtime / Event Log").

Events are the audit trail used by VERIFY (approval trace, REQUEST_CONTEXT-not-approval,
duplicate mutation prevention) and by Supervision. They are never edited after append.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .enums import Importance, Phase


class EventType(StrEnum):
    # state / flow
    SCENARIO_LOADED = "scenario_loaded"
    STATE_COMMITTED = "state_committed"
    SAFE_POINT_REACHED = "safe_point_reached"
    PHASE_TRANSITION = "phase_transition"
    TRANSITION_REJECTED = "transition_rejected"
    # discover / epistemics
    DISCOVERY_ACTION_SELECTED = "discovery_action_selected"
    EVIDENCE_ADDED = "evidence_added"
    EVIDENCE_REVISED = "evidence_revised"
    CLAIM_RECORDED = "claim_recorded"
    FACT_ESTABLISHED = "fact_established"
    CONFLICT_DETECTED = "conflict_detected"
    HYPOTHESIS_CHANGED = "hypothesis_changed"
    DATA_INSPECTED = "data_inspected"
    # define / design
    DEFINE_GATE_RESULT = "define_gate_result"
    UNKNOWN_DEFERRED = "unknown_deferred"
    VOB_CREATED = "vob_created"
    VOB_RESOLVED = "vob_resolved"
    VOB_SCOPE_NARROWED = "vob_scope_narrowed"
    METRIC_PROMOTED = "metric_promoted"
    DESIGN_STAGE_RECORDED = "design_stage_recorded"
    AGENTIFICATION_GATE_RESULT = "agentification_gate_result"
    # execute / recovery
    TOOL_CALLED = "tool_called"
    TOOL_FAILED = "tool_failed"
    TOOL_HEALTH_CHANGED = "tool_health_changed"
    PARTIAL_RESULT = "partial_result"
    RETRY_ATTEMPTED = "retry_attempted"
    RECOVERY_DECISION = "recovery_decision"
    FALLBACK_ACTIVATED = "fallback_activated"
    PROBLEM_INVALIDATED = "problem_invalidated"
    # budget / release reserve
    BUDGET_VARIANCE = "budget_variance"
    RELEASE_RESERVE_ENTERED = "release_reserve_entered"
    SCOPE_DROPPED_FOR_BUDGET = "scope_dropped_for_budget"
    # human gate
    PROTECTED_ACTION_PROPOSED = "protected_action_proposed"
    PROTECTED_ACTION_BLOCKED = "protected_action_blocked"
    RUNTIME_CONFIRMATION_REQUESTED = "runtime_confirmation_requested"
    APPROVAL_PACKET_EMITTED = "approval_packet_emitted"
    APPROVAL_GRANTED = "approval_granted"
    HUMAN_OVERRIDE_RECEIVED = "human_override_received"
    APPROVAL_REJECTED = "approval_rejected"
    HUMAN_CONTEXT_REQUESTED = "human_context_requested"
    APPROVAL_CONTEXT_INSUFFICIENT = "approval_context_insufficient"
    PROTECTED_ACTION_EXECUTED = "protected_action_executed"
    READ_BACK_VERIFIED = "read_back_verified"
    DUPLICATE_MUTATION_PREVENTED = "duplicate_mutation_prevented"
    HUMAN_CONTROL = "human_control"
    # verify / release
    VERIFY_COMPLETED = "verify_completed"
    RELEASE_GATE_RESULT = "release_gate_result"
    SIGNAL_EMITTED = "signal_emitted"


@dataclass(frozen=True)
class Event:
    seq: int
    type: EventType
    phase: Phase | None
    minute: float
    payload: dict[str, Any] = field(default_factory=dict)
    importance: Importance = Importance.NORMAL
    refs: tuple[str, ...] = ()


class EventLog:
    """Append-only log. No update/delete API exists by design."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(
        self,
        type: EventType,
        *,
        phase: Phase | None,
        minute: float,
        payload: dict[str, Any] | None = None,
        importance: Importance = Importance.NORMAL,
        refs: tuple[str, ...] | list[str] = (),
    ) -> Event:
        event = Event(
            seq=len(self._events) + 1,
            type=type,
            phase=phase,
            minute=minute,
            payload=dict(payload or {}),
            importance=importance,
            refs=tuple(refs),
        )
        self._events.append(event)
        return event

    def __iter__(self) -> Iterator[Event]:
        return iter(tuple(self._events))

    def __len__(self) -> int:
        return len(self._events)

    def of_type(self, *types: EventType) -> list[Event]:
        return [e for e in self._events if e.type in types]

    def last(self, type: EventType | None = None) -> Event | None:
        for e in reversed(self._events):
            if type is None or e.type is type:
                return e
        return None

    def get(self, seq: int) -> Event:
        return self._events[seq - 1]

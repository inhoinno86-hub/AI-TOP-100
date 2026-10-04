"""HarnessContext — the three canonical states + Event Log, and the only commit path.

Not a god object: phase logic lives in ``phases/*`` as functions over this context.
The context owns only cross-cutting mechanics: commit + State Diff, events, safe points, signals.
"""

from __future__ import annotations

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ..core.clock import SimulatedClock
from ..core.enums import Importance, SafePointKind
from ..core.errors import ScopeNarrowingRejected
from ..core.events import Event, EventLog, EventType
from ..core.scope import Scope
from ..core.serialization import from_dict, to_dict
from ..state.problem import ProblemState
from ..state.runtime import RuntimeState, SafePoint
from ..state.supervision import Signal, SupervisionState
from ..supervision import monitoring
from ..supervision.monitoring import SignalKind
from ..supervision.state_diff import compute_diff, fingerprint

CANONICAL_STATES = ("problem", "runtime", "supervision")


@dataclass
class HarnessContext:
    problem: ProblemState
    runtime: RuntimeState = field(default_factory=RuntimeState)
    supervision: SupervisionState = field(default_factory=SupervisionState)
    events: EventLog = field(default_factory=EventLog)
    clock: SimulatedClock = field(default_factory=SimulatedClock)

    # ------------------------------------------------------------------ events / signals

    def emit(
        self,
        type: EventType,
        payload: dict[str, Any] | None = None,
        *,
        importance: Importance = Importance.NORMAL,
        refs: list[str] | tuple[str, ...] = (),
    ) -> Event:
        event = self.events.append(
            type,
            phase=self.runtime.phase,
            minute=self.clock.now(),
            payload=payload,
            importance=importance,
            refs=refs,
        )
        self.runtime.event_refs.append(event.seq)
        return event

    def signal(
        self,
        kind: SignalKind,
        message: str,
        *,
        importance: Importance | None = None,
        refs: list[str] | None = None,
        event_seq: int | None = None,
    ) -> Signal:
        return monitoring.route(
            self.supervision, kind, message, importance=importance, refs=refs, event_seq=event_seq
        )

    # ------------------------------------------------------------------ commit / safe point

    @contextmanager
    def commit(self, reason: str, *, dropped_for_budget: list[str] | None = None) -> Iterator[ProblemState]:
        """Canonical ProblemState commit.

        On exception the ProblemState is restored and the exception re-raised (no swallowing).
        On success: version bump, State Diff, ``state_committed`` event, AFTER_STATE_COMMIT safe point.
        """
        before = fingerprint(self.problem)
        backup = copy.deepcopy(self.problem)
        from_version = self.problem.meta.version
        try:
            yield self.problem
        except BaseException:
            self.problem = backup
            raise
        self.problem.meta.version = from_version + 1
        diff = compute_diff(
            before,
            self.problem,
            from_version=from_version,
            to_version=self.problem.meta.version,
            reason=reason,
            dropped_for_budget=dropped_for_budget,
        )
        self.supervision.state_diff = diff
        event = self.emit(
            EventType.STATE_COMMITTED,
            {
                "reason": reason,
                "version": self.problem.meta.version,
                "diff": [
                    {"kind": e.kind.value, "collection": e.collection, "id": e.item_id,
                     "importance": e.importance.value}
                    for e in diff.entries
                ],
            },
        )
        self.safe_point(SafePointKind.AFTER_STATE_COMMIT, event_seq=event.seq)

    def safe_point(self, kind: SafePointKind, *, event_seq: int | None = None) -> SafePoint:
        if event_seq is None:
            event_seq = self.emit(EventType.SAFE_POINT_REACHED, {"kind": kind.value}).seq
        sp = SafePoint(
            kind=kind, phase=self.runtime.phase, event_seq=event_seq, problem_version=self.problem.meta.version
        )
        self.runtime.safe_point = sp
        return sp

    # ------------------------------------------------------------------ guarded mutations

    def narrow_vob_scope(self, vob_id: str, new_scope: Scope, evidence_id: str, rationale: str) -> None:
        """Narrow a VOB blocking_scope. Requires committed evidence (no artificial narrowing)."""
        if evidence_id not in self.problem.evidence:
            raise ScopeNarrowingRejected(
                f"cannot narrow {vob_id}: evidence {evidence_id!r} is not committed"
            )
        if not rationale:
            raise ScopeNarrowingRejected(f"cannot narrow {vob_id} without rationale")
        with self.commit(f"narrow blocking_scope of {vob_id}") as ps:
            vob = ps.verification_obligations[vob_id]
            old = vob.blocking_scope
            vob.blocking_scope = new_scope
        self.emit(
            EventType.VOB_SCOPE_NARROWED,
            {"vob": vob_id, "from": to_dict(old), "to": to_dict(new_scope), "rationale": rationale},
            importance=Importance.HIGH,
            refs=[evidence_id],
        )

    # ------------------------------------------------------------------ persistence

    def snapshot(self) -> dict[str, Any]:
        return {
            "problem": to_dict(self.problem),
            "runtime": to_dict(self.runtime),
            "supervision": to_dict(self.supervision),
        }

    @classmethod
    def restore(cls, data: dict[str, Any], events: EventLog | None = None) -> HarnessContext:
        return cls(
            problem=from_dict(ProblemState, data["problem"]),
            runtime=from_dict(RuntimeState, data["runtime"]),
            supervision=from_dict(SupervisionState, data["supervision"]),
            events=events or EventLog(),
        )

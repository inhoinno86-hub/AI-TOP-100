"""SupervisionState — what the Human sees and when to intervene (Design Freeze §3.3).

SupervisionState is a *projection*. It is never the execution truth source: everything here is
rebuilt from ProblemState / RuntimeState / Event Log by ``supervision.projection.refresh``.
ApprovalPacket is not stored here permanently either (v0.2.4 §15).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import DiffKind, EmissionChannel, Importance, SupervisionMode


@dataclass
class StateDiffEntry:
    kind: DiffKind
    collection: str
    item_id: str
    summary: str
    importance: Importance = Importance.NORMAL
    status_from: str | None = None
    status_to: str | None = None


@dataclass
class StateDiff:
    """Change-centric view of one commit; never a full state dump."""

    from_version: int
    to_version: int
    reason: str
    entries: list[StateDiffEntry] = field(default_factory=list)

    def of_kind(self, kind: DiffKind) -> list[StateDiffEntry]:
        return [e for e in self.entries if e.kind is kind]


@dataclass
class Signal:
    kind: str
    importance: Importance
    message: str
    channel: EmissionChannel = EmissionChannel.IMMEDIATE
    refs: list[str] = field(default_factory=list)
    event_seq: int | None = None
    throttled: bool = False


@dataclass
class MonitoringPolicy:
    """Design Freeze §26. Throttle only what is safe to throttle."""

    digest_low_impact_retry: bool = True
    digest_routine_validation: bool = True
    digest_low_value_rejected_hypothesis: bool = True


@dataclass
class Intervention:
    required: bool = False
    reason: str | None = None
    gate_id: str | None = None


@dataclass
class HumanControlRecord:
    command: str
    minute: float
    detail: str = ""


@dataclass
class SupervisionState:
    mode: SupervisionMode = SupervisionMode.AUTO
    live_summary: list[str] = field(default_factory=list)  # immediate notices, newest last
    current_problem: str | None = None
    top_hypotheses: list[str] = field(default_factory=list)
    critical_unknowns: list[str] = field(default_factory=list)
    critical_conflicts: list[str] = field(default_factory=list)
    data_quality_warnings: list[str] = field(default_factory=list)
    key_evidence: list[str] = field(default_factory=list)
    evidence_revisions: list[str] = field(default_factory=list)
    state_diff: StateDiff | None = None
    decision_rationale: list[str] = field(default_factory=list)
    gate_rationale: list[str] = field(default_factory=list)
    pending_verification_obligations: list[str] = field(default_factory=list)
    dependency_review: list[str] = field(default_factory=list)  # latest redefine review, non-trivial items
    current_action: str | None = None
    next_action: str | None = None
    monitoring_policy: MonitoringPolicy = field(default_factory=MonitoringPolicy)
    pending_digest: list[Signal] = field(default_factory=list)
    intervention: Intervention = field(default_factory=Intervention)
    human_control: list[HumanControlRecord] = field(default_factory=list)

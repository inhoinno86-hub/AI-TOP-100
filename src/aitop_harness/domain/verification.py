"""VerificationObligation + required_before + blocking_scope (Design Freeze §14, v0.2.4 §12)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import Criticality, Phase, RequiredBefore, VOBStatus
from ..core.scope import Scope


@dataclass
class VerificationObligation:
    """``Open VOB ≠ Global HOLD``.

    ``blocking_scope`` defaults to the *entire solution* — the conservative choice. Narrowing it
    requires committed evidence (see ``HarnessContext.narrow_vob_scope``) so scope cannot be
    artificially reduced to bypass risk.
    """

    id: str
    unresolved_question: str
    source_phase: Phase
    reason_deferred: str = ""
    decision_impact: Criticality = Criticality.HIGH
    linked_assumption: str | None = None
    linked_success_criterion: str | None = None
    validation_method: str | None = None
    required_evidence: list[str] = field(default_factory=list)
    instrumentation_needed: list[str] = field(default_factory=list)
    owner: str | None = None
    required_before: RequiredBefore = RequiredBefore.BEFORE_RELEASE
    blocking_scope: Scope = field(default_factory=Scope.entire)
    status: VOBStatus = VOBStatus.OPEN
    resolution: str | None = None
    linked_unknown: str | None = None

    def is_open(self) -> bool:
        return self.status is not VOBStatus.RESOLVED

    def is_critical(self) -> bool:
        return self.decision_impact in (Criticality.CRITICAL, Criticality.HIGH)

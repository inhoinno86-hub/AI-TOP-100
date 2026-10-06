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
    # Problem dependency (IDR-REDEFINE-04): the Problem version whose solution this VOB constrains.
    # ``None`` = not bound to a Problem version (applies regardless of version).
    problem_definition_id: str | None = None
    problem_version: int | None = None

    def is_open(self) -> bool:
        """OPEN / DEFERRED obligations are live; RESOLVED / INVALIDATED / SUPERSEDED are not."""
        return self.status in (VOBStatus.OPEN, VOBStatus.DEFERRED)

    def applies_to(self, problem_id: str, version: int) -> bool:
        if self.problem_version is None:
            return True
        return self.problem_version == version and self.problem_definition_id in (None, problem_id)

    def is_critical(self) -> bool:
        return self.decision_impact in (Criticality.CRITICAL, Criticality.HIGH)

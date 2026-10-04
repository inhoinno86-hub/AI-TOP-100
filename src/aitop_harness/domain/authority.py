"""Constraint / Authority and DOMAIN_AUTHORIZATION (Design Freeze §11-12).

``DomainAuthorization`` is world/policy knowledge → lives in ProblemState.
``RuntimeExecutionConfirmation`` is about executing *now* → lives in RuntimeState
(see ``state.runtime``). The two are deliberately separate types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import AuthorizationStatus, ConstraintStatus, ConstraintType, Criticality
from ..core.scope import Scope


@dataclass
class Constraint:
    id: str
    type: ConstraintType
    description: str
    actor: str | None = None
    protected_action: str | None = None
    enforcement: str = "block"
    approval_required: bool = False
    violation_behavior: str = "block"
    evidence_refs: list[str] = field(default_factory=list)
    status: ConstraintStatus = ConstraintStatus.ACTIVE
    criticality: Criticality = Criticality.HIGH
    # Explicit runtime-confirmation requirement independent of domain authorization.
    runtime_confirmation_required: bool = False


@dataclass
class DomainAuthorization:
    id: str
    action: str
    resource: str
    subject: str = ""
    authority_holder: str | None = None
    authorized_scope: Scope = field(default_factory=Scope)
    conditions: list[str] = field(default_factory=list)
    validity: str | None = None
    evidence_refs: list[str] = field(default_factory=list)
    status: AuthorizationStatus = AuthorizationStatus.UNKNOWN

    def is_effective(self) -> bool:
        return (
            self.status is AuthorizationStatus.GRANTED
            and self.authority_holder is not None
            and bool(self.evidence_refs)
        )

"""ApprovalPacket — a decision-support *projection* (Design Freeze §30, v0.2.4 §17).

Built from ProblemState + RuntimeState on demand. Never stored as canonical state, never edited
to change canonical state. Only committed evidence is cited; no raw policy dump.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import RequiredBefore
from ..core.scope import Scope, ScopeItem
from ..state.problem import ProblemState
from ..state.runtime import PendingProtectedAction, RuntimeState


@dataclass(frozen=True)
class ApprovalPacket:
    gate_id: str
    what: str
    why: str
    who_resource: str
    requested_scope: tuple[str, ...]
    authorized_scope: tuple[str, ...]
    scope_delta: tuple[str, ...]  # requested items outside authorized scope (must be empty to be here)
    domain_authorization: str
    why_human_now: str
    side_effect: str
    reversibility: str
    consequence_if_approved: str
    consequence_if_rejected: str
    alternatives: tuple[str, ...]
    unresolved_items: tuple[str, ...]
    open_vobs: tuple[str, ...]  # "VOB-x [required_before] blocking: …"
    time_release_impact: str
    key_evidence: tuple[str, ...]  # committed evidence ids only
    uncommitted_evidence: tuple[str, ...] = field(default=())

    def render(self) -> str:
        lines = [
            f"GATE {self.gate_id}",
            f"WHAT: {self.what}",
            f"WHY: {self.why}",
            f"WHO / RESOURCE: {self.who_resource}",
            f"REQUESTED SCOPE: {', '.join(self.requested_scope)}",
            f"AUTHORIZED SCOPE: {', '.join(self.authorized_scope)}",
            f"SCOPE DELTA: {', '.join(self.scope_delta) or 'none (requested ⊆ authorized)'}",
            f"DOMAIN AUTHORIZATION: {self.domain_authorization}",
            f"WHY HUMAN NOW: {self.why_human_now}",
            f"SIDE EFFECT: {self.side_effect}",
            f"REVERSIBILITY: {self.reversibility}",
            f"CONSEQUENCE IF APPROVED: {self.consequence_if_approved}",
            f"CONSEQUENCE IF REJECTED: {self.consequence_if_rejected}",
            f"ALTERNATIVES: {'; '.join(self.alternatives) or 'none recorded'}",
            f"UNRESOLVED ITEMS: {'; '.join(self.unresolved_items) or 'none'}",
            f"OPEN VOB + BLOCKING_SCOPE: {'; '.join(self.open_vobs) or 'none'}",
            f"TIME / RELEASE IMPACT: {self.time_release_impact}",
            f"KEY EVIDENCE: {', '.join(self.key_evidence) or 'none'}",
        ]
        return "\n".join(lines)


def _scope_str(scope: Scope) -> tuple[str, ...]:
    return ("ENTIRE_SOLUTION",) if scope.entire_solution else tuple(str(i) for i in scope.items)


def project_packet(problem: ProblemState, runtime: RuntimeState, pending: PendingProtectedAction) -> ApprovalPacket:
    p = pending.proposal
    auth = problem.domain_authorizations.get(pending.domain_authorization_ref or "")
    authorized = auth.authorized_scope if auth else Scope()
    _, outside = authorized.contains_all(p.requested_scope)
    committed = tuple(e for e in p.key_evidence if e in problem.evidence)
    uncommitted = tuple(e for e in p.key_evidence if e not in problem.evidence)
    vobs = []
    for v in problem.open_vobs():
        hits = v.blocking_scope.intersect(p.requested_scope)
        relevance = "intersects request" if hits else "outside request"
        vobs.append(
            f"{v.id} [{v.required_before.value}] blocking: {', '.join(_scope_str(v.blocking_scope))} ({relevance})"
        )
    unresolved = [f"uncommitted evidence {e}" for e in uncommitted]
    unresolved += [
        f"{u.id}: {u.question}" for u in problem.unknowns.values()
        if u.status.value != "RESOLVED" and u.affects_scope.intersect(p.requested_scope)
    ]
    br = runtime.budget_runtime
    auth_desc = (
        f"{auth.status.value} by {auth.authority_holder} (evidence {', '.join(auth.evidence_refs)})"
        if auth else "NONE"
    )
    return ApprovalPacket(
        gate_id=pending.gate_id,
        what=f"{p.action} on {p.protected_resource}",
        why=p.why,
        who_resource=f"{p.subject} / {p.protected_resource}",
        requested_scope=tuple(str(i) for i in p.requested_scope),
        authorized_scope=_scope_str(authorized),
        scope_delta=tuple(str(i) for i in outside),
        domain_authorization=auth_desc,
        why_human_now=pending.confirmation.reason,
        side_effect=p.side_effect,
        reversibility=p.reversibility.value,
        consequence_if_approved=f"execute {p.action} once (idempotency key {p.idempotency_key}), then read-back",
        consequence_if_rejected="action not executed; harness replans an alternate / manual path",
        alternatives=tuple(p.alternatives),
        unresolved_items=tuple(unresolved),
        open_vobs=tuple(vobs),
        time_release_impact=(
            f"remaining {br.remaining:.0f}m, reserve {runtime.release_runtime.reserve_status.value}"
        ),
        key_evidence=committed,
        uncommitted_evidence=uncommitted,
    )


def blocking_vobs_for(problem: ProblemState, scope: list[ScopeItem]) -> list[str]:
    """Open VOBs required before protected action whose blocking_scope intersects the action scope."""
    return [
        v.id for v in problem.open_vobs()
        if v.required_before is RequiredBefore.BEFORE_PROTECTED_ACTION and v.blocking_scope.intersect(scope)
    ]

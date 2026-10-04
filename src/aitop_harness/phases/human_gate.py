"""Safe Point + Mandatory Human Gate + REQUEST_CONTEXT (Design Freeze §28-31).

Flow before any protected action:
Domain Authorization Check → Scope Validation → Runtime Confirmation Requirement →
Canonical State Commit → Safe Point → ApprovalPacket → WAITING_APPROVAL.

* Domain authorization and runtime confirmation are separate; APPROVE never repairs missing
  domain authorization or a scope mismatch.
* REQUEST_CONTEXT is not approval: the gate stays WAITING_APPROVAL, nothing executes, domain
  authorization and execution state stay unchanged, explanation uses committed evidence only.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from ..core.enums import (
    ConstraintStatus,
    ExecutionStatus,
    FallbackUsage,
    HumanDecisionKind,
    Importance,
    Phase,
    ProtectedActionCategory,
    ResultStatus,
    SafePointKind,
    TransitionKind,
)
from ..core.errors import ProtectedActionBlocked
from ..core.events import EventType
from ..core.scope import ScopeItem
from ..domain.design import ActionRecord, DecisionRecord
from ..domain.epistemic import Evidence
from ..engine.context import HarnessContext
from ..state.runtime import (
    PendingProtectedAction,
    ProtectedActionProposal,
    RuntimeExecutionConfirmation,
    TransitionCandidate,
)
from ..state.supervision import HumanControlRecord, Intervention
from ..supervision.approval import ApprovalPacket, blocking_vobs_for, project_packet
from ..supervision.monitoring import SignalKind
from ..tools.base import ToolResult
from .discover import integrate_evidence
from .recovery import fallback_permits


class GateStatus(StrEnum):
    BLOCKED = "BLOCKED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    DUPLICATE_PREVENTED = "DUPLICATE_PREVENTED"
    EXECUTION_FAILED = "EXECUTION_FAILED"


class ProtectedExecutor(Protocol):
    tool_id: str

    def call(self, operation: str, params: dict[str, Any]) -> ToolResult: ...

    def read_back(self, key: str) -> dict[str, Any] | None: ...


@dataclass
class HumanDecision:
    kind: HumanDecisionKind
    text: str = ""
    modified_scope: list[ScopeItem] | None = None
    human_role: str | None = None


@dataclass
class GateOutcome:
    status: GateStatus
    gate_id: str | None = None
    reasons: list[str] = field(default_factory=list)
    packet: ApprovalPacket | None = None
    explanation: str | None = None
    action_record: ActionRecord | None = None


@dataclass
class ContextResponse:
    gate_id: str
    topics: list[str]
    explanation: str
    evidence_refs: list[str]
    unresolved: list[str]
    insufficient: bool
    reprofiled_evidence: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- human input interpretation

_QUESTION = re.compile(r"[?？]|\b(why|what|how|which|when|who|explain)\b|왜|무엇|뭐|어떻게|어떤|설명|이유|근거|되나|하나요|인가", re.I)
_APPROVE = re.compile(r"^\s*(approve|approved|yes,? approve|승인(합니다|함|해)?|진행(해|하세요)?)\s*[.!]?\s*$", re.I)
_REJECT = re.compile(r"^\s*(reject|rejected|deny|거절(합니다|함)?|반려(합니다|함)?)\s*[.!]?\s*$", re.I)


def interpret_human_input(text: str) -> HumanDecisionKind:
    """Map free-form human input to a decision. Ambiguity never becomes approval.

    Any question (e.g. "왜 이걸 지금 승인해야 해?") is REQUEST_CONTEXT even if it mentions approval.
    """
    if _QUESTION.search(text):
        return HumanDecisionKind.REQUEST_CONTEXT
    if _APPROVE.match(text):
        return HumanDecisionKind.APPROVE
    if _REJECT.match(text):
        return HumanDecisionKind.REJECT
    return HumanDecisionKind.REQUEST_CONTEXT


# --------------------------------------------------------------------------- pre-checks


def _precheck(ctx: HarnessContext, proposal: ProtectedActionProposal, scope: list[ScopeItem]) -> tuple[list[str], str | None]:
    """Domain authorization + scope + VOB + constraint + fallback checks. Returns (reasons, auth id)."""
    ps = ctx.problem
    reasons: list[str] = []
    auth = ps.authorization_for(proposal.action, proposal.protected_resource)
    if auth is None or not auth.is_effective():
        reasons.append(
            f"DOMAIN_AUTHORIZATION missing/not effective for {proposal.action} on {proposal.protected_resource}"
        )
    else:
        ok, outside = auth.authorized_scope.contains_all(scope)
        if not ok:
            reasons.append(f"SCOPE: requested ⊄ authorized; outside = {[str(i) for i in outside]}")
    blocking = blocking_vobs_for(ps, scope)
    if blocking:
        reasons.append(f"VOB required before protected action intersects scope: {blocking}")
    unknown_rules = [
        c.id for c in ps.constraints.values()
        if c.protected_action == proposal.action and c.status in (ConstraintStatus.UNKNOWN, ConstraintStatus.SUSPECTED)
    ]
    if unknown_rules:
        reasons.append(f"approval requirement unknown: {unknown_rules}")
    if proposal.uses_fallback_data:
        for primary in ctx.runtime.recovery.fallbacks:
            ok, why = fallback_permits(ctx, primary, FallbackUsage.CURRENT_PROTECTED_MUTATION)
            if not ok:
                reasons.append(f"fallback data: {why}")
    return reasons, (auth.id if auth else None)


def _confirmation_requirement(ctx: HarnessContext, proposal: ProtectedActionProposal) -> tuple[bool, str]:
    reasons = []
    if proposal.category is not ProtectedActionCategory.NONE:
        reasons.append(f"{proposal.category.value} requires runtime confirmation")
    for c in ctx.problem.constraints.values():
        if c.protected_action == proposal.action and (c.runtime_confirmation_required or c.approval_required):
            reasons.append(f"constraint {c.id} requires runtime confirmation")
    return bool(reasons), "; ".join(reasons) or "no runtime confirmation required"


def _block(ctx: HarnessContext, proposal: ProtectedActionProposal, reasons: list[str]) -> GateOutcome:
    event = ctx.emit(
        EventType.PROTECTED_ACTION_BLOCKED,
        {"action": proposal.action_id, "reasons": reasons},
        importance=Importance.CRITICAL,
    )
    kind = SignalKind.AUTHORITY_VIOLATION if any(
        r.startswith(("DOMAIN_AUTHORIZATION", "SCOPE")) for r in reasons
    ) else SignalKind.RELEASE_BLOCKING_VOB if any(r.startswith("VOB") for r in reasons) else SignalKind.HUMAN_INTERVENTION_REQUIRED
    ctx.signal(kind, f"{proposal.action} blocked: {'; '.join(reasons)}", event_seq=event.seq)
    return GateOutcome(GateStatus.BLOCKED, reasons=reasons)


# --------------------------------------------------------------------------- proposal


def propose_protected_action(
    ctx: HarnessContext, proposal: ProtectedActionProposal, executor: ProtectedExecutor
) -> GateOutcome:
    if ctx.runtime.pending_protected_action is not None:
        raise ProtectedActionBlocked("another protected action is already pending approval")
    ctx.emit(EventType.PROTECTED_ACTION_PROPOSED, {"action": proposal.action_id, "category": proposal.category.value},
             importance=Importance.HIGH)
    ctx.signal(SignalKind.PROTECTED_ACTION_PROPOSAL, f"{proposal.action} on {proposal.protected_resource}")

    # 1-2. Domain authorization check + scope validation (+ VOB / constraint / fallback)
    reasons, auth_id = _precheck(ctx, proposal, proposal.requested_scope)
    if reasons:
        return _block(ctx, proposal, reasons)

    # 3. Runtime confirmation requirement
    required, why_human = _confirmation_requirement(ctx, proposal)
    confirmation = RuntimeExecutionConfirmation(
        proposed_action=proposal.action,
        protected_resource=proposal.protected_resource,
        side_effect_level=proposal.reversibility.value,
        required=required,
        reason=why_human,
        requested_at=ctx.clock.now(),
    )
    gate_id = f"GATE-{proposal.action_id}"
    pending = PendingProtectedAction(gate_id, proposal, confirmation, auth_id)

    # 4. Canonical state commit
    with ctx.commit(f"protected action proposed {proposal.action_id}") as ps:
        ps.decision_log.append(DecisionRecord(
            id=f"D-{len(ps.decision_log) + 1}", phase=ctx.runtime.phase,
            decision=f"propose {proposal.action}", rationale=proposal.why, evidence_refs=list(proposal.key_evidence)))

    # 5. Safe point before protected action
    sp = ctx.safe_point(SafePointKind.BEFORE_PROTECTED_ACTION)
    pending.safe_point_seq = sp.event_seq

    if not required:
        ctx.runtime.pending_protected_action = pending
        return _execute_atomic(ctx, pending, proposal.requested_scope, executor, decision_event_seq=None)

    # 6. ApprovalPacket projection  7. WAITING_APPROVAL
    ctx.runtime.pending_protected_action = pending
    ctx.runtime.execution_status = ExecutionStatus.WAITING_APPROVAL
    packet = project_packet(ctx.problem, ctx.runtime, pending)
    ctx.emit(EventType.RUNTIME_CONFIRMATION_REQUESTED, {"gate": gate_id, "reason": why_human},
             importance=Importance.CRITICAL)
    pe = ctx.emit(EventType.APPROVAL_PACKET_EMITTED, {"gate": gate_id, "packet": packet.render()},
                  importance=Importance.CRITICAL, refs=list(packet.key_evidence))
    pending.packet_event_seq = pe.seq
    confirmation.event_ref = pe.seq
    ctx.supervision.intervention = Intervention(required=True, reason=why_human, gate_id=gate_id)
    ctx.signal(SignalKind.MANDATORY_HUMAN_GATE, f"{gate_id}: {proposal.action}", event_seq=pe.seq)
    return GateOutcome(GateStatus.WAITING_APPROVAL, gate_id=gate_id, packet=packet)


# --------------------------------------------------------------------------- decisions


def decide(
    ctx: HarnessContext,
    decision: HumanDecision,
    executor: ProtectedExecutor,
    *,
    context_probe: Callable[[list[str]], Evidence | None] | None = None,
) -> GateOutcome:
    pending = ctx.runtime.pending_protected_action
    if pending is None or ctx.runtime.execution_status is not ExecutionStatus.WAITING_APPROVAL:
        raise ProtectedActionBlocked("no gate is WAITING_APPROVAL")
    ctx.supervision.human_control.append(
        HumanControlRecord(decision.kind.value, ctx.clock.now(), decision.text)
    )
    if decision.kind is HumanDecisionKind.REQUEST_CONTEXT:
        response = request_context(ctx, decision.text, context_probe=context_probe)
        return GateOutcome(GateStatus.WAITING_APPROVAL, gate_id=pending.gate_id,
                           packet=project_packet(ctx.problem, ctx.runtime, pending),
                           explanation=response.explanation)
    if decision.kind is HumanDecisionKind.REJECT:
        return _reject(ctx, pending, decision)
    if decision.kind is HumanDecisionKind.APPROVE:
        ev = ctx.emit(EventType.APPROVAL_GRANTED,
                      {"gate": pending.gate_id, "approval_kind": "RUNTIME_EXECUTION_CONFIRMATION"},
                      importance=Importance.HIGH)
        # re-check domain authorization + scope: APPROVE cannot repair either
        reasons, _ = _precheck(ctx, pending.proposal, pending.proposal.requested_scope)
        if reasons:
            return _blocked_after_decision(ctx, pending, reasons)
        pending.confirmation.decision = HumanDecisionKind.APPROVE
        pending.confirmation.decided_at = ctx.clock.now()
        return _execute_atomic(ctx, pending, pending.proposal.requested_scope, executor, decision_event_seq=ev.seq)
    return _modify(ctx, pending, decision, executor)


def _blocked_after_decision(ctx: HarnessContext, pending: PendingProtectedAction, reasons: list[str]) -> GateOutcome:
    """Re-check failed after a decision: do not execute; gate stays pending for REJECT/MODIFY."""
    outcome = _block(ctx, pending.proposal, reasons)
    outcome.gate_id = pending.gate_id
    return outcome


def _modify(ctx: HarnessContext, pending: PendingProtectedAction, decision: HumanDecision,
            executor: ProtectedExecutor) -> GateOutcome:
    scope = list(decision.modified_scope or [])
    ev = ctx.emit(EventType.HUMAN_OVERRIDE_RECEIVED,
                  {"gate": pending.gate_id, "modified_scope": [str(i) for i in scope]}, importance=Importance.HIGH)
    if not scope:
        return _blocked_after_decision(ctx, pending, ["MODIFY without a modified scope"])
    reasons, _ = _precheck(ctx, pending.proposal, scope)
    if reasons:
        return _blocked_after_decision(ctx, pending, reasons)
    original = pending.proposal.requested_scope
    if not all(item in original for item in scope):
        # widened beyond what was presented: needs its own gate
        new_proposal = ProtectedActionProposal(**{**pending.proposal.__dict__, "requested_scope": scope,
                                                  "action_id": f"{pending.proposal.action_id}-M"})
        _clear_pending(ctx)
        return propose_protected_action(ctx, new_proposal, executor)
    pending.confirmation.decision = HumanDecisionKind.MODIFY
    pending.confirmation.decided_at = ctx.clock.now()
    return _execute_atomic(ctx, pending, scope, executor, decision_event_seq=ev.seq)


def _reject(ctx: HarnessContext, pending: PendingProtectedAction, decision: HumanDecision) -> GateOutcome:
    pending.confirmation.decision = HumanDecisionKind.REJECT
    pending.confirmation.decided_at = ctx.clock.now()
    ev = ctx.emit(EventType.APPROVAL_REJECTED, {"gate": pending.gate_id, "text": decision.text},
                  importance=Importance.HIGH)
    with ctx.commit(f"protected action rejected {pending.proposal.action_id}") as ps:
        ps.decision_log.append(DecisionRecord(
            id=f"D-{len(ps.decision_log) + 1}", phase=ctx.runtime.phase,
            decision=f"REJECT {pending.proposal.action}", rationale=decision.text or "human rejected"))
    gate_id = pending.gate_id
    _clear_pending(ctx)
    ctx.runtime.transition_candidate = TransitionCandidate(
        TransitionKind.REPLAN, Phase.EXECUTE, "protected action rejected: alternate / manual / reduced-scope path"
    )
    ctx.signal(SignalKind.STRATEGY_CHANGING_FAILURE, f"{gate_id} rejected → replan", event_seq=ev.seq)
    return GateOutcome(GateStatus.REJECTED, gate_id=gate_id, reasons=["rejected by human"])


def _clear_pending(ctx: HarnessContext) -> None:
    ctx.runtime.pending_protected_action = None
    ctx.runtime.execution_status = ExecutionStatus.RUNNING
    ctx.supervision.intervention = Intervention()


# --------------------------------------------------------------------------- execution


def _execute_atomic(
    ctx: HarnessContext,
    pending: PendingProtectedAction,
    scope: list[ScopeItem],
    executor: ProtectedExecutor,
    *,
    decision_event_seq: int | None,
) -> GateOutcome:
    proposal = pending.proposal
    key = proposal.idempotency_key or f"{proposal.action_id}:{','.join(map(str, scope))}"
    record = ActionRecord(
        id=f"A-{proposal.action_id}",
        action=proposal.action,
        scope=list(scope),
        protected=True,
        idempotency_key=key,
        approval_event_seq=decision_event_seq,
        domain_authorization_ref=pending.domain_authorization_ref,
        runtime_confirmation_required=pending.confirmation.required,
        used_fallback_data=proposal.uses_fallback_data,
    )
    if key in ctx.problem.execution.executed_idempotency_keys():
        ctx.emit(EventType.DUPLICATE_MUTATION_PREVENTED, {"key": key, "gate": pending.gate_id},
                 importance=Importance.HIGH)
        _clear_pending(ctx)
        return GateOutcome(GateStatus.DUPLICATE_PREVENTED, gate_id=pending.gate_id,
                           reasons=[f"idempotency key {key} already executed"])
    result = executor.call(proposal.action, {"scope": [str(i) for i in scope], "idempotency_key": key})
    ctx.clock.advance(result.time_cost)
    read_back = executor.read_back(key)
    verified = read_back is not None and read_back.get("scope") == [str(i) for i in scope]
    if result.status is ResultStatus.ERROR:
        ctx.runtime.recovery.mutation_uncertainty = result.partial_side_effect_possible and not verified
        if not verified:
            ctx.emit(EventType.TOOL_FAILED, {"tool": executor.tool_id, "operation": proposal.action,
                                             "error_class": result.error_class, "read_back": False},
                     importance=Importance.HIGH)
            _clear_pending(ctx)
            return GateOutcome(GateStatus.EXECUTION_FAILED, gate_id=pending.gate_id,
                               reasons=[f"{result.error_class}; read-back did not confirm mutation"])
    record.read_back_verified = verified
    record.result = result.status.value
    ev = ctx.emit(EventType.PROTECTED_ACTION_EXECUTED,
                  {"gate": pending.gate_id, "action": proposal.action, "scope": [str(i) for i in scope],
                   "idempotency_key": key, "approval_event_seq": decision_event_seq,
                   "runtime_confirmation_required": pending.confirmation.required},
                  importance=Importance.HIGH)
    record.executed_event_seq = ev.seq
    ctx.emit(EventType.READ_BACK_VERIFIED, {"key": key, "verified": verified},
             importance=Importance.NORMAL if verified else Importance.CRITICAL)
    ctx.safe_point(SafePointKind.AFTER_VALIDATION)
    with ctx.commit(f"protected action executed {proposal.action_id}") as ps:
        ps.execution.actions.append(record)
    ctx.runtime.recovery.mutation_uncertainty = False
    _clear_pending(ctx)
    return GateOutcome(GateStatus.EXECUTED, gate_id=pending.gate_id, action_record=record)


# --------------------------------------------------------------------------- REQUEST_CONTEXT

_TOPIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "WHY": re.compile(r"why|왜|이유|필요", re.I),
    "WHY_HUMAN_NOW": re.compile(r"now|지금|again|또|다시|승인", re.I),
    "SCOPE": re.compile(r"scope|범위|같은", re.I),
    "AUTHORITY": re.compile(r"author|권한|누가|reference|approval ref", re.I),
    "CONSEQUENCE": re.compile(r"reject|않으면|안 하면|거절|consequence|어떻게 되", re.I),
    "EVIDENCE": re.compile(r"evidence|근거|증거|data|데이터", re.I),
    "ALTERNATIVES": re.compile(r"alternative|대안|다른 방법", re.I),
}


def _topics(text: str) -> list[str]:
    found = [t for t, p in _TOPIC_PATTERNS.items() if p.search(text)]
    return found or ["WHY"]


def request_context(
    ctx: HarnessContext,
    text: str,
    *,
    context_probe: Callable[[list[str]], Evidence | None] | None = None,
) -> ContextResponse:
    """REQUEST_CONTEXT ≠ APPROVE. Explain from committed state; never execute; same gate stays pending."""
    pending = ctx.runtime.pending_protected_action
    assert pending is not None
    pending.context_requests += 1
    ev = ctx.emit(EventType.HUMAN_CONTEXT_REQUESTED,
                  {"gate": pending.gate_id, "text": text, "n": pending.context_requests},
                  importance=Importance.HIGH)
    topics = _topics(text)
    fresh = [t for t in topics if t not in pending.answered_topics]
    if not fresh:  # repeated question: go one level deeper instead of repeating the same answer
        fresh = [t for t in ("EVIDENCE", "AUTHORITY", "SCOPE", "CONSEQUENCE", "ALTERNATIVES")
                 if t not in pending.answered_topics] or topics
    packet = project_packet(ctx.problem, ctx.runtime, pending)
    answers: dict[str, str | None] = {
        "WHY": packet.why or None,
        "WHY_HUMAN_NOW": packet.why_human_now or None,
        "SCOPE": f"requested {list(packet.requested_scope)} ⊆ authorized {list(packet.authorized_scope)}; "
                 f"delta {list(packet.scope_delta) or 'none'}",
        "AUTHORITY": packet.domain_authorization if packet.domain_authorization != "NONE" else None,
        "CONSEQUENCE": f"approve → {packet.consequence_if_approved}; reject → {packet.consequence_if_rejected}",
        "EVIDENCE": (", ".join(f"{e}: {ctx.problem.evidence[e].content}" for e in packet.key_evidence)
                     if packet.key_evidence else None),
        "ALTERNATIVES": "; ".join(packet.alternatives) or None,
    }
    lines: list[str] = []
    unresolved = list(packet.unresolved_items)
    for t in fresh:
        a = answers.get(t)
        if a:
            lines.append(f"{t}: {a}")
        else:
            unresolved.append(f"{t}: not explainable from committed evidence")
    insufficient = any(u.startswith(tuple(fresh)) for u in unresolved) or bool(packet.uncommitted_evidence)
    reprofiled: list[str] = []
    if insufficient:
        ctx.emit(EventType.APPROVAL_CONTEXT_INSUFFICIENT, {"gate": pending.gate_id, "unresolved": unresolved},
                 importance=Importance.HIGH)
        if context_probe is not None:
            # safe read-only targeted reprofile: adds evidence only; no protected write, no execution change
            new_ev = context_probe(fresh)
            if new_ev is not None:
                integrate_evidence(ctx, new_ev)
                reprofiled.append(new_ev.id)
                lines.append(f"REPROFILE: {new_ev.id}: {new_ev.content}")
    # authority/scope still valid? a revealed mismatch is CRITICAL — but still no execution
    reasons, _ = _precheck(ctx, pending.proposal, pending.proposal.requested_scope)
    if reasons:
        ctx.signal(SignalKind.REQUEST_CONTEXT_SCOPE_MISMATCH, "; ".join(reasons), event_seq=ev.seq)
        unresolved += reasons
    else:
        ctx.signal(SignalKind.REQUEST_CONTEXT, f"{pending.gate_id}: {text}", event_seq=ev.seq)
    pending.answered_topics.extend(t for t in fresh if t not in pending.answered_topics)
    explanation = "\n".join(lines) if lines else "no additional committed context available"
    ctx.emit(EventType.APPROVAL_PACKET_EMITTED, {"gate": pending.gate_id, "explanation": explanation,
                                                  "topics": fresh},
             importance=Importance.HIGH, refs=list(packet.key_evidence))
    return ContextResponse(
        gate_id=pending.gate_id,
        topics=fresh,
        explanation=explanation,
        evidence_refs=list(packet.key_evidence) + reprofiled,
        unresolved=unresolved,
        insufficient=insufficient,
        reprofiled_evidence=reprofiled,
    )

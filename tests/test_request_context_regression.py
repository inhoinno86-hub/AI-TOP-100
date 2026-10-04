"""REQUEST_CONTEXT targeted regression (Design Freeze §31, §38; kickoff §10).

Scenario: protected publish proposal → ApprovalPacket → Human: "왜 이걸 지금 승인해야 해?"

Pass criteria:
  WAITING_APPROVAL remains · protected action NOT executed · domain authorization unchanged ·
  canonical execution state unchanged · explanation uses committed Evidence ·
  safe read-only reprofile allowed if needed · same gate remains pending / resumes.
"""

from __future__ import annotations

import copy

from builders import tool_evidence
from test_phase_hi_supervision_gate import proposal, setup_gate

from aitop_harness.core.enums import ExecutionStatus, HumanDecisionKind
from aitop_harness.core.events import EventType
from aitop_harness.core.serialization import to_dict
from aitop_harness.phases.human_gate import GateStatus, HumanDecision, decide, interpret_human_input, propose_protected_action
from aitop_harness.phases.verify import run_verify

QUESTION = "왜 이걸 지금 승인해야 해?"


def _snapshot(ctx):
    return {
        "auth": to_dict(ctx.problem.domain_authorizations),
        "execution": to_dict(ctx.problem.execution),
        "pending": copy.deepcopy(to_dict(ctx.runtime.pending_protected_action)),
        "status": ctx.runtime.execution_status,
        "phase": ctx.runtime.phase,
    }


def test_request_context_keeps_gate_pending_and_executes_nothing():
    ctx, executor = setup_gate()
    gate = propose_protected_action(ctx, proposal(), executor)
    assert gate.status is GateStatus.WAITING_APPROVAL
    before = _snapshot(ctx)

    kind = interpret_human_input(QUESTION)
    assert kind is HumanDecisionKind.REQUEST_CONTEXT  # a question is never approval intent
    out = decide(ctx, HumanDecision(kind, QUESTION), executor)
    after = _snapshot(ctx)

    # WAITING_APPROVAL remains, same gate pending
    assert out.status is GateStatus.WAITING_APPROVAL
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL
    assert out.gate_id == gate.gate_id == ctx.runtime.pending_protected_action.gate_id
    # protected action NOT executed
    assert executor.calls == []
    assert not ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED, EventType.APPROVAL_GRANTED)
    # domain authorization unchanged
    assert after["auth"] == before["auth"]
    # canonical execution state unchanged (only the context counter / answered topics move)
    assert after["execution"] == before["execution"]
    assert after["status"] == before["status"] and after["phase"] == before["phase"]
    for k in ("gate_id", "proposal", "confirmation", "domain_authorization_ref", "safe_point_seq"):
        assert after["pending"][k] == before["pending"][k], k
    assert ctx.runtime.pending_protected_action.confirmation.decision is None
    # explanation from committed evidence; WHY + WHY_HUMAN_NOW answered
    assert "WHY:" in out.explanation and "WHY_HUMAN_NOW:" in out.explanation
    ctx_event = ctx.events.last(EventType.HUMAN_CONTEXT_REQUESTED)
    assert ctx_event is not None and ctx_event.importance.value == "HIGH"
    explain_event = ctx.events.last(EventType.APPROVAL_PACKET_EMITTED)
    assert set(explain_event.refs) <= set(ctx.problem.evidence)
    assert any("REQUEST_CONTEXT" in s for s in ctx.supervision.live_summary)


def test_repeated_request_context_goes_deeper_and_never_approves():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    first = decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, QUESTION), executor)
    second = decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, QUESTION), executor)
    assert first.explanation != second.explanation  # does not repeat the same answer
    assert "EVIDENCE:" in second.explanation and "E-reg" in second.explanation
    assert ctx.runtime.pending_protected_action.context_requests == 2
    assert executor.calls == []


def test_insufficient_context_triggers_safe_read_only_reprofile_without_execution():
    ctx, executor = setup_gate()
    p = proposal(key_evidence=["E-reg", "E-not-yet-collected"])
    propose_protected_action(ctx, p, executor)
    exec_before = to_dict(ctx.problem.execution)
    auth_before = to_dict(ctx.problem.domain_authorizations)
    probed: list[list[str]] = []

    def probe(topics):
        probed.append(topics)
        return tool_evidence("E-not-yet-collected", "read-only lookup: partner confirmed CM-1/CM-2 effective today")

    out = decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, "근거 데이터가 뭐야?"), executor,
                 context_probe=probe)
    assert probed, "targeted read-only reprofile should run when context is insufficient"
    assert ctx.events.last(EventType.APPROVAL_CONTEXT_INSUFFICIENT) is not None
    assert "E-not-yet-collected" in ctx.problem.evidence  # evidence added, read-only
    assert "REPROFILE" in out.explanation
    assert executor.calls == []
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL
    assert to_dict(ctx.problem.execution) == exec_before
    assert to_dict(ctx.problem.domain_authorizations) == auth_before


def test_same_gate_resumes_after_context_and_verify_trace_is_clean():
    ctx, executor = setup_gate()
    gate = propose_protected_action(ctx, proposal(), executor)
    decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, QUESTION), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE, "approve"), executor)
    assert out.status is GateStatus.EXECUTED and out.gate_id == gate.gate_id
    assert executor.count("publish_mapping") == 1
    approval = ctx.events.get(out.action_record.approval_event_seq)
    assert approval.type is EventType.APPROVAL_GRANTED  # not the context request
    context_seq = ctx.events.last(EventType.HUMAN_CONTEXT_REQUESTED).seq
    assert context_seq < approval.seq
    report = run_verify(ctx, out.action_record.scope)
    assert report.check("request_context_not_approval").status.value == "PASS"
    assert report.check("approval_trace").status.value == "PASS"


def test_request_context_revealing_scope_mismatch_is_critical_and_still_blocks():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    with ctx.commit("authorization narrowed by owner") as ps:
        from aitop_harness.core.scope import Scope
        ps.domain_authorizations["DA-pub"].authorized_scope = Scope.of(("publish_mapping", "CM-1"))
    decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, "이 범위가 원래 승인된 범위와 같은가?"), executor)
    assert any("[CRITICAL] REQUEST_CONTEXT_SCOPE_MISMATCH" in s for s in ctx.supervision.live_summary)
    assert executor.calls == []
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL
    # and APPROVE cannot bypass the mismatch
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert out.status is GateStatus.BLOCKED and executor.calls == []

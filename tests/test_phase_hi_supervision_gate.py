"""PHASE H — Human Supervision; PHASE I — Safe Point + Mandatory Human Gate."""

from __future__ import annotations

import pytest
from builders import grant, make_ctx, mutation_ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.enums import (
    EmissionChannel,
    ExecutionStatus,
    HumanDecisionKind,
    Importance,
    Phase,
    ProtectedActionCategory,
    RequiredBefore,
    Reversibility,
    SafePointKind,
    TransitionKind,
)
from aitop_harness.core.errors import IllegalTransitionError, ProtectedActionBlocked
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.verification import VerificationObligation
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.discover import integrate_evidence
from aitop_harness.phases.human_gate import (
    GateStatus,
    HumanDecision,
    decide,
    interpret_human_input,
    propose_protected_action,
)
from aitop_harness.state.runtime import ProtectedActionProposal
from aitop_harness.supervision import monitoring
from aitop_harness.supervision.monitoring import NEVER_THROTTLE, SignalKind
from aitop_harness.tools.simulated import ScriptedTool

S = ScopeItem
REQ = [S("publish_mapping", "CM-1"), S("publish_mapping", "CM-2")]


# --------------------------------------------------------------------------- monitoring


def test_never_throttle_signals_are_immediate_even_if_marked_low():
    ctx = make_ctx()
    for kind in NEVER_THROTTLE:
        sig = monitoring.route(ctx.supervision, kind, "x", importance=Importance.LOW)
        assert sig.channel is EmissionChannel.IMMEDIATE and not sig.throttled
    required = {"STRATEGY_CHANGING_FAILURE", "PROBLEM_INVALIDATED", "DEFINE_GATE_RESULT", "RELEASE_BLOCKING_VOB",
                "RELEASE_RESERVE_ENTERED", "PACKAGING_AT_RISK", "SUBMISSION_AT_RISK", "MANDATORY_HUMAN_GATE",
                "AUTHORITY_VIOLATION", "PRIVACY_VIOLATION", "SAFETY_VIOLATION", "RELEASE_GATE_RESULT"}
    assert required <= {k.value for k in NEVER_THROTTLE}


def test_retry_noise_is_digested_and_aggregated():
    ctx = make_ctx()
    for i in range(5):
        monitoring.route(ctx.supervision, SignalKind.RETRY_DETAIL, f"retry {i}")
    monitoring.route(ctx.supervision, SignalKind.ROUTINE_VALIDATION_SUCCESS, "ok")
    assert ctx.supervision.live_summary == []
    lines = monitoring.flush_digest(ctx.supervision)
    assert "RETRY_DETAIL: retry detail (x5)" in lines and ctx.supervision.pending_digest == []


def test_importance_channels():
    assert monitoring.classify(SignalKind.STATE_DIFF) == (Importance.NORMAL, EmissionChannel.DIGEST)
    assert monitoring.classify(SignalKind.AUDIT) == (Importance.LOW, EmissionChannel.AUDIT)
    assert monitoring.classify(SignalKind.REQUEST_CONTEXT)[0] is Importance.HIGH
    assert monitoring.classify(SignalKind.REQUEST_CONTEXT_SCOPE_MISMATCH)[0] is Importance.CRITICAL


# --------------------------------------------------------------------------- human gate


def setup_gate(*, authorized: Scope | None = None, grant_auth: bool = True):
    ctx = make_ctx()
    seed_org(ctx)
    seed_success(ctx)
    integrate_evidence(ctx, tool_evidence("E-reg", "registry confirms CM-1, CM-2"))
    integrate_evidence(ctx, tool_evidence("E-policy", "policy P-7: owner may publish location mappings"))
    define_problem(ctx, problem(["E-reg"], intended=REQ, protected=["publish_mapping"]))
    if grant_auth:
        grant(ctx, "DA-pub", "publish_mapping", "registry",
              authorized or Scope.of(("publish_mapping", "*")), "E-policy")
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    ctx.runtime.phase = Phase.EXECUTE
    executor = ScriptedTool("registry", read_only=False, script={"publish_mapping": [mutation_ok()]})
    return ctx, executor


def proposal(scope=None, **kw) -> ProtectedActionProposal:
    fields = dict(
        action_id="PUB-1", action="publish_mapping", subject="location mappings", protected_resource="registry",
        requested_scope=list(scope or REQ), category=ProtectedActionCategory.SUBMISSION_PUBLISH,
        why="downstream rejects stop once mappings are published", side_effect="partner registry updated",
        reversibility=Reversibility.PARTIALLY_REVERSIBLE, alternatives=["manual publish by owner"],
        idempotency_key="pub-CM-1-2", key_evidence=["E-reg"],
    )
    fields.update(kw)
    return ProtectedActionProposal(**fields)


def test_gate_flow_order_and_waiting_approval_blocks_execution():
    ctx, executor = setup_gate()
    out = propose_protected_action(ctx, proposal(), executor)
    assert out.status is GateStatus.WAITING_APPROVAL
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL
    assert executor.calls == []  # nothing executed before the gate
    types = [e.type for e in ctx.events]
    order = [EventType.PROTECTED_ACTION_PROPOSED, EventType.STATE_COMMITTED, EventType.SAFE_POINT_REACHED,
             EventType.RUNTIME_CONFIRMATION_REQUESTED, EventType.APPROVAL_PACKET_EMITTED]
    idx = [len(types) - 1 - types[::-1].index(t) for t in order]
    assert idx == sorted(idx)
    assert ctx.runtime.pending_protected_action.safe_point_seq is not None
    assert ctx.supervision.intervention.required
    # packet is a projection containing the frozen minimum fields
    p = out.packet
    assert p is not None and p.scope_delta == () and p.key_evidence == ("E-reg",)
    assert "WHY HUMAN NOW" in p.render() and "OPEN VOB + BLOCKING_SCOPE" in p.render()
    # no transitions while waiting
    with pytest.raises(IllegalTransitionError):
        PhaseController(ctx).advance()


def test_approve_rechecks_and_executes_atomically_with_read_back():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert out.status is GateStatus.EXECUTED
    assert executor.count("publish_mapping") == 1
    rec = ctx.problem.execution.actions[-1]
    assert rec.read_back_verified and rec.approval_event_seq is not None
    assert ctx.events.get(rec.approval_event_seq).type is EventType.APPROVAL_GRANTED
    assert ctx.runtime.execution_status is ExecutionStatus.RUNNING
    assert ctx.runtime.pending_protected_action is None


def test_duplicate_mutation_prevented():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    propose_protected_action(ctx, proposal(), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert out.status is GateStatus.DUPLICATE_PREVENTED
    assert executor.count("publish_mapping") == 1


def test_missing_domain_authorization_blocks_and_approve_cannot_repair():
    ctx, executor = setup_gate(grant_auth=False)
    out = propose_protected_action(ctx, proposal(), executor)
    assert out.status is GateStatus.BLOCKED
    assert ctx.runtime.execution_status is not ExecutionStatus.WAITING_APPROVAL
    assert any("AUTHORITY_VIOLATION" in s for s in ctx.supervision.live_summary)
    with pytest.raises(ProtectedActionBlocked):
        decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert executor.calls == []


def test_authorization_revoked_while_waiting_blocks_approve():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    with ctx.commit("revoke") as ps:
        from aitop_harness.core.enums import AuthorizationStatus
        ps.domain_authorizations["DA-pub"].status = AuthorizationStatus.REVOKED
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert out.status is GateStatus.BLOCKED and executor.calls == []


def test_scope_exceeding_authorization_is_blocked():
    ctx, executor = setup_gate(authorized=Scope.of(("publish_mapping", "CM-1")))
    out = propose_protected_action(ctx, proposal(), executor)
    assert out.status is GateStatus.BLOCKED and "SCOPE" in out.reasons[0]


def test_vob_required_before_protected_action_blocks_only_its_scope():
    ctx, executor = setup_gate()
    with ctx.commit("vob") as ps:
        ps.verification_obligations["VOB-1"] = VerificationObligation(
            "VOB-1", "CM-2 identity", Phase.DEFINE, validation_method="owner",
            required_before=RequiredBefore.BEFORE_PROTECTED_ACTION, blocking_scope=Scope.of(("publish_mapping", "CM-2")))
    assert propose_protected_action(ctx, proposal(), executor).status is GateStatus.BLOCKED
    out = propose_protected_action(ctx, proposal([S("publish_mapping", "CM-1")]), executor)
    assert out.status is GateStatus.WAITING_APPROVAL


def test_modify_narrower_scope_executes_only_modified_action():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.MODIFY, modified_scope=[S("publish_mapping", "CM-1")]),
                 executor)
    assert out.status is GateStatus.EXECUTED
    assert executor.calls[-1][1]["scope"] == ["publish_mapping:CM-1"]
    assert ctx.events.get(out.action_record.approval_event_seq).type is EventType.HUMAN_OVERRIDE_RECEIVED


def test_modify_beyond_authorized_scope_blocks():
    ctx, executor = setup_gate(authorized=Scope.of(("publish_mapping", "CM-1"), ("publish_mapping", "CM-2")))
    propose_protected_action(ctx, proposal(), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.MODIFY, modified_scope=[S("publish_mapping", "CM-9")]),
                 executor)
    assert out.status is GateStatus.BLOCKED and executor.calls == []
    assert ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL  # still pending, nothing executed


def test_reject_does_not_execute_and_replans():
    ctx, executor = setup_gate()
    propose_protected_action(ctx, proposal(), executor)
    out = decide(ctx, HumanDecision(HumanDecisionKind.REJECT, "not today"), executor)
    assert out.status is GateStatus.REJECTED and executor.calls == []
    assert ctx.runtime.transition_candidate.kind is TransitionKind.REPLAN
    assert ctx.problem.execution.actions == []


def test_protected_action_without_runtime_confirmation_still_has_safe_point():
    ctx, executor = setup_gate()
    p = proposal(category=ProtectedActionCategory.NONE)
    out = propose_protected_action(ctx, p, executor)
    assert out.status is GateStatus.EXECUTED
    assert any(e.type is EventType.SAFE_POINT_REACHED and e.payload.get("kind") == SafePointKind.BEFORE_PROTECTED_ACTION
               for e in ctx.events)


def test_interpret_human_input_never_defaults_to_approval():
    assert interpret_human_input("왜 이걸 지금 승인해야 해?") is HumanDecisionKind.REQUEST_CONTEXT
    assert interpret_human_input("what happens if I reject?") is HumanDecisionKind.REQUEST_CONTEXT
    assert interpret_human_input("hmm") is HumanDecisionKind.REQUEST_CONTEXT
    assert interpret_human_input("승인합니다") is HumanDecisionKind.APPROVE
    assert interpret_human_input("approve") is HumanDecisionKind.APPROVE
    assert interpret_human_input("reject") is HumanDecisionKind.REJECT

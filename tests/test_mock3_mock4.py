"""Mock regressions #3 and #4.

Mock #3 — Hidden Critical Constraint:
  critical constraint · authority · protected action block · Mandatory Human Gate · safe resume
Mock #4 — Cross-organization Handoff:
  ProcessHandoff · delivery vs semantic validity · CanonicalMapping · duplicate vs status progression ·
  blocking_scope · Human Gate
"""

from __future__ import annotations

from builders import make_ctx, mutation_ok, problem, seed_org, seed_success, tool_evidence

from aitop_harness.core.enums import (
    AckLayer,
    AckStatus,
    AgentRole,
    AuthorizationStatus,
    ConstraintStatus,
    ConstraintType,
    Criticality,
    DataIssueType,
    DefineGateResult,
    ExecutionStatus,
    HumanDecisionKind,
    MappingConfidence,
    Phase,
    ProtectedActionCategory,
    ReleaseDecision,
    RequiredBefore,
    Reversibility,
    SemanticValidity,
    WorkClass,
)
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.authority import Constraint, DomainAuthorization
from aitop_harness.domain.design import StructuralRemedyCandidate, WorkItem
from aitop_harness.domain.organization import Acknowledgment, ProcessHandoff
from aitop_harness.domain.verification import VerificationObligation
from aitop_harness.engine.controller import PhaseController
from aitop_harness.phases.budget import set_plan
from aitop_harness.phases.data_inspection import inspect_records
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.design import DesignInputs, classify_roles, design_solution
from aitop_harness.phases.discover import integrate_evidence, record_claim
from aitop_harness.phases.handoff import record_acknowledgment
from aitop_harness.phases.human_gate import (
    GateStatus,
    HumanDecision,
    decide,
    interpret_human_input,
    propose_protected_action,
)
from aitop_harness.phases.identity import propose_mapping
from aitop_harness.phases.release import evaluate_release_gate
from aitop_harness.phases.verify import run_verify
from aitop_harness.state.runtime import Plan, ProtectedActionProposal
from aitop_harness.tools.base import ToolRegistry, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool

S = ScopeItem


def test_mock3_hidden_critical_constraint():
    ctx = make_ctx("MOCK-3", "let the agent auto-create temporary access credentials")
    seed_org(ctx)
    seed_success(ctx)
    # requester asks; tool can technically write; "we always did it this way"
    record_claim(ctx, "CL-REQ", "SH-REQ", "agent should create credentials", is_initial_request=True)
    record_claim(
        ctx,
        "CL-PRACTICE",
        "SH-REQ",
        "helpdesk always issues them directly",
        assertion="credential.policy",
        value="helpdesk_may_issue",
    )
    iam = ScriptedTool("iam", read_only=False, script={"create_temp_credential": [mutation_ok()]})
    reg = ToolRegistry()
    reg.register(iam, ToolSpec("iam", "iam", read_only=False))  # Available Tool ≠ Authorized Action
    assert ctx.problem.stakeholders["SH-REQ"].authority_scope == []  # Request ≠ Authority

    scope = [S("create_temp_credential", "contractor-17")]
    integrate_evidence(ctx, tool_evidence("E-tickets", "38 credential tickets/week, 4h wait"))
    with ctx.commit("suspected constraint") as ps:
        ps.constraints["K-SEC"] = Constraint(
            "K-SEC",
            ConstraintType.AUTHORITY,
            "restricted credential issuance",
            protected_action="create_temp_credential",
            status=ConstraintStatus.SUSPECTED,
            criticality=Criticality.CRITICAL,
        )
    define_problem(ctx, problem(["E-tickets"], intended=scope, protected=["create_temp_credential"]))
    gate = evaluate_define_gate(ctx)
    assert gate.result is DefineGateResult.FAIL  # authority owner + approval requirement unknown
    assert {"authority"} <= {f.check for f in gate.blocking()}

    # before authority is known, the protected action is blocked outright
    early = ProtectedActionProposal(
        "CRED-1",
        "create_temp_credential",
        "contractor-17",
        "iam",
        scope,
        ProtectedActionCategory.PROTECTED_MUTATION,
        why="unblock contractor",
        reversibility=Reversibility.REVERSIBLE,
        idempotency_key="cred-17",
        key_evidence=["E-tickets"],
    )
    assert propose_protected_action(ctx, early, iam).status is GateStatus.BLOCKED
    assert iam.calls == []

    # targeted reprofile finds the real approver in the policy; existing practice ≠ approved policy
    ctx.runtime.phase = Phase.DEFINE
    PhaseController(ctx).reprofile(["credential approver"], "authority owner unknown")
    integrate_evidence(
        ctx,
        tool_evidence(
            "E-policy",
            "SEC-12: security lead approves temp credentials; runtime confirmation per issuance",
            assertion="credential.policy",
            value="security_lead_only",
        ),
    )
    assert any(c.assertion == "credential.policy" for c in ctx.problem.conflicts.values())
    with ctx.commit("policy known") as ps:
        ps.constraints["K-SEC"].status = ConstraintStatus.ACTIVE
        ps.constraints["K-SEC"].approval_required = True
        ps.constraints["K-SEC"].evidence_refs = ["E-policy"]
        ps.domain_authorizations["DA-CRED"] = DomainAuthorization(
            "DA-CRED",
            "create_temp_credential",
            "iam",
            authority_holder="security-lead",
            authorized_scope=Scope.of(
                ("create_temp_credential", "contractor-*"), ("create_temp_credential", "contractor-17")
            ),
            evidence_refs=["E-policy"],
            status=AuthorizationStatus.GRANTED,
        )
    gate = evaluate_define_gate(ctx)
    assert gate.result is not DefineGateResult.FAIL, [f.message for f in gate.findings]
    apply_define_gate(ctx, gate)

    # agent role shrinks once structural integration exists
    sd = design_solution(
        ctx,
        DesignInputs(
            structural_remedies=[
                StructuralRemedyCandidate("SR-wf", "approval workflow integration", True, True)
            ],
            deterministic_rules_cover_cases=True,
            llm_reasoning_adds_value=True,
            release_scope=scope,
        ),
    )
    assert sd.agent_roles == [AgentRole.CONTROL_DETECTION, AgentRole.EXCEPTION_HANDLER]
    assert classify_roles(DesignInputs([], True, True), True, False)[0] is AgentRole.BRIDGE  # initial bridge

    # Mandatory Human Gate even though domain authorization exists
    ctx.runtime.phase = Phase.EXECUTE
    out = propose_protected_action(ctx, early, iam)
    assert out.status is GateStatus.WAITING_APPROVAL and iam.calls == []
    assert "security-lead" in out.packet.domain_authorization
    # Human asks first (Mock #3 observation), then approves — safe resume of the same gate
    q = "이 승인 reference는 무엇이고 왜 내가 또 승인해야 하나?"
    assert interpret_human_input(q) is HumanDecisionKind.REQUEST_CONTEXT
    decide(ctx, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, q), iam)
    assert iam.calls == [] and ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL
    done = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE, "approve"), iam)
    assert done.status is GateStatus.EXECUTED and iam.count("create_temp_credential") == 1
    assert ctx.runtime.execution_status is ExecutionStatus.RUNNING


def test_mock4_cross_org_handoff():
    ctx = make_ctx("MOCK-4", "AI auto-fixes downstream rejects and resubmits")
    seed_org(ctx)
    seed_success(ctx)
    # transport accepted ≠ business accepted
    with ctx.commit("handoff") as ps:
        ps.process_handoffs["H-SHIP"] = ProcessHandoff("H-SHIP", from_org="ORG-A", to_org="ORG-B")
    record_acknowledgment(ctx, "H-SHIP", Acknowledgment(AckLayer.TRANSPORT, "HTTP 200", AckStatus.ACCEPTED))
    record_acknowledgment(
        ctx, "H-SHIP", Acknowledgment(AckLayer.BUSINESS_ACCEPTANCE, "rows rejected", AckStatus.REJECTED)
    )
    h = ctx.problem.process_handoffs["H-SHIP"]
    assert h.delivery_status.value == "HEALTHY" and h.semantic_validity is SemanticValidity.BROKEN

    # same request_id ≠ exact duplicate
    rows = [
        {"request_id": "R1", "status": "CREATED", "v": 1},
        {"request_id": "R1", "status": "CANCELLED", "v": 1},
        {"request_id": "R2", "status": "CREATED", "v": 1},
        {"request_id": "R2", "status": "CREATED", "v": 2},
    ]
    rep = inspect_records(
        rows, key_fields=["request_id"], status_field="status", version_field="v", expected_count=4
    )
    assert (
        DataIssueType.STATUS_PROGRESSION in rep.issue_types()
        and DataIssueType.EVENT_VERSION in rep.issue_types()
    )
    assert DataIssueType.EXACT_RECORD_DUPLICATE not in rep.issue_types()

    # 51 high-confidence mappings from the registry; 6 ambiguous stay UNRESOLVED
    integrate_evidence(ctx, tool_evidence("E-reg", "location registry v7"))
    for i in range(1, 52):
        propose_mapping(
            ctx,
            f"CM-{i}",
            entity_type="location",
            source_namespace="A.loc",
            source_identifiers={"site": f"S{i}", "dock": "1"},
            target_namespace="B.loc",
            candidate_targets=[{"loc": f"B-{i}"}],
            basis=["REGISTRY_LOOKUP"],
            claimed_confidence=MappingConfidence.HIGH,
            authority="registry v7",
            derived_from=["E-reg"],
        )
    for i in range(52, 58):
        propose_mapping(
            ctx,
            f"CM-{i}",
            entity_type="location",
            source_namespace="A.loc",
            source_identifiers={"site": f"S{i}"},
            target_namespace="B.loc",
            candidate_targets=[{"loc": f"B-{i}a"}, {"loc": f"B-{i}b"}],
            basis=["TEXTUAL_EQUALITY"],
            claimed_confidence=MappingConfidence.MEDIUM,
            authority=None,
            derived_from=["E-reg"],
        )
    resolved = [m for m in ctx.problem.canonical_mappings.values() if m.confidence is MappingConfidence.HIGH]
    unresolved = [
        m.id for m in ctx.problem.canonical_mappings.values() if m.confidence is MappingConfidence.UNRESOLVED
    ]
    assert len(resolved) == 51 and len(unresolved) == 6

    publish_scope = [S("publish_mapping", m.id) for m in resolved]
    with ctx.commit("authority + VOB") as ps:
        ps.domain_authorizations["DA-PUB"] = DomainAuthorization(
            "DA-PUB",
            "publish_mapping",
            "partner-registry",
            authority_holder="interface owner",
            authorized_scope=Scope.of(("publish_mapping", "*")),
            evidence_refs=["E-reg"],
            status=AuthorizationStatus.GRANTED,
        )
        ps.verification_obligations["VOB-17"] = VerificationObligation(
            "VOB-17",
            "6 ambiguous locations",
            Phase.DEFINE,
            validation_method="owner confirmation",
            required_before=RequiredBefore.BEFORE_PROTECTED_ACTION,
            blocking_scope=Scope([S("publish_mapping", m) for m in unresolved]),
        )
    define_problem(
        ctx,
        problem(
            ["E-reg"],
            intended=publish_scope,
            protected=["publish_mapping"],
            depends_on_mappings=[m.id for m in resolved],
        ),
    )
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    sd = design_solution(
        ctx,
        DesignInputs(
            structural_remedies=[
                StructuralRemedyCandidate("SR-c", "versioned identity/event contract", True, False)
            ],
            deterministic_rules_cover_cases=True,
            llm_reasoning_adds_value=True,
            bridge_sunset_condition="contract v2 adopted by partner",
            release_scope=publish_scope,
            minimum_useful_scope=publish_scope,
        ),
    )
    assert set(sd.agent_roles) == {AgentRole.BRIDGE, AgentRole.CONTROL_DETECTION, AgentRole.EXCEPTION_HANDLER}

    # protected publish of the 51 passes the gate; adding an unresolved one is blocked by blocking_scope
    ctx.runtime.phase = Phase.EXECUTE
    registry = ScriptedTool("partner-registry", read_only=False, script={"publish_mapping": [mutation_ok()]})
    bad = ProtectedActionProposal(
        "PUB-X",
        "publish_mapping",
        "locations",
        "partner-registry",
        publish_scope + [S("publish_mapping", unresolved[0])],
        ProtectedActionCategory.SUBMISSION_PUBLISH,
        idempotency_key="pub-x",
    )
    assert propose_protected_action(ctx, bad, registry).status is GateStatus.BLOCKED
    good = ProtectedActionProposal(
        "PUB-51",
        "publish_mapping",
        "locations",
        "partner-registry",
        publish_scope,
        ProtectedActionCategory.SUBMISSION_PUBLISH,
        why="stop rejects",
        idempotency_key="pub-51",
        key_evidence=["E-reg"],
    )
    assert propose_protected_action(ctx, good, registry).status is GateStatus.WAITING_APPROVAL
    assert decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), registry).status is GateStatus.EXECUTED

    # release: VOB-17 open but outside release scope → partial safe release, not global HOLD
    set_plan(
        ctx,
        Plan(
            "P",
            work_items=[
                WorkItem(
                    "W", "publish verified mappings", WorkClass.CORE_FEATURE, 10, publish_scope, True, True
                )
            ],
        ),
    )
    ctx.runtime.phase = Phase.VERIFY
    report = run_verify(ctx, publish_scope)
    assert report.layer1_passed, [c.name for c in report.failed()]
    res = evaluate_release_gate(ctx, report)
    assert res.decision is ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION
    assert any("VOB-17" in limit for limit in res.known_limitations)

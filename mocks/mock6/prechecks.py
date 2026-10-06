"""PRECHECK B (frozen-core smoke) + PRECHECK C (REQUEST_CONTEXT targeted regression) against the real Harness.

PRECHECK C uses a fresh, domain-agnostic scenario (public library policy notice publish), a fake
protected executor (no production side effect) and the Harness's own Human Gate interface.
Usage: python3 mocks/mock6/prechecks.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

from aitop_harness.core.enums import (  # noqa: E402
    AuthorizationStatus,
    ConstraintType,
    EvidenceSourceType,
    ExecutionStatus,
    HumanDecisionKind,
    MetricType,
    Phase,
    ProtectedActionCategory,
    ResultStatus,
    Reversibility,
    SourceAuthority,
)
from aitop_harness.core.errors import ProtectedActionBlocked  # noqa: E402
from aitop_harness.core.events import EventLog, EventType  # noqa: E402
from aitop_harness.core.provenance import Provenance  # noqa: E402
from aitop_harness.core.scope import Scope, ScopeItem  # noqa: E402
from aitop_harness.core.serialization import to_dict  # noqa: E402
from aitop_harness.domain.authority import Constraint, DomainAuthorization  # noqa: E402
from aitop_harness.domain.design import ProblemDefinition  # noqa: E402
from aitop_harness.domain.epistemic import Evidence, SuccessCriterion  # noqa: E402
from aitop_harness.domain.metric import Metric  # noqa: E402
from aitop_harness.domain.organization import Organization, Stakeholder  # noqa: E402
from aitop_harness.engine.context import CANONICAL_STATES, HarnessContext  # noqa: E402
from aitop_harness.phases.budget import update_budget  # noqa: E402
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate  # noqa: E402
from aitop_harness.phases.discover import integrate_evidence, revise_evidence  # noqa: E402
from aitop_harness.phases.execute import evidence_from_outcome, invoke_tool  # noqa: E402
from aitop_harness.phases.human_gate import (  # noqa: E402
    HumanDecision,
    decide,
    interpret_human_input,
    propose_protected_action,
)
from aitop_harness.phases.verify import run_verify  # noqa: E402
from aitop_harness.state.problem import ProblemState, Scenario  # noqa: E402
from aitop_harness.state.runtime import ProtectedActionProposal, RuntimeState  # noqa: E402
from aitop_harness.state.supervision import SupervisionState  # noqa: E402
from aitop_harness.tools.base import ToolRegistry, ToolResult, ToolSpec  # noqa: E402
from aitop_harness.tools.simulated import ScriptedTool  # noqa: E402

S = ScopeItem
AUTH = SourceAuthority.AUTHORITATIVE


def ev(eid: str, content: str, source: str = "catalog-db", st: EvidenceSourceType = EvidenceSourceType.TOOL,
       **kw: Any) -> Evidence:
    return Evidence(eid, st, source, Provenance(st, source, method="query"), content, authority=AUTH, **kw)


def check(results: list[dict[str, Any]], name: str, ok: bool, detail: Any = "") -> None:
    results.append({"check": name, "pass": bool(ok), "detail": detail})
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail and not ok else ""))


# =========================================================================== PRECHECK B


def precheck_b() -> list[dict[str, Any]]:
    print("PRECHECK B — frozen core smoke")
    r: list[dict[str, Any]] = []
    ctx = HarnessContext(problem=ProblemState(scenario=Scenario(id="SMOKE")))
    update_budget(ctx)
    check(r, "three canonical states exist", CANONICAL_STATES == ("problem", "runtime", "supervision")
          and isinstance(ctx.problem, ProblemState) and isinstance(ctx.runtime, RuntimeState)
          and isinstance(ctx.supervision, SupervisionState))
    check(r, "no 4th canonical state (recovery inside RuntimeState)", hasattr(ctx.runtime, "recovery")
          and not hasattr(ctx, "recovery"))
    check(r, "event log append-only (no update/delete API)",
          not any(hasattr(EventLog, m) for m in ("update", "delete", "remove", "pop", "__setitem__", "__delitem__")))
    with ctx.commit("smoke evidence") as ps:
        ps.organizations["O"] = Organization("O", "Org")
    integrate_evidence(ctx, ev("E-1", "observation A", target_assertion="x", value=1))
    diff = ctx.supervision.state_diff
    check(r, "state diff after commit (change-centric)", diff is not None and any(
        e.collection == "evidence" and e.item_id == "E-1" for e in diff.entries) and len(diff.entries) < 5,
        [(e.kind.value, e.collection, e.item_id) for e in diff.entries] if diff else None)
    check(r, "provenance recorded", ctx.problem.evidence["E-1"].provenance.source_id == "catalog-db")
    integrate_evidence(ctx, ev("E-2", "observation B", source="other-db", target_assertion="x", value=2))
    revise_evidence(ctx, "E-1", "E-2", "A was a partial count")
    e1 = ctx.problem.evidence["E-1"]
    check(r, "evidence append preserves history (content + revision trail)",
          e1.content == "observation A" and e1.interpretation_history and "E-1" in ctx.problem.evidence
          and len(ctx.problem.evidence_revisions) == 1)
    pd = ProblemDefinition("PD-S", 1, root_problem="r", evidence_refs=["E-2"])
    define_problem(ctx, pd)
    check(r, "canonical problem representation (id/version/status)",
          (pd.id, pd.version, pd.status.value) == ("PD-S", 1, "DRAFT"))
    from aitop_harness.engine.controller import PhaseController
    PhaseController(ctx).advance()
    t = ctx.events.last(EventType.PHASE_TRANSITION)
    check(r, "transition event representation (kind/from/to)", t is not None and t.payload["kind"] == "ADVANCE"
          and t.payload["to"] == "DEFINE")
    snap = ctx.snapshot()
    restored = HarnessContext.restore(snap)
    check(r, "snapshot/restore roundtrip of 3 states", restored.snapshot() == snap)
    check(r, "event log persisted with snapshot", "events" in snap,
          "known limitation: Event Log is in-memory only (IMPLEMENTATION_DECISIONS §3)")
    return r


# =========================================================================== PRECHECK C


class FakePublisher(ScriptedTool):
    pass


def library_ctx() -> tuple[HarnessContext, FakePublisher, ToolRegistry]:
    ctx = HarnessContext(problem=ProblemState(scenario=Scenario(
        id="RC-LIBRARY", initial_request="Publish the revised late-fee policy notice on the public website")))
    update_budget(ctx)
    with ctx.commit("library org") as ps:
        ps.organizations["ORG-LIB"] = Organization("ORG-LIB", "Riverbend Public Library")
        ps.stakeholders["SH-DIR"] = Stakeholder("SH-DIR", "ORG-LIB", "Library Director",
                                                authority_scope=["publish_policy_notice"])
        ps.stakeholders["SH-WEB"] = Stakeholder("SH-WEB", "ORG-LIB", "Web coordinator")
        ps.metrics["M-ACC"] = Metric("M-ACC", "notice matches board-approved text", MetricType.RATE,
                                     numerator="matching clauses", denominator="clauses")
        ps.metrics["M-ACC"].promote(owner="ORG-LIB", target_value=1.0)
        ps.success_criteria["SC-ACC"] = SuccessCriterion("SC-ACC", "published text == board text", "M-ACC",
                                                         "1.0", "diff against board minute")
        ps.constraints["K-PUB"] = Constraint("K-PUB", ConstraintType
                                             .HUMAN_APPROVAL, "public notices need confirmation",
                                             protected_action="publish_policy_notice", approval_required=True,
                                             runtime_confirmation_required=True)
    integrate_evidence(ctx, ev("E-BOARD", "Board minute 2026-09-18: late fees abolished from 2026-10-15; director "
                                          "authorized to publish the notice", "board-minutes", EvidenceSourceType.DOCUMENT))
    integrate_evidence(ctx, ev("E-DRAFT", "Notice draft v3 matches board minute text (diff clean)", "cms-drafts"))
    with ctx.commit("authorization") as ps:
        ps.domain_authorizations["DA-PUB"] = DomainAuthorization(
            "DA-PUB", "publish_policy_notice", "public-website", "ORG-LIB", "SH-DIR",
            Scope.of(("publish_policy_notice", "late-fee-notice")), evidence_refs=["E-BOARD"],
            status=AuthorizationStatus.GRANTED)
    define_problem(ctx, ProblemDefinition(
        "PD-RC", 1, requested_solution="publish notice", root_problem="patrons are not yet informed of the "
        "board-approved late-fee abolition", evidence_refs=["E-BOARD", "E-DRAFT"],
        intended_scope=[S("publish_policy_notice", "late-fee-notice")], protected_actions=["publish_policy_notice"],
        success_criteria=["SC-ACC"], metric_ids=["M-ACC"]))
    apply_define_gate(ctx, evaluate_define_gate(ctx))
    ctx.runtime.phase = Phase.EXECUTE
    pub = FakePublisher("public-website", read_only=False, script={
        "publish_policy_notice": [ToolResult(ResultStatus.SUCCESS, is_mutation=True)]})
    reg = ToolRegistry()
    cms = ScriptedTool("cms-read", script={"translation_status": [ToolResult(
        ResultStatus.SUCCESS, records=[{"lang": "es", "status": "ready"}], expected_count=1,
        pagination_complete=True, source_authority=AUTH)]})
    reg.register(cms, ToolSpec("cms-read", "cms", True, AUTH))
    reg.register(pub, ToolSpec("public-website", "cms", False, AUTH))
    return ctx, pub, reg


def proposal(key_evidence: list[str] | None = None) -> ProtectedActionProposal:
    return ProtectedActionProposal(
        "PUB-NOTICE", "publish_policy_notice", "late-fee abolition notice", "public-website",
        [S("publish_policy_notice", "late-fee-notice")], ProtectedActionCategory.SUBMISSION_PUBLISH,
        why="board abolished late fees effective 10-15; patrons must be told before the effective date",
        side_effect="notice visible on public website", reversibility=Reversibility.PARTIALLY_REVERSIBLE,
        alternatives=["post notice at branches only"], idempotency_key="notice-latefee-2026",
        key_evidence=key_evidence or ["E-BOARD", "E-DRAFT"])


def exec_state(ctx: HarnessContext) -> dict[str, Any]:
    pa = ctx.runtime.pending_protected_action
    return {
        "auth": to_dict(ctx.problem.domain_authorizations),
        "execution": to_dict(ctx.problem.execution),
        "status": ctx.runtime.execution_status.value,
        "phase": ctx.runtime.phase.value,
        "pending_core": {k: copy.deepcopy(to_dict(getattr(pa, k))) for k in
                         ("gate_id", "proposal", "confirmation", "domain_authorization_ref", "safe_point_seq",
                          "packet_event_seq")} if pa else None,
        "problem_definition": to_dict(ctx.problem.problem_definition),
    }


def precheck_c() -> dict[str, Any]:
    print("PRECHECK C — REQUEST_CONTEXT targeted regression")
    r: list[dict[str, Any]] = []
    ctx, pub, reg = library_ctx()
    gate = propose_protected_action(ctx, proposal(), pub)
    check(r, "domain-authorized proposal reaches WAITING_APPROVAL", gate.status.value == "WAITING_APPROVAL",
          gate.reasons)
    check(r, "ApprovalPacket emitted", ctx.events.last(EventType.APPROVAL_PACKET_EMITTED) is not None)
    before = exec_state(ctx)
    ev_ids_before = set(ctx.problem.evidence)
    text = "왜 이 작업을 지금 승인해야 해?"
    kind = interpret_human_input(text)
    check(r, "natural-language question interpreted as REQUEST_CONTEXT", kind is HumanDecisionKind.REQUEST_CONTEXT,
          kind.value)
    n0 = len(ctx.events)
    out = decide(ctx, HumanDecision(kind, text), pub)
    new = list(ctx.events)[n0:]
    after = exec_state(ctx)
    check(r, "human_context_requested event exists", any(e.type is EventType.HUMAN_CONTEXT_REQUESTED for e in new))
    check(r, "WAITING_APPROVAL remains", ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL)
    check(r, "protected_action_executed = NO", pub.calls == [] and not ctx.events.of_type(
        EventType.PROTECTED_ACTION_EXECUTED, EventType.APPROVAL_GRANTED))
    check(r, "pending approval remains active (same gate)", ctx.runtime.pending_protected_action is not None
          and out.gate_id == gate.gate_id == ctx.runtime.pending_protected_action.gate_id)
    check(r, "domain authorization unchanged", after["auth"] == before["auth"])
    check(r, "canonical execution state unchanged", after["execution"] == before["execution"]
          and after["status"] == before["status"] and after["phase"] == before["phase"]
          and after["pending_core"] == before["pending_core"]
          and ctx.runtime.pending_protected_action.confirmation.decision is None)
    check(r, "problem definition unchanged", after["problem_definition"] == before["problem_definition"])
    expl = out.explanation or ""
    packet = out.packet
    cited = [e for e in ctx.problem.evidence if e in expl]
    check(r, "explanation grounded: WHY + WHY_HUMAN_NOW from packet / pending action",
          f"WHY: {packet.why}" in expl and f"WHY_HUMAN_NOW: {packet.why_human_now}" in expl, expl)
    expl_ev = ctx.events.last(EventType.APPROVAL_PACKET_EMITTED)
    check(r, "explanation cites only committed evidence", set(expl_ev.refs) <= set(ctx.problem.evidence),
          list(expl_ev.refs))
    check(r, "no evidence fabricated for the explanation", set(ctx.problem.evidence) == ev_ids_before,
          sorted(set(ctx.problem.evidence) - ev_ids_before))
    check(r, "REQUEST_CONTEXT signal visible (HIGH)", any("REQUEST_CONTEXT" in s for s in ctx.supervision.live_summary))
    # repeated / deeper question
    out2 = decide(ctx, HumanDecision(interpret_human_input("근거가 뭐야?"), "근거가 뭐야?"), pub)
    check(r, "follow-up question goes deeper, still no execution", "EVIDENCE:" in (out2.explanation or "")
          and pub.calls == [] and ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL, out2.explanation)
    # insufficient context → safe read-only targeted reprofile via the harness read-only tool path
    ctx2, pub2, reg2 = library_ctx()
    propose_protected_action(ctx2, proposal(["E-BOARD", "E-TRANSLATION"]), pub2)
    auth_b, exec_b = to_dict(ctx2.problem.domain_authorizations), to_dict(ctx2.problem.execution)

    def probe(topics: list[str]) -> Evidence:
        o = invoke_tool(ctx2, reg2, "cms-read", "translation_status")  # read-only harness tool path
        return evidence_from_outcome(ctx2, o, "E-TRANSLATION", "CMS: Spanish translation of the notice is ready")

    out3 = decide(ctx2, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, "다른 언어 공지는 준비됐어? 근거 데이터는?"),
                  pub2, context_probe=probe)
    check(r, "insufficient context → read-only targeted reprofile only", "REPROFILE" in (out3.explanation or "")
          and pub2.calls == [] and to_dict(ctx2.problem.execution) == exec_b
          and to_dict(ctx2.problem.domain_authorizations) == auth_b
          and ctx2.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL)
    # a probe that tries a write through the harness tool path is refused
    ctx3, pub3, reg3 = library_ctx()
    propose_protected_action(ctx3, proposal(["E-BOARD", "E-X"]), pub3)

    def bad_probe(topics: list[str]) -> Evidence:
        invoke_tool(ctx3, reg3, "public-website", "publish_policy_notice")
        raise AssertionError("unreachable")

    try:
        decide(ctx3, HumanDecision(HumanDecisionKind.REQUEST_CONTEXT, "근거는?"), pub3, context_probe=bad_probe)
        refused = False
    except ProtectedActionBlocked:
        refused = True
    check(r, "write attempted inside context probe is refused; gate still pending", refused and pub3.calls == []
          and ctx3.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL)
    # same gate resumes: APPROVE executes once with an approval_granted trace
    fin = decide(ctx, HumanDecision(interpret_human_input("승인합니다"), "승인합니다"), pub)
    check(r, "same gate resumes; APPROVE executes exactly once", fin.status.value == "EXECUTED"
          and fin.gate_id == gate.gate_id and pub.count("publish_policy_notice") == 1)
    rep = run_verify(ctx, fin.action_record.scope)
    check(r, "VERIFY: request_context_not_approval + approval_trace PASS",
          rep.check("request_context_not_approval").status.value == "PASS"
          and rep.check("approval_trace").status.value == "PASS")
    verdict = "PASS" if all(x["pass"] for x in r) else "FAIL_IMPLEMENTATION"
    print(f"  REQUEST_CONTEXT verdict: {verdict}")
    return {"verdict": verdict, "checks": r, "explanation_first": expl, "explanation_second": out2.explanation,
            "packet": packet.render()}


if __name__ == "__main__":
    b = precheck_b()
    c = precheck_c()
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "prechecks.json").write_text(json.dumps({"precheck_b": b, "precheck_c": c},
                                                                ensure_ascii=False, indent=1))

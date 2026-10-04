"""Test builders shared by phase tests and mock regressions."""

from __future__ import annotations

from typing import Any

from aitop_harness.core.enums import (
    AuthorizationStatus,
    EvidenceSourceType,
    MetricType,
    ResultCompleteness,
    ResultStatus,
    SourceAuthority,
)
from aitop_harness.core.provenance import Provenance
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.domain.authority import DomainAuthorization
from aitop_harness.domain.design import ProblemDefinition, StructuralRemedyCandidate
from aitop_harness.domain.epistemic import Evidence, SuccessCriterion
from aitop_harness.domain.metric import Metric
from aitop_harness.domain.organization import BusinessProcess, Organization, Stakeholder
from aitop_harness.engine.context import HarnessContext
from aitop_harness.phases.budget import update_budget
from aitop_harness.phases.define import apply_define_gate, define_problem, evaluate_define_gate
from aitop_harness.phases.design import DesignInputs, design_solution
from aitop_harness.state.problem import ProblemState, Scenario
from aitop_harness.tools.base import ToolResult


def make_ctx(scenario_id: str = "S", initial_request: str = "automate it") -> HarnessContext:
    ctx = HarnessContext(
        problem=ProblemState(scenario=Scenario(id=scenario_id, initial_request=initial_request))
    )
    update_budget(ctx)
    return ctx


def seed_org(ctx: HarnessContext) -> None:
    with ctx.commit("seed org") as ps:
        ps.organizations["ORG-A"] = Organization(id="ORG-A", name="Operator")
        ps.organizations["ORG-B"] = Organization(id="ORG-B", name="Partner")
        ps.stakeholders["SH-REQ"] = Stakeholder(id="SH-REQ", organization_id="ORG-A", role="requester")
        ps.stakeholders["SH-OWN"] = Stakeholder(
            id="SH-OWN", organization_id="ORG-A", role="process owner", authority_scope=["publish"]
        )
        ps.processes["P-1"] = BusinessProcess(id="P-1", name="intake", organization_ids=["ORG-A", "ORG-B"])


def tool_evidence(
    eid: str,
    content: str = "observation",
    *,
    assertion: str | None = None,
    value: Any = None,
    authority: SourceAuthority = SourceAuthority.AUTHORITATIVE,
    completeness: ResultCompleteness = ResultCompleteness.COMPLETE,
    source: str = "tool-db",
    is_fallback: bool = False,
) -> Evidence:
    return Evidence(
        id=eid,
        source_type=EvidenceSourceType.TOOL,
        source_id=source,
        provenance=Provenance(EvidenceSourceType.TOOL, source, method="query"),
        content=content,
        target_assertion=assertion,
        value=value,
        authority=authority,
        completeness=completeness,
        is_fallback=is_fallback,
    )


def seed_success(ctx: HarnessContext) -> None:
    with ctx.commit("seed success criteria") as ps:
        ps.metrics["M-1"] = Metric(
            id="M-1",
            name="reject rate",
            metric_type=MetricType.RATE,
            numerator="rejected",
            denominator="submitted",
        )
        ps.metrics["M-1"].promote(owner="ORG-A", target_value=0.01)
        ps.success_criteria["SC-1"] = SuccessCriterion(
            id="SC-1",
            statement="reject rate < 1%",
            metric_id="M-1",
            validation_method="replay test",
            test_refs=["test_replay"],
        )


def grant(ctx: HarnessContext, auth_id: str, action: str, resource: str, scope: Scope, evidence: str) -> None:
    with ctx.commit(f"grant {auth_id}") as ps:
        ps.domain_authorizations[auth_id] = DomainAuthorization(
            id=auth_id,
            action=action,
            resource=resource,
            authority_holder="SH-OWN",
            authorized_scope=scope,
            evidence_refs=[evidence],
            status=AuthorizationStatus.GRANTED,
        )


def problem(
    evidence_refs: list[str],
    *,
    intended: list[ScopeItem] | None = None,
    protected: list[str] | None = None,
    **kw: Any,
) -> ProblemDefinition:
    return ProblemDefinition(
        id="PD-1",
        requested_solution="LLM auto-fixer",
        symptoms=["downstream rejects"],
        root_problem="interface contract mismatch",
        evidence_refs=evidence_refs,
        intended_scope=intended or [],
        protected_actions=protected or [],
        success_criteria=["SC-1"],
        **kw,
    )


def pass_define(ctx: HarnessContext, pd: ProblemDefinition) -> None:
    define_problem(ctx, pd)
    outcome = evaluate_define_gate(ctx)
    apply_define_gate(ctx, outcome)
    assert pd.gate_result is not None and pd.gate_result.value != "FAIL", [
        f.message for f in outcome.findings
    ]


def design(ctx: HarnessContext, release_scope: list[ScopeItem], **kw: Any) -> None:
    inputs = DesignInputs(
        structural_remedies=[StructuralRemedyCandidate("SR-1", "versioned contract", True, True)],
        deterministic_rules_cover_cases=True,
        llm_reasoning_adds_value=True,
        release_scope=release_scope,
        **kw,
    )
    design_solution(ctx, inputs)


def ok(records: list[dict[str, Any]] | None = None, **kw: Any) -> ToolResult:
    records = records if records is not None else [{"id": 1}]
    kw.setdefault("expected_count", len(records))
    kw.setdefault("pagination_complete", True)
    kw.setdefault("source_authority", SourceAuthority.AUTHORITATIVE)
    return ToolResult(ResultStatus.SUCCESS, records=records, **kw)


def err(error_class: str = "TIMEOUT", retryable: bool | None = True, **kw: Any) -> ToolResult:
    return ToolResult(ResultStatus.ERROR, error_class=error_class, retryable_hint=retryable, **kw)


def mutation_ok(**kw: Any) -> ToolResult:
    return ToolResult(ResultStatus.SUCCESS, is_mutation=True, **kw)

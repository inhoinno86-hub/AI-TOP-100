"""Release Gate + Minimum Useful Release (Design Freeze §33-34).

Open VOB ≠ Global HOLD: only ``VOB.blocking_scope ∩ current_release_scope`` matters.
Some failures can never be covered by a known limitation (HOLD).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    CheckStatus,
    ConflictStatus,
    Criticality,
    DefineGateResult,
    ExecutionStatus,
    FallbackStatus,
    Importance,
    MappingConfidence,
    ReleaseDecision,
    RequiredBefore,
    ReserveStatus,
    SemanticValidity,
    ToolHealth,
    VerifyLayer,
)
from ..core.events import EventType
from ..core.scope import ScopeItem
from ..engine.context import HarnessContext
from ..supervision.monitoring import SignalKind
from .verify import VerifyReport

# Layer-1 checks whose failure cannot be covered by a known limitation.
_UNCOVERABLE_CHECKS = {
    "destructive_transformation": "destructive transformation",
    "authority_boundary": "authority violation",
    "constraint_enforcement": "constraint violation",
    "approval_trace": "protected mutation without required confirmation",
    "request_context_not_approval": "REQUEST_CONTEXT treated as approval",
    "mapping_uniqueness": "unresolved critical mapping used by released action",
    "handoff_delivery_semantic": "unresolved semantic mismatch used by released action",
    "pagination_coverage": "completeness unknown while release assumes completeness",
    "duplicate_mutation_prevention": "duplicate mutation",
    "read_back_validation": "protected mutation not read-back verified",
    "vob_blocking_scope": "VOB blocking_scope violated",
}


@dataclass
class MinimumUsefulAssessment:
    ok: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class ReleaseGateResult:
    decision: ReleaseDecision
    hold_reasons: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)
    release_scope: list[ScopeItem] = field(default_factory=list)
    minimum_useful: MinimumUsefulAssessment | None = None


def assess_minimum_useful_release(ctx: HarnessContext, release_scope: list[ScopeItem],
                                  report: VerifyReport) -> MinimumUsefulAssessment:
    """Root Problem alignment + operational value + safety + verification + explicit unfinished scope.

    Detects panic scope collapse (trivial demo unrelated to the root problem).
    """
    reasons: list[str] = []
    plan = ctx.runtime.current_plan
    aligned = [
        w for w in (plan.work_items if plan else [])
        if w.root_problem_aligned and w.status != "DROPPED" and any(i in release_scope for i in w.scope_items)
    ]
    sd = ctx.problem.solution_design
    if sd and sd.minimum_useful_scope:
        aligned_scope = all(i in release_scope for i in sd.minimum_useful_scope)
    else:
        aligned_scope = bool(aligned)
    if not release_scope:
        reasons.append("no operational value: empty release scope")
    if not aligned_scope:
        reasons.append("PANIC_SCOPE_COLLAPSE: release scope not aligned with root problem")
    if not report.layer1_passed:
        reasons.append("safety predicate / verification not established (Layer 1 failed)")
    dropped = ctx.runtime.release_runtime.dropped_scope
    unfinished = sd.unfinished_scope if sd else []
    if dropped and not unfinished:
        reasons.append("unfinished scope not made explicit")
    return MinimumUsefulAssessment(ok=not reasons, reasons=reasons)


def evaluate_release_gate(
    ctx: HarnessContext, report: VerifyReport, release_scope: list[ScopeItem] | None = None
) -> ReleaseGateResult:
    ps, rt = ctx.problem, ctx.runtime
    scope = list(release_scope if release_scope is not None else report.release_scope)
    hold: list[str] = []
    limits: list[str] = []

    pd = ps.problem_definition
    if pd is None or pd.gate_result not in (DefineGateResult.PASS, DefineGateResult.CONDITIONAL_PASS):
        hold.append("problem definition has not passed DEFINE Gate")
    elif pd.gate_result is DefineGateResult.CONDITIONAL_PASS:
        limits.append("DEFINE Gate CONDITIONAL_PASS (deferred items tracked as VOBs)")
    if pd is not None and pd.status.value == "INVALIDATED":
        hold.append("canonical problem invalidated; redefine pending")
    if rt.execution_status is ExecutionStatus.WAITING_APPROVAL:
        hold.append("a protected action is still WAITING_APPROVAL")

    # minimum safety verification executed?
    l1 = report.layer(VerifyLayer.DETERMINISTIC)
    if not l1:
        hold.append("minimum safety verification not executed")
    for c in l1:
        if c.status is CheckStatus.FAIL:
            label = _UNCOVERABLE_CHECKS.get(c.name.split(":")[0])
            if label or c.name.startswith(("completeness:", "missing:", "schema_type:")):
                hold.append(f"{label or c.name}: {c.detail}")
            else:
                limits.append(f"{c.name} failed: {c.detail}")
    for c in report.layer(VerifyLayer.SEMANTIC_JUDGE):
        if c.status is CheckStatus.FAIL:
            if c.name == "problem_solution_consistency":
                hold.append(f"{c.name}: {c.detail}")
            else:
                limits.append(f"semantic: {c.name}: {c.detail}")
    for item in report.human_review:
        if not item.satisfied:
            hold.append(f"human review required: {item.reason}")

    # VOB blocking_scope ∩ release scope
    for v in ps.open_vobs():
        hits = v.blocking_scope.intersect(scope)
        if v.required_before is RequiredBefore.BEFORE_PRODUCTION:
            limits.append(f"{v.id} open (required before production): {v.unresolved_question}")
            continue
        if not hits:
            limits.append(f"{v.id} open; blocking_scope outside release scope")
            continue
        if v.is_critical():
            hold.append(f"critical {v.id} intersects release scope at {[str(h) for h in hits]}")
        else:
            limits.append(f"{v.id} intersects release scope (non-critical): {v.unresolved_question}")

    # unresolved critical conflict / constraint / mapping / handoff within release scope
    for c in ps.conflicts.values():
        if c.status is ConflictStatus.OPEN and c.decision_impact is Criticality.CRITICAL:
            if c.affects_scope.entire_solution or c.affects_scope.intersect(scope):
                hold.append(f"unresolved critical conflict {c.id}")
            else:
                limits.append(f"conflict {c.id} open outside release scope")
    targets = {i.target for i in scope}
    for mid, m in ps.canonical_mappings.items():
        if mid in targets and (m.confidence is MappingConfidence.UNRESOLVED):
            hold.append(f"unresolved mapping {mid} in release scope")
        elif m.confidence is MappingConfidence.UNRESOLVED:
            limits.append(f"mapping {mid} unresolved; excluded from release scope")
    for hid, h in ps.process_handoffs.items():
        if hid in targets and h.semantic_validity is SemanticValidity.BROKEN:
            hold.append(f"handoff {hid} semantic mismatch in release scope")

    # tool health / fallback, recovery history
    for tid, tr in rt.tool_runtime.items():
        if tr.health in (ToolHealth.DEGRADED, ToolHealth.UNAVAILABLE):
            limits.append(f"tool {tid} {tr.health.value}")
    if rt.recovery.fallback_status is FallbackStatus.ACTIVE:
        limits.append("fallback data used within allowed usage (non-authoritative)")
    for w in rt.release_runtime.dropped_scope:
        limits.append(f"dropped for budget: {w}")

    # time / reserve / packaging feasibility
    br, rr = rt.budget_runtime, rt.release_runtime
    if rr.reserve_status is ReserveStatus.AT_RISK or br.remaining < ps.budget.packaging_minutes * 0.5:
        hold.append("packaging/submission infeasible in remaining time")
        ctx.signal(SignalKind.SUBMISSION_AT_RISK, f"remaining {br.remaining:.0f}m")

    mur = assess_minimum_useful_release(ctx, scope, report)
    if not mur.ok:
        hold.extend(r for r in mur.reasons if r not in hold)
    if hold:
        decision = ReleaseDecision.HOLD
    elif limits:
        decision = ReleaseDecision.RELEASE_WITH_KNOWN_LIMITATION
    else:
        decision = ReleaseDecision.RELEASE
    result = ReleaseGateResult(decision, hold, limits, scope, mur)

    with ctx.commit(f"Release Gate {decision.value}") as p:
        p.validation.release_decisions.append(decision)
    event = ctx.emit(EventType.RELEASE_GATE_RESULT,
                     {"decision": decision.value, "hold": hold, "limitations": limits,
                      "scope": [str(i) for i in scope]},
                     importance=Importance.CRITICAL)
    ctx.supervision.gate_rationale = [f"RELEASE {decision.value}"] + hold + limits
    ctx.signal(SignalKind.RELEASE_GATE_RESULT, decision.value, event_seq=event.seq)
    if hold and any("VOB" in h for h in hold):
        ctx.signal(SignalKind.RELEASE_BLOCKING_VOB, "; ".join(h for h in hold if "VOB" in h))
    return result

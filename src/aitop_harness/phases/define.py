"""DEFINE Gate — PASS / CONDITIONAL_PASS / FAIL (Design Freeze §13, v0.2.4 §11).

Critical unknown overlapping the release/action scope without a resolution path ⇒ never PASS.
CONDITIONAL_PASS requires a safe placeholder / no-write path, and deferred critical unknowns
are carried forward as VerificationObligations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from ..core.enums import (
    AuthorizationStatus,
    ConflictStatus,
    ConstraintStatus,
    ConstraintType,
    Criticality,
    DefineGateResult,
    DeliveryStatus,
    EvidenceSourceType,
    EvidenceStatus,
    Importance,
    MappingConfidence,
    MetricProfile,
    Phase,
    ProblemDefinitionStatus,
    RequiredBefore,
    SemanticValidity,
    ToolHealth,
    UnknownStatus,
)
from ..core.events import EventType
from ..core.scope import Scope, ScopeItem
from ..domain.design import DecisionRecord, ProblemDefinition
from ..domain.verification import VerificationObligation
from ..engine.context import HarnessContext
from ..supervision.monitoring import SignalKind
from ..tools.base import ToolRegistry


class Severity(StrEnum):
    OK = "OK"
    INFO = "INFO"
    CONDITIONAL = "CONDITIONAL"
    BLOCKING = "BLOCKING"


@dataclass
class GateFinding:
    check: str
    severity: Severity
    message: str
    refs: list[str] = field(default_factory=list)


@dataclass
class DefineGateOutcome:
    result: DefineGateResult
    findings: list[GateFinding]
    vobs_to_create: list[VerificationObligation] = field(default_factory=list)
    unknowns_to_defer: dict[str, str] = field(default_factory=dict)  # unknown id -> vob id

    def blocking(self) -> list[GateFinding]:
        return [f for f in self.findings if f.severity is Severity.BLOCKING]

    def conditional(self) -> list[GateFinding]:
        return [f for f in self.findings if f.severity is Severity.CONDITIONAL]


_CRITICAL = (Criticality.CRITICAL, Criticality.HIGH)


def define_problem(ctx: HarnessContext, definition: ProblemDefinition) -> ProblemDefinition:
    """Record (or replace after redefine) the canonical Problem draft."""
    with ctx.commit(f"problem definition {definition.id} v{definition.version}") as ps:
        ps.problem_definition = definition
        ctx.supervision.current_problem = definition.root_problem
    return definition


def evaluate_define_gate(ctx: HarnessContext, registry: ToolRegistry | None = None) -> DefineGateOutcome:
    ps = ctx.problem
    pd = ps.problem_definition
    findings: list[GateFinding] = []
    vobs: list[VerificationObligation] = []
    defer: dict[str, str] = {}

    def add(check: str, sev: Severity, msg: str, refs: list[str] | None = None) -> None:
        findings.append(GateFinding(check, sev, msg, list(refs or [])))

    if pd is None:
        add("problem", Severity.BLOCKING, "no problem definition")
        return DefineGateOutcome(DefineGateResult.FAIL, findings)

    intended = list(pd.intended_scope)
    protected_scope = [i for i in intended if i.action in pd.protected_actions]

    # --- Organization / Actor
    if not ps.organizations:
        add("organization", Severity.BLOCKING, "no organization modeled")
    # --- Process
    if not ps.processes:
        add("process", Severity.INFO, "no business process modeled")

    # --- Problem / Evidence (anti-anchoring: root problem must rest on non-request evidence)
    if not pd.root_problem:
        add("problem", Severity.BLOCKING, "root problem not stated")
    committed = [e for e in pd.evidence_refs if e in ps.evidence]
    if len(committed) != len(pd.evidence_refs) or not committed:
        add("evidence", Severity.BLOCKING, "problem definition cites missing or no evidence", pd.evidence_refs)
    else:
        independent = [e for e in committed if ps.evidence[e].source_type is not EvidenceSourceType.STAKEHOLDER]
        if not independent:
            add("evidence", Severity.BLOCKING,
                "root problem rests only on stakeholder statements (initial-request anchoring risk)", committed)
        stale = [e for e in committed if ps.evidence[e].status is not EvidenceStatus.ACTIVE]
        if stale:
            add("evidence", Severity.BLOCKING, "problem definition cites revised/superseded evidence", stale)

    # --- Handoff (only the ones the solution depends on — lazy)
    for hid in pd.depends_on_handoffs:
        h = ps.process_handoffs.get(hid)
        if h is None:
            add("handoff", Severity.BLOCKING, f"handoff {hid} not modeled", [hid])
        elif h.semantic_validity is SemanticValidity.UNKNOWN or h.delivery_status is DeliveryStatus.UNKNOWN:
            add("handoff", Severity.CONDITIONAL, f"handoff {hid} delivery/semantic validity unknown", [hid])

    # --- Data (export permission)
    for asset_id in pd.depends_on_exports:
        auth = ps.authorization_for("export", asset_id)
        if auth is None or auth.status is AuthorizationStatus.UNKNOWN:
            add("data", Severity.BLOCKING, f"solution depends on exporting {asset_id}; export permission unknown",
                [asset_id])

    # --- Identity / CanonicalMapping (only if the solution depends on it)
    open_vobs = ps.open_vobs()
    for mid in pd.depends_on_mappings:
        m = ps.canonical_mappings.get(mid)
        if m is None or m.confidence is MappingConfidence.UNRESOLVED:
            covered = any(v.blocking_scope.intersect([ScopeItem(a.action, mid) for a in intended]) for v in open_vobs)
            add("mapping", Severity.CONDITIONAL if covered else Severity.BLOCKING,
                f"critical mapping {mid} UNRESOLVED" + (" (scoped out by VOB)" if covered else ""), [mid])

    # --- Unknown (critical ∩ intended scope)
    for u in ps.unknowns.values():
        if u.status is not UnknownStatus.OPEN or u.criticality not in _CRITICAL:
            continue
        scope = u.affects_scope if not u.affects_scope.is_empty() else Scope.entire()
        overlap = scope.intersect(intended) if intended else ([ScopeItem("*")] if scope.entire_solution else [])
        if not overlap:
            add("unknown", Severity.INFO, f"critical unknown {u.id} outside intended scope", [u.id])
            continue
        if u.resolution_path and u.safe_placeholder:
            vob_id = f"VOB-{u.id}"
            touches_protected = bool(scope.intersect(protected_scope))
            vobs.append(
                VerificationObligation(
                    id=vob_id,
                    unresolved_question=u.question,
                    source_phase=Phase.DEFINE,
                    reason_deferred=f"deferred at DEFINE Gate; safe placeholder: {u.safe_placeholder}",
                    decision_impact=u.criticality,
                    validation_method=u.resolution_path,
                    required_before=(RequiredBefore.BEFORE_PROTECTED_ACTION if touches_protected
                                     else RequiredBefore.BEFORE_RELEASE),
                    blocking_scope=scope,
                    linked_unknown=u.id,
                )
            )
            defer[u.id] = vob_id
            add("unknown", Severity.CONDITIONAL, f"critical unknown {u.id} deferred to {vob_id}", [u.id])
        else:
            add("unknown", Severity.BLOCKING,
                f"critical unknown {u.id} overlaps intended scope without resolution path / safe placeholder", [u.id])

    # --- Conflict
    for c in ps.conflicts.values():
        if c.status is not ConflictStatus.OPEN:
            continue
        if c.gate_blocking or c.decision_impact is Criticality.CRITICAL:
            add("conflict", Severity.CONDITIONAL if c.resolution_strategy else Severity.BLOCKING,
                f"critical conflict {c.id} on {c.assertion}", [c.id])
        elif c.decision_impact is Criticality.HIGH:
            add("conflict", Severity.CONDITIONAL, f"high-impact conflict {c.id} open", [c.id])

    # --- Metric (gate-critical metrics must be EXTENDED with type semantics)
    linked_metrics = set(pd.metric_ids) | {
        sc.metric_id for sid in pd.success_criteria if (sc := ps.success_criteria.get(sid)) and sc.metric_id
    }
    for mid in sorted(linked_metrics):
        m = ps.metrics.get(mid)
        if m is None:
            add("metric", Severity.BLOCKING, f"metric {mid} not defined", [mid])
        elif m.profile is not MetricProfile.EXTENDED or m.missing_type_semantics():
            add("metric", Severity.BLOCKING,
                f"metric {mid} must be EXTENDED with {m.missing_type_semantics() or 'semantics'}", [mid])
        elif m.current_value_is_speculative:
            add("metric", Severity.CONDITIONAL, f"metric {mid} current value speculative", [mid])

    # --- Constraint / Authority
    for action in pd.protected_actions:
        auth = ps.authorization_for(action)
        if auth is None or auth.status is AuthorizationStatus.UNKNOWN or auth.authority_holder is None:
            add("authority", Severity.BLOCKING, f"protected action {action}: authority owner / authorization unknown",
                [action])
        approval_unknown = [
            c.id for c in ps.constraints.values()
            if c.protected_action == action and c.status in (ConstraintStatus.UNKNOWN, ConstraintStatus.SUSPECTED)
        ]
        if approval_unknown:
            add("authority", Severity.BLOCKING, f"protected action {action}: approval requirement unknown",
                approval_unknown)
    for c in ps.constraints.values():
        if (c.type in (ConstraintType.SAFETY, ConstraintType.PRIVACY) and c.status in
                (ConstraintStatus.UNKNOWN, ConstraintStatus.SUSPECTED) and c.criticality in _CRITICAL):
            add("constraint", Severity.BLOCKING, f"{c.type.value} constraint {c.id} may change solution path", [c.id])

    # --- Success criteria / verification readiness
    if not pd.success_criteria:
        add("verification", Severity.BLOCKING, "no success criteria")
    for sid in pd.success_criteria:
        sc = ps.success_criteria.get(sid)
        if sc is None or not sc.validation_method:
            add("verification", Severity.BLOCKING, f"success criterion {sid} has no validation method", [sid])
    for v in open_vobs:
        if v.blocking_scope.intersect(intended) and not v.validation_method:
            add("vob", Severity.BLOCKING, f"open {v.id} overlaps intended scope without resolution path", [v.id])

    # --- Tool dependency / fallback readiness
    for tid in pd.required_tools:
        health = ctx.runtime.tool(tid).health
        has_fallback = bool(registry and registry.fallbacks_for(tid))
        if health is ToolHealth.UNAVAILABLE and not has_fallback:
            add("tool", Severity.BLOCKING, f"required tool {tid} UNAVAILABLE without fallback", [tid])
        elif health is ToolHealth.DEGRADED and not has_fallback:
            add("tool", Severity.CONDITIONAL, f"required tool {tid} DEGRADED without fallback", [tid])

    # --- Budget feasibility
    br = ctx.runtime.budget_runtime
    floor = ps.budget.verification_floor_minutes + ps.budget.release_reserve_minutes
    if br.remaining < floor:
        add("budget", Severity.BLOCKING,
            f"remaining {br.remaining:.0f}m below verification floor + release reserve ({floor:.0f}m)")

    if any(f.severity is Severity.BLOCKING for f in findings):
        result = DefineGateResult.FAIL
    elif any(f.severity is Severity.CONDITIONAL for f in findings):
        result = DefineGateResult.CONDITIONAL_PASS
    else:
        result = DefineGateResult.PASS
    return DefineGateOutcome(result, findings, vobs, defer)


def apply_define_gate(ctx: HarnessContext, outcome: DefineGateOutcome) -> DefineGateResult:
    """Commit the gate result. CONDITIONAL_PASS: deferred unknowns → VOBs."""
    with ctx.commit(f"DEFINE Gate {outcome.result.value}") as ps:
        pd = ps.problem_definition
        assert pd is not None
        pd.gate_result = outcome.result
        if outcome.result is not DefineGateResult.FAIL:
            pd.status = ProblemDefinitionStatus.ACTIVE
            for vob in outcome.vobs_to_create:
                ps.verification_obligations[vob.id] = vob
            for uid, vob_id in outcome.unknowns_to_defer.items():
                ps.unknowns[uid].status = UnknownStatus.DEFERRED
                ps.unknowns[uid].deferred_to_vob = vob_id
        ps.decision_log.append(
            DecisionRecord(
                id=f"D-{len(ps.decision_log) + 1}",
                phase=Phase.DEFINE,
                decision=f"DEFINE Gate {outcome.result.value}",
                rationale="; ".join(f"[{f.severity.value}] {f.message}" for f in outcome.findings
                                    if f.severity is not Severity.OK),
            )
        )
    event = ctx.emit(
        EventType.DEFINE_GATE_RESULT,
        {
            "result": outcome.result.value,
            "findings": [{"check": f.check, "severity": f.severity.value, "message": f.message}
                         for f in outcome.findings],
            "vobs": [v.id for v in outcome.vobs_to_create],
        },
        importance=Importance.CRITICAL if outcome.result is DefineGateResult.FAIL else Importance.HIGH,
    )
    for vob in outcome.vobs_to_create:
        ctx.emit(EventType.VOB_CREATED, {"vob": vob.id, "required_before": vob.required_before.value},
                 refs=[vob.id])
    for uid in outcome.unknowns_to_defer:
        ctx.emit(EventType.UNKNOWN_DEFERRED, {"unknown": uid, "vob": outcome.unknowns_to_defer[uid]})
    rationale = [f"{f.check}: {f.message}" for f in outcome.findings if f.severity is not Severity.OK]
    ctx.supervision.gate_rationale = [f"DEFINE {outcome.result.value}"] + rationale
    ctx.signal(SignalKind.DEFINE_GATE_RESULT, f"{outcome.result.value} ({len(rationale)} findings)",
               event_seq=event.seq)
    return outcome.result


"""VERIFY layers (Design Freeze §32).

Layer 1 deterministic checks are authoritative. Layer 2 (semantic judge) may add findings but can
never override a Layer 1 result — an LLM does not out-rank authoritative tool/data/policy.
Layer 3 lists the human reviews that are required.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..core.enums import (
    CheckStatus,
    ConflictStatus,
    Criticality,
    DataIssueType,
    DeliveryStatus,
    FreshnessStatus,
    Importance,
    MappingConfidence,
    RequiredBefore,
    ResultCompleteness,
    SemanticValidity,
    SourceAuthority,
    VerifyLayer,
)
from ..core.events import EventType
from ..core.scope import ScopeItem
from ..domain.design import FailureHandlingPolicy
from ..engine.context import HarnessContext
from ..supervision.monitoring import SignalKind
from .data_inspection import inspect_records


@dataclass
class CheckResult:
    name: str
    layer: VerifyLayer
    status: CheckStatus
    detail: str = ""
    refs: list[str] = field(default_factory=list)


@dataclass
class OutputSpec:
    """A produced artifact to verify deterministically."""

    name: str
    records: list[dict[str, Any]]
    schema: dict[str, str] = field(default_factory=dict)
    key_fields: list[str] = field(default_factory=list)
    status_field: str | None = None
    version_field: str | None = None
    timestamp_field: str | None = None
    expected_count: int | None = None
    assumes_completeness: bool = True


@dataclass
class HumanReviewItem:
    reason: str
    satisfied: bool
    refs: list[str] = field(default_factory=list)


@dataclass
class VerifyReport:
    checks: list[CheckResult]
    human_review: list[HumanReviewItem]
    release_scope: list[ScopeItem]

    def layer(self, layer: VerifyLayer) -> list[CheckResult]:
        return [c for c in self.checks if c.layer is layer]

    def failed(self, layer: VerifyLayer | None = None) -> list[CheckResult]:
        return [
            c for c in self.checks if c.status is CheckStatus.FAIL and (layer is None or c.layer is layer)
        ]

    @property
    def layer1_passed(self) -> bool:
        l1 = self.layer(VerifyLayer.DETERMINISTIC)
        return bool(l1) and not any(c.status is CheckStatus.FAIL for c in l1)

    def check(self, name: str) -> CheckResult:
        return next(c for c in self.checks if c.name == name)


class SemanticJudge(Protocol):
    def judge(self, ctx: HarnessContext, report: VerifyReport) -> list[CheckResult]: ...


L1 = VerifyLayer.DETERMINISTIC
L2 = VerifyLayer.SEMANTIC_JUDGE


def _r(
    name: str, ok: bool | None, detail: str = "", refs: list[str] | None = None, layer: VerifyLayer = L1
) -> CheckResult:
    status = CheckStatus.NOT_APPLICABLE if ok is None else (CheckStatus.PASS if ok else CheckStatus.FAIL)
    return CheckResult(name, layer, status, detail, list(refs or []))


# --------------------------------------------------------------------------- layer 1


def relied_on(ctx: HarnessContext, release_scope: list[ScopeItem]) -> set[str]:
    """Ids whose correctness the released actions rely on.

    = declared ``SolutionDesign.scope_dependencies`` of released actions
    ∪ CanonicalMappings that are themselves the target of a released action (publishing/using a mapping
      propagates it). Merely *targeting* a handoff (e.g. detecting its breakage) is not reliance on it.
    """
    ps = ctx.problem
    deps: set[str] = set()
    sd = ps.solution_design
    actions = {i.action for i in release_scope}
    if sd is not None:
        for action in actions:
            deps.update(sd.scope_dependencies.get(action, []))
    deps.update(i.target for i in release_scope if i.target in ps.canonical_mappings)
    return deps


def layer1(
    ctx: HarnessContext, release_scope: list[ScopeItem], outputs: list[OutputSpec]
) -> list[CheckResult]:
    ps, rt = ctx.problem, ctx.runtime
    checks: list[CheckResult] = []
    scope_actions = {i.action for i in release_scope}
    reliance = relied_on(ctx, release_scope)

    # schema / missing / type / completeness / duplicate-event semantics / timestamp on outputs
    for out in outputs:
        rep = inspect_records(
            out.records,
            schema=out.schema,
            key_fields=out.key_fields,
            status_field=out.status_field,
            version_field=out.version_field,
            timestamp_field=out.timestamp_field,
            expected_count=out.expected_count,
        )
        types = rep.issue_types()
        checks.append(
            _r(
                f"schema_type:{out.name}",
                not (types & {DataIssueType.UNEXPECTED_TYPE}),
                f"{rep.count(DataIssueType.UNEXPECTED_TYPE)} type issues",
            )
        )
        checks.append(
            _r(
                f"missing:{out.name}",
                DataIssueType.MISSING not in types,
                f"{rep.count(DataIssueType.MISSING)} missing",
            )
        )
        checks.append(
            _r(f"timestamp:{out.name}", DataIssueType.MALFORMED not in types if out.timestamp_field else None)
        )
        checks.append(
            _r(
                f"duplicate_semantics:{out.name}",
                DataIssueType.EXACT_RECORD_DUPLICATE not in types,
                "status progression / event versions preserved, exact duplicates absent",
            )
        )
        if out.assumes_completeness:
            checks.append(
                _r(
                    f"completeness:{out.name}",
                    rep.completeness is ResultCompleteness.COMPLETE,
                    f"completeness={rep.completeness.value}",
                )
            )

    # pagination / coverage of data the release depends on
    dependent = [a for a in ps.data_assets.values() if set(a.used_by) & scope_actions or a.id in reliance]
    incomplete = [a.id for a in dependent if a.completeness is not ResultCompleteness.COMPLETE]
    checks.append(
        _r(
            "pagination_coverage",
            (not incomplete) if dependent else None,
            f"incomplete inputs used by release: {incomplete}",
            incomplete,
        )
    )

    # duplicate/event semantics on transformations: destructive dedupe forbidden
    destructive = [
        t.id for a in ps.data_assets.values() for t in a.transformations if t.destructive and not t.validated
    ]
    checks.append(
        _r(
            "destructive_transformation",
            not destructive,
            f"unvalidated destructive: {destructive}",
            destructive,
        )
    )

    # mapping uniqueness / confidence for mappings in release scope
    released_maps = [m for mid, m in ps.canonical_mappings.items() if mid in reliance]
    if released_maps:
        bad = [
            m.id for m in released_maps if not m.is_resolved() or m.confidence is not MappingConfidence.HIGH
        ]
        src = Counter(m.source_key() for m in released_maps)
        tgt = Counter(tuple(sorted(m.target_identifiers.items())) for m in released_maps)
        dup = [
            m.id
            for m in released_maps
            if src[m.source_key()] > 1 or tgt[tuple(sorted(m.target_identifiers.items()))] > 1
        ]
        checks.append(
            _r("mapping_uniqueness", not bad and not dup, f"unresolved/low={bad} non-unique={dup}", bad + dup)
        )
    else:
        checks.append(_r("mapping_uniqueness", None))

    # handoff delivery / semantic validity / freshness (only where release depends on it)
    handoffs = [h for hid, h in ps.process_handoffs.items() if hid in reliance]
    if handoffs:
        bad_h = [
            h.id
            for h in handoffs
            if h.delivery_status is not DeliveryStatus.HEALTHY
            or h.semantic_validity is not SemanticValidity.VALID
        ]
        checks.append(_r("handoff_delivery_semantic", not bad_h, f"unhealthy/invalid: {bad_h}", bad_h))
        fresh_req = [h for h in handoffs if h.freshness_requirement]
        stale = [h.id for h in fresh_req if h.freshness_status is not FreshnessStatus.FRESH]
        checks.append(_r("freshness", (not stale) if fresh_req else None, f"not fresh: {stale}", stale))
    else:
        checks.append(_r("handoff_delivery_semantic", None))
        checks.append(_r("freshness", None))

    # retry termination
    policy = ps.agent_spec.failure_handling if ps.agent_spec else FailureHandlingPolicy()
    per_sig = Counter(r.failure_signature for r in rt.recovery.retry_history)
    runaway = [s for s, n in per_sig.items() if n > policy.repeated_failure_threshold]
    checks.append(_r("retry_termination", not runaway if per_sig else None, f"unbounded: {runaway}", runaway))

    # fallback trigger / authority
    fb_issues = [
        k
        for k, fb in rt.recovery.fallbacks.items()
        if not fb.trigger or fb.authority is SourceAuthority.AUTHORITATIVE
    ]
    fb_issues += [
        e.id for e in ps.evidence.values() if e.is_fallback and e.authority is SourceAuthority.AUTHORITATIVE
    ]
    fb_issues += [a.id for a in ps.execution.actions if a.used_fallback_data]
    relevant_fb = bool(rt.recovery.fallbacks) or any(e.is_fallback for e in ps.evidence.values())
    checks.append(
        _r(
            "fallback_trigger_authority",
            (not fb_issues) if relevant_fb else None,
            f"issues: {fb_issues}",
            fb_issues,
        )
    )

    executed = [a for a in ps.execution.actions if a.protected]

    # constraint enforcement + authority boundary
    auth_issues = []
    for a in executed:
        auth = ps.domain_authorizations.get(a.domain_authorization_ref or "")
        if auth is None or not auth.is_effective() or not auth.authorized_scope.contains_all(a.scope)[0]:
            auth_issues.append(a.id)
    checks.append(
        _r(
            "authority_boundary",
            (not auth_issues) if executed else None,
            f"actions outside domain authorization: {auth_issues}",
            auth_issues,
        )
    )
    checks.append(_r("constraint_enforcement", (not auth_issues) if executed else None))

    # VOB blocking_scope
    vob_issues = [v.id for v in ps.open_vobs() if v.blocking_scope.is_empty()]
    for a in executed:
        for v in ps.open_vobs():
            if v.required_before is RequiredBefore.BEFORE_PROTECTED_ACTION and v.blocking_scope.intersect(
                a.scope
            ):
                vob_issues.append(f"{a.id}∩{v.id}")
    checks.append(_r("vob_blocking_scope", not vob_issues, f"issues: {vob_issues}", vob_issues))

    # approval trace + REQUEST_CONTEXT not treated as approval
    trace_issues, ctx_issues = [], []
    for a in executed:
        if not a.runtime_confirmation_required:
            continue
        if a.approval_event_seq is None:
            trace_issues.append(a.id)
            continue
        ev = ctx.events.get(a.approval_event_seq)
        if ev.type is EventType.HUMAN_CONTEXT_REQUESTED:
            ctx_issues.append(a.id)
        elif ev.type not in (EventType.APPROVAL_GRANTED, EventType.HUMAN_OVERRIDE_RECEIVED):
            trace_issues.append(a.id)
        elif a.executed_event_seq is not None and a.executed_event_seq < a.approval_event_seq:
            trace_issues.append(a.id)
    checks.append(
        _r(
            "approval_trace",
            (not trace_issues) if executed else None,
            f"untraced: {trace_issues}",
            trace_issues,
        )
    )
    checks.append(
        _r(
            "request_context_not_approval",
            not ctx_issues,
            f"executed on context request: {ctx_issues}",
            ctx_issues,
        )
    )

    # duplicate mutation prevention + read-back
    keys = Counter(a.idempotency_key for a in executed if a.idempotency_key)
    dups = [k for k, n in keys.items() if n > 1]
    checks.append(_r("duplicate_mutation_prevention", (not dups) if executed else None, f"dups: {dups}"))
    unverified = [a.id for a in executed if not a.read_back_verified]
    checks.append(
        _r(
            "read_back_validation",
            (not unverified) if executed else None,
            f"unverified: {unverified}",
            unverified,
        )
    )

    # metric ↔ test
    pd = ps.problem_definition
    if pd and pd.success_criteria:
        untested = [
            s
            for s in pd.success_criteria
            if (sc := ps.success_criteria.get(s)) is None or not (sc.test_refs or sc.validation_method)
        ]
        checks.append(_r("metric_test_link", not untested, f"no validation: {untested}", untested))
    return checks


# --------------------------------------------------------------------------- layer 2 / 3


def layer2_deterministic_proxies(ctx: HarnessContext) -> list[CheckResult]:
    """Checks the frozen design lists under Layer 2 that can be decided without an LLM."""
    ps = ctx.problem
    pd, sd = ps.problem_definition, ps.solution_design
    consistent: bool | None = None
    if pd and sd:
        consistent = (
            sd.problem_ref == pd.id and sd.problem_version == pd.version and pd.status.value == "ACTIVE"
        )
    fidelity_issues = [
        ref
        for e in ctx.events.of_type(EventType.APPROVAL_PACKET_EMITTED)
        for ref in e.refs
        if ref not in ps.evidence
    ]
    return [
        _r(
            "problem_solution_consistency",
            consistent,
            "solution design tracks current problem version" if consistent else "solution design stale",
            layer=L2,
        ),
        _r(
            "approval_packet_evidence_fidelity",
            not fidelity_issues,
            f"uncommitted evidence cited: {fidelity_issues}",
            fidelity_issues,
            layer=L2,
        ),
    ]


def layer3(ctx: HarnessContext, release_scope: list[ScopeItem]) -> list[HumanReviewItem]:
    ps = ctx.problem
    items: list[HumanReviewItem] = []
    for a in ps.execution.actions:
        if a.protected and a.runtime_confirmation_required:
            items.append(
                HumanReviewItem(f"protected mutation {a.id}", a.approval_event_seq is not None, [a.id])
            )
    for c in ps.conflicts.values():
        if (
            c.status is ConflictStatus.OPEN
            and c.decision_impact is Criticality.CRITICAL
            and (c.affects_scope.intersect(release_scope) or c.affects_scope.entire_solution)
        ):
            items.append(HumanReviewItem(f"high-impact ambiguity {c.id}", False, [c.id]))
    pd = ps.problem_definition
    for action in pd.protected_actions if pd else []:
        if action in {i.action for i in release_scope}:
            auth = ps.authorization_for(action)
            if auth is None or not auth.is_effective():
                items.append(HumanReviewItem(f"unresolved authority for {action}", False, [action]))
    return items


def run_verify(
    ctx: HarnessContext,
    release_scope: list[ScopeItem],
    *,
    outputs: list[OutputSpec] | None = None,
    judge: SemanticJudge | None = None,
) -> VerifyReport:
    checks = layer1(ctx, release_scope, outputs or [])
    report = VerifyReport(checks=checks, human_review=[], release_scope=list(release_scope))
    l2 = layer2_deterministic_proxies(ctx)
    if judge is not None:
        l1_names = {c.name for c in checks}
        for c in judge.judge(ctx, report):
            if c.name in l1_names:
                continue  # judge cannot override Layer 1
            c.layer = L2
            l2.append(c)
    report.checks.extend(l2)
    report.human_review = layer3(ctx, release_scope)
    pd = ctx.problem.problem_definition
    with ctx.commit("VERIFY run") as ps:
        ps.validation.verify_runs.append(
            {
                "problem_ref": pd.ref
                if pd
                else None,  # a run only counts for the Problem version it verified
                "minute": ctx.clock.now(),
                "layer1_passed": report.layer1_passed,
                "failed": [c.name for c in report.failed()],
                "release_scope": [str(i) for i in release_scope],
            }
        )
    event = ctx.emit(
        EventType.VERIFY_COMPLETED,
        {"layer1_passed": report.layer1_passed, "failed": [c.name for c in report.failed()]},
        importance=Importance.HIGH if report.failed() else Importance.NORMAL,
    )
    if report.failed():
        ctx.signal(
            SignalKind.STATE_DIFF,
            f"VERIFY failed: {[c.name for c in report.failed()]}",
            importance=Importance.HIGH,
            event_seq=event.seq,
        )
    else:
        ctx.signal(SignalKind.ROUTINE_VALIDATION_SUCCESS, "VERIFY layer 1 passed", event_seq=event.seq)
    return report

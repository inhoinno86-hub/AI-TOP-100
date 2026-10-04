"""EXECUTE — tool invocation with ToolHealth and partial-result semantics (Design Freeze §19, §22).

Only read-only tools are invoked here. Mutations are protected actions and go through
``phases.human_gate`` — there is no side door.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..core.enums import (
    EvidenceSourceType,
    Importance,
    ResultCompleteness,
    ResultStatus,
    SafePointKind,
    SourceAuthority,
    ToolHealth,
)
from ..core.errors import ProtectedActionBlocked
from ..core.events import EventType
from ..core.provenance import Provenance
from ..domain.epistemic import Evidence
from ..engine.context import HarnessContext
from ..tools.base import TRANSIENT_ERROR_CLASSES, ToolRegistry, ToolResult
from .budget import update_budget


@dataclass
class ToolCallOutcome:
    tool_id: str
    operation: str
    result: ToolResult
    completeness: ResultCompleteness
    health: ToolHealth
    failure_signature: str | None
    attempt: int


def failure_signature(tool_id: str, dependency: str, operation_family: str, error_class: str | None) -> str:
    """v0.2.5 §8: tool + dependency + operation family + error class.

    Parameters are deliberately excluded, so re-calling the same failing dependency with
    different parameters is recognised as the same failure (no hidden retry).
    """
    return f"{tool_id}|{dependency}|{operation_family}|{error_class or 'UNKNOWN'}"


def assess_completeness(result: ToolResult) -> ResultCompleteness:
    """``SUCCESS ≠ COMPLETE`` (v0.2.5 §12)."""
    if result.is_mutation:
        return ResultCompleteness.NOT_APPLICABLE
    if result.status is ResultStatus.ERROR:
        return ResultCompleteness.PARTIAL if result.records else ResultCompleteness.UNKNOWN
    if result.pagination_complete is False or result.missing_fields:
        return ResultCompleteness.PARTIAL
    if result.required_coverage_period and result.coverage_period != result.required_coverage_period:
        return ResultCompleteness.PARTIAL
    if result.expected_count is None:
        return ResultCompleteness.UNKNOWN
    returned = result.returned_count if result.returned_count is not None else len(result.records)
    if returned < result.expected_count:
        return ResultCompleteness.PARTIAL
    return ResultCompleteness.COMPLETE


def _next_health(previous: ToolHealth, result: ToolResult, completeness: ResultCompleteness,
                 consecutive_failures: int) -> ToolHealth:
    if result.status is ResultStatus.ERROR:
        if result.error_class == "UNAVAILABLE" or consecutive_failures >= 2:
            return ToolHealth.UNAVAILABLE
        if result.error_class in TRANSIENT_ERROR_CLASSES:
            return ToolHealth.DEGRADED
        return ToolHealth.DEGRADED if previous is not ToolHealth.UNAVAILABLE else previous
    if completeness is ResultCompleteness.PARTIAL:
        return ToolHealth.DEGRADED
    return ToolHealth.HEALTHY


def invoke_tool(
    ctx: HarnessContext,
    registry: ToolRegistry,
    tool_id: str,
    operation: str,
    params: dict[str, Any] | None = None,
    *,
    operation_family: str | None = None,
) -> ToolCallOutcome:
    spec = registry.spec(tool_id)
    if not spec.read_only:
        raise ProtectedActionBlocked(f"{tool_id} is not read-only; mutations must pass the Mandatory Human Gate")
    ctx.runtime.current_tool = tool_id
    ctx.runtime.current_action = f"{tool_id}.{operation}"
    ctx.safe_point(SafePointKind.BEFORE_ACTION)

    result = registry.adapter(tool_id).call(operation, dict(params or {}))
    ctx.clock.advance(result.time_cost)
    update_budget(ctx)
    completeness = assess_completeness(result)

    tr = ctx.runtime.tool(tool_id)
    previous_health = tr.health
    tr.operation = operation
    tr.attempt += 1
    tr.last_result_status = result.status.value
    tr.last_error_class = result.error_class
    tr.retryable_hint = result.retryable_hint
    tr.partial_side_effect_possible = result.partial_side_effect_possible
    tr.result_completeness = completeness
    tr.result_authority = result.source_authority if result.status is ResultStatus.SUCCESS else tr.result_authority
    tr.time_cost = result.time_cost
    tr.cumulative_cost += result.time_cost
    tr.consecutive_failures = tr.consecutive_failures + 1 if result.status is ResultStatus.ERROR else 0
    tr.health = _next_health(previous_health, result, completeness, tr.consecutive_failures)

    signature = None
    event = ctx.emit(
        EventType.TOOL_CALLED,
        {"tool": tool_id, "operation": operation, "status": result.status.value,
         "completeness": completeness.value, "cost": result.time_cost},
        importance=Importance.LOW,
    )
    if result.status is ResultStatus.ERROR:
        signature = failure_signature(tool_id, spec.dependency, operation_family or operation, result.error_class)
        rec = ctx.runtime.recovery
        rec.active = True
        rec.failure_signature = signature
        rec.signature_failures[signature] = rec.signature_failures.get(signature, 0) + 1
        rec.mutation_uncertainty = rec.mutation_uncertainty or result.partial_side_effect_possible
        ctx.emit(
            EventType.TOOL_FAILED,
            {"tool": tool_id, "operation": operation, "attempt": tr.attempt, "error_class": result.error_class,
             "retryable_hint": result.retryable_hint, "signature": signature,
             "partial_side_effect_possible": result.partial_side_effect_possible},
            importance=Importance.NORMAL,
        )
    elif completeness is ResultCompleteness.PARTIAL:
        ctx.runtime.recovery.partial_result_status = ResultCompleteness.PARTIAL
        ctx.emit(EventType.PARTIAL_RESULT,
                 {"tool": tool_id, "operation": operation, "expected": result.expected_count,
                  "returned": result.returned_count, "pagination_complete": result.pagination_complete},
                 importance=Importance.HIGH)
    if tr.health is not previous_health:
        ctx.emit(EventType.TOOL_HEALTH_CHANGED,
                 {"tool": tool_id, "from": previous_health.value, "to": tr.health.value})
    tr.evidence_ref = f"ev:{tool_id}:{event.seq}"
    ctx.safe_point(SafePointKind.AFTER_TOOL_RESULT)
    return ToolCallOutcome(tool_id, operation, result, completeness, tr.health, signature, tr.attempt)


def evidence_from_outcome(
    ctx: HarnessContext,
    outcome: ToolCallOutcome,
    evidence_id: str,
    content: str,
    *,
    target_assertion: str | None = None,
    value: Any = None,
    is_fallback: bool = False,
) -> Evidence:
    """Turn a successful tool result into Evidence, carrying completeness and authority faithfully."""
    authority = outcome.result.source_authority
    if is_fallback:
        authority = SourceAuthority.NON_AUTHORITATIVE  # fallback never auto-promoted
    return Evidence(
        id=evidence_id,
        source_type=EvidenceSourceType.TOOL,
        source_id=outcome.tool_id,
        provenance=Provenance(
            EvidenceSourceType.TOOL,
            outcome.tool_id,
            method=outcome.operation,
            event_seq=ctx.runtime.event_refs[-1] if ctx.runtime.event_refs else None,
            recorded_at_minute=ctx.clock.now(),
        ),
        content=content,
        target_assertion=target_assertion,
        value=value,
        reliability="HIGH" if outcome.completeness is ResultCompleteness.COMPLETE else "LIMITED",
        completeness=outcome.completeness,
        authority=authority,
        is_fallback=is_fallback,
    )

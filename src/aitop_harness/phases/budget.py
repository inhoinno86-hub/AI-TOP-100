"""Budget Awareness + Release Reserve (Design Freeze §24-25, v0.2.5 §14-15).

Budget is a decision input: it gates discovery actions, retries, and new work, and it drives
real scope reduction when the Release Reserve becomes ACTIVE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    RESERVE_DROP_CLASSES,
    RESERVE_KEEP_CLASSES,
    ArtifactStatus,
    BudgetSlot,
    Importance,
    Phase,
    ReserveStatus,
    WorkClass,
)
from ..core.errors import HarnessError
from ..core.events import EventType
from ..domain.design import WorkItem
from ..engine.context import HarnessContext
from ..state.runtime import Plan
from ..supervision.monitoring import SignalKind

_PHASE_SLOT = {
    Phase.DISCOVER: BudgetSlot.DISCOVER,
    Phase.DEFINE: BudgetSlot.DEFINE,
    Phase.DESIGN: BudgetSlot.DESIGN,
    Phase.EXECUTE: BudgetSlot.EXECUTE,
    Phase.VERIFY: BudgetSlot.VERIFY,
    Phase.RELEASE: BudgetSlot.RELEASE,
}


class ReserveViolation(HarnessError):
    """Attempt to start droppable work while the Release Reserve is active."""


def update_budget(ctx: HarnessContext) -> None:
    """Refresh BudgetRuntime / ReleaseRuntime from the clock; emit variance and reserve signals."""
    plan = ctx.problem.budget
    br = ctx.runtime.budget_runtime
    rr = ctx.runtime.release_runtime
    now = ctx.clock.now()
    delta = max(0.0, now - br.elapsed)
    br.total_budget = plan.total_minutes
    br.elapsed = now
    br.remaining = max(0.0, plan.total_minutes - now)
    if not br.phase_budget:
        br.phase_budget = {s.slot.value: s.minutes for s in plan.slots}
    slot = _PHASE_SLOT[ctx.runtime.phase].value
    br.phase_spent[slot] = br.phase_spent.get(slot, 0.0) + delta

    # planned end of the current slot vs now → variance
    planned_end = plan.slot(_PHASE_SLOT[ctx.runtime.phase]).end_minute
    variance = now - planned_end
    previous_variance = br.phase_variance.get(slot, 0.0)
    br.phase_variance[slot] = variance
    verify_start = plan.slot(BudgetSlot.VERIFY).start_minute
    if ctx.runtime.phase in (Phase.VERIFY, Phase.RELEASE):
        br.verification_budget_remaining = max(0.0, br.remaining - plan.release_reserve_minutes)
    else:
        br.verification_budget_remaining = max(
            0.0,
            min(
                plan.slot(BudgetSlot.VERIFY).minutes,
                plan.total_minutes - plan.release_reserve_minutes - max(now, verify_start),
            ),
        )
    br.packaging_budget_remaining = min(br.remaining, plan.release_reserve_minutes)
    if variance > 0 and previous_variance <= 0:
        br.variance_reason = f"{slot} exceeded soft budget by {variance:.0f}m"
        br.release_reserve_impact = (
            "reserve threatened"
            if br.remaining - plan.release_reserve_minutes < plan.verification_floor_minutes
            else "reserve intact"
        )
        br.recovery_action = "reduce scope of current phase"
        event = ctx.emit(
            EventType.BUDGET_VARIANCE,
            {
                "slot": slot,
                "variance": variance,
                "reason": br.variance_reason,
                "recovery_action": br.recovery_action,
                "release_reserve_impact": br.release_reserve_impact,
            },
        )
        ctx.signal(SignalKind.BUDGET_VARIANCE, br.variance_reason, event_seq=event.seq)

    # reserve status
    rr.reserve_threshold = plan.release_reserve_minutes
    pending_kept = 0.0
    if ctx.runtime.current_plan:
        pending_kept = sum(
            w.est_minutes
            for w in ctx.runtime.current_plan.work_items
            if w.status == "PENDING" and (w.work_class in RESERVE_KEEP_CLASSES or w.release_blocking)
        )
    rr.projected_finish = now + pending_kept
    old_status = rr.reserve_status
    if br.remaining <= plan.release_reserve_minutes:
        new_status = ReserveStatus.ACTIVE
        if rr.projected_finish > plan.total_minutes:
            new_status = ReserveStatus.AT_RISK
    elif br.remaining <= plan.release_reserve_minutes + plan.reserve_approach_window_minutes:
        new_status = ReserveStatus.APPROACHING
    else:
        new_status = ReserveStatus.NOT_ACTIVE
    rr.reserve_status = new_status
    if new_status in (ReserveStatus.ACTIVE, ReserveStatus.AT_RISK) and rr.reserve_entered_at is None:
        rr.reserve_entered_at = now
        event = ctx.emit(
            EventType.RELEASE_RESERVE_ENTERED,
            {"minute": now, "remaining": br.remaining},
            importance=Importance.CRITICAL,
        )
        ctx.signal(SignalKind.RELEASE_RESERVE_ENTERED, f"remaining {br.remaining:.0f}m", event_seq=event.seq)
    if new_status is ReserveStatus.AT_RISK and old_status is not ReserveStatus.AT_RISK:
        rr.packaging_status = ArtifactStatus.AT_RISK
        ctx.signal(SignalKind.PACKAGING_AT_RISK, f"projected finish {rr.projected_finish:.0f}m > budget")


def reserve_active(ctx: HarnessContext) -> bool:
    return ctx.runtime.release_runtime.reserve_status in (ReserveStatus.ACTIVE, ReserveStatus.AT_RISK)


def set_plan(ctx: HarnessContext, plan: Plan) -> None:
    if reserve_active(ctx):
        for w in plan.work_items:
            _guard_reserve(w)
    ctx.runtime.current_plan = plan


def add_work_item(ctx: HarnessContext, item: WorkItem) -> None:
    """Release Reserve 중 nice-to-have feature 추가 금지."""
    if reserve_active(ctx):
        _guard_reserve(item)
    if ctx.runtime.current_plan is None:
        ctx.runtime.current_plan = Plan(id="PLAN-1")
    ctx.runtime.current_plan.work_items.append(item)


def _guard_reserve(item: WorkItem) -> None:
    if item.work_class in RESERVE_DROP_CLASSES or (
        item.work_class is WorkClass.CORE_FEATURE and not item.release_blocking
    ):
        raise ReserveViolation(f"release reserve active: cannot start {item.work_class.value} work {item.id}")


@dataclass
class ScopeReduction:
    kept: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def apply_release_reserve(ctx: HarnessContext) -> ScopeReduction:
    """Actual scope reduction on reserve entry: DROP droppable work, KEEP release-critical work."""
    reduction = ScopeReduction()
    plan = ctx.runtime.current_plan
    if not reserve_active(ctx) or plan is None:
        return reduction
    for w in plan.work_items:
        if w.status != "PENDING":
            continue
        keep = w.work_class in RESERVE_KEEP_CLASSES or w.release_blocking
        if keep:
            reduction.kept.append(w.id)
        else:
            w.status = "DROPPED"
            reduction.dropped.append(w.id)
    rr = ctx.runtime.release_runtime
    rr.kept_scope = sorted(set(rr.kept_scope) | set(reduction.kept))
    rr.dropped_scope = sorted(set(rr.dropped_scope) | set(reduction.dropped))
    if reduction.dropped:
        with ctx.commit("release reserve scope reduction", dropped_for_budget=reduction.dropped) as ps:
            if ps.solution_design is not None:
                descs = {w.id: w.description for w in plan.work_items}
                ps.solution_design.unfinished_scope += [
                    f"{d} (dropped for budget)" for d in (descs[i] for i in reduction.dropped)
                ]
        ctx.emit(
            EventType.SCOPE_DROPPED_FOR_BUDGET,
            {"dropped": reduction.dropped, "kept": reduction.kept},
            importance=Importance.HIGH,
        )
    return reduction


def retry_budget_ok(ctx: HarnessContext, estimated_cost: float) -> tuple[bool, str | None]:
    """Minimum verify / release budget must survive a retry."""
    plan = ctx.problem.budget
    remaining_after = ctx.runtime.budget_runtime.remaining - estimated_cost
    if reserve_active(ctx):
        return False, "RELEASE_RESERVE_WOULD_BE_VIOLATED"
    floor = plan.release_reserve_minutes
    if ctx.runtime.phase not in (Phase.VERIFY, Phase.RELEASE):
        floor += plan.verification_floor_minutes
    if remaining_after < floor:
        return False, "BUDGET_THREATENS_VERIFICATION"
    return True, None

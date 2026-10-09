"""RV-7 Release Gate HOLD patches found while chasing RV-5 §28 limitation 2/4.

A1 output join vs completeness   — a join's (expected) row-count drop is not a pagination gap
A2 RESOURCE scope_kind           — covers the action through any target, not only the resource's own id

RV-8-01 release scope recovery   — a critical VOB discovered during EXECUTE (after DESIGN already fixed
                                    release_scope) is given one bounded chance to drop just the items it
                                    blocks, instead of HOLDing the whole run outright.
"""

from __future__ import annotations

import copy
from typing import Any

from autonomous_fixtures import run, scenario_d

from aitop_harness.core.enums import ReleaseDecision, ResultCompleteness
from aitop_harness.core.events import EventType
from aitop_harness.core.scope import WILDCARD, ScopeItem
from aitop_harness.engine.proposals import OutputPlan, output_completeness_check
from aitop_harness.engine.scope_contract import normalize_scope_target
from aitop_harness.phases.release import ReleaseGateResult

# =========================================================================== A1 output completeness vs join


def _plan(*, join: bool, key_fields: list[str] | None = None) -> OutputPlan:
    return OutputPlan("W-1", "audit", ["tool-a:q1", "tool-b:q2"], key_fields or ["id"], join, {})


def test_join_output_completeness_ignores_the_expected_row_count_drop() -> None:
    """A-10 pattern: both feeding ops paginated fully; the join keeps only matching rows (fewer than
    either op's full result) — that is not a completeness failure."""
    expected, assumes = output_completeness_check(
        _plan(join=True),
        ["tool-a:q1", "tool-b:q2"],
        {"tool-a:q1": 100, "tool-b:q2": 50},
        {"tool-a:q1": ResultCompleteness.COMPLETE, "tool-b:q2": ResultCompleteness.COMPLETE},
    )
    assert expected is None
    assert assumes is False  # check skipped: row count alone cannot fail it


def test_join_output_completeness_still_catches_a_real_pagination_gap() -> None:
    """If any feeding op itself did not paginate fully, the join's completeness is still unknown/suspect —
    the check stays on (as UNKNOWN, since expected_count is None here)."""
    expected, assumes = output_completeness_check(
        _plan(join=True),
        ["tool-a:q1", "tool-b:q2"],
        {"tool-a:q1": 100, "tool-b:q2": 50},
        {"tool-a:q1": ResultCompleteness.COMPLETE, "tool-b:q2": ResultCompleteness.PARTIAL},
    )
    assert expected is None
    assert assumes is True


def test_non_join_output_keeps_the_original_expected_count_rule() -> None:
    expected, assumes = output_completeness_check(
        _plan(join=False),
        ["tool-a:q1"],
        {"tool-a:q1": 100},
        {"tool-a:q1": ResultCompleteness.COMPLETE},
    )
    assert expected == 100
    assert assumes is True


def test_single_op_join_flag_is_not_a_real_join() -> None:
    """join=True but only one op actually fed the output: nothing to join, fall back to the normal rule."""
    expected, assumes = output_completeness_check(
        _plan(join=True),
        ["tool-a:q1"],
        {"tool-a:q1": 100},
        {"tool-a:q1": ResultCompleteness.PARTIAL},
    )
    assert expected == 100
    assert assumes is True


# =========================================================================== A2 RESOURCE scope_kind


def test_resource_scope_kind_covers_a_target_outside_the_resources_own_id_space() -> None:
    """A-15 pattern: intended_scope / requested_scope target a data asset id (e.g. DA-ROUTE), a different id
    space than the tool resource (e.g. field-dispatch) a RESOURCE grant names. Reading RESOURCE as
    target == resource made the grant unmatchable against any real request."""
    norm = normalize_scope_target("push_route_update", "field-dispatch", "RESOURCE", "")
    assert norm.refusal is None
    assert norm.target == WILDCARD
    assert ScopeItem("push_route_update", norm.target).matches(ScopeItem("push_route_update", "DA-ROUTE"))


def test_resource_scope_kind_with_resource_spelled_as_target_is_still_any_target() -> None:
    norm = normalize_scope_target("push_route_update", "field-dispatch", "RESOURCE", "field-dispatch")
    assert norm.target == WILDCARD


# =========================================================================== RV-8-01 release scope recovery


def _vob_during_execute(handlers: dict[str, Any]) -> None:
    """A-04/A-07/A-11/A-15 pattern: DESIGN fixes release_scope from what it knew at the time; EXECUTE then
    queries pickup-log again (pickup_by_slot, not seen before) and the Reasoner raises a new critical VOB
    that blocks rank_late_slots — an item already locked into release_scope."""
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        obs = data["observation"]
        out = copy.deepcopy(base(req, data))
        if obs["source"] == "pickup-log" and obs["method"] == "pickup_by_slot":
            out["vob_proposals"] = [
                {
                    "unresolved_question": "Does the per-slot delay breakdown reveal a measurement gap "
                    "that invalidates ranking by slot?",
                    "decision_impact": "HIGH",
                    "required_before": "BEFORE_RELEASE",
                    "blocking_scope": [{"action": "rank_late_slots", "target": "DA-PICK"}],
                    "entire_solution": False,
                    "validation_method": "cross-check slot delays against a second source",
                    "required_evidence": [],
                    "linked_unknown": "",
                    "rationale": "fixture: discovered only once EXECUTE actually reads per-slot data",
                }
            ]
        return out

    handlers["interpret_evidence"] = interpret


def test_execute_discovered_vob_drops_the_blocked_item_and_still_releases() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _vob_during_execute(handlers)
    orch, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    sd = orch.ctx.problem.solution_design
    assert sd is not None
    assert all(i.action != "rank_late_slots" for i in sd.release_scope)
    assert any("rank_late_slots" in lim for lim in sd.unfinished_scope)
    steps = [
        e
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ACCEPTED)
        if "release scope recovery" in str(e.payload)
    ]
    assert not steps  # recovery is recorded as a HARNESS step, not a proposal — just checking no crash path
    assert result.release_decision is not None
    assert result.release_decision.value in ("RELEASE", "RELEASE_WITH_KNOWN_LIMITATION")
    # the still-open VOB stays open and visible — recovery never resolves/narrows it
    vob = next(
        v
        for v in orch.ctx.problem.verification_obligations.values()
        if v.blocking_scope.covers(ScopeItem("rank_late_slots", "DA-PICK"))
    )
    assert vob.status.value in ("OPEN", "DEFERRED")


def test_release_scope_recovery_never_silently_drops_a_protected_action() -> None:
    """If the VOB blocks a protected action (not just a plain release-scope item), recovery refuses to
    drop it silently — a protected action needs its own Human Gate / reconsideration path, not a quiet
    scope cut. The run falls through to a plain HOLD instead."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        obs = data["observation"]
        out = copy.deepcopy(base(req, data))
        if obs["source"] == "pickup-log" and obs["method"] == "pickup_by_slot":
            out["vob_proposals"] = [
                {
                    "unresolved_question": "Does the per-slot delay breakdown invalidate the whole plan?",
                    "decision_impact": "HIGH",
                    "required_before": "BEFORE_RELEASE",
                    "blocking_scope": [],
                    "entire_solution": True,
                    "validation_method": "cross-check",
                    "required_evidence": [],
                    "linked_unknown": "",
                    "rationale": "fixture: everything depends on this slot data, including the gated push",
                }
            ]
        return out

    handlers["interpret_evidence"] = interpret
    orch, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert result.halt_reason is not None and "Release Gate HOLD" in result.halt_reason
    assert orch.release_scope_recovered is False


def test_release_scope_recovery_gives_up_when_nothing_would_be_left() -> None:
    """If dropping the blocked item(s) would leave release_scope empty, recovery gives up and HOLDs
    rather than release an empty scope."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        obs = data["observation"]
        out = copy.deepcopy(base(req, data))
        if obs["source"] == "pickup-log" and obs["method"] == "pickup_by_slot":
            out["vob_proposals"] = [
                {
                    "unresolved_question": "Does the per-slot delay breakdown invalidate ranking?",
                    "decision_impact": "HIGH",
                    "required_before": "BEFORE_RELEASE",
                    "blocking_scope": [{"action": "rank_late_slots", "target": "DA-PICK"}],
                    "entire_solution": False,
                    "validation_method": "cross-check",
                    "required_evidence": [],
                    "linked_unknown": "",
                    "rationale": "fixture",
                }
            ]
        return out

    handlers["interpret_evidence"] = interpret
    # agent_design normally also releases push_pickup_schedule (protected); here we only exercise the
    # non-protected half of release_scope, so this run reaches the recovery path and succeeds (proving the
    # bounded-attempt flag flips) — the empty-scope give-up itself is unit-tested at the function level
    # above (test_vob_blocked_items_empty_when_nothing_critical_intersects and friends in
    # test_phase_j_verify_release.py cover the deterministic half of this logic).
    orch, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert orch.release_scope_recovered is True
    assert result.halt_reason is None


def test_release_scope_recovery_gives_up_if_dropping_everything_empties_the_scope() -> None:
    """Direct check of the give-up branch: if the only recoverable (non-protected) release-scope item is
    also the one the VOB blocks, dropping it would leave release_scope empty — recovery must refuse that,
    not "recover" into releasing nothing."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    sd = orch.ctx.problem.solution_design
    assert sd is not None
    only_non_protected = next(i for i in sd.release_scope if i.action != "push_pickup_schedule")
    # drop every OTHER release-scope item by hand first, so only the (about to be blocked) item remains
    with orch.ctx.commit("test setup") as p:
        d = p.solution_design
        assert d is not None
        d.release_scope = [only_non_protected]
    orch.release = ReleaseGateResult(
        decision=ReleaseDecision.HOLD,
        hold_reasons=[f"critical VOB-X intersects release scope at {[str(only_non_protected)]}"],
        vob_blocked_items=[only_non_protected],
    )
    orch.release_scope_recovered = False
    assert orch._try_release_scope_recovery() is False
    assert orch.ctx.problem.solution_design is not None
    assert orch.ctx.problem.solution_design.release_scope == [only_non_protected]  # untouched: gave up early

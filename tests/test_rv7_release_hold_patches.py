"""RV-7 Release Gate HOLD patches found while chasing RV-5 §28 limitation 2/4.

A1 output join vs completeness   — a join's (expected) row-count drop is not a pagination gap
A2 RESOURCE scope_kind           — covers the action through any target, not only the resource's own id
"""

from __future__ import annotations

from aitop_harness.core.enums import ResultCompleteness
from aitop_harness.core.scope import WILDCARD, ScopeItem
from aitop_harness.engine.proposals import OutputPlan, output_completeness_check
from aitop_harness.engine.scope_contract import normalize_scope_target

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

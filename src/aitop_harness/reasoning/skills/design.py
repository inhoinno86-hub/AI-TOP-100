"""DESIGN skills (prompt §14): Structural Remedy first, then Agent design, then the execution plan.

The order is enforced by the Core (``phases.design.DesignSession``): the agent question is only asked
after the structural remedies and their feasibility were recorded.
"""

from __future__ import annotations

from typing import Any

from .discover import catalog_view


def remedy_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {"state": view}


def agent_payload(
    view: dict[str, Any],
    feasibility: dict[str, Any],
    tool_surface: list[dict[str, Any]],
    *,
    feedback: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"state": view, "feasibility": feasibility, "tool_surface": tool_surface}
    if feedback:
        out["core_feedback"] = feedback
    return out


def plan_payload(
    view: dict[str, Any], catalog: list[Any], executed: set[str], mutating_tools: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "state": view,
        "catalog": catalog_view(catalog, set()),
        "already_executed": sorted(executed),
        "mutating_tools": mutating_tools,
    }


def reconsider_payload(view: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"state": view, "reconsideration": request}


def reconsider_fallback() -> dict[str, Any]:
    """No judgement available: the Reasoner's original exclusion stands."""
    return {
        "decision": "KEEP_EXCLUDED",
        "rationale": "deterministic fallback: the original release scope stands",
        "evidence_refs": [],
        "risks": [],
        "needed_evidence": "",
        "confidence": 0.0,
    }


def blocking_review_payload(view: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"state": view, "blocking_review": request}


def blocking_review_fallback() -> dict[str, Any]:
    """No judgement available: every block stays as it is."""
    return {"reviews": [], "confidence": 0.0}

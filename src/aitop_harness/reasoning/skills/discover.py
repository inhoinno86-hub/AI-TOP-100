"""DISCOVER skills: initial hypotheses, Information-Value inputs for catalog actions, hypothesis assessment.

The LLM never executes a tool: it chooses among catalog affordances and estimates their value; the Core
ranks (``phases.discover.rank_actions``) under budget / tool health / reprofile targeting and executes.
"""

from __future__ import annotations

from typing import Any


def hypothesis_init_payload(view: dict[str, Any]) -> dict[str, Any]:
    keep = (
        "scenario",
        "organizations",
        "stakeholders",
        "processes",
        "handoffs",
        "data_assets",
        "constraints",
        "goals",
        "claims",
    )
    return {"state": {k: view[k] for k in keep if k in view}}


def hypothesis_init_fallback(view: dict[str, Any]) -> dict[str, Any]:
    request = view["scenario"].get("initial_request", "") or "the requested solution"
    return {
        "framing_assertion": {
            "key": "request.framing",
            "value": "as_requested",
            "rationale": "deterministic fallback: requester framing kept as a claim",
        },
        "hypotheses": [
            {
                "key": "REQUESTER_FRAMING",
                "statement": f"The requester's framing is correct: {request}"[:600],
                "origin": "REQUESTER_FRAMING",
                "decision_impact": "MEDIUM",
                "rationale": "deterministic fallback",
                "discriminating_evidence": [],
            },
            {
                "key": "ROOT_CAUSE_UNKNOWN",
                "statement": "The operational root cause differs from the requested "
                "solution and must be established from data",
                "origin": "ALTERNATIVE",
                "decision_impact": "HIGH",
                "rationale": "deterministic fallback",
                "discriminating_evidence": [],
            },
        ],
        "confidence": 0.3,
    }


def catalog_view(catalog: list[Any], executed: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "ref": a.ref,
            "kind": a.kind.value,
            "target": a.target,
            "operation": a.operation,
            "description": a.description,
        }
        for a in catalog
        if a.ref not in executed and a.read_only
    ]


def discover_payload(
    view: dict[str, Any], catalog: list[Any], executed: set[str], failed: dict[str, str]
) -> dict[str, Any]:
    return {
        "state": view,
        "catalog": catalog_view(catalog, executed),
        "already_executed": sorted(executed),
        "failed_or_deferred": failed,
        "reprofile_targets": view["runtime"]["reprofile_targets"],
        "budget_remaining_minutes": view["runtime"]["budget_remaining_minutes"],
    }


def discover_fallback(catalog: list[Any], executed: set[str]) -> dict[str, Any]:
    """Deterministic-first default: tool queries before interviews, neutral factors, no hypothesis links."""
    actions = []
    for a in catalog:
        if a.ref in executed or not a.read_only:
            continue
        tool = a.kind.value == "TOOL_QUERY"
        actions.append(
            {
                "catalog_ref": a.ref,
                "question": a.operation,
                "decision_impact": 0.5 if tool else 0.4,
                "uncertainty": 0.5,
                "discriminative_power": 0.4,
                "answerability": 0.8 if tool else 0.6,
                "process_data_handoff_impact": 0.3,
                "action_proximity": 0.2,
                "constraint_risk": 0.0,
                "estimated_cost_minutes": 3.0 if tool else 5.0,
                "expected_information_gain": "deterministic fallback estimate",
                "decision_impact_rationale": "deterministic fallback estimate",
                "discriminates_hypotheses": [],
                "resolves_unknowns": [],
                "addresses": [],
                "why_now": "deterministic fallback",
            }
        )
    return {"actions": actions, "stop": not actions, "stop_reason": "deterministic fallback"}


def assess_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {"state": view}


def assess_fallback(view: dict[str, Any]) -> dict[str, Any]:
    """Rule: authoritative contradiction ⇒ REJECTED; independent support and no contradiction ⇒ SUPPORTED."""
    ev = view["evidence"]

    def strong(eid: str) -> bool:
        e = ev.get(eid, {})
        return (
            e.get("authority") == "AUTHORITATIVE"
            and e.get("source_type") != "STAKEHOLDER"
            and e.get("completeness") in ("COMPLETE", "NOT_APPLICABLE")
            and e.get("status") == "ACTIVE"
        )

    updates = []
    for hid, h in view["hypotheses"].items():
        contra = [e for e in h["contradicting"] if strong(e)]
        support = [e for e in h["supporting"] if ev.get(e, {}).get("source_type") != "STAKEHOLDER"]
        if contra and h["status"] != "REJECTED":
            updates.append(
                {
                    "hypothesis": hid,
                    "status": "REJECTED",
                    "rationale": "deterministic: strong contradicting evidence",
                    "evidence_refs": contra,
                }
            )
        elif support and not h["contradicting"] and h["status"] == "CANDIDATE":
            updates.append(
                {
                    "hypothesis": hid,
                    "status": "SUPPORTED",
                    "rationale": "deterministic: independent support, no contradiction",
                    "evidence_refs": support,
                }
            )
    return {"updates": updates, "ready_to_define": True, "rationale": "deterministic fallback"}

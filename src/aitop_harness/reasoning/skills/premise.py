"""Premise Check skill (IDR-RV4-01/02): canonical premises vs one new authoritative observation.

The Core enumerates the premises of the ACTIVE canonical Problem (root problem, causal chain, premise
hypotheses, premise evidence readings, assumptions) and the Reasoner judges each one. The verdict is advisory:
``engine.premise`` routes only Core-consistent invalidation claims into the existing canonical challenge path.
"""

from __future__ import annotations

from typing import Any


def premise_payload(
    view: dict[str, Any],
    problem: dict[str, Any],
    premises: list[dict[str, Any]],
    new_evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "state": view,
        "problem": problem,
        "premises": premises,
        "new_evidence": new_evidence,
        "existing_conflicts": view.get("conflicts", {}),
        "existing_evidence_revisions": view.get("evidence_revisions", {}),
    }


def premise_fallback(problem: dict[str, Any], premises: list[dict[str, Any]]) -> dict[str, Any]:
    """Degrade safely: no judgement means no challenge claim (the Core's structured monitoring still runs)."""
    return {
        "problem_id": str(problem.get("id", "")) or "PD",
        "problem_version": int(problem.get("version", 1) or 1),
        "premises": [
            {
                "premise_id": p["premise_id"],
                "relation": "NOT_ADDRESS",
                "materiality": "LOW",
                "affected_layer": p.get("layer", "PROBLEM_PREMISE"),
                "problem_invalidating": False,
                "evidence_refs": [],
                "rationale": "deterministic fallback (no premise judgement available)",
            }
            for p in premises
        ],
        "overall_assessment": "UNCERTAIN",
        "rationale": "deterministic fallback",
        "confidence": 0.0,
    }

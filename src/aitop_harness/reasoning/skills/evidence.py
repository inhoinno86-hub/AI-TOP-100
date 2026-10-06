"""Evidence interpretation skill (prompt §12, §16): semantics of one new observation.

The observation text itself is rendered by the Core; the Reasoner only proposes its *meaning*.
"""

from __future__ import annotations

from typing import Any

from .discover import catalog_view


def interpret_payload(
    view: dict[str, Any],
    observation: dict[str, Any],
    catalog: list[Any],
    executed: set[str],
    failed: dict[str, str],
) -> dict[str, Any]:
    return {
        "state": view,
        "observation": observation,
        "known_assertions": view.get("known_assertions", {}),
        "catalog": catalog_view(catalog, executed),
        "failed_or_deferred": failed,
    }


def interpret_fallback() -> dict[str, Any]:
    """Degrade safely: the observation is committed with no semantics (no links, no challenge claim)."""
    return {
        "interpretation": "(no semantic interpretation available — deterministic fallback)",
        "hypothesis_effects": [],
        "new_hypotheses": [],
        "fact_candidates": [],
        "unknown_resolutions": [],
        "authorization_candidates": [],
        "contradiction_assessment": {
            "relation": "UNRELATED",
            "target_type": "NONE",
            "target_refs": [],
            "materiality": "LOW",
            "problem_invalidating": False,
            "rationale": "deterministic fallback",
        },
        "vob_proposals": [],
        "follow_up_actions": [],
        "confidence": 0.0,
    }

"""Recovery / Redefine skills (prompt §15, §17-19): revision wording + transition / reprofile proposal.

The Core decides which evidence needs re-interpretation (canonical challenge), the revision kind, and
whether a transition is valid. The Reasoner writes the revised interpretation and proposes the transition.
"""

from __future__ import annotations

from typing import Any

from .discover import catalog_view


def revise_payload(view: dict[str, Any], challenge_evidence: str, proposed: list[str]) -> dict[str, Any]:
    ev = view["evidence"]
    return {
        "state": view,
        "challenge_evidence": {"id": challenge_evidence, **ev.get(challenge_evidence, {})},
        "proposed_for_revision": [{"id": e, **ev.get(e, {})} for e in proposed],
    }


def transition_payload(
    view: dict[str, Any], trigger: dict[str, Any], catalog: list[Any], executed: set[str]
) -> dict[str, Any]:
    return {"state": view, "trigger": trigger, "reprofile_catalog": catalog_view(catalog, executed)}

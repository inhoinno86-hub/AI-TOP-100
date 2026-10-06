"""Skill definitions: per-skill input payload builders + deterministic fallbacks.

Skills operate only on *detached views* (plain dicts built by ``engine.views``) — never on a
``HarnessContext``. ``ESSENTIAL`` lists skills that keep running inside the Release Reserve; the others
are dropped there (reasoning scope reduction, prompt §36 A16).
"""

from __future__ import annotations

ESSENTIAL: frozenset[str] = frozenset(
    {
        "interpret_evidence",
        "define_problem",
        "structural_remedy",
        "agent_design",
        "plan_execution",
        "revise_evidence",
        "propose_transition",
    }
)

NON_ESSENTIAL: frozenset[str] = frozenset(
    {"hypothesis_init", "discover_actions", "assess_hypotheses", "semantic_judge", "release_summary"}
)

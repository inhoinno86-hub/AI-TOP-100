"""Scenario input → initial canonical state + tools + vertical-slice inputs.

JSON format (all objects use the same field names as the dataclasses):

    {"scenario": {...Scenario},
     "problem": {"organizations": {...}, "stakeholders": {...}, ...ProblemState collections},
     "tools": [{"tool_id", "dependency", "read_only", "authority", "fallback_for",
                "script": {"<operation>": [ToolResult, ...]}}],
     "discovery_actions": [{"id", "kind", "target", "question", "factors": {...}, "tool_id",
                            "evidence": {...Evidence}, "supports": [hypothesis ids]}],
     "problem_definition": {...ProblemDefinition},
     "design_inputs": {...DesignInputs},
     "release_scope": [{"action", "target"}]}
"""

from __future__ import annotations

import typing
from typing import Any

from .core.enums import SourceAuthority
from .core.scope import ScopeItem
from .core.serialization import convert, from_dict
from .domain.design import ProblemDefinition
from .domain.epistemic import Evidence
from .engine.context import HarnessContext
from .engine.slice import SliceInputs
from .phases.budget import update_budget
from .phases.design import DesignInputs
from .phases.discover import DiscoveryAction
from .phases.execute import ToolCallOutcome
from .state.problem import TRACKED_COLLECTIONS, ProblemState, Scenario
from .tools.base import ToolRegistry, ToolResult, ToolSpec
from .tools.simulated import ScriptedTool


def load_context(data: dict[str, Any]) -> HarnessContext:
    problem = ProblemState(scenario=from_dict(Scenario, data["scenario"]))
    collections = data.get("problem", {})
    unknown = set(collections) - set(TRACKED_COLLECTIONS)
    if unknown:
        raise ValueError(f"unknown ProblemState collections: {sorted(unknown)}")
    hints = typing.get_type_hints(ProblemState)
    for name, items in collections.items():
        setattr(problem, name, convert(hints[name], items))
    ctx = HarnessContext(problem=problem)
    update_budget(ctx)
    return ctx


def load_registry(data: dict[str, Any]) -> ToolRegistry:
    reg = ToolRegistry()
    for t in data.get("tools", []):
        script = {
            op: [from_dict(ToolResult, r) for r in results] for op, results in t.get("script", {}).items()
        }
        tool = ScriptedTool(t["tool_id"], read_only=t.get("read_only", True), script=script)
        reg.register(
            tool,
            ToolSpec(
                t["tool_id"],
                t.get("dependency", t["tool_id"]),
                t.get("read_only", True),
                SourceAuthority(t.get("authority", "UNKNOWN")),
                t.get("fallback_for"),
            ),
        )
    return reg


def load_slice_inputs(data: dict[str, Any]) -> SliceInputs:
    actions: list[DiscoveryAction] = []
    evidence_by_action: dict[str, tuple[dict[str, Any], list[str]]] = {}
    for a in data.get("discovery_actions", []):
        spec = {k: v for k, v in a.items() if k not in ("evidence", "supports")}
        actions.append(from_dict(DiscoveryAction, spec))
        if "evidence" in a:
            evidence_by_action[a["id"]] = (a["evidence"], list(a.get("supports", [])))

    def build(action: DiscoveryAction, outcome: ToolCallOutcome | None) -> tuple[Evidence, list[str]] | None:
        if action.id not in evidence_by_action:
            return None
        raw, supports = evidence_by_action[action.id]
        ev = from_dict(Evidence, raw)
        if outcome is not None:  # completeness/authority come from the observed result, not the script
            ev.completeness = outcome.completeness
            ev.authority = outcome.result.source_authority
        return ev, supports

    pd_raw = data["problem_definition"]
    return SliceInputs(
        actions=actions,
        evidence_builder=build,
        problem_definition=lambda _ctx: from_dict(ProblemDefinition, pd_raw),
        design_inputs=from_dict(DesignInputs, data["design_inputs"]),
        release_scope=[from_dict(ScopeItem, i) for i in data.get("release_scope", [])],
    )

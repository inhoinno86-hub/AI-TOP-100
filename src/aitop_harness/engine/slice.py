"""Thin end-to-end vertical slice (kickoff PHASE B).

Scenario → state init → DISCOVER action → evidence integration → State Diff → DEFINE Gate →
minimal DESIGN → minimal VERIFY → RELEASE / HOLD, wired through the real phase modules.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..core.enums import DefineGateResult, ReleaseDecision
from ..core.events import EventType
from ..core.scope import ScopeItem
from ..domain.design import ProblemDefinition, SolutionDesign
from ..domain.epistemic import Evidence
from ..phases.define import DefineGateOutcome, apply_define_gate, define_problem, evaluate_define_gate
from ..phases.design import DesignInputs, design_solution
from ..phases.discover import DiscoveryAction, integrate_evidence, select_next_action
from ..phases.execute import ToolCallOutcome, invoke_tool
from ..phases.release import ReleaseGateResult, evaluate_release_gate
from ..phases.verify import OutputSpec, VerifyReport, run_verify
from ..supervision.projection import refresh
from ..tools.base import ToolRegistry
from .context import HarnessContext
from .controller import PhaseController

EvidenceBuilder = Callable[[DiscoveryAction, ToolCallOutcome | None], tuple[Evidence, list[str]] | None]


@dataclass
class SliceInputs:
    actions: list[DiscoveryAction]
    evidence_builder: EvidenceBuilder
    problem_definition: Callable[[HarnessContext], ProblemDefinition]
    design_inputs: DesignInputs
    release_scope: list[ScopeItem]
    outputs: list[OutputSpec] = field(default_factory=list)
    max_discovery_steps: int = 5


@dataclass
class SliceResult:
    discovered: list[str]
    define: DefineGateOutcome
    design: SolutionDesign | None = None
    verify: VerifyReport | None = None
    release: ReleaseGateResult | None = None

    @property
    def decision(self) -> ReleaseDecision:
        return self.release.decision if self.release else ReleaseDecision.HOLD


def run_vertical_slice(ctx: HarnessContext, registry: ToolRegistry, inputs: SliceInputs) -> SliceResult:
    controller = PhaseController(ctx)
    ctx.emit(EventType.SCENARIO_LOADED, {"scenario": ctx.problem.scenario.id})
    remaining = list(inputs.actions)
    discovered: list[str] = []
    for _ in range(inputs.max_discovery_steps):
        action = select_next_action(ctx, remaining)
        if action is None:
            break
        remaining.remove(action)
        outcome = None
        if action.tool_id is not None:
            outcome = invoke_tool(ctx, registry, action.tool_id, action.question)
        built = inputs.evidence_builder(action, outcome)
        if built is not None:
            evidence, supports = built
            integrate_evidence(ctx, evidence, supports=supports)
        discovered.append(action.id)
    refresh(ctx)

    define_problem(ctx, inputs.problem_definition(ctx))
    controller.advance()  # → DEFINE
    gate = evaluate_define_gate(ctx, registry)
    apply_define_gate(ctx, gate)
    result = SliceResult(discovered=discovered, define=gate)
    if gate.result is DefineGateResult.FAIL:
        controller.hold("DEFINE Gate FAIL")
        refresh(ctx)
        return result

    controller.advance()  # → DESIGN
    result.design = design_solution(ctx, inputs.design_inputs)
    controller.advance()  # → EXECUTE (minimal: no protected actions in the thin slice)
    controller.advance()  # → VERIFY
    result.verify = run_verify(ctx, inputs.release_scope, outputs=inputs.outputs)
    controller.advance()  # → RELEASE
    result.release = evaluate_release_gate(ctx, result.verify, inputs.release_scope)
    if result.release.decision is ReleaseDecision.HOLD:
        controller.hold("Release Gate HOLD")
    else:
        controller.finish()
    refresh(ctx)
    return result

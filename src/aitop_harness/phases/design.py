"""DESIGN — Structural Remedy before Agent (Design Freeze §15-18).

Order is enforced in code:
ROOT_PROBLEM → STRUCTURAL_REMEDY → FEASIBILITY → WHY_AGENT → AGENT_ROLE → AGENTIFICATION_GATE.
Time pressure is not a reason to skip structural remedy consideration. Deterministic-first.
Tool failure never makes the design more agentic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.enums import (
    DESIGN_STAGE_ORDER,
    AgentRole,
    DesignStage,
    ProblemDefinitionStatus,
)
from ..core.errors import DesignOrderError
from ..core.events import EventType
from ..core.scope import ScopeItem
from ..domain.design import (
    AgentificationGateRecord,
    AgentSpec,
    DesignTraceEntry,
    SolutionDesign,
    StructuralRemedyCandidate,
)
from ..engine.context import HarnessContext

# How "agentic" each role is — used to refuse tool-failure-driven expansion.
_AGENTIC_RANK = {
    AgentRole.CONTROL_DETECTION: 1,
    AgentRole.EXCEPTION_HANDLER: 2,
    AgentRole.BRIDGE: 3,
    AgentRole.PRIMARY_SOLUTION: 4,
}


@dataclass
class DesignInputs:
    structural_remedies: list[StructuralRemedyCandidate]
    deterministic_rules_cover_cases: bool
    llm_reasoning_adds_value: bool
    autonomous_iteration_adds_value: bool = False
    residual_exceptions: bool = True
    detection_needed: bool = True
    why_agent: str | None = None
    bridge_sunset_condition: str | None = None
    deterministic_components: list[str] = field(default_factory=list)
    release_scope: list[ScopeItem] = field(default_factory=list)
    minimum_useful_scope: list[ScopeItem] = field(default_factory=list)
    scope_dependencies: dict[str, list[str]] = field(default_factory=dict)


class DesignSession:
    """Step-wise design with frozen-order enforcement."""

    def __init__(self, ctx: HarnessContext, design_id: str = "SD-1") -> None:
        pd = ctx.problem.problem_definition
        if pd is None or pd.status is not ProblemDefinitionStatus.ACTIVE:
            raise DesignOrderError("DESIGN requires an ACTIVE problem definition (DEFINE Gate passed)")
        self.ctx = ctx
        self.design = SolutionDesign(id=design_id, problem_ref=pd.id, problem_version=pd.version)
        self._next = 0

    # ------------------------------------------------------------------ ordering

    def _record(self, stage: DesignStage, summary: str, **details: object) -> None:
        expected = DESIGN_STAGE_ORDER[self._next] if self._next < len(DESIGN_STAGE_ORDER) else None
        if stage is not expected:
            raise DesignOrderError(f"design stage {stage.value} attempted before {expected}")
        self.design.trace.append(DesignTraceEntry(stage, summary, dict(details)))
        self.ctx.emit(EventType.DESIGN_STAGE_RECORDED, {"stage": stage.value, "summary": summary})
        self._next += 1

    # ------------------------------------------------------------------ stages

    def root_problem(self) -> None:
        pd = self.ctx.problem.problem_definition
        assert pd is not None
        self._record(DesignStage.ROOT_PROBLEM, pd.root_problem, requested_solution=pd.requested_solution)

    def structural_remedies(self, candidates: list[StructuralRemedyCandidate]) -> None:
        if not candidates:
            raise DesignOrderError("at least one structural remedy candidate must be considered and recorded")
        self.design.structural_remedies = list(candidates)
        self._record(
            DesignStage.STRUCTURAL_REMEDY,
            f"{len(candidates)} candidate(s)",
            removes_root_cause=[c.id for c in candidates if c.removes_root_cause],
        )

    def feasibility(self) -> tuple[bool, bool]:
        removes = any(c.removes_root_cause and c.constraint_feasible for c in self.design.structural_remedies)
        feasible = any(
            c.removes_root_cause and c.constraint_feasible and c.feasible_in_contest_time
            for c in self.design.structural_remedies
        )
        self._record(DesignStage.FEASIBILITY, f"removes_root_cause={removes} feasible_in_time={feasible}")
        return removes, feasible

    def why_agent(self, reason: str | None) -> None:
        self.design.why_agent = reason
        self._record(DesignStage.WHY_AGENT, reason or "no agent justification")

    def agent_roles(self, inputs: DesignInputs, removes: bool, feasible: bool) -> list[AgentRole]:
        roles = classify_roles(inputs, removes, feasible)
        if AgentRole.BRIDGE in roles and not inputs.bridge_sunset_condition:
            raise DesignOrderError("BRIDGE role requires a sunset condition")
        self.design.agent_roles = roles
        self.design.bridge_sunset_condition = inputs.bridge_sunset_condition
        self._record(DesignStage.AGENT_ROLE, ", ".join(r.value for r in roles) or "no agent")
        return roles

    def agentification_gate(
        self, inputs: DesignInputs, removes: bool, feasible: bool
    ) -> AgentificationGateRecord:
        justified = bool(self.design.agent_roles) and inputs.llm_reasoning_adds_value
        if self.design.agent_roles and not justified:
            # deterministic-first: no LLM value ⇒ no agent
            self.design.agent_roles = []
        record = AgentificationGateRecord(
            structural_change_removes_root_cause=removes,
            structural_change_feasible_in_time=feasible,
            deterministic_rules_cover_cases=inputs.deterministic_rules_cover_cases,
            llm_reasoning_adds_value=inputs.llm_reasoning_adds_value,
            autonomous_iteration_adds_value=inputs.autonomous_iteration_adds_value,
            agent_justified=justified,
            rationale="single-pass agent"
            if not inputs.autonomous_iteration_adds_value
            else "iterative agent",
        )
        self.design.agentification = record
        self._record(DesignStage.AGENTIFICATION_GATE, f"agent_justified={justified}")
        self.ctx.emit(
            EventType.AGENTIFICATION_GATE_RESULT,
            {"agent_justified": justified, "roles": [r.value for r in self.design.agent_roles]},
        )
        return record

    def finalize(self, inputs: DesignInputs) -> SolutionDesign:
        if self._next != len(DESIGN_STAGE_ORDER):
            raise DesignOrderError("design not complete: Agentification Gate not recorded")
        self.design.deterministic_components = list(inputs.deterministic_components)
        self.design.release_scope = list(inputs.release_scope)
        self.design.minimum_useful_scope = list(inputs.minimum_useful_scope)
        self.design.scope_dependencies = {k: list(v) for k, v in inputs.scope_dependencies.items()}
        self.design.unfinished_scope = [
            c.description
            for c in self.design.structural_remedies
            if c.removes_root_cause and not c.feasible_in_contest_time
        ]
        pd = self.ctx.problem.problem_definition
        assert pd is not None
        spec = None
        if self.design.agent_roles:
            spec = AgentSpec(
                identity=f"agent-{self.design.id}",
                problem_reference=f"{pd.id}@v{pd.version}",
                structural_role=list(self.design.agent_roles),
                success_criteria=list(pd.success_criteria),
                # only obligations relevant to the active Problem version (D9)
                verification_obligations=[
                    v.id for v in self.ctx.problem.open_vobs() if v.applies_to(pd.id, pd.version)
                ],
                human_gate=list(pd.protected_actions),
            )
        with self.ctx.commit(f"solution design {self.design.id}") as ps:
            ps.solution_design = self.design
            ps.agent_spec = spec
        return self.design


def classify_roles(inputs: DesignInputs, removes: bool, feasible: bool) -> list[AgentRole]:
    """Deterministic-first role classification (Design Freeze §16-17)."""
    roles: list[AgentRole] = []
    if removes and feasible:
        # structural remedy is the primary solution; agent at most monitors / handles exceptions
        if inputs.detection_needed:
            roles.append(AgentRole.CONTROL_DETECTION)
        if inputs.residual_exceptions and inputs.llm_reasoning_adds_value:
            roles.append(AgentRole.EXCEPTION_HANDLER)
    elif removes and not feasible:
        # cannot ship the structural fix in time: bridge until it lands
        roles.append(AgentRole.BRIDGE)
        if inputs.detection_needed:
            roles.append(AgentRole.CONTROL_DETECTION)
        if inputs.residual_exceptions and inputs.llm_reasoning_adds_value:
            roles.append(AgentRole.EXCEPTION_HANDLER)
    elif inputs.deterministic_rules_cover_cases:
        if inputs.detection_needed:
            roles.append(AgentRole.CONTROL_DETECTION)
        if inputs.residual_exceptions and inputs.llm_reasoning_adds_value:
            roles.append(AgentRole.EXCEPTION_HANDLER)
    elif inputs.llm_reasoning_adds_value:
        roles.append(AgentRole.PRIMARY_SOLUTION)
    return roles


def design_solution(ctx: HarnessContext, inputs: DesignInputs, design_id: str = "SD-1") -> SolutionDesign:
    session = DesignSession(ctx, design_id)
    session.root_problem()
    session.structural_remedies(inputs.structural_remedies)
    removes, feasible = session.feasibility()
    session.why_agent(inputs.why_agent)
    session.agent_roles(inputs, removes, feasible)
    session.agentification_gate(inputs, removes, feasible)
    return session.finalize(inputs)


def refuse_agentic_expansion_on_tool_failure(
    current: list[AgentRole], proposed: list[AgentRole]
) -> list[AgentRole]:
    """Tool failure must not make the design more agentic (Design Freeze §17)."""
    cur = max((_AGENTIC_RANK[r] for r in current), default=0)
    new = max((_AGENTIC_RANK[r] for r in proposed), default=0)
    if new > cur or set(proposed) - set(current):
        raise DesignOrderError("tool failure cannot expand agent roles; replan within existing roles")
    return proposed

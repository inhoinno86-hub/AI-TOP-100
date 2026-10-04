"""Phase Controller — explicit transitions only (Design Freeze §2, §21; v0.2.4 §25).

ADVANCE follows DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY → RELEASE with guards.
Conditional transitions keep their distinct meaning:
RETRY (stay), REPLAN (new path, same Problem), REPROFILE (targeted DISCOVER, then return),
REDEFINE (authoritative evidence invalidated the Problem → DEFINE), ABORT, FINISH.
REQUEST_CONTEXT is not a transition.
"""

from __future__ import annotations

from ..core.enums import (
    PHASE_ORDER,
    DefineGateResult,
    DesignStage,
    EvidenceStatus,
    ExecutionStatus,
    Importance,
    Phase,
    ProblemDefinitionStatus,
    ReleaseDecision,
    RequiredBefore,
    SafePointKind,
    SourceAuthority,
    TransitionKind,
)
from ..core.errors import IllegalTransitionError
from ..core.events import EventType
from ..domain.design import DecisionRecord
from ..state.runtime import Plan
from ..supervision.monitoring import SignalKind
from ..phases.budget import update_budget
from .context import HarnessContext


class PhaseController:
    def __init__(self, ctx: HarnessContext) -> None:
        self.ctx = ctx
        self._reprofile_return: Phase | None = None

    # ------------------------------------------------------------------ helpers

    def _move(self, kind: TransitionKind, target: Phase, rationale: str, **payload: object) -> None:
        ctx = self.ctx
        if ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL:
            ctx.emit(EventType.TRANSITION_REJECTED, {"kind": kind.value, "reason": "WAITING_APPROVAL"})
            raise IllegalTransitionError("cannot transition while a protected action is WAITING_APPROVAL")
        update_budget(ctx)  # attribute elapsed time to the phase being left
        ctx.safe_point(SafePointKind.BEFORE_TRANSITION)
        source = ctx.runtime.phase
        ctx.runtime.phase = target
        ctx.runtime.transition_candidate = None
        if ctx.runtime.execution_status in (ExecutionStatus.IDLE, ExecutionStatus.RECOVERING):
            ctx.runtime.execution_status = ExecutionStatus.RUNNING
        event = ctx.emit(
            EventType.PHASE_TRANSITION,
            {"kind": kind.value, "from": source.value, "to": target.value, "rationale": rationale, **payload},
            importance=Importance.HIGH if kind is not TransitionKind.ADVANCE else Importance.NORMAL,
        )
        ctx.signal(SignalKind.PHASE_CHECKPOINT, f"{kind.value}: {source.value} → {target.value}", event_seq=event.seq)

    def _reject(self, kind: TransitionKind, reason: str) -> None:
        self.ctx.emit(EventType.TRANSITION_REJECTED, {"kind": kind.value, "reason": reason})
        raise IllegalTransitionError(reason)

    # ------------------------------------------------------------------ advance

    def advance(self) -> Phase:
        ps, phase = self.ctx.problem, self.ctx.runtime.phase
        if phase is Phase.RELEASE:
            self._reject(TransitionKind.ADVANCE, "RELEASE is terminal; use finish()")
        target = PHASE_ORDER[PHASE_ORDER.index(phase) + 1]
        pd = ps.problem_definition
        if target is Phase.DEFINE and pd is None:
            self._reject(TransitionKind.ADVANCE, "DISCOVER → DEFINE requires a draft problem definition")
        if target is Phase.DESIGN:
            if pd is None or pd.gate_result not in (DefineGateResult.PASS, DefineGateResult.CONDITIONAL_PASS):
                self._reject(TransitionKind.ADVANCE, "DEFINE Gate has not passed")
        if target is Phase.EXECUTE:
            sd = ps.solution_design
            if sd is None or not sd.trace or sd.trace[-1].stage is not DesignStage.AGENTIFICATION_GATE:
                self._reject(TransitionKind.ADVANCE, "design incomplete: Agentification Gate not recorded")
            assert pd is not None and sd is not None
            if sd.problem_version != pd.version:
                self._reject(TransitionKind.ADVANCE, "solution design is stale for the current problem version")
            blocking = [v.id for v in ps.open_vobs()
                        if v.required_before is RequiredBefore.BEFORE_DESIGN_FINALIZATION
                        and v.blocking_scope.intersect(sd.release_scope)]
            if blocking:
                self._reject(TransitionKind.ADVANCE, f"VOBs required before design finalization open: {blocking}")
        if target is Phase.VERIFY and self.ctx.runtime.pending_protected_action is not None:
            self._reject(TransitionKind.ADVANCE, "protected action pending")
        if target is Phase.RELEASE and not ps.validation.verify_runs:
            self._reject(TransitionKind.ADVANCE, "VERIFY has not run")
        self._move(TransitionKind.ADVANCE, target, f"{phase.value} complete")
        return target

    # ------------------------------------------------------------------ conditional transitions

    def retry(self, rationale: str) -> None:
        if self.ctx.runtime.phase is not Phase.EXECUTE:
            self._reject(TransitionKind.RETRY, "retry applies to execution of the same path")
        if self.ctx.runtime.recovery.retry_eligible is not True:
            self._reject(TransitionKind.RETRY, "retry not eligible (bounded by evidence and budget)")
        self._move(TransitionKind.RETRY, Phase.EXECUTE, rationale)

    def replan(self, rationale: str, *, new_plan: Plan | None = None, to_design: bool = False) -> None:
        pd = self.ctx.problem.problem_definition
        if pd is None or pd.status is not ProblemDefinitionStatus.ACTIVE:
            self._reject(TransitionKind.REPLAN, "replan requires a valid canonical Problem")
        if new_plan is not None:
            old = self.ctx.runtime.current_plan
            new_plan.version = (old.version + 1) if old else new_plan.version
            self.ctx.runtime.current_plan = new_plan
        self._move(TransitionKind.REPLAN, Phase.DESIGN if to_design else Phase.EXECUTE, rationale)

    def reprofile(self, targets: list[str], rationale: str) -> None:
        if not targets:
            self._reject(TransitionKind.REPROFILE, "reprofile must be targeted (no broad rediscovery)")
        self._reprofile_return = self.ctx.runtime.phase
        self.ctx.runtime.reprofile_targets = list(targets)
        self._move(TransitionKind.REPROFILE, Phase.DISCOVER, rationale, targets=list(targets))

    def return_from_reprofile(self) -> Phase:
        if self._reprofile_return is None or self.ctx.runtime.phase is not Phase.DISCOVER:
            self._reject(TransitionKind.REPROFILE, "no reprofile in progress")
        target = self._reprofile_return
        assert target is not None
        self._reprofile_return = None
        self.ctx.runtime.reprofile_targets = []
        self._move(TransitionKind.REPROFILE, target, "targeted reprofile complete")
        return target

    def redefine(self, invalidating_evidence: str, rationale: str) -> None:
        """New authoritative Evidence invalidates the canonical Problem (never tool failure alone)."""
        ctx, ps = self.ctx, self.ctx.problem
        e = ps.evidence.get(invalidating_evidence)
        if e is None or e.status is not EvidenceStatus.ACTIVE or e.authority is not SourceAuthority.AUTHORITATIVE \
                or e.is_fallback:
            self._reject(TransitionKind.REDEFINE,
                         "redefine requires committed, active, authoritative, non-fallback evidence")
        pd = ps.problem_definition
        if pd is None:
            self._reject(TransitionKind.REDEFINE, "no canonical Problem to redefine")
        assert pd is not None
        with ctx.commit(f"redefine: problem {pd.id} v{pd.version} invalidated") as p:
            current = p.problem_definition
            assert current is not None
            current.status = ProblemDefinitionStatus.INVALIDATED
            current.invalidated_by.append(invalidating_evidence)
            p.meta.problem_definition_history.append(current)
            p.decision_log.append(DecisionRecord(
                id=f"D-{len(p.decision_log) + 1}", phase=ctx.runtime.phase, decision="REDEFINE",
                rationale=rationale, evidence_refs=[invalidating_evidence]))
        event = ctx.emit(EventType.PROBLEM_INVALIDATED,
                         {"problem": pd.id, "version": pd.version, "evidence": invalidating_evidence},
                         importance=Importance.CRITICAL, refs=[invalidating_evidence])
        ctx.signal(SignalKind.PROBLEM_INVALIDATED, f"{pd.id} v{pd.version}: {rationale}", event_seq=event.seq)
        self._move(TransitionKind.REDEFINE, Phase.DEFINE, rationale, evidence=invalidating_evidence)

    def abort(self, rationale: str) -> None:
        self._move(TransitionKind.ABORT, self.ctx.runtime.phase, rationale)
        self.ctx.runtime.execution_status = ExecutionStatus.ABORTED

    def finish(self) -> None:
        ps = self.ctx.problem
        if self.ctx.runtime.phase is not Phase.RELEASE:
            self._reject(TransitionKind.FINISH, "finish only from RELEASE")
        decisions = ps.validation.release_decisions
        if not decisions or decisions[-1] is ReleaseDecision.HOLD:
            self._reject(TransitionKind.FINISH, "Release Gate has not passed")
        self._move(TransitionKind.FINISH, Phase.RELEASE, f"Release Gate {decisions[-1].value}")
        self.ctx.runtime.execution_status = ExecutionStatus.RELEASED

    def hold(self, rationale: str) -> None:
        self.ctx.runtime.execution_status = ExecutionStatus.HOLD
        self.ctx.emit(EventType.PHASE_TRANSITION, {"kind": "HOLD", "rationale": rationale},
                      importance=Importance.CRITICAL)

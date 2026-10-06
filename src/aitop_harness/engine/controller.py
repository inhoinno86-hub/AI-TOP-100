"""Phase Controller — explicit transitions only (Design Freeze §2, §21; v0.2.4 §25).

ADVANCE follows DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY → RELEASE with guards.
Conditional transitions keep their distinct meaning:
RETRY (stay), REPLAN (new path, same Problem), REPROFILE (targeted DISCOVER, then return),
REDEFINE (authoritative evidence invalidated the Problem → DEFINE), ABORT, FINISH.
REQUEST_CONTEXT is not a transition.
"""

from __future__ import annotations

import copy

from ..core.enums import (
    PHASE_ORDER,
    ChallengeStatus,
    DefineGateResult,
    DependencyClassification,
    DesignStage,
    ExecutionStatus,
    Importance,
    Phase,
    ProblemDefinitionStatus,
    ReleaseDecision,
    RequiredBefore,
    SafePointKind,
    TransitionKind,
)
from ..core.errors import IllegalTransitionError
from ..core.events import EventType
from ..domain.design import CanonicalChallenge, DecisionRecord
from ..phases.budget import update_budget
from ..phases.human_gate import cancel_pending_for_invalidation
from ..phases.redefine import (
    apply_dependency_review,
    build_dependency_review,
    problem_reasons,
    summarize,
    validate_problem_invalidation,
)
from ..state.runtime import Plan
from ..supervision.monitoring import SignalKind
from .context import HarnessContext

# Advancing into these phases requires an ACTIVE, unchallenged canonical Problem (IDR-REDEFINE-02).
_CANONICAL_PHASES = (Phase.DESIGN, Phase.EXECUTE, Phase.VERIFY, Phase.RELEASE)


class PhaseController:
    def __init__(self, ctx: HarnessContext) -> None:
        self.ctx = ctx
        self._reprofile_return: Phase | None = None

    # ------------------------------------------------------------------ helpers

    def _move(
        self, kind: TransitionKind, target: Phase, rationale: str, *, signal: bool = True, **payload: object
    ) -> None:
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
        if signal:
            ctx.signal(
                SignalKind.PHASE_CHECKPOINT,
                f"{kind.value}: {source.value} → {target.value}",
                event_seq=event.seq,
            )

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
        if target in _CANONICAL_PHASES:
            reasons = problem_reasons(ps)
            if reasons:
                self._reject(
                    TransitionKind.ADVANCE,
                    f"{phase.value} → {target.value} requires an ACTIVE, unchallenged canonical Problem: "
                    f"{reasons[0]}",
                )
        if target is Phase.EXECUTE:
            sd = ps.solution_design
            if sd is None or not sd.trace or sd.trace[-1].stage is not DesignStage.AGENTIFICATION_GATE:
                self._reject(TransitionKind.ADVANCE, "design incomplete: Agentification Gate not recorded")
            assert pd is not None and sd is not None
            if sd.problem_ref != pd.id or sd.problem_version != pd.version:
                self._reject(
                    TransitionKind.ADVANCE, "solution design is stale for the current problem version"
                )
            blocking = [
                v.id
                for v in ps.open_vobs()
                if v.required_before is RequiredBefore.BEFORE_DESIGN_FINALIZATION
                and v.blocking_scope.intersect(sd.release_scope)
            ]
            if blocking:
                self._reject(
                    TransitionKind.ADVANCE, f"VOBs required before design finalization open: {blocking}"
                )
        if target is Phase.VERIFY and self.ctx.runtime.pending_protected_action is not None:
            self._reject(TransitionKind.ADVANCE, "protected action pending")
        if target is Phase.RELEASE and not any(
            r.get("problem_ref") == (pd.ref if pd else None) for r in ps.validation.verify_runs
        ):
            self._reject(TransitionKind.ADVANCE, "VERIFY has not run for the current Problem version")
        self._move(TransitionKind.ADVANCE, target, f"{phase.value} complete")
        return target

    # ------------------------------------------------------------------ conditional transitions

    def _reject_if_challenged(self, kind: TransitionKind) -> None:
        pd = self.ctx.problem.problem_definition
        if pd is not None and pd.open_challenges():
            self._reject(
                kind,
                f"canonical Problem {pd.ref} is challenged by "
                f"{[c.evidence_id for c in pd.open_challenges()]}: "
                f"REDEFINE outranks {kind.value} (redefine or dismiss the challenge first)",
            )

    def retry(self, rationale: str) -> None:
        self._reject_if_challenged(TransitionKind.RETRY)
        if self.ctx.runtime.phase is not Phase.EXECUTE:
            self._reject(TransitionKind.RETRY, "retry applies to execution of the same path")
        if self.ctx.runtime.recovery.retry_eligible is not True:
            self._reject(TransitionKind.RETRY, "retry not eligible (bounded by evidence and budget)")
        self._move(TransitionKind.RETRY, Phase.EXECUTE, rationale)

    def replan(self, rationale: str, *, new_plan: Plan | None = None, to_design: bool = False) -> None:
        pd = self.ctx.problem.problem_definition
        if pd is None or pd.status is not ProblemDefinitionStatus.ACTIVE:
            self._reject(TransitionKind.REPLAN, "replan requires a valid canonical Problem")
        self._reject_if_challenged(TransitionKind.REPLAN)
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
        """New authoritative Evidence invalidates the canonical Problem (never tool failure alone).

        * Harness-owned validation (IDR-REDEFINE-01/02): only an ACTIVE canonical Problem whose
          premise the evidence materially contradicts can be redefined — path-only evidence is REPLAN.
        * Atomic (IDR-REDEFINE-03): pending protected action cancelled, Problem invalidated,
          Dependency Review applied and Runtime moved to DEFINE — all or nothing.
        * Idempotent (D7): the same Problem version + evidence is an explicit no-op.
        """
        ctx = self.ctx
        evidence = invalidating_evidence
        pd = ctx.problem.problem_definition
        if (
            pd is not None
            and pd.status is ProblemDefinitionStatus.INVALIDATED
            and evidence in pd.invalidated_by
        ):
            ctx.emit(
                EventType.REDEFINE_NOOP,
                {"problem": pd.ref, "evidence": evidence, "reason": "already redefined (idempotent no-op)"},
                importance=Importance.LOW,
                refs=[evidence],
            )
            return
        found, why_not = validate_problem_invalidation(ctx.problem, evidence)
        if why_not is not None:
            self._reject(TransitionKind.REDEFINE, why_not)
        assert pd is not None
        contradicted = list(dict.fromkeys(c.object_id for c in found))
        source = ctx.runtime.phase
        with ctx.atomic(f"redefine {pd.ref} on {evidence}"):
            review = build_dependency_review(ctx.problem, ctx.runtime, pd, evidence, contradicted)
            cancelled = cancel_pending_for_invalidation(
                ctx,
                f"premise of {pd.ref} invalidated by {evidence}; approval does not carry over",
                [evidence],
            )
            with ctx.commit(f"redefine: problem {pd.id} v{pd.version} invalidated") as p:
                current = p.problem_definition
                assert current is not None
                current.status = ProblemDefinitionStatus.INVALIDATED
                current.invalidated_by.append(evidence)
                if not any(c.evidence_id == evidence for c in current.challenges):
                    current.challenges.append(
                        CanonicalChallenge(evidence, contradicted, "; ".join(c.detail for c in found))
                    )
                for ch in current.open_challenges():
                    ch.status = ChallengeStatus.REDEFINED
                    ch.resolution = f"redefine on {evidence}"
                p.decision_log.append(
                    DecisionRecord(
                        id=f"D-{len(p.decision_log) + 1}",
                        phase=ctx.runtime.phase,
                        decision="REDEFINE",
                        rationale=rationale,
                        evidence_refs=[evidence],
                    )
                )
                hyp_before = {h.id: h.status for h in p.hypotheses.values()}
                vob_changes = apply_dependency_review(p, ctx.runtime, review)
                # immutable snapshot, never an alias of the live object (D7)
                p.meta.problem_definition_history.append(copy.deepcopy(current))
            event = ctx.emit(
                EventType.PROBLEM_INVALIDATED,
                {
                    "problem": pd.id,
                    "version": pd.version,
                    "evidence": evidence,
                    "contradicted": contradicted,
                    "dependency_review": review.id,
                },
                importance=Importance.CRITICAL,
                refs=[evidence],
            )
            review.event_seq = ctx.emit(
                EventType.DEPENDENCY_REVIEW_CREATED,
                {
                    "review": review.id,
                    "problem": pd.ref,
                    "counts": {c.value: len(review.classified(c)) for c in DependencyClassification},
                    "affected": summarize(review),
                },
                importance=Importance.HIGH,
                refs=[review.id, evidence],
            ).seq
            for hid, before in hyp_before.items():
                after = ctx.problem.hypotheses[hid].status
                if after is not before:
                    ctx.emit(
                        EventType.HYPOTHESIS_CHANGED,
                        {"hypothesis": hid, "from": before.value, "to": after.value, "reason": review.id},
                    )
            for vid, frm, to in vob_changes:
                ctx.emit(
                    EventType.VOB_STATUS_CHANGED,
                    {"vob": vid, "from": frm, "to": to, "reason": review.id},
                    refs=[vid],
                )
            self._reprofile_return = None
            ctx.runtime.reprofile_targets = []
            # the REDEFINE transition is reported inside the single CRITICAL PROBLEM_INVALIDATED signal (D14)
            self._move(TransitionKind.REDEFINE, Phase.DEFINE, rationale, signal=False, evidence=evidence)
            pending_txt = (
                f"{cancelled.gate_id} CANCELLED (approval does not carry over)"
                if cancelled is not None
                else "none"
            )
            ctx.signal(
                SignalKind.PROBLEM_INVALIDATED,
                f"{pd.id} v{pd.version} INVALIDATED by {evidence}: {rationale}"
                f" | REDEFINE: {source.value} → {Phase.DEFINE.value}"
                f" | affected: {summarize(review)}"
                f" | pending protected action: {pending_txt}"
                f" | next: define v{pd.version + 1} at the DEFINE Gate; targeted reprofile only for "
                "NEEDS_REEVALUATION items",
                refs=[evidence],
                event_seq=event.seq,
            )

    def abort(self, rationale: str) -> None:
        self._move(TransitionKind.ABORT, self.ctx.runtime.phase, rationale)
        self.ctx.runtime.execution_status = ExecutionStatus.ABORTED

    def finish(self) -> None:
        ps = self.ctx.problem
        if self.ctx.runtime.phase is not Phase.RELEASE:
            self._reject(TransitionKind.FINISH, "finish only from RELEASE")
        reasons = problem_reasons(ps)
        if reasons:
            self._reject(
                TransitionKind.FINISH, f"final release requires an ACTIVE canonical Problem: {reasons[0]}"
            )
        decisions = ps.validation.release_decisions
        if not decisions or decisions[-1] is ReleaseDecision.HOLD:
            self._reject(TransitionKind.FINISH, "Release Gate has not passed")
        self._move(TransitionKind.FINISH, Phase.RELEASE, f"Release Gate {decisions[-1].value}")
        self.ctx.runtime.execution_status = ExecutionStatus.RELEASED

    def hold(self, rationale: str) -> None:
        self.ctx.runtime.execution_status = ExecutionStatus.HOLD
        self.ctx.emit(
            EventType.PHASE_TRANSITION,
            {"kind": "HOLD", "rationale": rationale},
            importance=Importance.CRITICAL,
        )

"""Autonomous orchestrator — Public Scenario → DISCOVER → … → RELEASE without an operator reasoner.

    Reasoner proposes  →  Core validates (engine.proposals + phases.*)  →  Controller executes

* The orchestrator is Harness Core. It asks the Reasoning Layer for *proposals* (passing detached views),
  validates them through the Proposal Gate, and drives the frozen ``PhaseController``.
* Transitions are executed only by the Controller after the existing Core validator accepted them
  (IDR-REASON-06). A REDEFINE needs both keys: a Core-validated premise contradiction and the Reasoner's
  REDEFINE proposal; any disagreement escalates to the Human (HOLD).
* Protected actions always stop at the Mandatory Human Gate. Only the ``HumanInterface`` answers; the
  text is interpreted by the Core (``interpret_human_input``: ambiguity is never approval).
* There is no parameter through which an operator could supply hypothesis / Problem / design / revision
  content (OPERATOR_REASONER = 0 by construction).
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.enums import (
    BudgetSlot,
    CheckStatus,
    DefineGateResult,
    EvidenceSourceType,
    ExecutionStatus,
    Importance,
    Phase,
    ProblemDefinitionStatus,
    RecoveryKind,
    ReleaseDecision,
    ResultCompleteness,
    ResultStatus,
    TransitionKind,
    VerifyLayer,
)
from ..core.errors import HarnessError
from ..core.events import EventType
from ..core.serialization import to_dict
from ..phases.budget import reserve_active, update_budget
from ..phases.data_inspection import apply_inspection, inspect_records
from ..phases.define import Severity, apply_define_gate, evaluate_define_gate
from ..phases.discover import DiscoveryAction, DiscoveryActionKind, select_next_action
from ..phases.execute import invoke_tool
from ..phases.human_gate import (
    GateStatus,
    HumanDecision,
    decide,
    interpret_human_input,
    propose_protected_action,
)
from ..phases.recovery import FailureContext, apply_recovery_decision, decide_recovery, record_retry
from ..phases.release import ReleaseGateResult, evaluate_release_gate
from ..phases.verify import CheckResult, OutputSpec, VerifyReport, run_verify
from ..reasoning.interface import ReasoningStatus
from ..reasoning.models import (
    PARSERS,
    AgentDesignProposal,
    EvidenceInterpretationProposal,
    ProblemDefinitionProposal,
    RevisionSetProposal,
    ScopeRef,
)
from ..reasoning.reasoner import Reasoner, ReasoningRecord, ReasoningResult
from ..reasoning.skills import ESSENTIAL
from ..reasoning.skills import define as define_skill
from ..reasoning.skills import design as design_skill
from ..reasoning.skills import discover as discover_skill
from ..reasoning.skills import evidence as evidence_skill
from ..reasoning.skills import premise as premise_skill
from ..reasoning.skills import recovery as recovery_skill
from ..reasoning.skills import verify as verify_skill
from ..supervision.approval import project_packet
from ..supervision.monitoring import SignalKind
from ..supervision.projection import refresh
from .context import HarnessContext
from .controller import PhaseController
from .define_repair import (
    REPROFILE_TYPES,
    RepairAttempt,
    RepairFinding,
    blocking,
    build_request,
    classify_findings,
    diff_proposals,
    framing_finding,
    keep_locked,
    settle,
)
from .environment import Affordance, Environment, ExternalInput, GateView, HumanInterface
from .premise import build_premises, evidence_view, premise_check_due, validate_premise_check
from .proposals import (
    CommittedPlan,
    DefineContext,
    FramingRejected,
    IntegrationOutcome,
    Notes,
    Observation,
    ProposalRejected,
    TransitionVerdict,
    apply_blocking_review,
    apply_framing_resolution,
    blocking_review_candidates,
    build_discovery_actions,
    build_output,
    commit_document_authorizations,
    commit_hypothesis_init,
    commit_plan,
    commit_problem_definition,
    commit_repair_authorizations,
    commit_revisions,
    evaluate_transition,
    finish_design,
    infer_schema,
    integrate_observation,
    output_completeness_check,
    output_ops,
    preview_release_scope,
    reconsideration_candidates,
    record,
    start_design,
    validate_reprofile_targets,
)
from .views import render_records, state_view

_CRIT_REASON = ReasoningStatus.SUCCESS, ReasoningStatus.LOW_CONFIDENCE


@dataclass
class AutonomousConfig:
    max_steps: int = 60
    max_discover_rounds: int = 4
    replan_after: int = 3  # re-estimate Information Value after this many executed actions
    max_define_repair_attempts: int = 3  # typed DEFINE repair re-proposals per DEFINE pass (IDR-RV4-04)
    max_redefines: int = 2
    max_replans: int = 2
    human_rounds: int = 6
    wait_minutes: float = 5.0  # simulated time passing while a gate waits for the Human
    action_overhead_minutes: float = 2.0
    pace: bool = True  # advance the simulated clock to the soft-budget slot starts (Freeze §24)
    min_transition_confidence: float = 0.5
    ignore_unknown_scope_versions: set[int] = field(default_factory=set)  # robustness variant knob
    use_semantic_judge: bool = True
    premise_check: bool = True  # IDR-RV4-01
    premise_check_authority: str = "STRONG"  # STRONG (authoritative, complete, non-fallback) | AUTHORITATIVE
    protected_reconsideration: bool = True  # IDR-RV4-05
    blocking_scope_review: bool = True  # IDR-RV5-04
    observer: Callable[[str, AutonomousOrchestrator], None] | None = None


@dataclass
class AutonomousResult:
    release_decision: ReleaseDecision | None
    halt_reason: str | None
    phase: Phase
    execution_status: ExecutionStatus
    problem_ref: str | None
    trace: list[dict[str, Any]]
    reasoning: list[ReasoningRecord]
    operator_reasoner_calls: int = 0


class AutonomousOrchestrator:
    def __init__(
        self,
        ctx: HarnessContext,
        env: Environment,
        reasoner: Reasoner,
        human: HumanInterface,
        *,
        public_notes: dict[str, Any] | None = None,
        config: AutonomousConfig | None = None,
    ) -> None:
        self.ctx = ctx
        self.env = env
        self.registry = env.registry
        self.reasoner = reasoner
        self.human = human
        self.public_notes = dict(public_notes or {})
        self.cfg = config or AutonomousConfig()
        self.ctl = PhaseController(ctx)
        self.dctx = DefineContext(ignore_unknown_scope_versions=set(self.cfg.ignore_unknown_scope_versions))
        self.executed: set[str] = set()
        self.failed: dict[str, str] = {}
        self.records_by_op: dict[str, list[dict[str, Any]]] = {}
        self.expected_by_op: dict[str, int | None] = {}
        self.complete_by_op: dict[str, ResultCompleteness] = {}
        self.trace: list[dict[str, Any]] = []
        self.interpretations: dict[str, EvidenceInterpretationProposal] = {}
        self.proposals: dict[str, Any] = {}  # last proposal per skill (for probes / reports)
        self.plan: CommittedPlan | None = None
        self.plan_for: str | None = None
        self.plan_count = 0
        self.replans = 0
        self.redefines = 0
        self.report: VerifyReport | None = None
        self.release: ReleaseGateResult | None = None
        self.halt_reason: str | None = None
        self.summary: dict[str, Any] | None = None
        self.last_verdict: TransitionVerdict | None = None
        self.authority_rechecked: set[str] = set()
        self.premise_checked: set[tuple[str, str]] = set()  # (evidence id, problem ref)
        self.last_definition: ProblemDefinitionProposal | None = None
        self.last_define_rid: str | None = None
        self.define_reprofiled: set[str] = set()  # problem refs (one repair-driven reprofile each)
        self.authorization_refusals: list[str] = []  # repair-path authorization refusals (fed back)
        self.reconsidered: set[str] = set()  # problem refs (one protected-action reconsideration each)
        self.blocking_reviewed: set[str] = set()  # problem refs (one blocking-scope review each, IDR-RV5-04)

    # ================================================================== loop

    def run(self) -> AutonomousResult:
        self._initialize()
        handlers = {
            Phase.DISCOVER: self._discover,
            Phase.DEFINE: self._define,
            Phase.DESIGN: self._design,
            Phase.EXECUTE: self._execute,
            Phase.VERIFY: self._verify,
            Phase.RELEASE: self._release,
        }
        for _ in range(self.cfg.max_steps):
            if self.ctx.runtime.execution_status in (
                ExecutionStatus.HOLD,
                ExecutionStatus.RELEASED,
                ExecutionStatus.ABORTED,
            ):
                break
            try:
                handlers[self.ctx.runtime.phase]()
            except HarnessError as exc:  # a Core guard refused the step: never bypassed, escalated
                self._hold(f"{type(exc).__name__}: {exc}")
        else:
            self._hold("autonomous step budget exhausted")
        refresh(self.ctx)
        return AutonomousResult(
            release_decision=self.ctx.problem.validation.release_decisions[-1]
            if self.ctx.problem.validation.release_decisions
            else None,
            halt_reason=self.halt_reason,
            phase=self.ctx.runtime.phase,
            execution_status=self.ctx.runtime.execution_status,
            problem_ref=self.ctx.problem.problem_definition.ref
            if self.ctx.problem.problem_definition
            else None,
            trace=self.trace,
            reasoning=list(self.reasoner.records),
            operator_reasoner_calls=sum(1 for t in self.trace if t["actor"] == "OPERATOR_REASONER"),
        )

    # ================================================================== helpers

    def _observe(self, name: str) -> None:
        if self.cfg.observer is not None:
            self.cfg.observer(name, self)

    def _step(self, actor: str, what: str, **detail: Any) -> None:
        self.trace.append(
            {
                "n": len(self.trace) + 1,
                "actor": actor,
                "what": what,
                "phase": self.ctx.runtime.phase.value,
                "minute": self.ctx.clock.now(),
                "event_seq": len(self.ctx.events),
                **detail,
            }
        )

    def view(self) -> dict[str, Any]:
        return state_view(self.ctx, public_notes=self.public_notes)

    def _pace(self, slot: BudgetSlot) -> None:
        if not self.cfg.pace:
            return
        start = self.ctx.problem.budget.slot(slot).start_minute
        now = self.ctx.clock.now()
        if now < start:
            self.ctx.clock.advance(start - now)
            update_budget(self.ctx)

    def _hold(self, reason: str) -> None:
        if self.ctx.runtime.execution_status in (ExecutionStatus.HOLD, ExecutionStatus.RELEASED):
            return
        self.halt_reason = reason
        self.ctl.hold(reason)
        self.ctx.signal(SignalKind.HUMAN_INTERVENTION_REQUIRED, f"autonomous run halted: {reason}")
        self._step("HARNESS", "HOLD", reason=reason)

    def _changed(self, phase: Phase, ref: str | None) -> bool:
        pd = self.ctx.problem.problem_definition
        return (
            self.ctx.runtime.phase is not phase
            or (pd.ref if pd else None) != ref
            or self.ctx.runtime.execution_status in (ExecutionStatus.HOLD, ExecutionStatus.ABORTED)
            or bool(pd and pd.open_challenges())
        )

    def _reason(
        self,
        skill: str,
        payload: dict[str, Any],
        *,
        fallback: Callable[[], dict[str, Any] | None] | None = None,
    ) -> ReasoningResult:
        version = self.ctx.problem.meta.version
        if skill not in ESSENTIAL and reserve_active(self.ctx):
            rec = self.reasoner.skipped(
                skill, "release reserve active: non-essential reasoning dropped", state_version=version
            )
            self.ctx.emit(
                EventType.REASONING_SKIPPED,
                {"reasoning_id": rec.reasoning_id, "skill": skill, "reason": rec.errors[0]},
            )
            out = fallback() if fallback else None
            if out is not None:
                rec.fallback_used, rec.output = "deterministic", out
            self._step("HARNESS", f"skip {skill} (release reserve)", reasoning_id=rec.reasoning_id)
            return ReasoningResult(rec, PARSERS[skill](out) if out is not None else None)
        result = self.reasoner.invoke(skill, payload, state_version=version, deterministic_fallback=fallback)
        rec = result.record
        body: dict[str, Any] = {
            "reasoning_id": rec.reasoning_id,
            "skill": skill,
            "status": rec.status.value,
            "provider": rec.provider,
            "model": rec.model,
            "input_state_version": rec.input_state_version,
            "schema_version": rec.schema_version,
            "order": rec.order,
            "attempts": rec.attempts,
            "input_digest": rec.input_digest,
            "evidence_refs": rec.evidence_refs,
            "confidence": rec.confidence,
            "fallback_used": rec.fallback_used,
            "errors": rec.errors[:6],
        }
        if result.ok:
            body["proposal"] = rec.output
            self.ctx.emit(EventType.REASONING_COMPLETED, body, refs=rec.evidence_refs)
            self.proposals[skill] = result.proposal
        else:
            event = self.ctx.emit(EventType.REASONING_FAILED, body, importance=Importance.HIGH)
            self.ctx.signal(
                SignalKind.STATE_DIFF,
                f"reasoning {skill} failed: {rec.status.value}",
                importance=Importance.HIGH,
                event_seq=event.seq,
            )
        self._step(
            "REASONER",
            skill,
            reasoning_id=rec.reasoning_id,
            status=rec.status.value,
            provider=f"{rec.provider}/{rec.model}",
            fallback=rec.fallback_used,
        )
        return result

    # ================================================================== DISCOVER

    def _initialize(self) -> None:
        self._pace(BudgetSlot.DISCOVER)
        update_budget(self.ctx)
        if self.ctx.problem.hypotheses:
            return
        view = self.view()
        res = self._reason(
            "hypothesis_init",
            discover_skill.hypothesis_init_payload(view),
            fallback=lambda: discover_skill.hypothesis_init_fallback(view),
        )
        if not res.ok:
            self._hold("no initial hypotheses (reasoning failed)")
            return
        try:
            _, framing = commit_hypothesis_init(self.ctx, res.proposal, res.record.reasoning_id)
        except ProposalRejected as exc:
            out = discover_skill.hypothesis_init_fallback(view)
            _, framing = commit_hypothesis_init(self.ctx, PARSERS["hypothesis_init"](out), "deterministic")
            self._step("HARNESS", "hypotheses from deterministic fallback", reason=str(exc))
        self.dctx.framing_hypotheses = framing
        self._step("HARNESS", "initial hypotheses committed", hypotheses=sorted(self.ctx.problem.hypotheses))

    def _discover(self) -> None:
        reprofile = bool(self.ctx.runtime.reprofile_targets)
        stage = "reprofile" if reprofile else "discover"
        catalog = self.env.catalog(stage, self.ctx)
        candidates: list[DiscoveryAction] = []
        questions: dict[str, str] = {}
        rounds = since = 0
        slot_end = self.ctx.problem.budget.slot(BudgetSlot.DISCOVER).end_minute
        while (
            self.ctx.runtime.phase is Phase.DISCOVER
            and self.ctx.runtime.execution_status is not ExecutionStatus.HOLD
        ):
            self._poll(catalog)
            if self.ctx.runtime.phase is not Phase.DISCOVER:
                return
            if (not candidates or since >= self.cfg.replan_after) and rounds < self.cfg.max_discover_rounds:
                view = self.view()
                excluded = self.executed | set(self.failed)
                res = self._reason(
                    "discover_actions",
                    discover_skill.discover_payload(view, catalog, excluded, self.failed),
                    fallback=functools.partial(discover_skill.discover_fallback, catalog, excluded),
                )
                rounds += 1
                since = 0
                if res.ok:
                    candidates, questions = build_discovery_actions(
                        self.ctx, res.proposal, catalog, excluded, res.record.reasoning_id
                    )
                    if res.proposal.stop and not candidates:
                        break
            candidates = [a for a in candidates if a.id not in self.executed and a.id not in self.failed]
            if not candidates:
                break
            if not reprofile and self.ctx.clock.now() >= slot_end:
                self._step("HARNESS", "DISCOVER soft budget reached")
                break
            action = select_next_action(self.ctx, candidates)
            if action is None:
                break
            candidates.remove(action)
            self._run_action(action, questions.get(action.id, action.question), catalog)
            since += 1
            if self.ctx.runtime.phase is not Phase.DISCOVER:
                return
            self.ctx.clock.advance(self.cfg.action_overhead_minutes)
        if (
            self.ctx.runtime.phase is not Phase.DISCOVER
            or self.ctx.runtime.execution_status is ExecutionStatus.HOLD
        ):
            return
        if reprofile:
            self._assess_hypotheses()  # new evidence may settle hypotheses before the successor DEFINE
            self.ctl.return_from_reprofile()
            self._step("HARNESS", "return from targeted reprofile", to=self.ctx.runtime.phase.value)
            return
        self._assess_hypotheses()
        self._pace(BudgetSlot.DEFINE)
        if self._propose_definition():
            self.ctl.advance()
            self._step("HARNESS", "advance DISCOVER → DEFINE")

    def _assess_hypotheses(self) -> None:
        view = self.view()
        res = self._reason(
            "assess_hypotheses",
            discover_skill.assess_payload(view),
            fallback=lambda: discover_skill.assess_fallback(view),
        )
        if res.ok:
            from .proposals import apply_hypothesis_assessment

            changed = apply_hypothesis_assessment(self.ctx, res.proposal, res.record.reasoning_id)
            self._step("HARNESS", "hypothesis assessment applied", changed=changed)

    # ------------------------------------------------------------------ actions / observations

    def _run_action(self, action: DiscoveryAction, question: str, catalog: list[Affordance]) -> None:
        ref = action.id
        if action.kind is DiscoveryActionKind.TOOL_QUERY and action.tool_id:
            self._run_tool_ref(ref, action.tool_id, action.question, catalog, alternates=action)
        elif action.kind is DiscoveryActionKind.STAKEHOLDER_INTERVIEW:
            answer = self.env.interview(action.target, question)
            self.executed.add(ref)
            self._note(ref)
            self._step("ENVIRONMENT", f"interview {action.target}", question=question)
            self._interpret(
                Observation(
                    EvidenceSourceType.STAKEHOLDER,
                    action.target,
                    "interview",
                    answer,
                    authority=self._na(),
                    stakeholder_id=action.target,
                    catalog_ref=ref,
                ),
                catalog,
            )
        elif action.kind is DiscoveryActionKind.DOCUMENT_REVIEW:
            doc = self.env.review_document(action.target)
            self.executed.add(ref)
            self._note(ref)
            self._integrate_external(doc, catalog, ref=ref)

    @staticmethod
    def _na() -> Any:
        from ..core.enums import SourceAuthority

        return SourceAuthority.NON_AUTHORITATIVE

    def _note(self, ref: str) -> None:
        note = getattr(self.env, "note_executed", None)
        if callable(note):
            note(ref)

    def _run_tool_ref(
        self,
        ref: str,
        tool_id: str,
        operation: str,
        catalog: list[Affordance],
        *,
        alternates: DiscoveryAction | None = None,
        interpret: bool = True,
    ) -> bool:
        outcome = invoke_tool(self.ctx, self.registry, tool_id, operation)
        self._note(ref)
        self._step(
            "HARNESS",
            f"invoke {ref}",
            status=outcome.result.status.value,
            completeness=outcome.completeness.value,
        )
        if outcome.result.status is ResultStatus.ERROR:
            value = 10.0 * (alternates.factors.decision_impact if alternates is not None else 0.8)
            fc = FailureContext(
                tool_id,
                operation,
                outcome.failure_signature,
                outcome.result.error_class,
                outcome.result.retryable_hint,
                estimated_retry_cost=max(1.0, outcome.result.time_cost),
                expected_value=value,  # minutes-equivalent value of the answer (decision impact scaled)
                alternate_paths=[
                    a.ref
                    for a in catalog
                    if a.ref not in self.executed
                    and a.ref != ref
                    and a.kind is DiscoveryActionKind.TOOL_QUERY
                ][:3],
                fallbacks=self.registry.fallbacks_for(tool_id),
            )
            decision = decide_recovery(self.ctx, fc)
            apply_recovery_decision(self.ctx, decision, fc)
            self._step("HARNESS", f"recovery {decision.kind.value} for {ref}", rationale=decision.rationale)
            if decision.kind is RecoveryKind.RETRY:
                retry = invoke_tool(self.ctx, self.registry, tool_id, operation)
                record_retry(self.ctx, fc, retry.result.time_cost, retry.result.status.value)
                if retry.result.status is ResultStatus.SUCCESS:
                    outcome = retry
                else:
                    self.failed[ref] = retry.result.error_class or "ERROR"
                    return False
            else:
                self.failed[ref] = outcome.result.error_class or "ERROR"
                return False
        self.failed.pop(ref, None)
        self.executed.add(ref)
        self.records_by_op[ref] = list(outcome.result.records)
        self.expected_by_op[ref] = outcome.result.expected_count
        self.complete_by_op[ref] = outcome.completeness
        if interpret:
            self._interpret(
                Observation(
                    EvidenceSourceType.TOOL,
                    tool_id,
                    operation,
                    render_records(tool_id, operation, outcome.result.records),
                    authority=outcome.result.source_authority,
                    completeness=outcome.completeness,
                    catalog_ref=ref,
                    event_seq=len(self.ctx.events),
                ),
                catalog,
            )
        return True

    def _poll(self, catalog: list[Affordance] | None = None) -> list[ExternalInput]:
        inputs = self.env.poll(self.ctx)
        for x in inputs:
            self._integrate_external(x, catalog or self.env.catalog("discover", self.ctx))
        return inputs

    def _integrate_external(
        self, x: ExternalInput, catalog: list[Affordance], *, ref: str | None = None
    ) -> None:
        self.ctx.emit(
            EventType.EXTERNAL_INPUT_RECEIVED,
            {"source": x.source_id, "type": x.source_type.value, "label": x.label},
            importance=Importance.HIGH,
        )
        self._step("ENVIRONMENT", f"external input from {x.source_id}", label=x.label)
        self._interpret(
            Observation(
                x.source_type,
                x.source_id,
                x.method,
                x.content,
                authority=x.authority,
                completeness=ResultCompleteness.NOT_APPLICABLE,
                stakeholder_id=x.source_id if x.source_type is EvidenceSourceType.STAKEHOLDER else None,
                catalog_ref=ref,
            ),
            catalog,
        )

    def interpretation_key(self, obs: Observation) -> str:
        return obs.catalog_ref or f"{obs.source_id}:{hash(obs.content) & 0xFFFFFFFF:x}"

    def _interpret(self, obs: Observation, catalog: list[Affordance]) -> IntegrationOutcome:
        phase0 = self.ctx.runtime.phase
        pd0 = self.ctx.problem.problem_definition
        ref0 = pd0.ref if pd0 else None
        view = self.view()
        obs_view = {
            "source_type": obs.source_type.value,
            "source": obs.source_id,
            "method": obs.method,
            "authority": obs.authority.value,
            "completeness": obs.completeness.value,
            "content": obs.content,
            "catalog_ref": obs.catalog_ref,
            "will_be_evidence_id": f"E-{len(self.ctx.problem.evidence) + 1:02d}",
        }
        excluded = self.executed
        res = self._reason(
            "interpret_evidence",
            evidence_skill.interpret_payload(view, obs_view, catalog, excluded, self.failed),
            fallback=evidence_skill.interpret_fallback,
        )
        prop = res.proposal if res.ok else None
        if prop is not None:
            self.interpretations[self.interpretation_key(obs)] = prop
        outcome = integrate_observation(
            self.ctx,
            obs,
            prop,
            res.record.reasoning_id,
            catalog=catalog,
            provider=f"{res.record.provider}/{res.record.model}",
        )
        self._step(
            "HARNESS",
            f"evidence {outcome.evidence_id} committed",
            source=obs.source_id,
            assessment=outcome.assessment,
            challenge=outcome.challenge_raised,
        )
        # Follow-ups re-attempt only DEFERRED (failed / access-pending) queries, and only when something new
        # arrived from outside (message / document / interview) — never a way around Information-Value
        # ranking, and never a blind retry of a tool result.
        follow: list[str] = []
        if obs.source_type is not EvidenceSourceType.TOOL:
            follow = [r for r in outcome.follow_ups if r in self.failed]
            # deterministic-first: a message from the organisation owning a deferred tool's data
            if obs.source_type is EvidenceSourceType.STAKEHOLDER and obs.stakeholder_id:
                org = self.ctx.problem.stakeholders.get(obs.stakeholder_id)
                owned = {
                    d.source
                    for d in self.ctx.problem.data_assets.values()
                    if org is not None and d.organization_id == org.organization_id
                }
                follow += [r for r in self.failed if r.split(":", 1)[0] in owned and r not in follow]
        rejected = [r for r in outcome.follow_ups if r not in follow]
        if rejected:
            self.ctx.emit(
                EventType.PROPOSAL_ADJUSTED,
                {
                    "skill": "interpret_evidence",
                    "reasoning_id": res.record.reasoning_id,
                    "detail": [
                        f"follow-up {r!r} not run: only deferred queries are re-attempted, and only on new "
                        "external input (Information-Value ranking decides the rest)"
                        for r in rejected
                    ],
                },
            )
        by_ref = {a.ref: a for a in self._catalog_all()}
        for ref in follow:
            aff = by_ref.get(ref)
            if aff is None or ref in self.executed or aff.kind is not DiscoveryActionKind.TOOL_QUERY:
                continue
            self._step("HARNESS", f"follow-up {ref}", because=outcome.evidence_id)
            self._run_tool_ref(ref, aff.target, aff.operation, catalog)
            if self._changed(phase0, ref0):
                return outcome
        self._after_evidence(outcome, prop)
        return outcome

    # ------------------------------------------------------------------ challenge / transitions

    def _mutating_tools(self) -> list[dict[str, Any]]:
        surface = {t.get("tool_id"): t for t in self.public_notes.get("tool_surface", [])}
        return [
            {"tool_id": tid, "describes": surface.get(tid, {}).get("describes", "")}
            for tid in self.registry._specs  # noqa: SLF001 — read-only listing of registered tools
            if not self.registry.spec(tid).read_only
        ]

    def _catalog_all(self) -> list[Affordance]:
        seen: dict[str, Affordance] = {}
        for stage in ("discover", "reprofile", "execute"):
            for a in self.env.catalog(stage, self.ctx):
                seen.setdefault(a.ref, a)
        return list(seen.values())

    def _challenge_open(self) -> bool:
        pd = self.ctx.problem.problem_definition
        return bool(pd and pd.is_canonical() and pd.open_challenges())

    def _after_evidence(
        self, outcome: IntegrationOutcome, prop: EvidenceInterpretationProposal | None = None
    ) -> None:
        pd = self.ctx.problem.problem_definition
        if pd is None or not pd.is_canonical():
            return
        if not pd.open_challenges() and outcome.assessment == "CONSISTENT_NOT_CONFIRMED":
            # the Reasoner sees a premise contradiction the structured relations did not express:
            # route it through a Core-checked, problem-invalidating revision of the premise evidence
            premise = set(pd.evidence_refs)
            targets = [t for t in outcome.premise_targets if t in premise]
            if not targets:
                hyps = [
                    self.ctx.problem.hypotheses[t]
                    for t in outcome.premise_targets
                    if t in self.ctx.problem.hypotheses
                ]
                targets = [e for h in hyps for e in h.supporting_evidence if e in premise]
            if targets:
                self._revise(outcome.evidence_id, sorted(set(targets)))
        if self.cfg.premise_check and not self._challenge_open():
            self._premise_check(outcome.evidence_id, prop)
        if self._challenge_open():
            self._handle_challenge()

    def _premise_check(self, eid: str, prop: EvidenceInterpretationProposal | None) -> None:
        """IDR-RV4-01/02: authoritative evidence against an ACTIVE canonical Problem → per-premise check →
        only Core-consistent invalidation claims enter the existing revision → challenge → transition path."""
        due, _ = premise_check_due(
            self.ctx, eid, prop, checked=self.premise_checked, min_authority=self.cfg.premise_check_authority
        )
        pd = self.ctx.problem.problem_definition
        if not due or pd is None:
            return
        self.premise_checked.add((eid, pd.ref))
        record_ = self.dctx.premise_records.get(pd.ref, {})
        premises = build_premises(self.ctx, record_)
        view = self.view()
        problem = {**(view.get("problem_definition") or {}), **record_}
        listed = [p.view() for p in premises]
        res = self._reason(
            "premise_check",
            premise_skill.premise_payload(view, problem, listed, evidence_view(self.ctx, eid, prop)),
            fallback=lambda: premise_skill.premise_fallback(problem, listed),
        )
        if not res.ok:
            return
        verdict, notes = validate_premise_check(self.ctx, res.proposal, eid, premises)
        if notes:
            record(self.ctx, "ADJUSTED", "premise_check", res.record.reasoning_id, notes)
        if verdict.targets:
            # IDR-RV5-03: the Core-accepted invalidation is handed on as constrained context — the revision
            # step may explain / phrase it, it cannot downgrade it (rejected claims never reach it)
            chosen = [p for p in res.proposal.premises if p.premise_id in verdict.accepted]
            self._revise(
                eid,
                verdict.targets,
                accepted={
                    "accepted_problem_id": pd.id,
                    "accepted_problem_version": pd.version,
                    "accepted_premise_ids": list(verdict.accepted),
                    "accepted_relation": {p.premise_id: p.relation for p in chosen},
                    "accepted_materiality": {p.premise_id: p.materiality.value for p in chosen},
                    "accepted_problem_invalidating": True,
                    "accepted_evidence_refs": list(verdict.targets),
                    "challenge_evidence": eid,
                    "rationale": {p.premise_id: p.rationale for p in chosen},
                    "constraint": "accepted by the Harness Core: revisions of accepted_evidence_refs keep "
                    "problem_invalidating=true; write what the observation still shows and no longer means",
                },
            )
        challenge = self._challenge_open()
        record(
            self.ctx,
            "ACCEPTED",
            "premise_check",
            res.record.reasoning_id,
            {**verdict.detail(), "challenge_raised": challenge, "fallback": res.record.fallback_used},
            refs=[eid],
        )
        self._step(
            "HARNESS",
            f"premise check of {eid}",
            overall=verdict.overall,
            invalidating_claims=verdict.invalidating_claims,
            accepted=verdict.accepted,
            challenge=challenge,
        )

    def _revise(
        self, challenge_evidence: str, proposed: list[str], *, accepted: dict[str, Any] | None = None
    ) -> None:
        view = self.view()
        payload = recovery_skill.revise_payload(view, challenge_evidence, proposed)
        if accepted:
            payload["accepted_premise_check"] = accepted
        res = self._reason("revise_evidence", payload)
        if res.ok or accepted:
            done = commit_revisions(
                self.ctx,
                res.proposal if res.ok else RevisionSetProposal(revisions=[]),
                res.record.reasoning_id,
                challenge_evidence=challenge_evidence,
                allowed=proposed,
                accepted=accepted,
            )
            self._step("HARNESS", "evidence revisions committed", revisions=done)

    def _handle_challenge(self) -> None:
        pd = self.ctx.problem.problem_definition
        assert pd is not None
        challenge = pd.open_challenges()[-1]
        self._observe("challenge_detected")
        if self.redefines >= self.cfg.max_redefines:
            self._hold(f"canonical challenge {challenge.evidence_id}: redefine limit reached (Human decides)")
            return
        revised = {
            r.evidence_id
            for r in self.ctx.problem.evidence_revisions.values()
            if r.revised_by == challenge.evidence_id
        }
        pending = [e for e in challenge.proposed_revisions if e not in revised]
        if pending:
            self._revise(challenge.evidence_id, pending)
        view = self.view()
        trigger = {"challenge": to_dict(challenge), "problem": view.get("problem_definition")}
        res = self._reason(
            "propose_transition",
            recovery_skill.transition_payload(
                view, trigger, self.env.catalog("reprofile", self.ctx), self.executed
            ),
        )
        if not res.ok:
            self._hold(f"canonical challenge {challenge.evidence_id}: no transition proposal (Human decides)")
            return
        verdict = evaluate_transition(
            self.ctx, res.proposal, res.record.reasoning_id, min_confidence=self.cfg.min_transition_confidence
        )
        self.last_verdict = verdict
        self._step(
            "HARNESS",
            "transition validated",
            proposed=verdict.proposed,
            core=verdict.core_kind.value if verdict.core_kind else None,
            execute=verdict.execute_redefine,
            escalate=verdict.escalate,
        )
        self._observe("transition_validated")
        if not verdict.execute_redefine:
            self._hold(
                f"canonical challenge {challenge.evidence_id}: Reasoner proposed {verdict.proposed}, "
                f"Core decided {verdict.core_kind.value if verdict.core_kind else '-'}; Human decides"
            )
            return
        assert verdict.trigger is not None
        core_reason = verdict.decision.rationale if verdict.decision else ""
        self.ctl.redefine(
            verdict.trigger,
            f"{res.proposal.rationale} [reasoner {res.record.reasoning_id}; Core: {core_reason}]",
        )
        self.redefines += 1
        self.plan, self.plan_for = None, None
        self._step(
            "HARNESS",
            "REDEFINE executed by controller",
            evidence=verdict.trigger,
            problem=self.ctx.problem.problem_definition.ref if self.ctx.problem.problem_definition else None,
        )
        self._observe("after_redefine")
        if verdict.reprofile_targets and self.ctx.runtime.execution_status is not ExecutionStatus.HOLD:
            reason = res.proposal.reprofile.reason if res.proposal.reprofile else "targeted reprofile"
            self.ctl.reprofile(verdict.reprofile_targets, reason or "targeted reprofile")
            self._step("HARNESS", "targeted REPROFILE", targets=verdict.reprofile_targets)

    # ================================================================== DEFINE

    def _propose_definition(self, repair: dict[str, Any] | None = None) -> bool:
        rejected: str | None = None
        framing: dict[str, Any] | None = None  # typed anti-anchoring finding of the previous attempt
        last_rejection = ""
        for _ in range(2):
            view = self.view()
            res = self._reason(
                "define_problem",
                define_skill.define_payload(
                    view,
                    tool_surface=self.public_notes.get("tool_surface", []),
                    repair_request=repair,
                    rejected=rejected,
                    framing_repair=framing,
                ),
            )
            if not res.ok:
                self._hold("DEFINE proposal unavailable (reasoning failed): manual escalation")
                return False
            if repair and repair.get("locked_fields") and self.last_definition is not None:
                restored = keep_locked(res.proposal, self.last_definition, repair["locked_fields"])
                if restored:
                    record(
                        self.ctx,
                        "ADJUSTED",
                        "define_problem",
                        res.record.reasoning_id,
                        [
                            f"{restored} kept from the previous proposal: "
                            "no repair finding concerned the problem framing"
                        ],
                    )
            if framing is not None and res.proposal.framing_resolution:
                accepted = apply_framing_resolution(
                    self.ctx, res.proposal, res.record.reasoning_id, dctx=self.dctx
                )
                self._step("HARNESS", "framing repair validated", accepted=accepted)
            try:
                pd = commit_problem_definition(
                    self.ctx, res.proposal, res.record.reasoning_id, registry=self.registry, dctx=self.dctx
                )
            except FramingRejected as exc:  # IDR-RV5-02: typed repair finding instead of free text
                rejected, framing = (
                    None,
                    framing_finding(
                        self.ctx, exc.hypothesis, exc.proposal_ref, str(exc), self.dctx.framing_hypotheses
                    ),
                )
                self._step(
                    "HARNESS", "DEFINE proposal rejected", reason=str(exc), typed=framing["finding_type"]
                )
                last_rejection = str(exc)
                continue
            except ProposalRejected as exc:
                rejected, framing = str(exc), None
                self._step("HARNESS", "DEFINE proposal rejected", reason=rejected)
                last_rejection = rejected
                continue
            self.last_definition, self.last_define_rid = res.proposal, res.record.reasoning_id
            if res.proposal.authorization_candidates:
                if repair is None:
                    record(
                        self.ctx,
                        "ADJUSTED",
                        "define_problem",
                        res.record.reasoning_id,
                        ["authorization candidates outside a DEFINE repair ignored"],
                    )
                else:
                    added, refused = commit_repair_authorizations(
                        self.ctx, res.proposal, res.record.reasoning_id
                    )
                    self.authorization_refusals += refused
                    self._step("HARNESS", "repair authorizations", authorizations=added, refused=refused)
            self._step("HARNESS", f"problem {pd.ref} drafted", root_problem=pd.root_problem)
            return True
        self._hold(f"DEFINE proposal rejected twice: {last_rejection}")
        return False

    def _define(self) -> None:
        self._poll()
        pd = self.ctx.problem.problem_definition
        if pd is None or pd.status is ProblemDefinitionStatus.INVALIDATED:
            self._observe("before_define")
            if not self._propose_definition():
                return
        if self.ctx.problem.problem_definition.status is ProblemDefinitionStatus.DRAFT:  # type: ignore[union-attr]
            self._observe("draft_ready")
        history: list[RepairAttempt] = []
        while True:
            outcome = evaluate_define_gate(self.ctx, self.registry)
            self._observe("define_gate_evaluated")
            typed = classify_findings(self.ctx, outcome)
            if history and not history[-1].settled:
                settle(history[-1], typed)
                self._record_repair(history[-1], outcome.result.value)
            if outcome.result is not DefineGateResult.FAIL:
                apply_define_gate(self.ctx, outcome)
                self._step(
                    "HARNESS",
                    f"DEFINE Gate {outcome.result.value}",
                    problem=_ref(self.ctx),
                )
                self._observe("define_gate_passed")
                self._pace(BudgetSlot.DESIGN)
                self.ctl.advance()
                return
            findings = [
                f"[{f.severity.value}] {f.check}: {f.message}"
                for f in outcome.findings
                if f.severity in (Severity.BLOCKING, Severity.CONDITIONAL)
            ]
            apply_define_gate(self.ctx, outcome)  # FAIL is recorded; the draft stays DRAFT
            self._step(
                "HARNESS", "DEFINE Gate FAIL", findings=findings, typed=[f.signature for f in blocking(typed)]
            )
            if self._recheck_authority(outcome.findings):
                continue  # same draft, re-evaluated with the newly established domain authorization
            if history and not history[-1].resolved and not history[-1].feedback:
                # the repair fixed nothing and the Core has nothing new to say: no blind retry (IDR-RV4-04)
                if self._repair_reprofile(typed):
                    return
                self._hold(
                    "DEFINE Gate FAIL: repair resolved none of the blocking findings (same findings repeated)"
                )
                return
            if len(history) >= self.cfg.max_define_repair_attempts:
                self._hold("DEFINE Gate FAIL after bounded repair attempts")
                return
            attempt = RepairAttempt(len(history) + 1, [f.signature for f in blocking(typed)])
            request = build_request(
                self.ctx,
                typed,
                self.last_definition,
                history,
                attempt=attempt.attempt,
                max_attempts=self.cfg.max_define_repair_attempts,
                refusals=self.authorization_refusals,
            )
            previous = self.last_definition
            refusals_before = len(self.authorization_refusals)
            if not self._propose_definition(request):
                return
            attempt.feedback = self.authorization_refusals[refusals_before:]
            assert self.last_definition is not None
            attempt.reasoning_id = self.last_define_rid
            attempt.changed = diff_proposals(previous, self.last_definition)
            attempt.resolution_claimed = [
                {"finding": r.finding, "option": r.option} for r in self.last_definition.repair_resolution
            ]
            history.append(attempt)

    def _record_repair(self, attempt: RepairAttempt, gate: str) -> None:
        record(
            self.ctx,
            "ACCEPTED",
            "define_repair",
            attempt.reasoning_id,
            {**attempt.view(), "resolution_claimed": attempt.resolution_claimed, "gate_after": gate},
        )
        self._step(
            "HARNESS",
            f"DEFINE repair attempt {attempt.attempt}",
            resolved=attempt.resolved,
            remaining=attempt.remaining,
            new=attempt.new,
            gate_after=gate,
        )

    def _repair_reprofile(self, typed: list[RepairFinding]) -> bool:
        """Repeated findings evidence could answer → one targeted reprofile per Problem draft, else HOLD."""
        pd = self.ctx.problem.problem_definition
        if pd is None or pd.ref in self.define_reprofiled:
            return False
        notes = Notes()
        refs = [r for f in blocking(typed) if f.type in REPROFILE_TYPES for r in f.refs]
        targets = validate_reprofile_targets(self.ctx, refs, notes)
        open_actions = [a for a in self.env.catalog("reprofile", self.ctx) if a.ref not in self.executed]
        if not targets or not open_actions:
            return False
        self.define_reprofiled.add(pd.ref)
        record(
            self.ctx,
            "ACCEPTED",
            "define_repair",
            None,
            {"mode": "repetition → targeted reprofile", "targets": targets},
        )
        self.ctl.reprofile(targets, "DEFINE repair: blocking findings need evidence")
        self._step("HARNESS", "targeted REPROFILE (DEFINE repair)", targets=targets)
        return True

    def _recheck_authority(self, findings: list[Any]) -> bool:
        """DEFINE Gate: a protected action's authority is unknown. A re-proposed Problem cannot fix that — the
        authority comes from documents. Ask once per committed authoritative document whether it grants the
        authority; candidates go through the usual Core authorization rules. Bounded: each document once."""
        from ..core.enums import SourceAuthority

        missing = [f.message for f in findings if f.check == "authority" and f.severity is Severity.BLOCKING]
        if not missing:
            return False
        ps = self.ctx.problem
        before = len(ps.domain_authorizations)
        for e in list(ps.evidence.values()):
            if (
                e.id in self.authority_rechecked
                or e.source_type not in (EvidenceSourceType.DOCUMENT, EvidenceSourceType.POLICY)
                or e.authority is not SourceAuthority.AUTHORITATIVE
            ):
                continue
            self.authority_rechecked.add(e.id)
            obs_view = {
                "source_type": e.source_type.value,
                "source": e.source_id,
                "method": e.provenance.method,
                "authority": e.authority.value,
                "completeness": e.completeness.value,
                "content": e.content,
                "catalog_ref": None,
                "already_committed_as": e.id,
            }
            payload = evidence_skill.interpret_payload(self.view(), obs_view, [], self.executed, self.failed)
            payload["define_gate_findings"] = missing
            res = self._reason("interpret_evidence", payload)
            if res.ok:
                added = commit_document_authorizations(self.ctx, res.proposal, e.id, res.record.reasoning_id)
                self._step("HARNESS", f"authority recheck of {e.id}", authorizations=added)
        return len(ps.domain_authorizations) > before

    # ================================================================== DESIGN

    def _design(self) -> None:
        self._pace(BudgetSlot.DESIGN)
        view = self.view()
        res = self._reason("structural_remedy", design_skill.remedy_payload(view))
        if not res.ok:
            self._hold("structural remedy proposal unavailable: manual escalation")
            return
        session, removes, feasible = start_design(self.ctx, res.proposal, res.record.reasoning_id)
        feasibility = {
            "remedies": [to_dict(c) for c in session.design.structural_remedies],
            "removes_root_cause": removes,
            "feasible_in_contest_time": feasible,
            "why_agent_needed": res.proposal.why_agent_needed,
        }
        self._review_blocking_scope(feasibility, removes=removes, feasible=feasible)
        res2 = self._reason(
            "agent_design",
            design_skill.agent_payload(self.view(), feasibility, self.public_notes.get("tool_surface", [])),
        )
        if not res2.ok:
            self._hold("agent design proposal unavailable: manual escalation")
            return
        release, blocked = preview_release_scope(self.ctx, res2.proposal)
        if not release:  # bounded re-proposal with the Core's reasons, then an honest HOLD
            feedback = [f"release scope would be empty: {b}" for b in blocked] or [
                "release scope would be empty"
            ]
            res2 = self._reason(
                "agent_design",
                design_skill.agent_payload(
                    self.view(), feasibility, self.public_notes.get("tool_surface", []), feedback=feedback
                ),
            )
            if not res2.ok or not preview_release_scope(self.ctx, res2.proposal)[0]:
                self._hold("no releasable scope: every intended item is blocked by an open critical VOB")
                return
        agent = self._reconsider(res2.proposal, feasibility, removes=removes, feasible=feasible)
        design = finish_design(
            self.ctx,
            session,
            agent,
            res2.record.reasoning_id,
            removes=removes,
            feasible=feasible,
            registry=self.registry,
            known_limitations=self.dctx.known_limitations,
        )
        self._step(
            "HARNESS",
            f"design {design.id} finalized",
            roles=[r.value for r in design.agent_roles],
            release_scope=[str(i) for i in design.release_scope],
        )
        self._observe("design_finalized")
        self._pace(BudgetSlot.EXECUTE)
        self.ctl.advance()

    def _review_blocking_scope(self, feasibility: dict[str, Any], *, removes: bool, feasible: bool) -> None:
        """IDR-RV5-04 / IDR-RV6-01: at most one evidence-aware review per Problem version of Reasoner-raised
        critical unknowns whose obligation blocks either the whole intended scope (IDR-RV5-04) or at least one
        protected action's scope (IDR-RV6-01). Narrowing is Core-validated (``apply_blocking_review``); a true
        block (safety / privacy / conflict-backed / Core obligation) is never reviewed."""
        pd = self.ctx.problem.problem_definition
        if not self.cfg.blocking_scope_review or pd is None or pd.ref in self.blocking_reviewed:
            return
        eligible, why_not = blocking_review_candidates(
            self.ctx,
            removes=removes,
            feasible=feasible,
            skip_versions=set(self.cfg.ignore_unknown_scope_versions),
        )
        if not eligible:
            if why_not:
                record(
                    self.ctx, "ACCEPTED", "review_blocking_scope", None, {"eligible": [], "why_not": why_not}
                )
            return
        self.blocking_reviewed.add(pd.ref)
        ps = self.ctx.problem
        request = {
            "root_problem": pd.root_problem,
            "structural_remedies": feasibility["remedies"],
            "intended_scope": [{"action": i.action, "target": i.target} for i in pd.intended_scope],
            "protected_actions": list(pd.protected_actions),
            "obligations": [
                {
                    "vob": v.id,
                    "question": v.unresolved_question,
                    "required_before": v.required_before.value,
                    "blocking_scope": "ENTIRE_SOLUTION"
                    if v.blocking_scope.entire_solution
                    else [str(i) for i in v.blocking_scope.items],
                    "unknown": {
                        "id": u.id,
                        "criticality": u.criticality.value,
                        "decision_impact": u.decision_impact,
                        "resolution_path": u.resolution_path,
                        "safe_placeholder": u.safe_placeholder,
                    },
                }
                for v in eligible
                if (u := ps.unknowns[v.linked_unknown or ""]) is not None
            ],
        }
        res = self._reason(
            "review_blocking_scope",
            design_skill.blocking_review_payload(self.view(), request),
            fallback=design_skill.blocking_review_fallback,
        )
        if not res.ok:
            return
        narrowed = apply_blocking_review(self.ctx, res.proposal, eligible, res.record.reasoning_id)
        self._step(
            "HARNESS",
            "blocking-scope review",
            eligible=[v.id for v in eligible],
            decisions={r.vob: r.decision for r in res.proposal.reviews},
            narrowed=narrowed,
        )

    def _reconsider(
        self, prop: AgentDesignProposal, feasibility: dict[str, Any], *, removes: bool, feasible: bool
    ) -> AgentDesignProposal:
        """IDR-RV4-05: one bounded second look at a feasible protected structural remedy the release scope
        left out — never when authority / safety / an open critical VOB forces the exclusion.
        Bounded reconsideration ≠ force gate."""
        pd = self.ctx.problem.problem_definition
        if not self.cfg.protected_reconsideration or pd is None or pd.ref in self.reconsidered:
            return prop
        cands, why_not = reconsideration_candidates(
            self.ctx, prop, removes=removes, feasible=feasible, registry=self.registry
        )
        if not cands:
            if why_not:
                record(
                    self.ctx,
                    "ACCEPTED",
                    "protected_reconsideration",
                    None,
                    {"eligible": False, "why_not": why_not},
                )
            return prop
        self.reconsidered.add(pd.ref)
        cand = cands[0]
        ps = self.ctx.problem
        request = {
            "root_problem": pd.root_problem,
            "structural_remedies": feasibility["remedies"],
            "candidate_action": cand.action,
            "candidate_scope": [f"{i.action}:{i.target}" for i in cand.scope],
            "authority": {
                "authorization": cand.authorization,
                "holder": cand.holder,
                "constraints": {c: ps.constraints[c].description for c in cand.constraints},
            },
            "known_risks": [u.question for u in ps.unknowns.values() if u.status.value != "RESOLVED"],
            "vobs": {v.id: v.unresolved_question for v in ps.open_vobs() if v.applies_to(pd.id, pd.version)},
            "release_scope": [f"{r.action}:{r.target}" for r in prop.release_scope],
            "reason_for_exclusion": {
                "core": "not blocked by authority, safety or an open critical VOB",
                "design_known_limitations": prop.known_limitations,
                "design_authority_boundary": prop.authority_boundary,
            },
        }
        res = self._reason(
            "reconsider_protected_action",
            design_skill.reconsider_payload(self.view(), request),
            fallback=design_skill.reconsider_fallback,
        )
        decision = res.proposal.decision if res.ok else "KEEP_EXCLUDED"
        included = False
        out = prop
        if decision == "INCLUDE_WITH_HUMAN_GATE":
            trial = copy.copy(prop)
            trial.release_scope = list(prop.release_scope) + [
                ScopeRef(i.action, i.target) for i in cand.scope
            ]
            trial.human_gate = sorted(set(prop.human_gate) | {cand.action})
            release, _ = preview_release_scope(self.ctx, trial)
            if all(i in release for i in cand.scope):
                out, included = trial, True
        elif decision == "NEEDS_MORE_EVIDENCE" and res.ok:
            out = copy.copy(prop)
            out.known_limitations = list(prop.known_limitations) + [
                f"protected action {cand.action} not proposed yet: needs "
                f"{res.proposal.needed_evidence or 'evidence'}"
            ]
        record(
            self.ctx,
            "ACCEPTED",
            "protected_reconsideration",
            res.record.reasoning_id,
            {
                "eligible": True,
                "action": cand.action,
                "decision": decision,
                "included": included,
                "fallback": res.record.fallback_used,
                "rationale": res.proposal.rationale if res.ok else "",
            },
        )
        self._step(
            "HARNESS", f"protected-action reconsideration {cand.action}", decision=decision, included=included
        )
        return out

    # ================================================================== EXECUTE

    def _execute(self) -> None:
        pd = self.ctx.problem.problem_definition
        ref = pd.ref if pd else None
        catalog = self.env.catalog("execute", self.ctx)
        if self.plan is None or self.plan_for != ref:
            res = self._reason(
                "plan_execution",
                design_skill.plan_payload(self.view(), catalog, self.executed, self._mutating_tools()),
            )
            if not res.ok:
                self._hold("execution plan unavailable: manual escalation")
                return
            self.plan_count += 1
            self.plan = commit_plan(
                self.ctx,
                res.proposal,
                res.record.reasoning_id,
                catalog=catalog,
                registry=self.registry,
                plan_id=f"PLAN-{self.plan_count}",
            )
            self.plan_for = ref
            self._step(
                "HARNESS",
                f"plan {self.plan.plan.id} set",
                work_items=[w.id for w in self.plan.plan.work_items],
            )
        by_ref = {a.ref: a for a in catalog}
        for w in self.plan.plan.work_items:
            ops = self.plan.data_ops.get(w.id, [])
            if w.status != "PENDING" or not ops:
                continue
            ok = True
            for op_ref in ops:
                if op_ref in self.records_by_op:
                    continue
                aff = by_ref[op_ref]
                ok = self._run_tool_ref(op_ref, aff.target, aff.operation, catalog) and ok
                if self._changed(Phase.EXECUTE, ref):
                    return
            for op_ref in ops:
                self._inspect(op_ref)
            w.status = "DONE" if ok else "BLOCKED"
        self._observe("execute_data_done")
        for wid, proposal in self.plan.protected:
            if any(a.idempotency_key == proposal.idempotency_key for a in self.ctx.problem.execution.actions):
                continue
            if any(
                e.payload.get("action") == proposal.action_id
                for e in self.ctx.events.of_type(EventType.PROTECTED_ACTION_PROPOSED)
            ):
                continue
            gate = propose_protected_action(
                self.ctx, proposal, self.env.executor(proposal.protected_resource)
            )
            self._step(
                "HARNESS",
                f"protected action {proposal.action_id} → {gate.status.value}",
                reasons=gate.reasons,
            )
            self._observe("protected_action_proposed")
            if gate.status is GateStatus.WAITING_APPROVAL:
                self._human_loop(
                    gate.gate_id or "",
                    proposal.protected_resource,
                    gate.packet.render() if gate.packet else "",
                )
                if self._changed(Phase.EXECUTE, ref):
                    return
            item = next((w for w in self.plan.plan.work_items if w.id == wid), None)
            if item is not None:
                item.status = "DONE" if gate.status is GateStatus.EXECUTED else "BLOCKED"
        self._poll(catalog)
        if self._changed(Phase.EXECUTE, ref):
            return
        cand = self.ctx.runtime.transition_candidate
        if cand is not None and cand.kind is TransitionKind.REPLAN and self.replans < self.cfg.max_replans:
            self.replans += 1
            self.ctl.replan(cand.rationale)
            self.plan, self.plan_for = None, None
            self._step("HARNESS", "REPLAN executed by controller", rationale=cand.rationale)
            return
        self._pace(BudgetSlot.VERIFY)
        self.ctl.advance()

    def _inspect(self, ref: str) -> None:
        """Deterministic data inspection of the assets an executed operation reads (no reasoning)."""
        records = self.records_by_op.get(ref)
        if records is None:
            return
        tool_id = ref.split(":", 1)[0]
        complete = self.complete_by_op.get(ref) is ResultCompleteness.COMPLETE
        for asset in self.ctx.problem.data_assets.values():
            if asset.source != tool_id:
                continue
            report = inspect_records(
                records,
                schema=infer_schema(records),
                expected_count=self.expected_by_op.get(ref),
                pagination_complete=complete,
            )
            apply_inspection(self.ctx, asset.id, report)

    def _human_loop(self, gate_id: str, resource: str, packet: str) -> None:
        executor = self.env.executor(resource)
        explanation: str | None = None
        ref = self.ctx.problem.problem_definition.ref if self.ctx.problem.problem_definition else None
        for n in range(self.cfg.human_rounds):
            pending = self.ctx.runtime.pending_protected_action
            if pending is None or pending.gate_id != gate_id or self._changed(Phase.EXECUTE, ref):
                return
            packet = project_packet(self.ctx.problem, self.ctx.runtime, pending).render()
            text = self.human.respond(GateView(gate_id, packet, explanation, n))
            if text is None:  # the gate waits; time passes and the world may deliver new evidence
                self._step("HUMAN", f"{gate_id}: no decision yet")
                self.ctx.clock.advance(self.cfg.wait_minutes)
                update_budget(self.ctx)
                self._poll()
                continue
            kind = interpret_human_input(text)
            out = decide(self.ctx, HumanDecision(kind, text), executor)
            self._step("HUMAN", f"{gate_id}: {kind.value}", text=text, outcome=out.status.value)
            self._observe(f"human_{kind.value.lower()}")
            explanation = out.explanation
            if out.status is not GateStatus.WAITING_APPROVAL and (
                out.status is not GateStatus.BLOCKED or self.ctx.runtime.pending_protected_action is None
            ):
                return
        self._hold(f"{gate_id}: awaiting Human decision")

    # ================================================================== VERIFY / RELEASE

    def outputs(self) -> list[OutputSpec]:
        specs = []
        for out in self.plan.outputs if self.plan else []:
            rows = build_output(self.records_by_op, out)
            ops = output_ops(self.records_by_op, out)
            expected, assumes_completeness = output_completeness_check(
                out, ops, self.expected_by_op, self.complete_by_op
            )
            specs.append(
                OutputSpec(
                    out.name,
                    rows,
                    schema=infer_schema(rows),
                    key_fields=list(out.key_fields),
                    expected_count=expected,
                    assumes_completeness=assumes_completeness,
                )
            )
        return specs

    def _verify(self) -> None:
        self._pace(BudgetSlot.VERIFY)
        sd = self.ctx.problem.solution_design
        scope = list(sd.release_scope) if sd else []
        # deterministic inspection of every data asset the release relies on, from results already collected
        relied = {d for ids in (sd.scope_dependencies.values() if sd else []) for d in ids}
        sources = {
            a.source
            for a in self.ctx.problem.data_assets.values()
            if a.id in relied and a.completeness is not ResultCompleteness.COMPLETE
        }
        for ref in list(self.records_by_op):
            if ref.split(":", 1)[0] in sources:
                self._inspect(ref)
        judge = _ReasonerJudge(self) if self.cfg.use_semantic_judge else None
        self.report = run_verify(self.ctx, scope, outputs=self.outputs(), judge=judge)
        self._step(
            "HARNESS",
            "VERIFY run",
            layer1_passed=self.report.layer1_passed,
            failed=[c.name for c in self.report.failed()],
        )
        self._observe("verified")
        self.ctl.advance()

    def _release(self) -> None:
        sd = self.ctx.problem.solution_design
        report = self.report
        if report is None:
            self._hold("RELEASE without VERIFY report")
            return
        self.release = evaluate_release_gate(self.ctx, report, list(sd.release_scope) if sd else [])
        self._step(
            "HARNESS",
            f"Release Gate {self.release.decision.value}",
            hold=self.release.hold_reasons,
            limitations=self.release.known_limitations,
        )
        release_view = {
            "decision": self.release.decision.value,
            "hold": self.release.hold_reasons,
            "limitations": self.release.known_limitations,
        }
        view = self.view()
        res = self._reason(
            "release_summary",
            verify_skill.summary_payload(view, release_view),
            fallback=lambda: verify_skill.summary_fallback(view, release_view),
        )
        if res.ok:
            self.summary = to_dict(res.proposal)
        self._observe("release_gate")
        if self.release.decision is ReleaseDecision.HOLD:
            self._hold("Release Gate HOLD")
        else:
            self.ctl.finish()
            self._step("HARNESS", "FINISH", decision=self.release.decision.value)


def _ref(ctx: HarnessContext) -> str | None:
    pd = ctx.problem.problem_definition
    return pd.ref if pd else None


class _ReasonerJudge:
    """VERIFY Layer 2 semantic judge backed by the Reasoning Layer. Cannot override Layer 1."""

    def __init__(self, orch: AutonomousOrchestrator) -> None:
        self.orch = orch

    def judge(self, ctx: HarnessContext, report: VerifyReport) -> list[CheckResult]:
        l1 = {c.name: c.status.value for c in report.layer(VerifyLayer.DETERMINISTIC)}
        res = self.orch._reason("semantic_judge", verify_skill.judge_payload(self.orch.view(), l1))
        if not res.ok:
            return []
        status = {"PASS": CheckStatus.PASS, "FAIL": CheckStatus.FAIL, "WARN": CheckStatus.WARN}
        return [
            CheckResult(
                f"semantic:{c.name}",
                VerifyLayer.SEMANTIC_JUDGE,
                status[c.status],
                c.detail,
                [r for r in c.refs if r in ctx.problem.evidence],
            )
            for c in res.proposal.checks
        ]

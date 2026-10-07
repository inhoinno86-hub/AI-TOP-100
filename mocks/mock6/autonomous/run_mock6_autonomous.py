"""Mock #6 — AUTONOMOUS rerun (OPERATOR_REASONER = 0).

Same scenario pack as the baseline runner (public scenario, controller, sealed hidden ground truth, late
evidence schedule, evaluation criteria) — none of it is changed. What changed is who produces the
content the Harness needs:

* baseline ``run_mock6.py``: hypotheses, Problem text, metrics / unknowns / assumptions, design inputs,
  plan, revision wording, hypothesis status, evidence mapping were written by ``OPERATOR_REASONER``;
* here: the Harness's own Skill / Reasoning Layer proposes all of it, the Harness Core validates and
  commits, the Controller executes transitions. This runner only

  - loads the PUBLIC scenario through the Harness scenario loader,
  - adapts the unchanged Scenario Controller to the Harness ``Environment`` interface (tools, stakeholder
    answers, the contract document, the checkpoint-gated late evidence) — ``CONTROLLER`` actor,
  - plays the Human at the Mandatory Human Gate (asks a question, then never decides) — ``HUMAN`` actor,
  - forks the state to run the baseline's negative-control probes — ``PROBE`` actor,
  - records what the Harness produced.

Affordance catalog (which operations / interviews are reachable at which stage) = exactly the
operations the baseline runner exposed at that stage (no IV factors, no hypothesis links, no evidence
mapping — those are now Reasoner proposals).

Usage:
  python3 mocks/mock6/autonomous/run_mock6_autonomous.py --variant scoped --provider claude [--model sonnet]
  python3 mocks/mock6/autonomous/run_mock6_autonomous.py --variant u1_default_scope   # replays scoped
  python3 mocks/mock6/autonomous/run_mock6_autonomous.py --variant scoped --provider replay
  python3 mocks/mock6/autonomous/run_mock6_autonomous.py --variant scoped --provider api \
      --outdir artifacts/reliability/runs/<run_id>     # independent API provider (AITOP_REASONER_* env)
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MOCK = HERE.parent
sys.path.insert(0, str(MOCK))  # baseline runner module (measurement helpers + hidden-truth guard)
sys.path.insert(0, str(MOCK.parents[1] / "src"))
sys.path.insert(0, str(MOCK / "scenario_pack"))

import run_mock6 as base  # noqa: E402  — installs the same hidden-ground-truth open() guard
from controller import ScenarioController  # noqa: E402

from aitop_harness.core.enums import (  # noqa: E402
    Criticality,
    EvidenceSourceType,
    ExecutionStatus,
    HumanDecisionKind,
    Phase,
    ProtectedActionCategory,
    Reversibility,
    SourceAuthority,
)
from aitop_harness.core.errors import HarnessError  # noqa: E402
from aitop_harness.core.events import EventType  # noqa: E402
from aitop_harness.core.scope import ScopeItem  # noqa: E402
from aitop_harness.core.serialization import to_dict  # noqa: E402
from aitop_harness.engine.autonomous import AutonomousConfig, AutonomousOrchestrator  # noqa: E402
from aitop_harness.engine.context import HarnessContext  # noqa: E402
from aitop_harness.engine.controller import PhaseController  # noqa: E402
from aitop_harness.engine.environment import Affordance, ExternalInput, GateView  # noqa: E402
from aitop_harness.engine.proposals import (  # noqa: E402
    DefineContext,
    Observation,
    commit_problem_definition,
    integrate_observation,
)
from aitop_harness.engine.views import render_records, state_view  # noqa: E402
from aitop_harness.phases.define import apply_define_gate, evaluate_define_gate  # noqa: E402
from aitop_harness.phases.discover import (  # noqa: E402
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    integrate_evidence,
    rank_actions,
    select_next_action,
)
from aitop_harness.phases.execute import invoke_tool  # noqa: E402
from aitop_harness.phases.human_gate import HumanDecision, decide, propose_protected_action  # noqa: E402
from aitop_harness.phases.recovery import FailureContext, decide_recovery  # noqa: E402
from aitop_harness.phases.redefine import validate_problem_invalidation  # noqa: E402
from aitop_harness.phases.release import evaluate_release_gate  # noqa: E402
from aitop_harness.phases.verify import run_verify  # noqa: E402
from aitop_harness.reasoning.providers.claude_cli import ClaudeCLIProvider  # noqa: E402
from aitop_harness.reasoning.providers.config import config_from_env, describe, provider_from_config  # noqa: E402
from aitop_harness.reasoning.providers.fault import FaultInjectingProvider  # noqa: E402
from aitop_harness.reasoning.providers.replay import RecordingProvider, ReplayProvider  # noqa: E402
from aitop_harness.reasoning.reasoner import Reasoner  # noqa: E402
from aitop_harness.reasoning.skills.evidence import interpret_payload  # noqa: E402
from aitop_harness.scenario import load_context  # noqa: E402
from aitop_harness.state.runtime import ProtectedActionProposal  # noqa: E402
from aitop_harness.supervision.projection import refresh  # noqa: E402
from aitop_harness.tools.base import ToolRegistry  # noqa: E402

S = ScopeItem
inventory, event_dict, save = base.inventory, base.event_dict, base.save

# Affordances exposed per stage = the operations the baseline runner exposed at that stage.
CATALOG = {
    "discover": [
        "crm-tickets:dispute_response_times", "crm-tickets:dispute_volume_monthly",
        "billing-db:disputed_bills_by_read_type", "route-log:route_completion_aug_sep",
        "mdms-export:read_events_for_disputed_estimated", "billing-db:tariff_change_log",
        "interview:SH-FIELD", "interview:SH-BILL",
    ],
    "reprofile": ["billing-config:validation_rule_changes", "mdms-export:meter_firmware_units"],
    "execute@v1": ["route-log:lagging_routes", "billing-db:accounts_estimated_last_cycle"],
    "execute@v2": ["billing-db:import_status_estimated_disputed", "billing-db:affected_accounts_v42",
                   "mdms-export:reads_for_accounts"],
}
LATE_REF = "mdms-export:read_events_for_disputed_estimated"
HUMAN_SCRIPT: list[str | None] = ["왜 지금 이걸 승인해야 해? 근거는?"] + [None] * 8


# =========================================================================== environment adapter


class Mock6Environment:
    """Adapts the unchanged ScenarioController to the Harness Environment interface (CONTROLLER)."""

    def __init__(self, ctl: ScenarioController, reg: ToolRegistry, public: dict[str, Any], runner: Runner) -> None:
        self.ctl = ctl
        self.registry = reg
        self.runner = runner
        self.describes = {t["tool_id"]: t["describes"] for t in public["tool_surface"]}
        self.contract_delivered = False
        self.late_delivered = False

    def _aff(self, ref: str) -> Affordance:
        kind, _, rest = ref.partition(":")
        if kind == "interview":
            return Affordance(ref, DiscoveryActionKind.STAKEHOLDER_INTERVIEW, rest, "interview",
                              f"interview stakeholder {rest}")
        return Affordance(ref, DiscoveryActionKind.TOOL_QUERY, kind, rest, self.describes.get(kind, ""))

    def catalog(self, stage: str, ctx: HarnessContext) -> list[Affordance]:
        pd = ctx.problem.problem_definition
        version = pd.version if pd else 1
        refs = CATALOG.get(f"{stage}@v{version}", CATALOG.get(stage, []))
        return [self._aff(r) for r in refs]

    def interview(self, stakeholder_id: str, question: str) -> str:
        return self.ctl.interview(stakeholder_id)

    def review_document(self, ref: str) -> ExternalInput:
        raise KeyError(ref)

    def executor(self, tool_id: str) -> Any:
        if tool_id != self.ctl.dispatch.tool_id:
            raise KeyError(tool_id)
        return self.ctl.dispatch

    def poll(self, ctx: HarnessContext) -> list[ExternalInput]:
        out: list[ExternalInput] = []
        if not self.contract_delivered and ctx.runtime.phase is not Phase.DISCOVER:
            self.contract_delivered = True
            doc = self.ctl.contract_document()
            out.append(ExternalInput(EvidenceSourceType.DOCUMENT, doc.source_id, doc.content,
                                     SourceAuthority.AUTHORITATIVE, method="document review",
                                     label="field services contract"))
        if not self.late_delivered and self._late_due(ctx):
            self.late_delivered = True
            self.runner.before_late(ctx)
            msg = self.ctl.provision_mdms(ctx)  # refuses before the Phase-1 checkpoint
            self.runner.after_provision(ctx)
            out.append(ExternalInput(EvidenceSourceType.STAKEHOLDER, "SH-AMI", msg, label="vendor notice"))
        return out

    def _late_due(self, ctx: HarnessContext) -> bool:
        if ctx.runtime.phase is not Phase.EXECUTE or not self.ctl.phase1_checkpoint(ctx)["ok"]:
            return False
        pending = ctx.runtime.pending_protected_action
        if ctx.runtime.execution_status is ExecutionStatus.WAITING_APPROVAL and pending is not None:
            requested = pending.confirmation.requested_at or 0.0
            return ctx.clock.now() - requested >= 5.0  # baseline: late evidence 5 minutes after the gate
        # no gate: delivered at the end of phase-1 execution (the orchestrator polls before leaving EXECUTE)
        return ctx.runtime.current_plan is not None


class Human:
    """HUMAN: asks why (REQUEST_CONTEXT) at the gate, then never decides on the main line."""

    def __init__(self) -> None:
        self.script = list(HUMAN_SCRIPT)
        self.seen: list[dict[str, Any]] = []

    def respond(self, gate: GateView) -> str | None:
        text = self.script.pop(0) if self.script else None
        self.seen.append({"gate": gate.gate_id, "round": gate.round, "said": text,
                          "explanation_received": gate.explanation})
        return text


# =========================================================================== runner


def fork(*objs: Any) -> Any:
    return copy.deepcopy(objs)


class Runner:
    def __init__(self, variant: str, reasoner: Reasoner, probe_reasoner: Reasoner,
                 outdir: Path | None = None) -> None:
        self.variant = variant
        self.outdir = outdir or MOCK / "results_autonomous" / variant
        with base._real_open(MOCK / "scenario_pack" / "public_scenario.json", encoding="utf-8") as fh:
            self.public = json.load(fh)
        self.ctl = ScenarioController()
        self.reg = self.ctl.registry()
        self.ctx = load_context(self.public)  # PUBLIC scenario only
        self.env = Mock6Environment(self.ctl, self.reg, self.public, self)
        self.human = Human()
        self.reasoner = reasoner
        self.probe_reasoner = probe_reasoner
        self.obs: dict[str, Any] = {"variant": variant, "probes": {}, "checkpoints": {}, "catalog": CATALOG,
                                    "late_ref": LATE_REF}
        self.pre_late: Any = None
        self.late_event_index = 0
        self.late_live_index = 0
        self.v1_protected: list[ProtectedActionProposal] = []
        self.pre_define_v2: Any = None
        self.challenges_seen = 0
        cfg = AutonomousConfig(observer=self.observe)
        if variant == "u1_default_scope":
            cfg.ignore_unknown_scope_versions = {1}  # every v1 unknown keeps the default (ENTIRE) scope
        notes = {k: v for k, v in self.public.items() if k not in ("scenario", "problem", "_comment")}
        self.orch = AutonomousOrchestrator(self.ctx, self.env, reasoner, self.human, public_notes=notes, config=cfg)

    # ------------------------------------------------------------------ recording helpers

    def snap(self, name: str) -> None:
        save(self.outdir, name, self.ctx.snapshot())

    def probe(self, name: str, fn: Any) -> None:
        try:
            self.obs["probes"][name] = fn()
        except Exception as exc:  # noqa: BLE001 — a probe crash is recorded, never hidden
            self.obs["probes"][name] = {"probe_error": f"{type(exc).__name__}: {exc}",
                                        "trace": traceback.format_exc(limit=4)}

    @staticmethod
    def attempt(fn: Any) -> tuple[Any, str | None]:
        try:
            return fn(), None
        except HarnessError as exc:
            return None, f"{type(exc).__name__}: {exc}"

    def evidence_from(self, ctx: HarnessContext, source: str, method: str | None = None) -> str | None:
        for e in ctx.problem.evidence.values():
            if e.source_id == source and (method is None or e.provenance.method == method):
                return e.id
        return None

    # ------------------------------------------------------------------ observer (named Harness checkpoints)

    def observe(self, name: str, orch: AutonomousOrchestrator) -> None:
        ctx = orch.ctx
        pd = ctx.problem.problem_definition
        version = pd.version if pd else 0
        if name == "draft_ready" and version == 1:
            self.probe("P1_P2_precanonical", lambda: self.probe_precanonical())
        elif name == "define_gate_passed":
            last = ctx.events.last(EventType.DEFINE_GATE_RESULT)
            key = "define_gate_v1" if version == 1 else "define_gate_v2"
            self.obs[key] = {"result": last.payload["result"] if last else None,
                             "findings": [(f["check"], f["severity"], f["message"]) for f in
                                          (last.payload["findings"] if last else []) if f["severity"] != "OK"],
                             "vobs": last.payload["vobs"] if last else []}
            if version == 1:
                self.obs["inventory_define_v1"] = inventory(ctx)
        elif name == "protected_action_proposed" and version == 1 and orch.plan is not None:
            self.v1_protected = [p for _, p in orch.plan.protected]
            last = ctx.events.last(EventType.APPROVAL_PACKET_EMITTED)
            blocked = ctx.events.last(EventType.PROTECTED_ACTION_BLOCKED)
            self.obs["dispatch_gate_v1"] = {
                "status": ctx.runtime.execution_status.value,
                "pending": ctx.runtime.pending_protected_action.gate_id if ctx.runtime.pending_protected_action else None,
                "packet": last.payload.get("packet") if last else None,
                "blocked_reasons": blocked.payload.get("reasons") if blocked else None,
            }
        elif name.startswith("human_"):
            self.obs.setdefault("human_interactions", []).append(
                {"kind": name, "minute": ctx.clock.now(), "status": ctx.runtime.execution_status.value,
                 "pending": ctx.runtime.pending_protected_action.gate_id if ctx.runtime.pending_protected_action else None,
                 "executed_actions": len(ctx.problem.execution.actions)})
        elif name == "challenge_detected" and self.challenges_seen == 0:
            self.challenges_seen += 1
            refresh(ctx)
            self.obs["harness_reaction_to_late_evidence"] = {
                "new_events": [event_dict(e) for e in list(ctx.events)[self.late_event_index:]],
                "new_live_summary": ctx.supervision.live_summary[self.late_live_index:],
                "problem_status": pd.status.value if pd else None,
                "transition_candidate": to_dict(ctx.runtime.transition_candidate),
                "recovery_candidate": ctx.runtime.recovery.candidate_transition.value
                if ctx.runtime.recovery.candidate_transition else None,
                "execution_status": ctx.runtime.execution_status.value,
                "pending_gate": ctx.runtime.pending_protected_action.gate_id
                if ctx.runtime.pending_protected_action else None,
                "challenge": to_dict(pd.open_challenges()[-1]) if pd and pd.open_challenges() else None,
            }
            self.obs["inventory_after_late_evidence"] = inventory(ctx)
            self.snap("snapshot_after_late_evidence.json")
            if self.pre_late is not None:
                for impact in (None, Criticality.MEDIUM, Criticality.CRITICAL):
                    label = "P4_control_no_late_evidence" if impact is None else f"P4_no_transition_{impact.value}"
                    self.probe(label, lambda i=impact: self.probe_no_transition(i))
            self.probe("P5_discrimination", lambda: self.probe_discrimination())
            if not self.obs.get("human_interactions"):  # main line opened no gate: exercise one on a fork
                self.probe("RC_autonomous_gate", lambda: self.probe_request_context())
        elif name == "transition_validated" and orch.last_verdict is not None:
            v = orch.last_verdict
            self.obs.setdefault("transition_decisions", []).append(
                {"proposed": v.proposed, "kind": v.core_kind.value if v.core_kind else None,
                 "execute": v.execute_redefine, "escalate": v.escalate, "trigger": v.trigger,
                 "rationale": v.decision.rationale if v.decision else v.rationale,
                 "reprofile_targets": v.reprofile_targets,
                 "transition_candidate": to_dict(ctx.runtime.transition_candidate)})
            self.obs["transition_decision"] = self.obs["transition_decisions"][-1]
        elif name == "after_redefine" and "redefine_attempt_1" not in self.obs:
            self.obs["redefine_attempt_1"] = {"error": None, "inventory": inventory(ctx)}
            self.probe("P6b_approve_after_failed_redefine", lambda: self.probe_approve_after_redefine())
            refresh(ctx)
            self.obs["inventory_after_redefine"] = inventory(ctx)
            self.snap("snapshot_after_redefine.json")
            self.probe("P9_advance_without_new_definition", lambda: self.probe_advance_without_new_definition())
            self.probe("P10_duplicate_redefine", lambda: self.probe_duplicate_redefine())
            self.probe("P8_reprofile_targeting", lambda: self.probe_reprofile_targeting())
        elif name == "before_define" and version >= 1:
            self.pre_define_v2 = fork(ctx, self.reg, self.ctl)
        elif name == "draft_ready" and version >= 2 and "P7_version_reuse" not in self.obs["probes"]:
            self.probe("P7_version_reuse", lambda: self.probe_version_reuse())
        if name == "define_gate_passed" and version >= 2 and "C5_citability" not in self.obs["probes"]:
            self.probe("C5_citability", lambda: self.probe_citability())
        elif name == "release_gate" and orch.release is not None:
            r = orch.release
            self.obs["release_v2" if version >= 2 else f"release_v{version}"] = {
                "decision": r.decision.value, "hold": r.hold_reasons, "limitations": r.known_limitations,
                "minimum_useful": to_dict(r.minimum_useful)}

    def before_late(self, ctx: HarnessContext) -> None:
        refresh(ctx)
        self.obs["checkpoints"]["phase1"] = self.ctl.phase1_checkpoint(ctx)
        self.obs["inventory_v1"] = inventory(ctx)
        self.snap("snapshot_checkpoint_v1.json")
        self.pre_late = fork(ctx, self.reg, self.ctl)
        self.late_event_index = len(ctx.events)
        self.late_live_index = len(ctx.supervision.live_summary)

    def after_provision(self, ctx: HarnessContext) -> None:
        self.obs["late_evidence_provisioned_at_minute"] = ctx.clock.now()

    # ------------------------------------------------------------------ probes (negative controls on forks)

    def _late_interpretation(self) -> Any:
        return self.orch.interpretations.get(LATE_REF)

    def probe_precanonical(self) -> dict[str, Any]:
        c, _, _ = fork(self.ctx, self.reg, self.ctl)
        sla = self.evidence_from(c, "crm-tickets", "dispute_response_times") or next(
            (e for e in c.problem.evidence if c.problem.evidence[e].source_type is EvidenceSourceType.TOOL), None)
        res: dict[str, Any] = {"problem_status": c.problem.problem_definition.status.value,
                               "gate_result": str(c.problem.problem_definition.gate_result), "evidence_used": sla}
        dec, err = self.attempt(lambda: decide_recovery(c, FailureContext("n/a", "n/a", None, None, None,
                                                                          problem_invalidating_evidence=sla)))
        res["decide_recovery_kind_on_draft"] = dec.kind.value if dec else err
        _, err = self.attempt(lambda: PhaseController(c).redefine(sla, "probe: pre-canonical contradiction"))
        res["redefine_on_draft_error"] = err
        res["redefine_on_draft_accepted"] = err is None
        res["problem_status_after"] = c.problem.problem_definition.status.value
        res["problem_invalidated_events"] = len(c.events.of_type(EventType.PROBLEM_INVALIDATED))
        return res

    def probe_no_transition(self, impact: Criticality | None) -> dict[str, Any]:
        c, r, k = fork(*self.pre_late)
        res: dict[str, Any] = {"impact": impact.value if impact else "CONTROL (no late evidence)"}
        if impact is not None:
            k.provision_mdms(c)
            o = invoke_tool(c, r, "mdms-export", "read_events_for_disputed_estimated")
            integrate_observation(
                c,
                Observation(EvidenceSourceType.TOOL, "mdms-export", o.operation,
                            render_records("mdms-export", o.operation, o.result.records),
                            authority=o.result.source_authority, completeness=o.completeness, catalog_ref=LATE_REF),
                self._late_interpretation(), "probe-replay-of-main-line-interpretation", decision_impact=impact,
            )
        res["problem_status"] = c.problem.problem_definition.status.value
        res["transition_candidate"] = to_dict(c.runtime.transition_candidate)
        res["conflicts"] = {i: (x.decision_impact.value, x.assertion) for i, x in c.problem.conflicts.items()}
        out, err = self.attempt(lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE, "approve"), k.dispatch))
        res["approve_status"] = out.status.value if out else err
        res["dispatch_calls"] = k.dispatch.count("push_route_update")
        ctl_ = PhaseController(c)
        self.attempt(ctl_.advance)
        scope = list(c.problem.solution_design.release_scope) if c.problem.solution_design else []
        rep, err = self.attempt(lambda: run_verify(c, scope))
        res["verify_failed"] = [x.name for x in rep.failed()] if rep else err
        self.attempt(ctl_.advance)
        gate, err = self.attempt(lambda: evaluate_release_gate(c, rep, scope))
        res["release_decision"] = gate.decision.value if gate else err
        res["hold_reasons"] = gate.hold_reasons if gate else None
        res["known_limitations"] = gate.known_limitations if gate else None
        return res

    def probe_discrimination(self) -> dict[str, Any]:
        c, _, k = fork(self.ctx, self.reg, self.ctl)
        late = self.evidence_from(c, "mdms-export", "read_events_for_disputed_estimated")
        decoy = k.dispatch_api_notice()
        integrate_evidence(c, decoy)
        res: dict[str, Any] = {"late_evidence": late}
        for label, ev in (("late_mdms", late), ("decoy_path_only", decoy.id), ("none", None)):
            fc = FailureContext("field-dispatch", "push_route_update", None, "ENDPOINT_RETIRED", False,
                                alternate_paths=["dispatch API v3"], problem_invalidating_evidence=ev)
            d, err = self.attempt(lambda fc=fc: decide_recovery(c, fc))
            res[f"decide_recovery[{label}]"] = d.kind.value if d else err
        if c.runtime.pending_protected_action is not None:
            self.attempt(lambda: decide(c, HumanDecision(HumanDecisionKind.REJECT, "reject"), k.dispatch))
        _, err = self.attempt(lambda: PhaseController(c).redefine(decoy.id, "probe: path-only evidence"))
        res["redefine_on_path_only_evidence_accepted"] = err is None
        res["redefine_on_path_only_error"] = err
        # autonomous path: the Reasoner interprets the same path-only notice; the Core must not redefine
        c2, _, _ = fork(self.ctx, self.reg, self.ctl)
        before = len(c2.problem.problem_definition.challenges)
        obs = Observation(EvidenceSourceType.DOCUMENT, decoy.source_id, "vendor notice", decoy.content,
                          authority=SourceAuthority.AUTHORITATIVE)
        payload = interpret_payload(
            state_view(c2, public_notes=self.orch.public_notes),
            {"source_type": "DOCUMENT", "source": decoy.source_id, "method": "vendor notice",
             "authority": "AUTHORITATIVE", "completeness": "NOT_APPLICABLE", "content": decoy.content,
             "catalog_ref": None},
            [], set(), {},
        )
        rr = self.probe_reasoner.invoke("interpret_evidence", payload, state_version=c2.problem.meta.version)
        prop = rr.proposal if rr.ok else None
        out = integrate_observation(c2, obs, prop, rr.record.reasoning_id)
        res["autonomous_decoy"] = {
            "reasoning_status": rr.record.status.value,
            "evidence": out.evidence_id,
            "reasoner_target_type": prop.assessment.target_type if prop else None,
            "reasoner_problem_invalidating": prop.assessment.problem_invalidating if prop else None,
            "core_assessment": out.assessment,
            "new_challenge_from_decoy": len(c2.problem.problem_definition.challenges) > before,
            "core_redefine_validation": validate_problem_invalidation(c2.problem, out.evidence_id)[1],
        }
        return res

    def probe_request_context(self) -> dict[str, Any]:
        """REQUEST_CONTEXT at a Mandatory Human Gate under the canonical v1 Problem (fork before late evidence).

        Used only when the Reasoner's own v1 plan proposed no protected action: the constrained action
        (K-DISPATCH) is proposed through the Core gate, the Human asks a question, nothing may execute.
        """
        c, _, k = fork(*self.pre_late)
        auth = next((a for a in c.problem.domain_authorizations.values()
                     if a.action == "push_route_update" and a.is_effective()), None)
        scope = [auth.authorized_scope.items[0]] if auth and auth.authorized_scope.items else [
            S("push_route_update", "field-dispatch")]
        scope = [S(i.action, "field-dispatch" if i.target == "*" else i.target) for i in scope]
        prop = ProtectedActionProposal(
            "RC-DISPATCH", "push_route_update", "route priority update", "field-dispatch", scope,
            ProtectedActionCategory.PROTECTED_MUTATION, why="probe: v1 route priority", side_effect="crews re-sequenced",
            reversibility=Reversibility.REVERSIBLE, idempotency_key="rc-probe",
            key_evidence=list(c.problem.problem_definition.evidence_refs)[:2])
        gate, err = self.attempt(lambda: propose_protected_action(c, prop, k.dispatch))
        res: dict[str, Any] = {"propose_status": gate.status.value if gate else err,
                               "blocked_reasons": gate.reasons if gate else None}
        if gate is None or gate.status.value != "WAITING_APPROVAL":
            return res
        from aitop_harness.phases.human_gate import interpret_human_input

        text = HUMAN_SCRIPT[0]
        kind = interpret_human_input(text or "")
        before = len(c.events)
        out = decide(c, HumanDecision(kind, text or ""), k.dispatch)
        new = list(c.events)[before:]
        res.update(
            text=text, interpreted=kind.value, status_after=c.runtime.execution_status.value,
            same_gate_pending=bool(c.runtime.pending_protected_action
                                   and c.runtime.pending_protected_action.gate_id == gate.gate_id),
            executed=k.dispatch.count("push_route_update"),
            approval_granted=any(e.type is EventType.APPROVAL_GRANTED for e in new),
            context_requested_event=any(e.type is EventType.HUMAN_CONTEXT_REQUESTED for e in new),
            explanation=out.explanation,
        )
        return res

    def probe_approve_after_redefine(self) -> dict[str, Any]:
        c, _, k = fork(self.ctx, self.reg, self.ctl)
        res: dict[str, Any] = {"problem_status_before": c.problem.problem_definition.status.value,
                               "execution_status_before": c.runtime.execution_status.value}
        out, err = self.attempt(lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE, "approve"), k.dispatch))
        res["approve_status"] = out.status.value if out else err
        res["dispatch_calls"] = k.dispatch.count("push_route_update")
        res["protected_action_executed_events"] = len(c.events.of_type(EventType.PROTECTED_ACTION_EXECUTED))
        return res

    def _old_dispatch(self) -> ProtectedActionProposal:
        if self.v1_protected:
            p = copy.deepcopy(self.v1_protected[0])
        else:  # v1 never proposed it (e.g. blocked by a VOB): re-propose the constrained action itself
            p = ProtectedActionProposal("DISPATCH-OLD", "push_route_update", "v1 route priorities", "field-dispatch",
                                        [S("push_route_update", "field-dispatch")],
                                        ProtectedActionCategory.PROTECTED_MUTATION, why="v1 premise",
                                        reversibility=Reversibility.REVERSIBLE)
        p.action_id, p.idempotency_key = f"{p.action_id}-B", f"{p.idempotency_key}-b"
        return p

    def probe_advance_without_new_definition(self) -> dict[str, Any]:
        c, _, k = fork(self.ctx, self.reg, self.ctl)
        ctl_ = PhaseController(c)
        res: dict[str, Any] = {"pd_status": c.problem.problem_definition.status.value,
                               "pd_gate_result": str(c.problem.problem_definition.gate_result)}
        _, e1 = self.attempt(ctl_.advance)
        _, e2 = self.attempt(ctl_.advance)
        res.update(advance_design_error=e1, advance_execute_error=e2, phase=c.runtime.phase.value)
        g, e3 = self.attempt(lambda: propose_protected_action(c, self._old_dispatch(), k.dispatch))
        res["propose_status"] = g.status.value if g else e3
        if g is not None and g.status.value == "WAITING_APPROVAL":
            o, _ = self.attempt(lambda: decide(c, HumanDecision(HumanDecisionKind.APPROVE), k.dispatch))
            res["approve_status"] = o.status.value if o else None
        res["dispatch_calls"] = k.dispatch.count("push_route_update")
        scope = list(c.problem.solution_design.release_scope) if c.problem.solution_design else []
        rep, _ = self.attempt(lambda: run_verify(c, scope))
        gate, _ = self.attempt(lambda: evaluate_release_gate(c, rep, scope))
        res["release_decision"] = gate.decision.value if gate else None
        res["hold_reasons"] = gate.hold_reasons if gate else None
        return res

    def probe_duplicate_redefine(self) -> dict[str, Any]:
        c, _, _ = fork(self.ctx, self.reg, self.ctl)
        ps = c.problem
        late = self.evidence_from(c, "mdms-export", "read_events_for_disputed_estimated")

        def counts() -> dict[str, Any]:
            return {"history": len(ps.meta.problem_definition_history),
                    "redefine_decisions": sum(1 for d in ps.decision_log if d.decision == "REDEFINE"),
                    "problem_invalidated_events": len(c.events.of_type(EventType.PROBLEM_INVALIDATED)),
                    "invalidated_by": list(ps.problem_definition.invalidated_by),
                    "dependency_reviews": len(ps.dependency_reviews)}

        before = counts()
        _, err = self.attempt(lambda: PhaseController(c).redefine(late, "probe: duplicate redefine"))
        after = counts()
        return {"evidence": late, "before": before, "after": after, "error": err, "no_mutation": before == after,
                "noop_events": len(c.events.of_type(EventType.REDEFINE_NOOP))}

    def probe_reprofile_targeting(self) -> dict[str, Any]:
        c, _, _ = fork(self.ctx, self.reg, self.ctl)
        verdict = self.orch.last_verdict
        targets = list(verdict.reprofile_targets) if verdict and verdict.reprofile_targets else ["DA-RULES"]
        ctl_ = PhaseController(c)
        _, err = self.attempt(lambda: ctl_.reprofile(targets, "probe: confirm mechanism"))
        old = ["route-log:route_completion_aug_sep", "billing-db:disputed_bills_by_read_type", "interview:SH-FIELD"]
        f = InformationValueFactors(0.8, 0.6, 0.7, 0.9, 0.5, 0.3, 0.0, 3.0)  # uniform: targeting decides
        cands = [DiscoveryAction(r, a.kind, a.target, a.operation, f,
                                 tool_id=a.target if a.kind is DiscoveryActionKind.TOOL_QUERY else None)
                 for r in old + CATALOG["reprofile"] for a in [self.env._aff(r)]]  # noqa: SLF001
        ranked = rank_actions(c, cands)
        sel = select_next_action(c, cands)
        reprofile_tools = {r.split(":")[0] for r in CATALOG["reprofile"]}
        return {"reprofile_targets": list(c.runtime.reprofile_targets), "reprofile_error": err,
                "ranking": [(x.action.id, x.score, x.excluded, x.reason) for x in ranked],
                "selected": sel.id if sel else None,
                "selected_is_targeted": bool(sel and sel.target in reprofile_tools),
                "old_actions_excluded": all(x.excluded for x in ranked if x.action.id in old)}

    def probe_version_reuse(self) -> dict[str, Any]:
        c, r, _ = fork(*self.pre_define_v2)
        prop = self.orch.proposals.get("define_problem")
        pd, err = self.attempt(lambda: commit_problem_definition(
            c, prop, "probe-v2-proposal", registry=r, dctx=DefineContext(
                framing_hypotheses=list(self.orch.dctx.framing_hypotheses))))
        res: dict[str, Any] = {"define_error": err, "assigned_version": pd.version if pd else None,
                               "version_assigned_events": [e.payload for e in
                                                           c.events.of_type(EventType.PROBLEM_VERSION_ASSIGNED)][-1:]}
        g, _ = self.attempt(lambda: apply_define_gate(c, evaluate_define_gate(c, r)))
        ctl_ = PhaseController(c)
        self.attempt(ctl_.advance)
        _, err = self.attempt(ctl_.advance)
        res.update(gate=str(g), stale_sd1_reached_execute=err is None and c.runtime.phase is Phase.EXECUTE,
                   advance_error=err, solution_design=c.problem.solution_design.id if c.problem.solution_design else None,
                   sd_problem_version=c.problem.solution_design.problem_version if c.problem.solution_design else None)
        return res

    def probe_citability(self) -> dict[str, Any]:
        """C5 attempt A: a still-true observation whose interpretation was revised stays citable."""
        pd = self.ctx.problem.problem_definition
        revised = [r.evidence_id for r in self.ctx.problem.evidence_revisions.values()
                   if r.revision_kind.value != "OBSERVATION_INVALIDATED"]
        cited = [e for e in pd.evidence_refs if e in revised]
        if cited:
            g = evaluate_define_gate(self.ctx, self.reg)
            return {"mode": "main line cites revised evidence", "cited_revised": cited, "result": g.result.value,
                    "findings": [(f.check, f.severity.value, f.message) for f in g.findings if f.severity.value != "OK"]}
        c, r, _ = fork(self.ctx, self.reg, self.ctl)
        add = revised[:1]
        c.problem.problem_definition.evidence_refs = list(pd.evidence_refs) + add
        g = evaluate_define_gate(c, r)
        return {"mode": "probe adds a revised evidence citation", "cited_revised": add, "result": g.result.value,
                "findings": [(f.check, f.severity.value, f.message) for f in g.findings if f.severity.value != "OK"]}

    # ------------------------------------------------------------------ main

    def run(self) -> dict[str, Any]:
        t0 = time.time()
        self.ctx.clock.advance(0)
        result = self.orch.run()
        refresh(self.ctx)
        o = self.obs
        o["result"] = {"release_decision": result.release_decision.value if result.release_decision else None,
                       "halt_reason": result.halt_reason, "phase": result.phase.value,
                       "execution_status": result.execution_status.value, "problem_ref": result.problem_ref,
                       "operator_reasoner_calls": result.operator_reasoner_calls,
                       "trace_actors": sorted({t["actor"] for t in result.trace}),
                       "wall_seconds": round(time.time() - t0, 1)}
        rec = next((e for e in self.ctx.events.of_type(EventType.RECOVERY_DECISION)
                    if e.payload.get("tool") == "mdms-export"), None)
        o["tool_failure_recovery"] = {"kind": rec.payload["kind"], "rationale": rec.payload["rationale"],
                                      "stop_reason": rec.payload["stop_reason"]} if rec else {"kind": None}
        if "transition_decision" not in o:
            o["transition_decision"] = {"kind": None}
        o["inventory_final"] = inventory(self.ctx)
        o["final_live_summary"] = list(self.ctx.supervision.live_summary)
        o["human"] = self.human.seen
        o["release_summary"] = self.orch.summary
        o["reasoning"] = [to_dict(r) | {"output": None} for r in result.reasoning]
        o["proposals"] = {r.reasoning_id: {"skill": r.skill, "status": r.status.value, "output": r.output}
                          for r in result.reasoning}
        self.snap("snapshot_final.json")
        save(self.outdir, "events.json", [event_dict(e) for e in self.ctx.events])
        save(self.outdir, "trace.json", result.trace)
        save(self.outdir, "observations.json", o)
        print(f"[{self.variant}] done: {len(self.ctx.events)} events, release={result.release_decision}, "
              f"halt={result.halt_reason}, reasoning calls={len(result.reasoning)}")
        return o


def live_provider(args: argparse.Namespace) -> Any:
    if args.provider == "api" or (args.provider not in ("claude", "api") and args.live == "api"):
        cfg = (json.loads(Path(args.provider_config).read_text(encoding="utf-8")) if args.provider_config
               else config_from_env(default=None))
        if args.model:
            cfg["model"] = args.model
        live: Any = provider_from_config(cfg)
    else:
        live = ClaudeCLIProvider(model=args.model or "sonnet")
    if args.faults:  # controlled provider-failure injection (main line only; probes stay clean)
        live = FaultInjectingProvider(live, json.loads(Path(args.faults).read_text(encoding="utf-8")))
    return live


def build_reasoner(args: argparse.Namespace, outdir: Path) -> tuple[Reasoner, Reasoner]:
    transcript = outdir / "reasoning_transcript.jsonl"
    probe_transcript = outdir / "reasoning_transcript_probes.jsonl"
    live = live_provider(args)
    probe_live = live.inner if isinstance(live, FaultInjectingProvider) else live
    if args.provider in ("claude", "api"):
        for p in (transcript, probe_transcript):
            if p.exists():
                p.unlink()
        return (Reasoner(RecordingProvider(live, transcript)),
                Reasoner(RecordingProvider(probe_live, probe_transcript)))
    if args.provider == "resume":  # replay a recorded (interrupted) run, continue live where it stops
        src = Path(args.transcript)
        entries = [json.loads(x) for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
        probe_src = src.with_name(src.stem + "_probes.jsonl")
        probe_entries = ([json.loads(x) for x in probe_src.read_text(encoding="utf-8").splitlines() if x.strip()]
                         if probe_src.exists() else [])
        for p in (transcript, probe_transcript):
            if p.exists():
                p.unlink()
        return (Reasoner(RecordingProvider(ReplayProvider(entries, strict=True, fallback=live), transcript)),
                Reasoner(RecordingProvider(ReplayProvider(probe_entries, strict=True, fallback=live), probe_transcript)))
    source = Path(args.transcript) if args.transcript else transcript
    source_probe = source.with_name(source.stem + "_probes.jsonl")
    fallback = RecordingProvider(live, outdir / "reasoning_transcript_fallback.jsonl") if args.live_fallback else None
    main = ReplayProvider.from_file(source, fallback=fallback)
    probes = (ReplayProvider.from_file(source_probe, fallback=fallback) if source_probe.exists()
              else ReplayProvider([], fallback=fallback))
    return Reasoner(main), Reasoner(probes)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--variant", default="scoped", choices=["scoped", "u1_default_scope"])
    p.add_argument("--provider", default=None, choices=["claude", "api", "replay", "resume"])
    p.add_argument("--model", default=None, help="claude: sonnet (default); api: provider config default")
    p.add_argument("--provider-config", default=None, help="api provider runtime config JSON (else AITOP_REASONER_*)")
    p.add_argument("--live", default="claude", choices=["claude", "api"],
                   help="live provider behind replay / resume / --live-fallback")
    p.add_argument("--faults", default=None, help="fault-injection rules JSON (FaultInjectingProvider)")
    p.add_argument("--outdir", default=None, help="results root (default mocks/mock6/results_autonomous)")
    p.add_argument("--transcript", default=None, help="replay transcript (default: this variant's own)")
    p.add_argument("--live-fallback", action="store_true", help="replay misses fall back to the live model")
    args = p.parse_args()
    root = Path(args.outdir) if args.outdir else MOCK / "results_autonomous"
    outdir = root / args.variant
    outdir.mkdir(parents=True, exist_ok=True)
    if args.provider is None:  # variant B replays the scoped run's reasoning (isolates the Core variant)
        args.provider = "claude" if args.variant == "scoped" else "replay"
        if args.variant == "u1_default_scope" and not args.transcript:
            args.transcript = str(root / "scoped" / "reasoning_transcript.jsonl")
            args.live_fallback = True
    reasoner, probe_reasoner = build_reasoner(args, outdir)
    runner = Runner(args.variant, reasoner, probe_reasoner, outdir)
    live = reasoner.provider
    while hasattr(live, "inner") or hasattr(live, "fallback"):
        live = getattr(live, "inner", None) or getattr(live, "fallback", None)
    runner.obs["provider"] = {"mode": args.provider, "model": args.model, "transcript": args.transcript,
                              "config": describe(live) if live is not None else None,
                              "faults": args.faults}
    try:
        runner.run()
    finally:
        injector = reasoner.provider.inner if isinstance(reasoner.provider, RecordingProvider) else None
        if isinstance(injector, FaultInjectingProvider):
            save(outdir, "faults_injected.json", injector.injected)
        save(outdir, "replay_misses.json", {"main": list(getattr(reasoner.provider, "misses", [])),
                                            "probes": list(getattr(probe_reasoner.provider, "misses", []))})
    for r in (reasoner, probe_reasoner):
        misses = getattr(r.provider, "misses", None)
        if misses:
            print("replay misses:", misses)


if __name__ == "__main__":
    main()

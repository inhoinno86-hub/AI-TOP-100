"""Proposal Gate — Harness Core validation boundary for Reasoning Layer proposals (IDR-REASON-01..05).

    Reasoner proposal → (this module) validate refs / authority / scope / evidence strength
                      → commit ONLY through existing Core paths (ctx.commit, phases.*) or reject

Rules applied everywhere:
* ids are Harness-owned (the Reasoner proposes a short key, the Core assigns / dedupes the id);
* every cited id must exist in committed state — unknown refs are dropped and recorded (hallucination
  control), and a proposal left without grounding is rejected;
* nothing becomes a Fact unless the existing ``establish_fact`` guard accepts the evidence;
* observations (Evidence.content) are rendered by the Core from raw results; the Reasoner's text is only
  ever stored as an *interpretation*;
* every accept / adjust / reject is written to the Event Log with the proposal's ``reasoning_id``.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from ..core.enums import (
    AssumptionStatus,
    AuthorizationStatus,
    ConflictStatus,
    ConstraintStatus,
    ConstraintType,
    Criticality,
    EvidenceSourceType,
    HypothesisStatus,
    Importance,
    MetricType,
    Phase,
    ProblemDefinitionStatus,
    ProtectedActionCategory,
    RecoveryKind,
    RequiredBefore,
    ResultCompleteness,
    Reversibility,
    RevisionKind,
    SourceAuthority,
    TransitionKind,
    UnknownStatus,
    VOBStatus,
    WorkClass,
)
from ..core.errors import HarnessError, StateIntegrityError
from ..core.events import EventType
from ..core.provenance import Provenance
from ..core.scope import WILDCARD, Scope, ScopeItem
from ..domain.authority import DomainAuthorization
from ..domain.design import (
    DecisionRecord,
    ProblemDefinition,
    SolutionDesign,
    StructuralRemedyCandidate,
    WorkItem,
)
from ..domain.epistemic import (
    Assumption,
    Evidence,
    Hypothesis,
    InterpretationEntry,
    SuccessCriterion,
    Unknown,
)
from ..domain.metric import Metric
from ..domain.verification import VerificationObligation
from ..phases.budget import reserve_active, set_plan
from ..phases.define import define_problem
from ..phases.design import DesignInputs, DesignSession
from ..phases.discover import (
    DiscoveryAction,
    DiscoveryActionKind,
    InformationValueFactors,
    establish_fact,
    integrate_evidence,
    record_claim,
    resolve_unknown,
    revise_evidence,
    update_hypothesis,
)
from ..phases.recovery import FailureContext, RecoveryDecision, apply_recovery_decision, decide_recovery
from ..phases.redefine import infer_revision_kind, is_strong, validate_problem_invalidation
from ..reasoning.models import (
    AgentDesignProposal,
    BlockingScopeReviewProposal,
    DiscoveryPlanProposal,
    EvidenceInterpretationProposal,
    ExecutionPlanProposal,
    HypothesisAssessmentProposal,
    HypothesisInitProposal,
    ProblemDefinitionProposal,
    RevisionSetProposal,
    ScopeRef,
    StructuralRemedyProposal,
    TransitionProposal,
    VOBProposal,
)
from ..state.runtime import Plan, ProtectedActionProposal, TransitionCandidate
from ..tools.base import ToolRegistry
from .context import HarnessContext
from .environment import Affordance
from .scope_contract import accepted_targets, normalize_scope_target

_HELD = (HypothesisStatus.SUPPORTED, HypothesisStatus.CONFIRMED)
_MATERIAL = (Criticality.HIGH, Criticality.CRITICAL)
_KEY = re.compile(r"^[a-z0-9][a-z0-9_.]*$")


class ProposalRejected(HarnessError):
    """The Core refused a Reasoner proposal (nothing was committed)."""


class FramingRejected(ProposalRejected):
    """Anti-anchoring refusal: the Problem rests on a hypothesis recorded as the requester's framing.

    Carried as a typed DEFINE repair finding (IDR-RV5-02) instead of free text."""

    def __init__(self, message: str, *, hypothesis: str, proposal_ref: str | None) -> None:
        super().__init__(message)
        self.hypothesis = hypothesis
        self.proposal_ref = proposal_ref


# --------------------------------------------------------------------------- bookkeeping


def record(
    ctx: HarnessContext,
    verdict: str,
    skill: str,
    reasoning_id: str | None,
    detail: dict[str, Any] | list[str] | str,
    *,
    refs: list[str] | None = None,
) -> None:
    kind = {
        "ACCEPTED": EventType.PROPOSAL_ACCEPTED,
        "ADJUSTED": EventType.PROPOSAL_ADJUSTED,
        "REJECTED": EventType.PROPOSAL_REJECTED,
    }[verdict]
    ctx.emit(
        kind,
        {"skill": skill, "reasoning_id": reasoning_id, "detail": detail},
        importance=Importance.HIGH if verdict == "REJECTED" else Importance.NORMAL,
        refs=list(refs or []),
    )


@dataclass
class Notes:
    """Adjustments made while validating one proposal (all recorded as a single PROPOSAL_ADJUSTED)."""

    items: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.items.append(msg)

    def flush(self, ctx: HarnessContext, skill: str, rid: str | None) -> None:
        if self.items:
            record(ctx, "ADJUSTED", skill, rid, self.items)


def make_id(prefix: str, key: str, existing: Any) -> str:
    slug = re.sub(r"[^A-Z0-9]+", "-", key.upper()).strip("-")
    if slug.startswith(prefix + "-"):
        slug = slug[len(prefix) + 1 :]
    slug = slug[:28].strip("-") or "X"
    cand, n = f"{prefix}-{slug}", 2
    while cand in existing:
        cand, n = f"{prefix}-{slug}-{n}", n + 1
    return cand


def _seq_id(prefix: str, existing: Any) -> str:
    n = len(existing) + 1
    while f"{prefix}-{n:02d}" in existing:
        n += 1
    return f"{prefix}-{n:02d}"


def _key(raw: str) -> str | None:
    k = re.sub(r"[^a-z0-9_.]+", "_", raw.strip().lower()).strip("_.")
    return k if k and _KEY.match(k) else None


_TOKEN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,47}$")
_NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?(e[+-]?\d+)?$")


def _value(v: Any) -> Any:
    """Assertion values must be canonical (number / boolean / short snake_case token) to be compared.

    The Core detects conflicts and premise contradictions by *equality*; free text would make two phrasings
    of the same fact look contradictory. Non-canonical text is therefore not used as a comparable value.
    """
    if v == "" or v is None:
        return None
    if isinstance(v, (bool, int, float)):
        return v
    token = str(v).strip().lower()
    # one canonical form per value: "1184" and 1184 (or "true" and True) are the same assertion value —
    # comparing them as different tokens would turn agreeing evidence into a false contradiction
    if token in ("true", "false"):
        return token == "true"
    if _NUMBER.match(token):
        number = float(token.replace(",", ""))
        return int(number) if number.is_integer() and "." not in token and "e" not in token else number
    return token if _TOKEN.match(token) else None


def _scope_items(refs: list[ScopeRef]) -> list[ScopeItem]:
    return [ScopeItem(r.action.strip(), r.target.strip() or WILDCARD) for r in refs]


def _filter(ids: list[str], known: Any, label: str, notes: Notes) -> list[str]:
    out = []
    for i in ids:
        if i in known:
            if i not in out:
                out.append(i)
        else:
            notes.add(f"dropped unknown {label} ref {i!r}")
    return out


# =========================================================================== DISCOVER


def commit_hypothesis_init(
    ctx: HarnessContext, prop: HypothesisInitProposal, rid: str | None
) -> tuple[dict[str, str], list[str]]:
    """Initial hypotheses + the initial request recorded as a Claim (never a Fact).

    Returns (key → hypothesis id, ids of requester-framing hypotheses).
    """
    notes = Notes()
    if not any(h.origin != "REQUESTER_FRAMING" for h in prop.hypotheses):
        record(ctx, "REJECTED", "hypothesis_init", rid, "no alternative to the requester framing")
        raise ProposalRejected(
            "hypothesis_init must contain at least one alternative to the requester framing"
        )
    mapping: dict[str, str] = {}
    framing: list[str] = []
    with ctx.commit(f"initial hypotheses ({rid})") as ps:
        for h in prop.hypotheses:
            hid = make_id("H", h.key, ps.hypotheses)
            ps.hypotheses[hid] = Hypothesis(id=hid, statement=h.statement, decision_impact=h.decision_impact)
            mapping[h.key] = hid
            if h.origin == "REQUESTER_FRAMING":
                framing.append(hid)
    sc = ctx.problem.scenario
    key = _key(prop.framing_key)
    if key is None:
        notes.add(f"framing assertion key {prop.framing_key!r} invalid; claim recorded without assertion")
    record_claim(
        ctx,
        _seq_id("CL", ctx.problem.claims),
        sc.requested_by or "requester",
        sc.initial_request,
        assertion=key,
        value=_value(prop.framing_value) if key else None,
        is_initial_request=True,
    )
    notes.flush(ctx, "hypothesis_init", rid)
    record(
        ctx, "ACCEPTED", "hypothesis_init", rid, {"hypotheses": list(mapping.values()), "framing": framing}
    )
    return mapping, framing


def build_discovery_actions(
    ctx: HarnessContext,
    plan: DiscoveryPlanProposal,
    catalog: list[Affordance],
    executed: set[str],
    rid: str | None,
) -> tuple[list[DiscoveryAction], dict[str, str]]:
    """Reasoner IV estimates → DiscoveryActions. Only catalog, read-only, not-yet-executed refs.

    Returns (actions, action id → interview question).
    """
    notes = Notes()
    by_ref = {a.ref: a for a in catalog}
    actions: list[DiscoveryAction] = []
    questions: dict[str, str] = {}
    ps = ctx.problem
    for p in plan.actions:
        aff = by_ref.get(p.catalog_ref)
        if aff is None:
            notes.add(f"catalog ref {p.catalog_ref!r} not offered: dropped")
            continue
        if not aff.read_only:
            notes.add(f"{p.catalog_ref} is not read-only: discovery actions must be read-only")
            continue
        if p.catalog_ref in executed or any(a.id == p.catalog_ref for a in actions):
            continue
        hyps = _filter(p.discriminates_hypotheses, ps.hypotheses, "hypothesis", notes)
        unks = _filter(p.resolves_unknowns, ps.unknowns, "unknown", notes)
        actions.append(
            DiscoveryAction(
                id=aff.ref,
                kind=aff.kind,
                target=aff.target,
                question=aff.operation,
                factors=InformationValueFactors(
                    p.decision_impact,
                    p.uncertainty,
                    p.discriminative_power,
                    p.answerability,
                    p.process_data_handoff_impact,
                    p.action_proximity,
                    p.constraint_risk,
                    max(0.5, p.estimated_cost),
                ),
                resolves_unknowns=unks,
                discriminates_hypotheses=hyps,
                tool_id=aff.target if aff.kind is DiscoveryActionKind.TOOL_QUERY else None,
                read_only=True,
                addresses=list(p.addresses),
            )
        )
        questions[aff.ref] = p.question
    notes.flush(ctx, "discover_actions", rid)
    return actions, questions


# =========================================================================== evidence


@dataclass
class Observation:
    """Core-rendered observation of the world (never Reasoner text)."""

    source_type: EvidenceSourceType
    source_id: str
    method: str
    content: str
    authority: SourceAuthority
    completeness: ResultCompleteness = ResultCompleteness.NOT_APPLICABLE
    is_fallback: bool = False
    stakeholder_id: str | None = None
    catalog_ref: str | None = None
    event_seq: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)  # extra data shown to the Reasoner


@dataclass
class IntegrationOutcome:
    evidence_id: str
    claim_id: str | None = None
    challenge_raised: bool = False
    follow_ups: list[str] = field(default_factory=list)
    assessment: str = "NONE"  # CONSISTENT_CONFIRMED / CONSISTENT_NOT_CONFIRMED / INCONSISTENT / NONE / ...
    path_contradiction: bool = False
    problem_invalidating_claimed: bool = False
    premise_targets: list[str] = field(default_factory=list)


def _premise_ids(ctx: HarnessContext) -> set[str]:
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None:
        return set()
    premise = set(pd.evidence_refs)
    hyps = {
        h.id for h in ps.hypotheses.values() if h.status in _HELD and set(h.supporting_evidence) & premise
    }
    return premise | hyps


def integrate_observation(
    ctx: HarnessContext,
    obs: Observation,
    prop: EvidenceInterpretationProposal | None,
    rid: str | None,
    *,
    catalog: list[Affordance] | None = None,
    decision_impact: Criticality | None = None,
    provider: str = "",
) -> IntegrationOutcome:
    """Commit one observation as Evidence with the Reasoner's *validated* semantics."""
    ps = ctx.problem
    notes = Notes()
    eid = _seq_id("E", ps.evidence)
    key = value = None
    supports: list[str] = []
    contradicts: list[str] = []
    claim_id: str | None = None
    if prop is not None:
        key = _key(prop.assertion_key) if prop.assertion_key else None
        value = _value(prop.assertion_value) if key else None
        if key and value is None and prop.assertion_value not in ("", None):
            notes.add(
                f"assertion value {str(prop.assertion_value)[:60]!r} is not a canonical token: not compared"
            )
            key = None
        if prop.assertion_key and key is None:
            notes.add(f"assertion key {prop.assertion_key!r} invalid: dropped")
        # new hypotheses revealed by this observation (CANDIDATE; Core-assigned ids)
        new_ids: dict[str, str] = {}
        if prop.new_hypotheses:
            with ctx.commit(f"hypotheses proposed with {eid} ({rid})") as p:
                for h in prop.new_hypotheses:
                    if any(
                        x.statement.strip().lower() == h.statement.strip().lower()
                        for x in p.hypotheses.values()
                    ):
                        continue
                    hid = make_id("H", h.key, p.hypotheses)
                    p.hypotheses[hid] = Hypothesis(
                        id=hid, statement=h.statement, decision_impact=h.decision_impact
                    )
                    new_ids[h.key] = hid
                    supports.append(hid)
        for eff in prop.hypothesis_effects:
            hid = new_ids.get(eff.hypothesis, eff.hypothesis)
            if hid not in ps.hypotheses:
                notes.add(f"effect on unknown hypothesis {eff.hypothesis!r} dropped")
                continue
            if eff.effect == "SUPPORTS" and hid not in supports:
                supports.append(hid)
            elif eff.effect == "CONTRADICTS" and hid not in contradicts:
                contradicts.append(hid)
        both = set(supports) & set(contradicts)
        if both:
            notes.add(f"hypotheses both supported and contradicted {sorted(both)}: links dropped")
            supports = [h for h in supports if h not in both]
            contradicts = [h for h in contradicts if h not in both]
    if obs.source_type is EvidenceSourceType.STAKEHOLDER and obs.stakeholder_id:
        ckey = _key(prop.claim_assertion_key) if prop and prop.claim_assertion_key else key
        cval = (
            (_value(prop.claim_assertion_value) if prop and prop.claim_assertion_key else value)
            if ckey
            else None
        )
        claim_id = _seq_id("CL", ps.claims)
        record_claim(ctx, claim_id, obs.stakeholder_id, obs.content, assertion=ckey, value=cval)
        key, value = ckey, cval  # the evidence is "the stakeholder said so" — same assertion as the claim
    evidence = Evidence(
        id=eid,
        source_type=obs.source_type,
        source_id=obs.source_id,
        provenance=Provenance(
            obs.source_type,
            obs.source_id,
            method=obs.method,
            derived_from=[x for x in (obs.catalog_ref, rid) if x],
            event_seq=obs.event_seq if obs.event_seq is not None else (len(ctx.events) or None),
            recorded_at_minute=ctx.clock.now(),
        ),
        content=obs.content,
        target_assertion=key,
        value=value,
        reliability="HIGH" if obs.completeness is ResultCompleteness.COMPLETE else "LIMITED",
        extraction_confidence="REASONER" if prop is not None else "NONE",
        completeness=obs.completeness,
        authority=obs.authority
        if obs.source_type is not EvidenceSourceType.STAKEHOLDER
        else SourceAuthority.NON_AUTHORITATIVE,
        is_fallback=obs.is_fallback,
    )
    if prop is not None:
        evidence.interpretation_history.append(
            InterpretationEntry(prop.interpretation, f"proposed by reasoner {rid} ({provider or 'reasoner'})")
        )
    # Conflict impact stays the Core default unless a caller overrides it: the Reasoner's materiality is
    # recorded with the assessment, and premise conflicts are escalated by the Core's own challenge logic.
    impact = decision_impact
    challenges_before = (
        len(ctx.problem.problem_definition.challenges) if ctx.problem.problem_definition else 0
    )
    integrate_evidence(
        ctx,
        evidence,
        supports=supports,
        contradicts=contradicts,
        decision_impact=impact or Criticality.MEDIUM,
    )
    pd = ctx.problem.problem_definition
    out = IntegrationOutcome(evidence_id=eid, claim_id=claim_id)
    out.challenge_raised = bool(pd and len(pd.challenges) > challenges_before)
    if prop is None:
        notes.flush(ctx, "interpret_evidence", rid)
        return out
    strong = is_strong(ctx.problem.evidence[eid])
    # facts: only through the existing guard (hallucinated / weak facts are refused)
    for fc in prop.fact_candidates:
        refs = [r for r in fc.evidence_refs if r in ctx.problem.evidence] or [eid]
        fkey = _key(fc.assertion_key)
        try:
            establish_fact(
                ctx,
                _seq_id("F", ctx.problem.facts),
                fc.statement,
                refs,
                assertion=fkey,
                value=_value(fc.value),
            )
        except (StateIntegrityError, ValueError) as exc:
            notes.add(f"fact candidate refused: {exc}")
    # unknown resolution needs strong, committed evidence (a claim cannot resolve an unknown)
    for uid, resolution in prop.unknown_resolutions:
        u = ctx.problem.unknowns.get(uid)
        if u is None or u.status is UnknownStatus.RESOLVED:
            notes.add(f"resolution of {uid!r} refused: unknown not open")
        elif not strong:
            notes.add(f"resolution of {uid} refused: {eid} is not strong evidence")
        else:
            resolve_with_evidence(ctx, uid, resolution, eid, rid)
    for ac in prop.authorization_candidates:
        _authorization(ctx, ac, eid, notes)
    if prop.vob_proposals:
        commit_vob_proposals(ctx, prop.vob_proposals, rid, notes=notes)
    # follow-up actions: validated against the catalog (read-only only)
    by_ref = {a.ref: a for a in catalog or []}
    for ref in prop.follow_up_actions:
        aff = by_ref.get(ref)
        if aff is None or not aff.read_only:
            notes.add(f"follow-up {ref!r} refused: not a read-only catalog action")
        elif ref not in out.follow_ups:
            out.follow_ups.append(ref)
    _check_assessment(ctx, prop, eid, out, notes)
    notes.flush(ctx, "interpret_evidence", rid)
    record(
        ctx,
        "ACCEPTED",
        "interpret_evidence",
        rid,
        {
            "evidence": eid,
            "assertion": key,
            "supports": supports,
            "contradicts": contradicts,
            "assessment": out.assessment,
            "challenge_raised": out.challenge_raised,
        },
        refs=[eid],
    )
    return out


def resolve_with_evidence(ctx: HarnessContext, uid: str, resolution: str, eid: str, rid: str | None) -> None:
    """Resolve an OPEN / DEFERRED unknown with committed strong evidence; a VOB it was deferred to is
    resolved with it (the VOB existed only because this question was open)."""
    resolve_unknown(ctx, uid, resolution, [eid])
    vob_id = ctx.problem.unknowns[uid].deferred_to_vob
    vob = ctx.problem.verification_obligations.get(vob_id or "")
    if vob is None or not vob.is_open():
        return
    with ctx.commit(f"VOB {vob.id} resolved by {eid}") as p:
        v = p.verification_obligations[vob.id]
        old = v.status.value
        v.status = VOBStatus.RESOLVED
        v.resolution = f"{uid} answered by {eid} ({rid}): {resolution}"
    ctx.emit(
        EventType.VOB_RESOLVED,
        {"vob": vob.id, "unknown": uid, "evidence": eid, "from": old, "reasoning_id": rid},
        importance=Importance.HIGH,
        refs=[vob.id, eid],
    )


def reevaluate_predecessor_vobs(
    ctx: HarnessContext, decisions: list[tuple[str, str, str, list[str]]], rid: str | None, notes: Notes
) -> None:
    """Successor DEFINE (IDR-REDEFINE-04 "rebind or retire"): the Reasoner proposes KEEP / RETIRE per open VOB
    bound to the invalidated version; the Core accepts RETIRE only for such VOBs and only with a rationale.
    KEEP (or no decision) leaves the deterministic rebind rule of ``bind_successor`` in charge."""
    ps = ctx.problem
    prev = ps.problem_definition
    if prev is None or prev.status is not ProblemDefinitionStatus.INVALIDATED:
        if decisions:
            notes.add("vob_reevaluation ignored: no invalidated predecessor Problem")
        return
    for vid, decision, rationale, refs in decisions:
        v = ps.verification_obligations.get(vid)
        if v is None or not v.is_open() or v.problem_version != prev.version:
            notes.add(f"vob_reevaluation of {vid!r} ignored: not an open VOB of {prev.ref}")
            continue
        if decision != "RETIRE":
            continue
        if not rationale.strip():
            notes.add(f"RETIRE of {vid} refused: rationale required")
            continue
        cited = [r for r in refs if r in ps.evidence]
        with ctx.commit(f"VOB {vid} retired at successor DEFINE ({rid})") as p:
            x = p.verification_obligations[vid]
            x.status = VOBStatus.SUPERSEDED
            x.resolution = f"retired at successor DEFINE by {rid}: {rationale}" + (
                f" [{', '.join(cited)}]" if cited else ""
            )
        ctx.emit(
            EventType.VOB_STATUS_CHANGED,
            {
                "vob": vid,
                "from": "OPEN",
                "to": "SUPERSEDED",
                "reason": f"successor DEFINE re-evaluation ({rid})",
            },
            refs=[vid],
        )


def commit_document_authorizations(
    ctx: HarnessContext, prop: EvidenceInterpretationProposal, eid: str, rid: str | None
) -> list[str]:
    """Authorization candidates for an evidence item that is ALREADY committed (no new evidence, no other
    semantics are taken from the proposal). Same Core rules as at integration time (``_authorization``)."""
    ps = ctx.problem
    before = set(ps.domain_authorizations)
    notes = Notes()
    for ac in prop.authorization_candidates:
        _authorization(ctx, ac, eid, notes)
    notes.flush(ctx, "interpret_evidence", rid)
    added = sorted(set(ps.domain_authorizations) - before)
    record(
        ctx,
        "ACCEPTED",
        "interpret_evidence",
        rid,
        {"evidence": eid, "authorizations": added, "mode": "authority recheck"},
    )
    return added


def commit_repair_authorizations(
    ctx: HarnessContext, prop: ProblemDefinitionProposal, rid: str | None
) -> tuple[list[str], list[str]]:
    """DEFINE repair "identify the authorized actor" (IDR-RV4-03): each candidate must cite a committed
    authoritative document that names the holder and must authorize what the Problem intends to do (its
    scope_target is the action's resource, one of the Problem's intended targets for the action, or "*" —
    RV-4b C-03: a grant scoped to the action name could never cover the protected action). Then the usual
    Core authorization rules apply. Returns (added authorization ids, refusal reasons)."""
    from .define_repair import grounded_in_document

    ps = ctx.problem
    pd = ps.problem_definition
    before = set(ps.domain_authorizations)
    notes = Notes()
    refusals: list[str] = []
    for ac in prop.authorization_candidates:
        intended = [i.target for i in (pd.intended_scope if pd else []) if i.action == ac.action]
        targets = set(accepted_targets(ac.resource, intended))
        why = grounded_in_document(ctx, ac.evidence_ref, ac.authority_holder)
        norm = normalize_scope_target(
            ac.action, ac.resource, ac.scope_kind, ac.scope_target, known_ids=_known_ids(ctx, intended)
        )
        if not why and norm.refusal:
            why = norm.refusal
        elif not why and norm.target not in targets:
            why = (
                f"scope_target {ac.scope_target!r} is neither the resource, an intended target of "
                f"{ac.action} nor '*'"
            )
        if why:
            # the contract (accepted canonical forms) is fed back; which one applies is the Reasoner's call
            refusals.append(
                f"authorization candidate {ac.action} refused: {why} — accepted: scope_kind RESOURCE "
                f"({ac.resource!r}), ANY_TARGET ('*') or INTENDED_TARGET with one of "
                f"{accepted_targets(ac.resource, intended)[2:]}"
            )
            notes.add(refusals[-1])
            continue
        notes.items += norm.notes
        _authorization(ctx, ac, ac.evidence_ref, notes, target=norm.target)
    notes.flush(ctx, "define_problem", rid)
    added = sorted(set(ps.domain_authorizations) - before)
    if prop.authorization_candidates:
        record(
            ctx,
            "ACCEPTED",
            "define_problem",
            rid,
            {"mode": "repair authorization", "authorizations": added, "refused": refusals},
        )
    return added, refusals


def _known_ids(ctx: HarnessContext, extra: list[str] | None = None) -> list[str]:
    """Committed ids a scope target may spell (syntax normalization only, engine.scope_contract)."""
    ps = ctx.problem
    pd = ps.problem_definition
    ids = [*ps.data_assets, *ps.process_handoffs, *ps.stakeholders, *(extra or [])]
    ids += [i.target for i in (pd.intended_scope if pd else [])]
    return ids


def _authorization(
    ctx: HarnessContext, ac: Any, eid: str, notes: Notes, *, target: str | None = None
) -> None:
    ps = ctx.problem
    ev = ps.evidence[eid]
    if ev.source_type not in (EvidenceSourceType.DOCUMENT, EvidenceSourceType.POLICY) or (
        ev.authority is not SourceAuthority.AUTHORITATIVE
    ):
        notes.add(f"authorization candidate {ac.action} refused: {eid} is not an authoritative document")
        return
    constraint = next((c for c in ps.constraints.values() if c.protected_action == ac.action), None)
    if constraint is None:
        notes.add(f"authorization candidate {ac.action} refused: no constraint protects that action")
        return
    holder = ac.authority_holder
    if holder not in ps.stakeholders:
        notes.add(f"authorization candidate {ac.action} refused: holder {holder!r} unknown")
        return
    if constraint.actor and constraint.actor != holder:
        notes.add(
            f"authorization candidate {ac.action} refused: constraint names {constraint.actor}, not {holder}"
        )
        return
    if any(a.action == ac.action and a.is_effective() for a in ps.domain_authorizations.values()):
        return
    if target is None:  # integration path: syntax normalization only (IDR-RV5-01), no new acceptance rule
        norm = normalize_scope_target(
            ac.action, ac.resource, getattr(ac, "scope_kind", ""), ac.scope_target, known_ids=_known_ids(ctx)
        )
        if norm.refusal and norm.kind:
            notes.add(f"authorization candidate {ac.action} refused: {norm.refusal}")
            return
        notes.items += norm.notes
        # untyped text that is not an id keeps its legacy reading (as written; never widened)
        target = norm.target or ac.scope_target.strip() or WILDCARD
    org = ps.stakeholders[holder].organization_id
    with ctx.commit(f"domain authorization for {ac.action} from {eid}") as p:
        aid = make_id("DA", ac.action, p.domain_authorizations)
        p.domain_authorizations[aid] = DomainAuthorization(
            id=aid,
            action=ac.action,
            resource=ac.resource,
            subject=org,
            authority_holder=holder,
            authorized_scope=Scope.of((ac.action, target)),
            conditions=list(ac.conditions),
            evidence_refs=[eid],
            status=AuthorizationStatus.GRANTED,
        )


def _check_assessment(
    ctx: HarnessContext, prop: EvidenceInterpretationProposal, eid: str, out: IntegrationOutcome, notes: Notes
) -> None:
    """Prompt §16: the Core never trusts a contradiction assessment blindly."""
    a = prop.assessment
    pd = ctx.problem.problem_definition
    if a.target_type == "NONE" or a.relation in ("UNRELATED", "SUPPORTS"):
        if a.problem_invalidating:
            out.assessment = "INCONSISTENT"
            notes.add("assessment claims problem invalidation with a non-contradicting relation: ignored")
        else:
            out.assessment = "NONE"
        return
    if pd is None or not pd.is_canonical():
        out.assessment = "NO_CANONICAL_PROBLEM"
        if a.problem_invalidating:
            notes.add(
                "problem-invalidation claimed before a canonical Problem exists: ignored "
                "(pre-canonical change = hypothesis_changed, never redefine)"
            )
        return
    known = set(ctx.problem.evidence) | set(ctx.problem.hypotheses) | set(ctx.problem.claims)
    targets = [t for t in a.target_refs if t in known]
    if len(targets) != len(a.target_refs):
        notes.add(f"assessment cites unknown refs {sorted(set(a.target_refs) - known)}")
    premise = _premise_ids(ctx)
    if a.target_type == "SOLUTION_PATH":
        out.assessment = "PATH_ONLY"
        if is_strong(ctx.problem.evidence[eid]) and a.materiality in _MATERIAL:
            out.path_contradiction = True
            ctx.runtime.propose_transition(
                TransitionCandidate(
                    TransitionKind.REPLAN,
                    Phase.EXECUTE,
                    f"solution-path contradiction by {eid}: {a.rationale}",
                    [eid],
                )
            )
        return
    if not a.problem_invalidating:
        out.assessment = "NON_INVALIDATING"
        return
    out.problem_invalidating_claimed = True
    out.premise_targets = [t for t in targets if t in premise]
    consistent = (
        a.target_type == "PROBLEM_PREMISE"
        and a.relation in ("CONTRADICTS", "PARTIAL_CONTRADICTION")
        and a.materiality in _MATERIAL
        and is_strong(ctx.problem.evidence[eid])
        and bool(out.premise_targets)
    )
    if not consistent:
        out.assessment = "INCONSISTENT"
        notes.add(
            "problem-invalidation assessment failed Core consistency checks (needs PROBLEM_PREMISE, "
            "CONTRADICTS, HIGH+ materiality, strong evidence, premise targets): not trusted"
        )
        return
    challenged = any(c.evidence_id == eid for c in pd.challenges)
    out.assessment = "CONSISTENT_CONFIRMED" if challenged else "CONSISTENT_NOT_CONFIRMED"


def apply_hypothesis_assessment(
    ctx: HarnessContext, prop: HypothesisAssessmentProposal, rid: str | None
) -> list[str]:
    """Hypothesis status changes, validated against the linked evidence."""
    notes = Notes()
    changed: list[str] = []
    ps = ctx.problem
    for u in prop.updates:
        h = ps.hypotheses.get(u.hypothesis)
        if h is None:
            notes.add(f"update of unknown hypothesis {u.hypothesis!r} dropped")
            continue
        status = HypothesisStatus(u.status)
        if status is h.status:
            continue
        contra = [e for e in h.contradicting_evidence if e in ps.evidence]
        support = [e for e in h.supporting_evidence if e in ps.evidence]
        strong_contra = [e for e in contra if is_strong(ps.evidence[e])]
        independent = [e for e in support if ps.evidence[e].source_type is not EvidenceSourceType.STAKEHOLDER]
        why_not = None
        if status is HypothesisStatus.REJECTED and not contra:
            why_not = "REJECTED needs contradicting evidence"
        elif status is HypothesisStatus.SUPPORTED and (not support or strong_contra):
            why_not = "SUPPORTED needs supporting evidence and no strong contradiction"
        elif status is HypothesisStatus.CONFIRMED and (
            contra or not any(is_strong(ps.evidence[e]) for e in independent)
        ):
            why_not = "CONFIRMED needs strong independent support and no contradiction"
        if why_not:
            notes.add(f"{h.id} → {status.value} refused: {why_not}")
            continue
        refs = [e for e in u.evidence_refs if e in ps.evidence]
        update_hypothesis(ctx, h.id, status, f"{u.rationale} [{', '.join(refs)}] ({rid})")
        changed.append(h.id)
    notes.flush(ctx, "assess_hypotheses", rid)
    record(ctx, "ACCEPTED", "assess_hypotheses", rid, {"changed": changed})
    return changed


# =========================================================================== DEFINE


@dataclass
class DefineContext:
    """Harness-side memory the DEFINE gate needs (not canonical state)."""

    framing_hypotheses: list[str] = field(default_factory=list)
    ignore_unknown_scope_versions: set[int] = field(default_factory=set)  # robustness variant knob
    known_limitations: list[str] = field(default_factory=list)
    # problem ref → causal chain + premise hypotheses as proposed at DEFINE (Premise Check input, IDR-RV4-01)
    premise_records: dict[str, dict[str, list[str]]] = field(default_factory=dict)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()


def independent_support(ctx: HarnessContext, hid: str) -> tuple[list[str], list[str]]:
    """(strong non-stakeholder supporting evidence, contradicting evidence) of a hypothesis."""
    ps = ctx.problem
    h = ps.hypotheses[hid]
    strong = [
        e
        for e in h.supporting_evidence
        if e in ps.evidence
        and ps.evidence[e].source_type is not EvidenceSourceType.STAKEHOLDER
        and is_strong(ps.evidence[e])
    ]
    return strong, [e for e in h.contradicting_evidence if e in ps.evidence]


def apply_framing_resolution(
    ctx: HarnessContext, prop: ProblemDefinitionProposal, rid: str | None, *, dctx: DefineContext
) -> list[str]:
    """Typed framing repair (IDR-RV5-02). The Reasoner says how it resolves a FRAMING_CLASSIFICATION_CONFLICT;
    the Core validates by evidence provenance and never writes the hypothesis itself:

    * KEEP_AS_CLAIM — the requester framing stays a claim; the proposal must not rest on it (checked at
      commit).
    * RECLASSIFY_BY_PROVENANCE — the hypothesis was mislabelled as the requester's framing. Accepted only with
      the Core's CONFIRMED-grade independence: strong non-stakeholder support and no contradicting evidence.
    * SEPARATE_INDEPENDENT_HYPOTHESIS — a new hypothesis, distinct from the framing and from the request, that
      cites strong non-stakeholder committed evidence; the premise reference moves to it.

    Returns the accepted resolutions (as notes)."""
    ps = ctx.problem
    notes = Notes()
    accepted: list[str] = []
    request = _norm_text(ps.scenario.initial_request)
    for r in prop.framing_resolution:
        hid = r.hypothesis
        if hid not in dctx.framing_hypotheses or hid not in ps.hypotheses:
            notes.add(f"framing resolution for {hid!r} ignored: not a requester-framing hypothesis")
            continue
        if r.option == "KEEP_AS_CLAIM":
            accepted.append(f"{hid}: kept as requester claim")
            continue
        if not r.rationale.strip():
            notes.add(f"framing resolution {r.option} for {hid} refused: rationale required")
            continue
        if r.option == "RECLASSIFY_BY_PROVENANCE":
            strong, contra = independent_support(ctx, hid)
            h = ps.hypotheses[hid]
            why = None
            if h.status not in _HELD:
                why = f"{hid} is {h.status.value}, not SUPPORTED/CONFIRMED"
            elif not strong:
                why = "no strong non-stakeholder supporting evidence"
            elif contra:
                why = f"contradicting evidence {contra}"
            elif _norm_text(h.statement) == request:
                why = "the hypothesis restates the initial request"
            if why:
                notes.add(f"reclassification of {hid} refused: {why}")
                continue
            dctx.framing_hypotheses = [x for x in dctx.framing_hypotheses if x != hid]
            accepted.append(f"{hid}: reclassified by provenance (independent support {strong})")
            continue
        if r.option == "SEPARATE_INDEPENDENT_HYPOTHESIS":
            cited = [e for e in r.evidence_refs if e in ps.evidence]
            independent = [
                e for e in cited if ps.evidence[e].source_type is not EvidenceSourceType.STAKEHOLDER
            ]
            stmt = _norm_text(r.statement)
            why = None
            if not stmt or stmt in (request, _norm_text(ps.hypotheses[hid].statement)):
                why = "statement missing or identical to the requester framing / initial request"
            elif not any(is_strong(ps.evidence[e]) for e in independent):
                why = "no strong non-stakeholder evidence cited"
            if why:
                notes.add(f"separation from {hid} refused: {why}")
                continue
            with ctx.commit(f"independent hypothesis separated from {hid} ({rid})") as p:
                nid = make_id("H", f"{hid}-INDEPENDENT", p.hypotheses)
                p.hypotheses[nid] = Hypothesis(
                    id=nid,
                    statement=r.statement,
                    supporting_evidence=independent,
                    decision_impact=Criticality.HIGH,
                )
            update_hypothesis(
                ctx,
                nid,
                HypothesisStatus.SUPPORTED,
                f"separated from requester framing {hid} [{', '.join(independent)}] ({rid})",
            )
            prop.premise_hypotheses = [nid if x == hid else x for x in prop.premise_hypotheses]
            accepted.append(f"{hid}: independent hypothesis {nid} separated (premise moved to {nid})")
            continue
        notes.add(f"framing resolution option {r.option!r} for {hid} unknown: ignored")
    notes.flush(ctx, "define_problem", rid)
    if prop.framing_resolution:
        record(ctx, "ACCEPTED", "framing_repair", rid, {"accepted": accepted, "refused": list(notes.items)})
    return accepted


def commit_problem_definition(
    ctx: HarnessContext,
    prop: ProblemDefinitionProposal,
    rid: str | None,
    *,
    registry: ToolRegistry,
    dctx: DefineContext,
) -> ProblemDefinition:
    ps = ctx.problem
    notes = Notes()
    evidence = _filter(prop.evidence_refs, ps.evidence, "evidence", notes)
    if not evidence:
        record(ctx, "REJECTED", "define_problem", rid, "no committed evidence cited")
        raise ProposalRejected("problem definition cites no committed evidence")
    premise = []
    for hid in prop.premise_hypotheses:
        h = ps.hypotheses.get(hid)
        if h is None or h.status not in _HELD:
            notes.add(f"premise hypothesis {hid!r} dropped (unknown or not SUPPORTED/CONFIRMED)")
        elif hid in dctx.framing_hypotheses:
            record(ctx, "REJECTED", "define_problem", rid, f"rests on requester framing {hid}")
            raise FramingRejected(
                f"problem rests on the requester framing hypothesis {hid} (anchoring)",
                hypothesis=hid,
                proposal_ref=rid,
            )
        else:
            premise.append(hid)
    rejected_premise = [
        h
        for h in prop.premise_hypotheses
        if (x := ps.hypotheses.get(h)) and x.status is HypothesisStatus.REJECTED
    ]
    if rejected_premise:
        record(ctx, "REJECTED", "define_problem", rid, f"rests on rejected hypotheses {rejected_premise}")
        raise ProposalRejected(f"problem rests on rejected hypotheses {rejected_premise}")
    if prop.problem_statement.strip().lower() == ps.scenario.initial_request.strip().lower():
        record(ctx, "REJECTED", "define_problem", rid, "root problem restates the initial request")
        raise ProposalRejected("root problem restates the initial request")
    intended = _scope_items(prop.intended_scope)
    constraint_actions = {c.protected_action for c in ps.constraints.values() if c.protected_action}
    mutating_tools = {t for t in _tool_ids(registry) if not registry.spec(t).read_only}
    protected: list[str] = []
    for action in prop.protected_actions:
        if action in constraint_actions or any(
            i.action == action and i.target in mutating_tools for i in intended
        ):
            protected.append(action)
        else:
            notes.add(f"protected action {action!r} dropped: not a constrained / mutating operation")
    for i in intended:  # never silently un-protect a constrained action
        if i.action in constraint_actions and i.action not in protected:
            protected.append(i.action)
            notes.add(
                f"{i.action} is constrained "
                f"({[c.id for c in ps.constraints.values() if c.protected_action == i.action]}): "
                "added to protected_actions"
            )
    tools = _filter(prop.required_tools, set(_tool_ids(registry)), "tool", notes)
    handoffs = _filter(prop.depends_on_handoffs, ps.process_handoffs, "handoff", notes)
    prev = ps.problem_definition
    version_hint = (
        (prev.version + 1)
        if prev and prev.status is ProblemDefinitionStatus.INVALIDATED
        else (prev.version if prev else 1)
    )
    ignore_scope = version_hint in dctx.ignore_unknown_scope_versions
    intended_actions = {i.action for i in intended}
    sc_ids: list[str] = []
    metric_ids: list[str] = []
    dctx.known_limitations = [s.statement for s in prop.success_criteria if s.kind == "KNOWN_LIMITATION"]
    with ctx.commit(f"DEFINE inputs ({rid})") as p:
        for hid in premise:  # adopted as the canonical premise ⇒ material by definition
            h = p.hypotheses[hid]
            if h.decision_impact not in _MATERIAL:
                notes.add(f"{hid} decision_impact {h.decision_impact.value} → HIGH (canonical premise)")
                h.decision_impact = Criticality.HIGH
        for a in prop.assumptions:
            aid = _reuse_or_new("A", a.key, p.assumptions)
            if aid in p.assumptions and p.assumptions[aid].status is not AssumptionStatus.ACTIVE:
                aid = make_id("A", a.key, p.assumptions)  # never overwrite an invalidated / validated record
            refs = [r for r in a.evidence_refs if r in p.evidence]
            p.assumptions[aid] = Assumption(
                id=aid,
                statement=a.statement,
                basis=", ".join(refs) or "not evidenced (assumption)",
                risk_if_wrong=a.risk_if_wrong,
                evidence_refs=refs,
            )
        for u in prop.unknowns:
            uid = _reuse_or_new("U", u.key, p.unknowns)
            existing = p.unknowns.get(uid)
            if existing is not None and existing.status is not UnknownStatus.OPEN:
                continue  # deferred / resolved unknowns are not re-opened by a proposal
            items = [
                i
                for i in _scope_items(u.affects_scope)
                if i.action == WILDCARD or i.action in intended_actions
            ]
            if len(items) != len(u.affects_scope):
                notes.add(f"{uid}: scope items outside intended scope dropped")
            scope = Scope() if ignore_scope else Scope(items=items)
            p.unknowns[uid] = Unknown(
                id=uid,
                question=u.question,
                criticality=u.criticality,
                decision_impact=u.decision_impact,
                affects_scope=scope,
                resolution_path=u.resolution_path or None,
                safe_placeholder=u.safe_placeholder or None,
            )
        mkeys: dict[str, str] = {}
        for m in prop.metrics:
            mid = _reuse_or_new("M", m.key, p.metrics)
            metric = Metric(id=mid, name=m.name, metric_type=MetricType(m.metric_type))
            sem: dict[str, Any] = dict(m.semantics)
            if m.target_value is not None:
                sem["target_value"] = float(m.target_value)
            cited = [r for r in m.current_value_evidence_refs if r in p.evidence]
            if m.current_value is not None:
                sem["current_value"] = float(m.current_value)
                metric.current_value_is_speculative = not cited
                if not cited:
                    notes.add(f"{mid} current_value has no evidence: marked speculative")
            metric.promote(**sem)
            p.metrics[mid] = metric
            mkeys[m.key] = mid
            metric_ids.append(mid)
        for s in prop.success_criteria:
            if s.kind == "KNOWN_LIMITATION":
                continue
            sid = _reuse_or_new("SC", s.key, p.success_criteria)
            p.success_criteria[sid] = SuccessCriterion(
                id=sid,
                statement=s.statement,
                metric_id=mkeys.get(s.metric) or (s.metric if s.metric in p.metrics else None),
                threshold=s.threshold or None,
                validation_method=s.validation_method,
                test_refs=[f"{s.kind.lower()}:{sid}"],
            )
            sc_ids.append(sid)
        p.decision_log.append(
            DecisionRecord(
                id=f"D-{len(p.decision_log) + 1}",
                phase=ctx.runtime.phase,
                decision=f"DEFINE proposal {rid}",
                rationale="causal chain: "
                + " → ".join(prop.causal_chain)
                + (f"; rejected framings: {prop.rejected_framings}" if prop.rejected_framings else ""),
                evidence_refs=list(evidence),
            )
        )
    reevaluate_predecessor_vobs(ctx, prop.vob_reevaluation, rid, notes)
    pd = ProblemDefinition(
        id=prev.id if prev else "PD-1",
        requested_solution=prop.requested_solution,
        symptoms=list(prop.symptoms),
        root_problem=prop.problem_statement,
        evidence_refs=evidence,
        intended_scope=intended,
        protected_actions=protected,
        depends_on_handoffs=handoffs,
        required_tools=tools,
        success_criteria=sc_ids,
        metric_ids=metric_ids,
    )
    define_problem(ctx, pd)
    dctx.premise_records[pd.ref] = {
        "causal_chain": list(prop.causal_chain),
        "premise_hypotheses": list(premise),
    }
    notes.flush(ctx, "define_problem", rid)
    record(
        ctx,
        "ACCEPTED",
        "define_problem",
        rid,
        {"problem": pd.ref, "premise_hypotheses": premise, "confidence": prop.confidence},
        refs=evidence,
    )
    return pd


def _reuse_or_new(prefix: str, key: str, existing: dict[str, Any]) -> str:
    """Same key ⇒ same object (carried across Problem versions, e.g. a still-valid success criterion)."""
    cand = make_id(prefix, key, {})
    return cand if cand in existing else make_id(prefix, key, existing)


def _tool_ids(registry: ToolRegistry) -> list[str]:
    return list(registry._specs)  # noqa: SLF001 — read-only listing of registered tool ids


# =========================================================================== VOB


def commit_vob_proposals(
    ctx: HarnessContext, vobs: list[VOBProposal], rid: str | None, *, notes: Notes | None = None
) -> list[str]:
    """Prompt §20: scope validity, duplication and Problem-version linkage are Core-checked."""
    own = notes is None
    notes = notes or Notes()
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None or not pd.is_canonical():
        notes.add("VOB proposals need an ACTIVE canonical Problem: dropped")
        if own:
            notes.flush(ctx, "vob", rid)
        return []
    intended_actions = {i.action for i in pd.intended_scope}
    created: list[str] = []
    for v in vobs:
        norm = v.unresolved_question.strip().lower()
        dup = next(
            (
                x.id
                for x in ps.open_vobs()
                if x.unresolved_question.strip().lower() == norm
                or (v.linked_unknown and x.linked_unknown == v.linked_unknown)
            ),
            None,
        )
        if dup:
            notes.add(f"VOB proposal duplicates {dup}: dropped")
            continue
        items = [
            i for i in _scope_items(v.blocking_scope) if i.action == WILDCARD or i.action in intended_actions
        ]
        if v.entire_solution or not items:
            scope = Scope.entire()
            if not v.entire_solution:
                notes.add("VOB proposal without a valid blocking scope: conservative ENTIRE_SOLUTION")
        else:
            scope = Scope(items=items)
        with ctx.commit(f"VOB proposed ({rid})") as p:
            vid = make_id("VOB-R", str(len(p.verification_obligations) + 1), p.verification_obligations)
            p.verification_obligations[vid] = VerificationObligation(
                id=vid,
                unresolved_question=v.unresolved_question,
                source_phase=ctx.runtime.phase,
                reason_deferred=f"proposed by reasoner {rid}: {v.rationale}",
                decision_impact=v.decision_impact,
                validation_method=v.validation_method,
                required_evidence=list(v.required_evidence),
                required_before=RequiredBefore(v.required_before),
                blocking_scope=scope,
                linked_unknown=v.linked_unknown if v.linked_unknown in p.unknowns else None,
                problem_definition_id=pd.id,
                problem_version=pd.version,
            )
        ctx.emit(
            EventType.VOB_CREATED,
            {"vob": vid, "required_before": v.required_before, "reasoning_id": rid},
            refs=[vid],
        )
        created.append(vid)
    if own:
        notes.flush(ctx, "vob", rid)
    return created


# =========================================================================== DESIGN


def start_design(
    ctx: HarnessContext, prop: StructuralRemedyProposal, rid: str | None
) -> tuple[DesignSession, bool, bool]:
    """Frozen order: ROOT_PROBLEM → STRUCTURAL_REMEDY → FEASIBILITY recorded *before* any agent question."""
    pd = ctx.problem.problem_definition
    assert pd is not None
    session = DesignSession(ctx, f"SD-{pd.version}")
    session.root_problem()
    candidates = []
    seen: set[str] = set()
    for r in prop.remedies:
        rid_ = make_id("SR", r.key, seen)
        seen.add(rid_)
        candidates.append(
            StructuralRemedyCandidate(
                id=rid_,
                description=r.description,
                removes_root_cause=r.removes_root_cause,
                feasible_in_contest_time=r.feasible_in_contest_time,
                constraint_feasible=r.constraint_feasible,
                rationale=r.feasibility_rationale
                + (f"; residual gap: {r.residual_gap}" if r.residual_gap else ""),
            )
        )
    session.structural_remedies(candidates)
    removes, feasible = session.feasibility()
    record(
        ctx,
        "ACCEPTED",
        "structural_remedy",
        rid,
        {"remedies": [c.id for c in candidates], "removes_root_cause": removes, "feasible_in_time": feasible},
    )
    return session, removes, feasible


def preview_release_scope(
    ctx: HarnessContext, prop: AgentDesignProposal, notes: Notes | None = None
) -> tuple[list[ScopeItem], list[str]]:
    """Release scope the Core would accept: ⊆ intended scope, minus items an open critical VOB blocks."""
    notes = notes or Notes()
    ps = ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    intended = list(pd.intended_scope)
    release = [i for i in _scope_items(prop.release_scope) if i in intended]
    if len(release) != len(prop.release_scope):
        notes.add("release scope items outside the Problem's intended scope dropped")
    if not release:
        release = [i for i in intended]
        notes.add("empty release scope: defaulted to the intended scope")
    blocked: list[str] = []
    for v in ps.open_vobs():
        if not v.applies_to(pd.id, pd.version) or not v.is_critical():
            continue
        if v.required_before is RequiredBefore.BEFORE_PRODUCTION:
            continue
        hits = v.blocking_scope.intersect(release)
        if hits and not v.blocking_scope.entire_solution:
            release = [i for i in release if i not in hits]
            blocked += [f"{h} (blocked by {v.id} until resolved: {v.unresolved_question})" for h in hits]
    if blocked:
        notes.add(f"release scope items blocked by open critical VOBs moved to unfinished scope: {blocked}")
    return release, blocked


def _covers_all(scope: Scope, items: list[ScopeItem]) -> bool:
    return bool(items) and (scope.entire_solution or all(scope.covers(i) for i in items))


def _covers_any_protected_action(
    scope: Scope, intended: list[ScopeItem], protected_actions: set[str]
) -> bool:
    """True if the scope blocks at least one intended item whose action is protected (RV-6 trigger)."""
    return any(i.action in protected_actions for i in scope.intersect(intended))


def blocking_review_candidates(
    ctx: HarnessContext, *, removes: bool, feasible: bool, skip_versions: set[int] | None = None
) -> tuple[list[VerificationObligation], list[str]]:
    """IDR-RV5-04 / IDR-RV6-01 eligibility (deterministic): an open critical VOB that defers a Reasoner-raised
    critical unknown and either (a) blocks the whole intended scope of the ACTIVE Problem (IDR-RV5-04), or
    (b) blocks at least one protected action of the intended scope without blocking the entire scope
    (IDR-RV6-01: a protected-fix-only block starves the Mandatory Human Gate of a candidate to approve, since
    ``preview_release_scope`` drops that action from the release scope and ``commit_plan`` then never builds a
    proposal for it — ``propose_protected_action`` is never called and the gate never opens) — while a
    root-cause structural remedy is feasible and nothing in committed state backs the entire block — no
    safety / privacy constraint on a blocked action and no open material conflict on the blocked scope.
    Core-made obligations (no linked unknown) and BEFORE_PRODUCTION obligations are never reviewed. The VOB
    stays open and the Mandatory Human Gate is unaffected either way — this only decides whether
    `apply_blocking_review` gets a chance to narrow scope on evidence; it never bypasses the gate itself."""
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None or not pd.is_canonical():
        return [], []
    intended = list(pd.intended_scope)
    protected = set(pd.protected_actions)
    candidates = [
        v
        for v in ps.open_vobs()
        if v.applies_to(pd.id, pd.version)
        and v.is_critical()
        and v.required_before is not RequiredBefore.BEFORE_PRODUCTION
        and (
            _covers_all(v.blocking_scope, intended)
            or _covers_any_protected_action(v.blocking_scope, intended, protected)
        )
    ]
    if not candidates:  # nothing blocks the entire scope or a protected action: no review, nothing recorded
        return [], []
    if pd.version in (skip_versions or set()):
        return [], [f"v{pd.version}: unknown scopes are fixed by configuration (robustness variant)"]
    if not (removes and feasible):
        return [], ["no structural remedy that removes the root cause is feasible"]
    actions = {i.action for i in intended}
    out: list[VerificationObligation] = []
    why_not: list[str] = []
    for v in candidates:
        u = ps.unknowns.get(v.linked_unknown or "")
        if u is None:
            why_not.append(f"{v.id}: not a Reasoner-raised unknown (Core obligation)")
            continue
        safety = [
            c.id
            for c in ps.constraints.values()
            if c.type in (ConstraintType.SAFETY, ConstraintType.PRIVACY)
            and (c.protected_action in actions or not c.protected_action)
        ]
        conflicts = [
            c.id
            for c in ps.conflicts.values()
            if c.status is ConflictStatus.OPEN
            and (c.gate_blocking or c.decision_impact in _MATERIAL)
            and (c.affects_scope.is_empty() or c.affects_scope.intersect(intended))
        ]
        if safety:
            why_not.append(f"{v.id}: safety / privacy constraints {safety} on the blocked scope")
        elif conflicts:
            why_not.append(f"{v.id}: open material conflicts {conflicts} back the block")
        else:
            out.append(v)
    return out, why_not


def apply_blocking_review(
    ctx: HarnessContext,
    prop: BlockingScopeReviewProposal,
    eligible: list[VerificationObligation],
    rid: str | None,
) -> list[str]:
    """Core validation of a NARROW_BLOCKING_SCOPE claim: only an eligible VOB, only to a strict subset of the
    items it blocks (empty = verification-only), only with a rationale and strong non-stakeholder committed
    evidence (``HarnessContext.narrow_vob_scope`` guard). The VOB stays open; Human Gates are untouched.
    Returns the narrowed VOB ids."""
    ps = ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    by_id = {v.id: v for v in eligible}
    intended = list(pd.intended_scope)
    notes = Notes()
    narrowed: list[str] = []
    decisions: dict[str, str] = {}
    for r in prop.reviews:
        v = by_id.get(r.vob)
        if v is None:
            notes.add(f"review of {r.vob!r} ignored: not an eligible obligation")
            continue
        if r.vob in decisions:
            continue
        decisions[r.vob] = r.decision
        if r.decision != "NARROW_BLOCKING_SCOPE":
            continue
        blocked = [i for i in intended if v.blocking_scope.covers(i)]
        items = _scope_items(r.narrowed_scope)
        cited = [e for e in r.evidence_refs if e in ps.evidence]
        strong = [
            e
            for e in cited
            if ps.evidence[e].source_type is not EvidenceSourceType.STAKEHOLDER and is_strong(ps.evidence[e])
        ]
        why = None
        if any(i not in blocked for i in items):
            why = "narrowed_scope must reuse intended items the obligation blocks"
        elif len({str(i) for i in items}) >= len(blocked):
            why = "narrowed_scope is not narrower than the current block"
        elif not r.rationale.strip():
            why = "rationale required"
        elif not strong:
            why = "no strong non-stakeholder committed evidence cited"
        if why:
            notes.add(f"narrowing of {v.id} refused: {why}")
            decisions[r.vob] = f"NARROW_BLOCKING_SCOPE refused ({why})"
            continue
        unique = list(dict.fromkeys(items))
        ctx.narrow_vob_scope(
            v.id, Scope(items=unique), strong[0], f"blocking-scope review {rid}: {r.rationale}"
        )
        narrowed.append(v.id)
    notes.flush(ctx, "review_blocking_scope", rid)
    record(
        ctx,
        "ACCEPTED",
        "review_blocking_scope",
        rid,
        {"eligible": sorted(by_id), "decisions": decisions, "narrowed": narrowed},
    )
    return narrowed


@dataclass
class ReconsiderationCandidate:
    action: str
    scope: list[ScopeItem]
    constraints: list[str]
    authorization: str
    holder: str


def reconsideration_candidates(
    ctx: HarnessContext, prop: AgentDesignProposal, *, removes: bool, feasible: bool, registry: ToolRegistry
) -> tuple[list[ReconsiderationCandidate], list[str]]:
    """IDR-RV4-05 eligibility (deterministic): a feasible root-cause remedy exists, a protected action of the
    canonical Problem's intended scope was left out of the proposed release scope, and nothing forces that
    exclusion — authority is established, no safety / privacy constraint on it is unresolved, a mutating tool
    exists to carry it, and no open critical VOB blocks it (``preview_release_scope``'s own rule)."""
    ps = ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    if not (removes and feasible):
        return [], ["no structural remedy that removes the root cause is feasible"]
    release, _ = preview_release_scope(ctx, prop)
    in_release = {i.action for i in release}
    mutating = [t for t in _tool_ids(registry) if not registry.spec(t).read_only]
    out: list[ReconsiderationCandidate] = []
    why_not: list[str] = []
    for action in pd.protected_actions:
        items = [i for i in pd.intended_scope if i.action == action]
        if not items or action in in_release:
            continue
        constraints = [c for c in ps.constraints.values() if c.protected_action == action]
        auth = ps.authorization_for(action)
        trial = copy.copy(prop)
        trial.release_scope = list(prop.release_scope) + [ScopeRef(i.action, i.target) for i in items]
        trial_release, trial_blocked = preview_release_scope(ctx, trial)
        if auth is None or not auth.is_effective():
            why_not.append(f"{action}: domain authorization missing")
        elif any(
            c.type in (ConstraintType.SAFETY, ConstraintType.PRIVACY)
            and c.status is not ConstraintStatus.ACTIVE
            for c in constraints
        ):
            why_not.append(f"{action}: unresolved safety / privacy constraint")
        elif not mutating:
            why_not.append(f"{action}: no registered mutating tool can carry it")
        elif trial_blocked or not all(i in trial_release for i in items):
            why_not.append(f"{action}: an open critical VOB blocks it ({trial_blocked})")
        else:
            out.append(
                ReconsiderationCandidate(
                    action, items, [c.id for c in constraints], auth.id, auth.authority_holder or ""
                )
            )
    return out, why_not


def finish_design(
    ctx: HarnessContext,
    session: DesignSession,
    prop: AgentDesignProposal,
    rid: str | None,
    *,
    removes: bool,
    feasible: bool,
    registry: ToolRegistry,
    known_limitations: list[str] | None = None,
) -> SolutionDesign:
    ps = ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    notes = Notes()
    if prop.vob_proposals:
        commit_vob_proposals(ctx, prop.vob_proposals, rid, notes=notes)
    release, blocked = preview_release_scope(ctx, prop, notes)
    minimum = [i for i in _scope_items(prop.minimum_useful_scope) if i in release] or list(release)
    deps: dict[str, list[str]] = {}
    known_deps = set(ps.data_assets) | set(ps.process_handoffs) | set(ps.canonical_mappings)
    release_actions = {i.action for i in release}
    for action, ids in prop.scope_dependencies.items():
        if action in release_actions:
            deps[action] = _filter(ids, known_deps, "dependency", notes)
    sunset = prop.bridge_sunset_condition.strip()
    if not sunset and removes and not feasible:
        infeasible = next((c for c in session.design.structural_remedies if c.removes_root_cause), None)
        sunset = f"until structural remedy {infeasible.id if infeasible else '?'} is in place"
        notes.add("BRIDGE needs a sunset condition: defaulted to the structural remedy landing")
    inputs = DesignInputs(
        structural_remedies=list(session.design.structural_remedies),
        deterministic_rules_cover_cases=prop.deterministic_rules_cover_cases,
        llm_reasoning_adds_value=prop.llm_reasoning_adds_value,
        autonomous_iteration_adds_value=prop.autonomous_iteration_adds_value,
        residual_exceptions=prop.residual_exceptions,
        detection_needed=prop.detection_needed,
        why_agent=prop.why_agent or None,
        bridge_sunset_condition=sunset or None,
        deterministic_components=list(prop.deterministic_components),
        release_scope=release,
        minimum_useful_scope=minimum,
        scope_dependencies=deps,
    )
    session.why_agent(inputs.why_agent)
    session.agent_roles(inputs, removes, feasible)
    session.agentification_gate(inputs, removes, feasible)
    design = session.finalize(inputs)
    protected_in_release = sorted({i.action for i in release if i.action in pd.protected_actions})
    human_gate = sorted(set(protected_in_release) | (set(prop.human_gate) & set(pd.protected_actions)))
    suggestion = sorted(prop.role_suggestion)
    actual = sorted(r.value for r in design.agent_roles)
    if suggestion and suggestion != actual:
        notes.add(f"role suggestion {suggestion} ≠ Core classification {actual} (Core wins)")
    with ctx.commit(f"design details {design.id} ({rid})") as p:
        sd = p.solution_design
        assert sd is not None
        sd.unfinished_scope += blocked
        sd.unfinished_scope += [
            f"known limitation: {k}" for k in (known_limitations or []) + prop.known_limitations
        ]
        spec = p.agent_spec
        if spec is not None:
            spec.capabilities = list(prop.capabilities)
            spec.tools = [t for t in prop.tools if t in set(_tool_ids(registry))]
            spec.authority_boundary = list(prop.authority_boundary)
            spec.human_gate = human_gate
            spec.termination = prop.termination
            spec.validation = list(prop.validation)
            spec.decision_rules = list(prop.deterministic_components)
            spec.workflow = [f"LLM: {x}" for x in prop.llm_required_for]
            spec.required_data = sorted({d for ids in deps.values() for d in ids})
            spec.constraints = [c.id for c in p.constraints.values() if c.protected_action in human_gate]
    notes.flush(ctx, "agent_design", rid)
    record(
        ctx,
        "ACCEPTED",
        "agent_design",
        rid,
        {"design": design.id, "roles": actual, "release_scope": [str(i) for i in release]},
    )
    return design


# =========================================================================== EXECUTE


@dataclass
class OutputPlan:
    work_item: str
    name: str
    data_ops: list[str]
    key_fields: list[str]
    join: bool
    constant_fields: dict[str, str]


@dataclass
class CommittedPlan:
    plan: Plan
    data_ops: dict[str, list[str]]  # work item id → catalog refs
    outputs: list[OutputPlan]
    protected: list[tuple[str, ProtectedActionProposal]]  # (work item id, proposal)


def commit_plan(
    ctx: HarnessContext,
    prop: ExecutionPlanProposal,
    rid: str | None,
    *,
    catalog: list[Affordance],
    registry: ToolRegistry,
    plan_id: str,
) -> CommittedPlan:
    ps = ctx.problem
    pd, sd = ps.problem_definition, ps.solution_design
    assert pd is not None and sd is not None
    notes = Notes()
    by_ref = {a.ref: a for a in catalog}
    release = list(sd.release_scope)
    items: list[WorkItem] = []
    data_ops: dict[str, list[str]] = {}
    outputs: list[OutputPlan] = []
    keys: dict[str, str] = {}
    seen: set[str] = set()
    for w in prop.work_items:
        wid = make_id("W", w.key, seen)
        seen.add(wid)
        keys[w.key] = wid
        scope = [i for i in _scope_items(w.scope_items) if i in release]
        if len(scope) != len(w.scope_items):
            notes.add(f"{wid}: scope items outside the release scope dropped")
        ops = [
            r
            for r in w.data_ops
            if r in by_ref and by_ref[r].read_only and by_ref[r].kind is DiscoveryActionKind.TOOL_QUERY
        ]
        if len(ops) != len(w.data_ops):
            notes.add(
                f"{wid}: data ops not in the execute catalog dropped {sorted(set(w.data_ops) - set(ops))}"
            )
        wc = WorkClass(w.work_class)
        if (
            reserve_active(ctx)
            and (wc is not WorkClass.CORE_FEATURE or not w.release_blocking)
            and wc
            not in (
                WorkClass.RELEASE_BLOCKING_VERIFICATION,
                WorkClass.AUTHORITY_SAFETY_CHECK,
                WorkClass.PACKAGING,
                WorkClass.SUBMISSION,
            )
        ):
            notes.add(f"{wid}: droppable work refused while the Release Reserve is active")
            continue
        items.append(
            WorkItem(
                wid,
                w.description,
                wc,
                w.est_minutes,
                scope,
                w.root_problem_aligned and bool(scope),
                w.release_blocking,
            )
        )
        data_ops[wid] = ops
        if w.output_name and ops:
            outputs.append(
                OutputPlan(
                    wid,
                    w.output_name,
                    ops,
                    list(w.output_key_fields),
                    w.output_join,
                    dict(w.output_constant_fields),
                )
            )
    classes = {i.work_class for i in items}
    if WorkClass.RELEASE_BLOCKING_VERIFICATION not in classes:
        items.append(
            WorkItem("W-VERIFY", "release-blocking verification", WorkClass.RELEASE_BLOCKING_VERIFICATION, 10)
        )
        notes.add("added release-blocking verification work item")
    if WorkClass.PACKAGING not in classes:
        items.append(WorkItem("W-PACK", "packaging + submission", WorkClass.PACKAGING, 8))
        notes.add("added packaging work item")
    protected: list[tuple[str, ProtectedActionProposal]] = []
    release_actions = {i.action for i in release}
    for pa in prop.protected_actions:
        why_not = None
        if pa.action not in pd.protected_actions:
            why_not = "not a protected action of the active Problem"
        elif pa.action not in release_actions:
            why_not = "not in the release scope"
        elif pa.resource not in set(_tool_ids(registry)) or registry.spec(pa.resource).read_only:
            why_not = f"resource {pa.resource!r} is not a registered mutating tool"
        scope = [i for i in _scope_items(pa.scope) if i in release]
        if not why_not and not scope:
            why_not = "scope outside the release scope"
        if why_not:
            notes.add(f"protected action {pa.key} refused: {why_not}")
            continue
        evidence = _filter(pa.key_evidence, ps.evidence, "evidence", notes)
        try:
            rev = Reversibility(pa.reversibility)
        except ValueError:
            rev = Reversibility.UNKNOWN
        proposal = ProtectedActionProposal(
            action_id=make_id("PA", pa.key, {p.action_id for _, p in protected}),
            action=pa.action,
            subject=pa.subject,
            protected_resource=pa.resource,
            requested_scope=scope,
            category=ProtectedActionCategory.PROTECTED_MUTATION,
            why=f"{pd.ref}: {pa.why}",
            side_effect=pa.side_effect,
            reversibility=rev,
            alternatives=list(pa.alternatives),
            idempotency_key=f"{pa.action}:{pd.ref}:{pa.key}",
            key_evidence=evidence,
        )
        protected.append((keys.get(pa.work_item, ""), proposal))
    plan = Plan(plan_id, work_items=items, rationale=f"{prop.rationale} ({rid})")
    set_plan(ctx, plan)
    notes.flush(ctx, "plan_execution", rid)
    record(
        ctx,
        "ACCEPTED",
        "plan_execution",
        rid,
        {
            "plan": plan_id,
            "work_items": [i.id for i in items],
            "protected": [p.action_id for _, p in protected],
        },
    )
    return CommittedPlan(plan, data_ops, outputs, protected)


def output_ops(records_by_op: dict[str, list[dict[str, Any]]], out: OutputPlan) -> list[str]:
    """Operations that actually feed an output. A join uses only operations whose records carry every key
    field (an aggregate without the key can neither be joined nor drive the join)."""
    ops = [o for o in out.data_ops if o in records_by_op]
    if out.join and out.key_fields:
        keyed = [o for o in ops if records_by_op[o] and all(f in records_by_op[o][0] for f in out.key_fields)]
        return keyed or ops[:1]
    return ops


def build_output(records_by_op: dict[str, list[dict[str, Any]]], out: OutputPlan) -> list[dict[str, Any]]:
    """Deterministic dataset assembly (join / concat + constant fields). No reasoning involved."""
    ops = output_ops(records_by_op, out)
    if not ops:
        return []
    if out.join and len(ops) > 1 and out.key_fields:

        def k(r: dict[str, Any]) -> tuple[Any, ...]:
            return tuple(r.get(f) for f in out.key_fields)

        index = [{k(r): r for r in records_by_op[o]} for o in ops[1:]]
        rows = []
        for r in records_by_op[ops[0]]:
            if all(k(r) in idx for idx in index):
                merged = dict(r)
                for idx in index:
                    for f, v in idx[k(r)].items():
                        merged.setdefault(f, v)
                rows.append(merged)
    else:
        rows = [dict(r) for o in ops for r in records_by_op[o]]
    for f, v in out.constant_fields.items():
        for r in rows:
            r[f] = v
    return rows


def output_completeness_check(
    out: OutputPlan, ops: list[str], expected_by_op: dict[str, int | None], complete_by_op: dict[str, Any]
) -> tuple[int | None, bool]:
    """RV-7 (A-10 pattern): returns (expected_count, assumes_completeness) for VERIFY's completeness check.

    A real join (>1 feeding op) keeps only rows every op has a matching key for — the row count is
    *expected* to drop below any single feeding op's full result, that is the join doing its job, not a
    pagination gap. So join completeness is judged by whether every feeding op itself paginated fully
    (``complete_by_op``), never by comparing the (necessarily smaller) joined row count against one op's
    ``expected_count``. If every feeding op was COMPLETE, the completeness check is skipped entirely
    (``assumes_completeness=False``) — row count alone cannot fail it. If any op fell short, the check
    stays on (as UNKNOWN) so a true pagination gap is still caught. A non-join (or single-op) output keeps
    the original rule: expected_count comes from its one driving operation."""
    driving = ops[0] if ops else None
    if out.join and len(ops) > 1:
        all_complete = all(complete_by_op.get(o) is ResultCompleteness.COMPLETE for o in ops)
        return None, not all_complete
    return (expected_by_op.get(driving) if driving else None), True


def infer_schema(rows: list[dict[str, Any]]) -> dict[str, str]:
    names = {bool: "bool", int: "int", float: "float", str: "str"}
    schema: dict[str, str] = {}
    for r in rows[:50]:
        for f, v in r.items():
            if v is not None and f not in schema:
                schema[f] = names.get(type(v), "str")
    return schema


# =========================================================================== recovery


def commit_revisions(
    ctx: HarnessContext,
    prop: RevisionSetProposal,
    rid: str | None,
    *,
    challenge_evidence: str,
    allowed: list[str],
    accepted: dict[str, Any] | None = None,
) -> list[str]:
    """Prompt §17: Core validates observation validity, revision kind and dependency links.

    ``accepted`` (IDR-RV5-03): a premise invalidation the Core already accepted for this Problem version. The
    revision of each accepted premise evidence keeps ``problem_invalidating=true`` (the revision step words
    it, it cannot downgrade it); an accepted target the revision step left out is revised from the accepted
    premise-check rationale. A context bound to another Problem version is not applied."""
    notes = Notes()
    ps = ctx.problem
    done: list[str] = []
    locked: list[str] = []
    if accepted:
        pd = ps.problem_definition
        if (
            pd is not None
            and pd.is_canonical()
            and (pd.id, pd.version)
            == (
                accepted.get("accepted_problem_id"),
                accepted.get("accepted_problem_version"),
            )
        ):
            locked = [e for e in accepted.get("accepted_evidence_refs", []) if e in allowed]
        else:
            notes.add("accepted premise context bound to another Problem version: not applied")
    revised: set[str] = set()
    for r in prop.revisions:
        if r.evidence not in allowed or r.evidence not in ps.evidence or r.evidence == challenge_evidence:
            notes.add(f"revision of {r.evidence!r} refused: not proposed for re-interpretation")
            continue
        if r.evidence in revised:
            continue
        inferred = infer_revision_kind(ps.evidence[r.evidence], ps.evidence[challenge_evidence])
        kind = inferred
        if r.revision_kind != inferred.value:
            if (
                r.revision_kind == RevisionKind.SCOPE_REVISED.value
                and inferred is RevisionKind.INTERPRETATION_ONLY
            ):
                kind = RevisionKind.SCOPE_REVISED
            else:
                notes.add(
                    f"{r.evidence}: suggested {r.revision_kind}, Core inferred {inferred.value} (Core wins)"
                )
        invalidating = r.problem_invalidating
        if r.evidence in locked and not invalidating:
            invalidating = True
            notes.add(
                f"{r.evidence}: problem_invalidating=false refused — the Core accepted the premise "
                f"invalidation {accepted.get('accepted_premise_ids') if accepted else []} "
                "(revision cannot downgrade it)"
            )
        rev = revise_evidence(
            ctx,
            r.evidence,
            challenge_evidence,
            r.revised_interpretation,
            invalidates_problem=invalidating,
            revision_kind=kind,
        )
        done.append(rev.id)
        revised.add(r.evidence)
    for eid in locked:
        if eid in revised:
            continue
        why = "; ".join(f"{k}: {v}" for k, v in ((accepted or {}).get("rationale") or {}).items())
        text = (
            f"re-read under {challenge_evidence} (accepted premise check) — {why or 'premise contradicted'}"
        )
        rev = revise_evidence(
            ctx,
            eid,
            challenge_evidence,
            text[:1200],
            invalidates_problem=True,
            revision_kind=infer_revision_kind(ps.evidence[eid], ps.evidence[challenge_evidence]),
        )
        done.append(rev.id)
        notes.add(
            f"{eid}: revision written from the accepted premise-check rationale (revision step omitted it)"
        )
    notes.flush(ctx, "revise_evidence", rid)
    record(ctx, "ACCEPTED", "revise_evidence", rid, {"revisions": done}, refs=[challenge_evidence])
    return done


@dataclass
class TransitionVerdict:
    proposed: str
    core_kind: RecoveryKind | None
    execute_redefine: bool = False
    trigger: str | None = None
    reprofile_targets: list[str] = field(default_factory=list)
    escalate: bool = False
    rationale: str = ""
    decision: RecoveryDecision | None = None


def evaluate_transition(
    ctx: HarnessContext, prop: TransitionProposal, rid: str | None, *, min_confidence: float = 0.5
) -> TransitionVerdict:
    """Reasoner proposes; the existing Core validator (``decide_recovery`` /
    ``validate_problem_invalidation``) decides; the Controller executes (IDR-REASON-06).

    A REDEFINE needs both keys: a validated premise contradiction AND the Reasoner's proposal. A
    disagreement with an open Core challenge escalates to the Human — the Reasoner can never dismiss a
    challenge."""
    ps = ctx.problem
    pd = ps.problem_definition
    notes = Notes()
    triggers = _filter(prop.trigger_evidence_refs, ps.evidence, "evidence", notes)
    verdict = TransitionVerdict(proposed=prop.transition_candidate, core_kind=None, rationale=prop.rationale)
    open_challenge = [c.evidence_id for c in pd.open_challenges()] if pd else []
    if prop.reprofile is not None:
        verdict.reprofile_targets = validate_reprofile_targets(ctx, prop.reprofile.targets, notes)
    if prop.transition_candidate == "REDEFINE":
        candidates = triggers + [e for e in open_challenge if e not in triggers]
        chosen = next((e for e in candidates if validate_problem_invalidation(ps, e)[1] is None), None)
        fc = FailureContext(
            "n/a",
            "semantic-evidence-review",
            None,
            None,
            None,
            problem_invalidating_evidence=chosen or (triggers[0] if triggers else None),
        )
        decision = decide_recovery(ctx, fc)
        apply_recovery_decision(ctx, decision, fc)
        verdict.core_kind, verdict.decision, verdict.trigger = (
            decision.kind,
            decision,
            fc.problem_invalidating_evidence,
        )
        verdict.execute_redefine = (
            decision.kind is RecoveryKind.REDEFINE and prop.confidence >= min_confidence
        )
        if decision.kind is RecoveryKind.REDEFINE and not verdict.execute_redefine:
            verdict.escalate = True
            notes.add(
                f"REDEFINE validated but reasoner confidence {prop.confidence} < {min_confidence}: escalate"
            )
    elif open_challenge:
        verdict.escalate = True
        notes.add(
            f"reasoner proposes {prop.transition_candidate} while Core challenge {open_challenge} is open: "
            "Human decides (the Reasoner cannot dismiss a challenge)"
        )
    elif prop.transition_candidate == "REPROFILE":
        verdict.core_kind = RecoveryKind.REPROFILE if verdict.reprofile_targets else None
    elif prop.transition_candidate == "REPLAN":
        verdict.core_kind = RecoveryKind.REPLAN if pd is not None and pd.is_canonical() else None
    notes.flush(ctx, "propose_transition", rid)
    record(
        ctx,
        "ACCEPTED" if not verdict.escalate else "REJECTED",
        "propose_transition",
        rid,
        {
            "proposed": prop.transition_candidate,
            "core": verdict.core_kind.value if verdict.core_kind else None,
            "execute_redefine": verdict.execute_redefine,
            "escalate": verdict.escalate,
            "reprofile_targets": verdict.reprofile_targets,
        },
        refs=triggers,
    )
    return verdict


def validate_reprofile_targets(ctx: HarnessContext, targets: list[str], notes: Notes) -> list[str]:
    """Prompt §19: targeted only — known ids, 1-4 of them, never 'everything'."""
    ps = ctx.problem
    known = (
        set(ps.data_assets)
        | set(ps.process_handoffs)
        | set(ps.stakeholders)
        | set(ps.organizations)
        | set(ps.hypotheses)
        | set(ps.unknowns)
        | set(ps.processes)
    )
    out = _filter(targets, known, "reprofile target", notes)[:4]
    if ps.data_assets and set(ps.data_assets) <= set(out):
        notes.add("reprofile targeting every data asset is broad rediscovery: refused")
        return []
    return out


# =========================================================================== VERIFY


def problem_ref(ctx: HarnessContext) -> str | None:
    pd = ctx.problem.problem_definition
    return pd.ref if pd else None


def strong_evidence(ctx: HarnessContext, eid: str) -> bool:
    e: Evidence | None = ctx.problem.evidence.get(eid)
    return bool(e and is_strong(e))

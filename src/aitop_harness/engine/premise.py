"""Premise Check — Core side (IDR-RV4-01/02).

    interpret_evidence → commit evidence semantics → [trigger] premise_check (Reasoner, advisory)
                       → Core consistency check → existing canonical challenge path
                         (evidence revision → assess_canonical_challenge → propose_transition →
                          validate_problem_invalidation → Controller)

* The Core enumerates the premises of the ACTIVE canonical Problem; the Reasoner judges each one.
* Trigger (IDR-RV4-01): an ACTIVE canonical Problem without an open challenge + a new observation at or
  above the configured authority threshold + the observation is decision-relevant (it asserts something or
  bears on a hypothesis / premise). Each evidence item is checked at most once per Problem version.
* ``problem_invalidating=true`` is never a redefine by itself (IDR-RV4-02): only a premise judgement that is
  consistent with the Core's rules (material contradiction of a problem-level premise by strong evidence, with
  premise evidence to revise) is routed into the existing revision → challenge → transition validation path.
  Everything else is recorded as a rejected claim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..core.enums import Criticality, HypothesisStatus, SourceAuthority
from ..phases.redefine import assumption_refs, is_strong
from ..reasoning.models import EvidenceInterpretationProposal, PremiseCheckProposal
from .context import HarnessContext
from .views import latest_interpretation

_HELD = (HypothesisStatus.SUPPORTED, HypothesisStatus.CONFIRMED)
_MATERIAL = (Criticality.HIGH, Criticality.CRITICAL)
_CONTRA = ("CONTRADICTS", "PARTIALLY_CONTRADICTS")
RELATIONS = ("SUPPORTS", "CONTRADICTS", "PARTIALLY_CONTRADICTS", "NOT_ADDRESS")


@dataclass
class Premise:
    premise_id: str
    layer: str  # PROBLEM_PREMISE / HYPOTHESIS / CLAIM / ASSUMPTION
    statement: str
    refs: list[str]  # premise evidence of the Problem this premise rests on (revision candidates)

    def view(self) -> dict[str, Any]:
        return {
            "premise_id": self.premise_id,
            "layer": self.layer,
            "statement": self.statement,
            "rests_on": self.refs,
        }


@dataclass
class PremiseVerdict:
    evidence_id: str
    problem_ref: str
    distribution: dict[str, int] = field(default_factory=dict)
    invalidating_claims: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)  # Core-consistent invalidation claims
    rejected: dict[str, str] = field(default_factory=dict)  # premise id → why the Core did not trust it
    targets: list[str] = field(default_factory=list)  # premise evidence routed to the revision path
    overall: str = "UNCERTAIN"
    stale: bool = False

    def detail(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence_id,
            "problem": self.problem_ref,
            "relations": self.distribution,
            "overall": self.overall,
            "invalidating_claims": self.invalidating_claims,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "targets": self.targets,
            "stale": self.stale,
        }


def build_premises(ctx: HarnessContext, record: dict[str, Any] | None) -> list[Premise]:
    """Premises of the ACTIVE canonical Problem: root problem, causal chain (as proposed at DEFINE), premise
    hypotheses, the readings of its premise evidence, and the active assumptions resting on that evidence."""
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None:
        return []
    record = record or {}
    evidence = [e for e in pd.evidence_refs if e in ps.evidence]
    out = [Premise("PR-ROOT", "PROBLEM_PREMISE", pd.root_problem, list(evidence))]
    out += [
        Premise(f"PR-CHAIN-{i}", "PROBLEM_PREMISE", step, list(evidence))
        for i, step in enumerate(record.get("causal_chain", []), 1)
    ]
    for hid in record.get("premise_hypotheses", []):
        h = ps.hypotheses.get(hid)
        if h is not None and h.status in _HELD:
            rests = [e for e in evidence if e in h.supporting_evidence]
            out.append(Premise(f"PR-{hid}", "HYPOTHESIS", h.statement, rests))
    for eid in evidence:
        e = ps.evidence[eid]
        out.append(Premise(f"PR-{eid}", "CLAIM", latest_interpretation(e) or e.content, [eid]))
    for a in ps.assumptions.values():
        rests = sorted(assumption_refs(ps, a) & set(evidence))
        if a.status.value == "ACTIVE" and rests:
            out.append(Premise(f"PR-{a.id}", "ASSUMPTION", a.statement, rests))
    return out


def decision_relevant(prop: EvidenceInterpretationProposal | None) -> bool:
    if prop is None:
        return False
    return (
        bool(prop.assertion_key.strip())
        or any(eff.effect in ("SUPPORTS", "CONTRADICTS") for eff in prop.hypothesis_effects)
        or prop.assessment.relation != "UNRELATED"
        or bool(prop.new_hypotheses)
    )


def premise_check_due(
    ctx: HarnessContext,
    evidence_id: str,
    prop: EvidenceInterpretationProposal | None,
    *,
    checked: set[tuple[str, str]],
    min_authority: str = "STRONG",
) -> tuple[bool, str]:
    ps = ctx.problem
    pd = ps.problem_definition
    if pd is None or not pd.is_canonical():
        return False, "no ACTIVE canonical Problem"
    if pd.open_challenges():
        return False, "a canonical challenge is already open"
    e = ps.evidence.get(evidence_id)
    if e is None or evidence_id in pd.evidence_refs:
        return False, "not new evidence for the Problem"
    if (evidence_id, pd.ref) in checked:
        return False, "already premise-checked for this Problem version"
    strong_enough = (
        is_strong(e) if min_authority == "STRONG" else e.authority is SourceAuthority.AUTHORITATIVE
    )
    if not strong_enough:
        return False, f"below authority threshold {min_authority}"
    if not decision_relevant(prop):
        return False, "not decision-relevant"
    return True, ""


def evidence_view(
    ctx: HarnessContext, evidence_id: str, prop: EvidenceInterpretationProposal | None
) -> dict[str, Any]:
    e = ctx.problem.evidence[evidence_id]
    return {
        "id": evidence_id,
        "source": e.source_id,
        "method": e.provenance.method,
        "authority": e.authority.value,
        "completeness": e.completeness.value,
        "content": e.content,
        "interpretation": prop.interpretation if prop is not None else None,
        "assertion": {e.target_assertion: e.value} if e.target_assertion else {},
    }


def validate_premise_check(
    ctx: HarnessContext, prop: PremiseCheckProposal, evidence_id: str, premises: list[Premise]
) -> tuple[PremiseVerdict, list[str]]:
    """Core consistency check of an advisory premise judgement. Returns the verdict and adjustment notes."""
    ps = ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    notes: list[str] = []
    verdict = PremiseVerdict(evidence_id, pd.ref, overall=prop.overall_assessment)
    if prop.problem_version != pd.version:
        verdict.stale = True
        notes.append(
            f"premise check names {prop.problem_id} v{prop.problem_version}, active is {pd.ref}: ignored"
        )
        return verdict, notes
    if prop.problem_id not in (pd.id, pd.ref):  # the Core binds the Problem; a mislabelled id is only noted
        notes.append(f"premise check names problem {prop.problem_id!r}; judged against {pd.ref}")
    by_id = {p.premise_id: p for p in premises}
    seen: set[str] = set()
    targets: list[str] = []
    for a in prop.premises:
        p = by_id.get(a.premise_id)
        if p is None or a.premise_id in seen:
            notes.append(f"assessment of unknown / duplicate premise {a.premise_id!r} dropped")
            continue
        seen.add(a.premise_id)
        verdict.distribution[a.relation] = verdict.distribution.get(a.relation, 0) + 1
        if not a.problem_invalidating:
            continue
        verdict.invalidating_claims.append(a.premise_id)
        cited = [r for r in a.evidence_refs if r in ps.evidence]
        if len(cited) != len(a.evidence_refs):
            notes.append(
                f"{a.premise_id}: unknown evidence refs {sorted(set(a.evidence_refs) - set(cited))} dropped"
            )
        why = None
        if a.relation not in _CONTRA:
            why = f"relation {a.relation} does not contradict"
        elif a.materiality not in _MATERIAL:
            why = f"materiality {a.materiality.value} below HIGH"
        elif a.affected_layer != "PROBLEM_PREMISE":
            why = f"affected layer {a.affected_layer} is not the problem premise (not problem invalidation)"
        elif not is_strong(ps.evidence[evidence_id]):
            why = f"{evidence_id} is not strong evidence"
        elif not p.refs:
            why = "premise rests on no committed premise evidence to revise"
        if why:
            verdict.rejected[a.premise_id] = why
            continue
        verdict.accepted.append(a.premise_id)
        named = [r for r in cited if r in p.refs]
        targets += [r for r in (named or p.refs) if r not in targets]
    missing = [p for p in by_id if p not in seen]
    if missing:
        notes.append(f"premises not assessed: {missing}")
    verdict.targets = targets
    return verdict, notes

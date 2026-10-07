"""DEFINE Repair Feedback Loop (IDR-RV4-03/04) — Core side.

A failed DEFINE Gate is turned into a typed ``DefineRepairRequest`` instead of free text:

    DEFINE Gate FAIL → (IDR-REL-09 authority recheck, re-run Gate) → still FAIL
                     → typed findings + allowed repair option *types* → Reasoner re-proposes
                     → Core records what changed / which findings were resolved / which remain

* The Core classifies findings and lists the kinds of fix it accepts; it never writes the fix (no action
  names, metric fields or scope items are chosen for the Reasoner).
* Bounded: ``max_define_repair_attempts`` per DEFINE pass; a repair that resolves none of the blocking
  findings ends in a targeted reprofile (when evidence could answer them) or an honest HOLD.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..core.enums import AuthorizationStatus, EvidenceSourceType, SourceAuthority
from ..phases.define import DefineGateOutcome, GateFinding, Severity
from ..reasoning.models import ProblemDefinitionProposal
from .context import HarnessContext

FINDING_TYPES = (
    "UNAUTHORIZED_ACTION_IN_PROBLEM",
    "UNKNOWN_ACTION",
    "UNSUPPORTED_CAUSAL_CLAIM",
    "MISSING_METRIC",
    "INVALID_METRIC",
    "BLOCKING_UNKNOWN",
    "MISSING_AUTHORITY",
    "SCOPE_EXCEEDS_AUTHORIZATION",
    "STALE_EVIDENCE",
    "INSUFFICIENT_EVIDENCE",
    "UNAVAILABLE_TOOL",
    "UNMODELED_DEPENDENCY",
    "CRITICAL_CONFLICT",
    "BUDGET_INFEASIBLE",
    "OTHER",
)

_AUTHORITY_OPTIONS = [
    "remove the action from the canonical Problem (protected_actions and intended_scope)",
    "move the action to unfinished / proposed scope (state it as a KNOWN_LIMITATION success criterion)",
    "identify the authorized actor: cite a committed authoritative document that grants the action "
    "(authorization_candidates with evidence_ref)",
    "replace the action with non-protected diagnostic / detection scope",
]
_REPROFILE = "targeted reprofile to obtain the missing evidence (the Harness decides whether it runs)"

REPAIR_OPTIONS: dict[str, list[str]] = {
    "UNAUTHORIZED_ACTION_IN_PROBLEM": _AUTHORITY_OPTIONS,
    "MISSING_AUTHORITY": _AUTHORITY_OPTIONS,
    "UNKNOWN_ACTION": [
        "use the exact protected-action / operation name defined by a constraint or the tool surface",
        "remove the action from protected_actions and intended_scope",
    ],
    "UNSUPPORTED_CAUSAL_CLAIM": [
        "cite committed non-stakeholder evidence that establishes the causal premise",
        "narrow the root problem to what the evidence supports and move the rest to unknowns",
    ],
    "MISSING_METRIC": [
        "define a minimal measurable success criterion backed by a typed metric",
        "downgrade to a qualitative criterion only if explicitly justified (KNOWN_LIMITATION)",
    ],
    "INVALID_METRIC": [
        "complete the metric's type semantics (the missing fields are named in the finding)",
        "change the metric type to one whose semantics can be stated",
        "drop the metric and the success criterion that uses it",
    ],
    "BLOCKING_UNKNOWN": [
        "give the unknown a resolution_path and a safe_placeholder (it is then deferred to a VOB)",
        "narrow the intended scope so the unknown no longer overlaps it",
        _REPROFILE,
    ],
    "SCOPE_EXCEEDS_AUTHORIZATION": [
        "narrow the intended scope to operations that are authorized",
        "remove the dependency on the unauthorized export / operation",
    ],
    "STALE_EVIDENCE": [
        "cite current (non-revised) evidence instead",
        "drop the stale citation",
    ],
    "INSUFFICIENT_EVIDENCE": ["cite committed evidence ids for symptom and cause", _REPROFILE],
    "UNAVAILABLE_TOOL": [
        "drop the tool from required_tools",
        "narrow the scope that needs the unavailable tool",
    ],
    "UNMODELED_DEPENDENCY": ["drop the dependency", "cite a modeled handoff / asset id"],
    "CRITICAL_CONFLICT": [
        "cite evidence that resolves the conflict",
        "narrow the scope away from the conflicted assertion",
        _REPROFILE,
    ],
    "BUDGET_INFEASIBLE": ["narrow the intended scope to the minimum useful solution"],
    "OTHER": ["address the finding message"],
}
REPROFILE_TYPES = frozenset({"BLOCKING_UNKNOWN", "INSUFFICIENT_EVIDENCE", "CRITICAL_CONFLICT"})
# findings that question the problem framing; without one a repair keeps the framing (RV-4 A-04, R4-S3)
FRAMING_TYPES = frozenset({"UNSUPPORTED_CAUSAL_CLAIM", "INSUFFICIENT_EVIDENCE", "STALE_EVIDENCE"})
LOCKABLE = ("root_problem", "causal_chain", "premise_hypotheses")
_ACTION = re.compile(r"protected action (\S+?):")


@dataclass
class RepairFinding:
    id: str
    type: str
    severity: str
    check: str
    message: str
    refs: list[str]
    subject: str
    repair_options: list[str]

    @property
    def signature(self) -> str:
        return f"{self.type}:{self.subject}"

    def view(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "severity": self.severity,
            "check": self.check,
            "message": self.message,
            "refs": self.refs,
            "subject": self.subject,
            "repair_options": self.repair_options,
        }


@dataclass
class RepairAttempt:
    attempt: int
    findings_before: list[str]
    reasoning_id: str | None = None
    changed: list[str] = field(default_factory=list)
    resolution_claimed: list[dict[str, str]] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    remaining: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    feedback: list[str] = field(default_factory=list)  # Core refusals made during this attempt (fed back)
    settled: bool = False

    def view(self) -> dict[str, Any]:
        return {
            "attempt": self.attempt,
            "findings_before": self.findings_before,
            "changed": self.changed,
            "resolved": self.resolved,
            "remaining": self.remaining,
            "new": self.new,
            "feedback": self.feedback,
        }


def _authority_type(ctx: HarnessContext, action: str) -> str:
    ps = ctx.problem
    if not any(c.protected_action == action for c in ps.constraints.values()):
        return "UNKNOWN_ACTION"
    auth = ps.authorization_for(action)
    if auth is None or auth.status in (AuthorizationStatus.NOT_GRANTED, AuthorizationStatus.REVOKED):
        return "UNAUTHORIZED_ACTION_IN_PROBLEM"
    return "MISSING_AUTHORITY"


def classify_finding(ctx: HarnessContext, f: GateFinding) -> tuple[str, str]:
    """(type, subject) of one DEFINE Gate finding — deterministic, from the Gate's own check + message."""
    msg = f.message
    subject = f.refs[0] if f.refs else f.check
    if f.check == "authority":
        m = _ACTION.search(msg)
        action = m.group(1) if m else subject
        if "approval requirement unknown" in msg:
            return "MISSING_AUTHORITY", action
        return _authority_type(ctx, action), action
    if f.check in ("metric", "verification"):
        return (
            "INVALID_METRIC" if "must be EXTENDED" in msg or "speculative" in msg else "MISSING_METRIC"
        ), subject
    if f.check == "evidence":
        if "stakeholder" in msg:
            return "UNSUPPORTED_CAUSAL_CLAIM", subject
        if "revised" in msg or "superseded" in msg:
            return "STALE_EVIDENCE", subject
        return "INSUFFICIENT_EVIDENCE", subject
    if f.check in ("unknown", "mapping", "vob", "constraint"):
        return "BLOCKING_UNKNOWN", subject
    if f.check == "data":
        return "SCOPE_EXCEEDS_AUTHORIZATION", subject
    if f.check == "handoff":
        return ("UNMODELED_DEPENDENCY" if "not modeled" in msg else "BLOCKING_UNKNOWN"), subject
    if f.check == "tool":
        return "UNAVAILABLE_TOOL", subject
    if f.check == "conflict":
        return "CRITICAL_CONFLICT", subject
    if f.check == "budget":
        return "BUDGET_INFEASIBLE", "budget"
    if f.check == "problem":
        return "UNSUPPORTED_CAUSAL_CLAIM", "root_problem"
    return "OTHER", subject


def classify_findings(ctx: HarnessContext, outcome: DefineGateOutcome) -> list[RepairFinding]:
    out: list[RepairFinding] = []
    for f in outcome.findings:
        if f.severity not in (Severity.BLOCKING, Severity.CONDITIONAL):
            continue
        ftype, subject = classify_finding(ctx, f)
        out.append(
            RepairFinding(
                id=f"F-{len(out) + 1}",
                type=ftype,
                severity=f.severity.value,
                check=f.check,
                message=f.message,
                refs=list(f.refs),
                subject=subject,
                repair_options=list(REPAIR_OPTIONS[ftype]) if f.severity is Severity.BLOCKING else [],
            )
        )
    return out


def blocking(findings: list[RepairFinding]) -> list[RepairFinding]:
    return [f for f in findings if f.severity == Severity.BLOCKING.value]


def locked_fields(findings: list[RepairFinding]) -> list[str]:
    """Problem-framing fields a repair must not rewrite: no blocking finding concerns the framing."""
    return [] if any(f.type in FRAMING_TYPES for f in blocking(findings)) else list(LOCKABLE)


def keep_locked(
    prop: ProblemDefinitionProposal, previous: ProblemDefinitionProposal, locked: list[str]
) -> list[str]:
    """Restore the previous proposal's locked framing fields (the Reasoner's own earlier text, never Core
    content). Returns what was restored."""
    restored: list[str] = []
    pairs = {
        "root_problem": ("problem_statement", "problem_statement"),
        "causal_chain": ("causal_chain", "causal_chain"),
        "premise_hypotheses": ("premise_hypotheses", "premise_hypotheses"),
    }
    for name in locked:
        attr, _ = pairs[name]
        if getattr(prop, attr) != getattr(previous, attr):
            setattr(prop, attr, getattr(previous, attr))
            restored.append(name)
    return restored


def authority_context(ctx: HarnessContext, findings: list[RepairFinding]) -> dict[str, Any]:
    """What the committed state says about each action an authority finding names (no decision made)."""
    ps = ctx.problem
    docs = [
        {"evidence": e.id, "source": e.source_id, "content": e.content[:800]}
        for e in ps.evidence.values()
        if e.source_type in (EvidenceSourceType.DOCUMENT, EvidenceSourceType.POLICY)
        and e.authority is SourceAuthority.AUTHORITATIVE
    ]
    out: dict[str, Any] = {}
    for f in findings:
        if f.type not in ("UNAUTHORIZED_ACTION_IN_PROBLEM", "MISSING_AUTHORITY", "UNKNOWN_ACTION"):
            continue
        auth = ps.authorization_for(f.subject)
        out[f.subject] = {
            "constraints": [
                {"id": c.id, "type": c.type.value, "description": c.description, "actor": c.actor}
                for c in ps.constraints.values()
                if c.protected_action == f.subject
            ],
            "authorization": (
                {"id": auth.id, "status": auth.status.value, "holder": auth.authority_holder}
                if auth
                else None
            ),
            "authoritative_documents": docs,
        }
    return out


def proposal_summary(prop: ProblemDefinitionProposal | None) -> dict[str, Any] | None:
    if prop is None:
        return None
    return {
        "root_problem": prop.problem_statement,
        "causal_chain": prop.causal_chain,
        "premise_hypotheses": prop.premise_hypotheses,
        "evidence_refs": prop.evidence_refs,
        "intended_scope": [f"{i.action}:{i.target}" for i in prop.intended_scope],
        "protected_actions": prop.protected_actions,
        "required_tools": prop.required_tools,
        "metrics": {m.key: {"type": m.metric_type, "semantics": sorted(m.semantics)} for m in prop.metrics},
        "success_criteria": {s.key: {"kind": s.kind, "metric": s.metric} for s in prop.success_criteria},
        "unknowns": {
            u.key: {
                "criticality": u.criticality.value,
                "resolution_path": bool(u.resolution_path),
                "safe_placeholder": bool(u.safe_placeholder),
            }
            for u in prop.unknowns
        },
    }


def diff_proposals(old: ProblemDefinitionProposal | None, new: ProblemDefinitionProposal) -> list[str]:
    """What a repair changed (recorded per attempt; Core-computed, not the Reasoner's claim)."""
    if old is None:
        return ["first proposal"]
    a, b = proposal_summary(old) or {}, proposal_summary(new) or {}
    out: list[str] = []
    if a["root_problem"] != b["root_problem"]:
        out.append("root_problem reworded")
    if a["causal_chain"] != b["causal_chain"]:
        out.append("causal_chain changed")
    for key in (
        "protected_actions",
        "intended_scope",
        "required_tools",
        "evidence_refs",
        "premise_hypotheses",
    ):
        removed = sorted(set(a[key]) - set(b[key]))
        added = sorted(set(b[key]) - set(a[key]))
        if removed:
            out.append(f"{key} removed {removed}")
        if added:
            out.append(f"{key} added {added}")
    for key in ("metrics", "success_criteria", "unknowns"):
        if a[key] != b[key]:
            changed = sorted(k for k in set(a[key]) | set(b[key]) if a[key].get(k) != b[key].get(k))
            out.append(f"{key} changed {changed}")
    if new.authorization_candidates:
        out.append(f"authorization candidates {[c.action for c in new.authorization_candidates]}")
    return out or ["no change"]


def settle(attempt: RepairAttempt, after: list[RepairFinding]) -> None:
    before = set(attempt.findings_before)
    now = {f.signature for f in blocking(after)}
    attempt.resolved = sorted(before - now)
    attempt.remaining = sorted(before & now)
    attempt.new = sorted(now - before)
    attempt.settled = True


def build_request(
    ctx: HarnessContext,
    findings: list[RepairFinding],
    previous: ProblemDefinitionProposal | None,
    history: list[RepairAttempt],
    *,
    attempt: int,
    max_attempts: int,
    refusals: list[str] | None = None,
) -> dict[str, Any]:
    """The DefineRepairRequest handed to the Reasoner (typed findings + allowed option types, no answers)."""
    ps = ctx.problem
    return {
        "attempt": attempt,
        "max_attempts": max_attempts,
        "findings": [f.view() for f in findings],
        "locked_fields": locked_fields(findings),
        "previous_proposal": proposal_summary(previous),
        "authority_context": authority_context(ctx, findings),
        "refused_authorization_candidates": list(refusals or []),
        "open_unknowns": [u.id for u in ps.unknowns.values() if u.status.value == "OPEN"],
        "open_vobs": [v.id for v in ps.open_vobs()],
        "constraints": [c.id for c in ps.constraints.values()],
        "history": [h.view() for h in history],
    }


def grounded_in_document(ctx: HarnessContext, evidence_id: str, holder: str) -> str | None:
    """Repair-path authorization grounding (hallucination control): the cited committed authoritative
    document must name the authority holder (id or role). Returns why not, or None."""
    ps = ctx.problem
    e = ps.evidence.get(evidence_id)
    if e is None:
        return f"{evidence_id!r} is not committed evidence"
    if e.source_type not in (EvidenceSourceType.DOCUMENT, EvidenceSourceType.POLICY) or (
        e.authority is not SourceAuthority.AUTHORITATIVE
    ):
        return f"{evidence_id} is not an authoritative document"
    sh = ps.stakeholders.get(holder)
    names = [holder] + ([sh.role] if sh is not None and sh.role else [])
    text = e.content.lower()
    if not any(n and n.lower() in text for n in names):
        return f"{evidence_id} does not name {holder} ({sh.role if sh else '?'})"
    return None


# ----------------------------------------------------------------------- framing typed repair (IDR-RV5-02)

FRAMING_FINDING = "FRAMING_CLASSIFICATION_CONFLICT"
FRAMING_REPAIR_TYPE = "REPAIR_FRAMING_CLASSIFICATION"
FRAMING_OPTIONS = [
    "KEEP_AS_CLAIM: keep the requester framing as a claim, not a root-cause hypothesis — remove it from "
    "premise_hypotheses and rest the problem on independent SUPPORTED / CONFIRMED hypotheses",
    "SEPARATE_INDEPENDENT_HYPOTHESIS: separate the requester statement from an independent causal "
    "hypothesis — state it (statement) and cite the non-stakeholder evidence it rests on (evidence_refs)",
    "RECLASSIFY_BY_PROVENANCE: the hypothesis was mislabelled as the requester's framing — the Harness "
    "accepts this only if its support includes strong non-stakeholder evidence and nothing contradicts it",
]


def framing_finding(
    ctx: HarnessContext, hypothesis: str, proposal_ref: str | None, reason: str, framing: list[str]
) -> dict[str, Any]:
    """Anti-anchoring refusal as a typed finding: what was refused and the evidence provenance behind the
    hypothesis (no answer: which option applies is the Reasoner's call, the Core validates it)."""
    ps = ctx.problem
    h = ps.hypotheses.get(hypothesis)

    def prov(eid: str, relation: str) -> dict[str, Any]:
        e = ps.evidence[eid]
        return {
            "id": eid,
            "relation": relation,
            "source_type": e.source_type.value,
            "source": e.source_id,
            "authority": e.authority.value,
            "completeness": e.completeness.value,
        }

    support = [prov(e, "SUPPORTS") for e in (h.supporting_evidence if h else []) if e in ps.evidence]
    contra = [prov(e, "CONTRADICTS") for e in (h.contradicting_evidence if h else []) if e in ps.evidence]
    claim = next((c for c in ps.claims.values() if c.is_initial_request), None)
    return {
        "id": "F-FRAMING-1",
        "finding_type": FRAMING_FINDING,
        "severity": Severity.BLOCKING.value,
        "proposal_ref": proposal_ref,
        "hypothesis_ref": hypothesis,
        "hypothesis_statement": h.statement if h else None,
        "reason": reason,
        "evidence_refs": support + contra,
        "expected_repair_type": FRAMING_REPAIR_TYPE,
        "repair_options": list(FRAMING_OPTIONS),
        "requester_claim": {"id": claim.id, "statement": claim.statement} if claim else None,
        "framing_hypotheses": list(framing),
        "independent_hypotheses": sorted(
            hid
            for hid, x in ps.hypotheses.items()
            if hid not in framing and x.status.value in ("SUPPORTED", "CONFIRMED")
        ),
    }

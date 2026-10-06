"""Read-only state views for the Reasoning Layer (Core → Reasoner).

The Reasoner never receives a ``HarnessContext``. The Core builds a plain, JSON-compatible *copy* of the
decision-relevant part of the canonical state; whatever the Reasoner does with it cannot reach the state
(IDR-REASON-02). Hidden ground truth never enters (Evidence.hidden_ground_truth is refused at integration).
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from ..core.enums import Importance
from ..core.scope import Scope, ScopeItem
from ..core.serialization import to_dict
from .context import HarnessContext

_RECENT_EVENT_TYPES = (Importance.CRITICAL, Importance.HIGH)


def _scope(scope: Scope) -> Any:
    return "ENTIRE_SOLUTION" if scope.entire_solution else [str(i) for i in scope.items]


def _items(items: list[ScopeItem]) -> list[dict[str, str]]:
    return [{"action": i.action, "target": i.target} for i in items]


def latest_interpretation(e: Any) -> str | None:
    return e.interpretation_history[-1].interpretation if e.interpretation_history else None


def state_view(ctx: HarnessContext, *, public_notes: dict[str, Any] | None = None) -> dict[str, Any]:
    ps, rt = ctx.problem, ctx.runtime
    pd = ps.problem_definition
    sc = ps.scenario
    assertions: dict[str, list[str]] = {}
    for e in ps.evidence.values():
        if e.target_assertion:
            assertions.setdefault(e.target_assertion, []).append(f"{e.id}={e.value!r}")
    for c in ps.claims.values():
        if c.assertion:
            assertions.setdefault(c.assertion, []).append(f"{c.id}={c.value!r}")
    view: dict[str, Any] = {
        "state_version": ps.meta.version,
        "scenario": {
            "id": sc.id,
            "title": sc.title,
            "description": sc.description,
            "initial_request": sc.initial_request,
            "requested_by": sc.requested_by,
            **(public_notes or {}),
        },
        "organizations": {
            o.id: {
                "name": o.name,
                "role": o.role,
                "objectives": o.objectives,
                "data_assets": o.data_assets,
                "external_dependencies": o.external_dependencies,
            }
            for o in ps.organizations.values()
        },
        "stakeholders": {
            s.id: {
                "organization": s.organization_id,
                "role": s.role,
                "responsibilities": s.responsibilities,
                "authority_scope": s.authority_scope,
                "incentives": s.incentives,
                "potential_bias": s.potential_bias,
                "information_topics": s.information_topics,
            }
            for s in ps.stakeholders.values()
        },
        "processes": {
            p.id: {
                "name": p.name,
                "purpose": p.purpose,
                "steps": p.steps,
                "actors": p.actors,
                "systems": p.systems,
                "data_assets": p.data_assets,
                "handoffs": p.handoff_ids,
                "pain_points": getattr(p, "pain_points", []),
            }
            for p in ps.processes.values()
        },
        "handoffs": {
            h.id: {
                "from_org": h.from_org,
                "to_org": h.to_org,
                "payload": h.payload,
                "channel": h.channel,
                "delivery_status": h.delivery_status.value,
                "semantic_validity": h.semantic_validity.value,
            }
            for h in ps.process_handoffs.values()
        },
        "data_assets": {
            d.id: {
                "name": d.name,
                "organization": d.organization_id,
                "source": d.source,
                "authority": d.authority.value,
                "acquisition": d.acquisition,
                "completeness": d.completeness.value,
            }
            for d in ps.data_assets.values()
        },
        "constraints": {
            k.id: {
                "type": k.type.value,
                "description": k.description,
                "actor": k.actor,
                "protected_action": k.protected_action,
                "approval_required": k.approval_required,
                "runtime_confirmation_required": k.runtime_confirmation_required,
                "status": k.status.value,
            }
            for k in ps.constraints.values()
        },
        "goals": {g.id: g.statement for g in ps.goals.values()},
        "domain_authorizations": {
            a.id: {
                "action": a.action,
                "resource": a.resource,
                "holder": a.authority_holder,
                "scope": _scope(a.authorized_scope),
                "status": a.status.value,
                "evidence": a.evidence_refs,
            }
            for a in ps.domain_authorizations.values()
        },
        "evidence": {
            e.id: {
                "source_type": e.source_type.value,
                "source": e.source_id,
                "method": e.provenance.method,
                "authority": e.authority.value,
                "completeness": e.completeness.value,
                "status": e.status.value,
                "observation": e.content,
                "assertion": e.target_assertion,
                "value": e.value,
                "interpretation": latest_interpretation(e),
                "fallback": e.is_fallback,
            }
            for e in ps.evidence.values()
        },
        "known_assertions": assertions,
        "claims": {
            c.id: {
                "stakeholder": c.stakeholder_id,
                "statement": c.statement,
                "assertion": c.assertion,
                "value": c.value,
                "status": c.status.value,
                "initial_request": c.is_initial_request,
            }
            for c in ps.claims.values()
        },
        "facts": {f.id: {"statement": f.statement, "evidence": f.evidence_refs} for f in ps.facts.values()},
        "hypotheses": {
            h.id: {
                "statement": h.statement,
                "status": h.status.value,
                "decision_impact": h.decision_impact.value,
                "supporting": h.supporting_evidence,
                "contradicting": h.contradicting_evidence,
            }
            for h in ps.hypotheses.values()
        },
        "conflicts": {
            c.id: {
                "assertion": c.assertion,
                "sides": [c.side_a, c.side_b],
                "impact": c.decision_impact.value,
                "status": c.status.value,
            }
            for c in ps.conflicts.values()
        },
        "unknowns": {
            u.id: {
                "question": u.question,
                "criticality": u.criticality.value,
                "status": u.status.value,
                "affects_scope": _scope(u.affects_scope),
                "deferred_to": u.deferred_to_vob,
            }
            for u in ps.unknowns.values()
        },
        "assumptions": {
            a.id: {"statement": a.statement, "status": a.status.value, "evidence": a.evidence_refs}
            for a in ps.assumptions.values()
        },
        "metrics": {
            m.id: {
                "name": m.name,
                "type": m.metric_type.value,
                "profile": m.profile.value,
                "numerator": m.numerator,
                "denominator": m.denominator,
                "current_value": m.current_value,
                "target_value": m.target_value,
            }
            for m in ps.metrics.values()
        },
        "success_criteria": {
            s.id: {
                "statement": s.statement,
                "metric": s.metric_id,
                "threshold": s.threshold,
                "validation_method": s.validation_method,
            }
            for s in ps.success_criteria.values()
        },
        "verification_obligations": {
            v.id: {
                "question": v.unresolved_question,
                "status": v.status.value,
                "required_before": v.required_before.value,
                "blocking_scope": _scope(v.blocking_scope),
                "impact": v.decision_impact.value,
                "problem": f"{v.problem_definition_id}@v{v.problem_version}" if v.problem_version else None,
            }
            for v in ps.verification_obligations.values()
        },
        "evidence_revisions": {
            r.id: {
                "evidence": r.evidence_id,
                "revised_by": r.revised_by,
                "kind": r.revision_kind.value,
                "previous": r.previous_interpretation,
                "revised": r.revised_interpretation,
                "invalidates_problem": r.invalidates_problem,
            }
            for r in ps.evidence_revisions.values()
        },
        "runtime": {
            "phase": rt.phase.value,
            "execution_status": rt.execution_status.value,
            "minute": ctx.clock.now(),
            "budget_remaining_minutes": rt.budget_runtime.remaining,
            "release_reserve": rt.release_runtime.reserve_status.value,
            "tool_health": {t: r.health.value for t, r in rt.tool_runtime.items()},
            "reprofile_targets": list(rt.reprofile_targets),
            "transition_candidate": to_dict(rt.transition_candidate) if rt.transition_candidate else None,
            "pending_protected_action": (
                {
                    "gate": rt.pending_protected_action.gate_id,
                    "action": rt.pending_protected_action.proposal.action,
                    "why": rt.pending_protected_action.proposal.why,
                    "problem_ref": rt.pending_protected_action.problem_ref,
                }
                if rt.pending_protected_action
                else None
            ),
        },
        "recent_events": [
            {"seq": e.seq, "type": e.type.value, "payload": _short(e.payload)}
            for e in list(ctx.events)[-60:]
            if e.importance in _RECENT_EVENT_TYPES
        ][-15:],
    }
    if pd is not None:
        view["problem_definition"] = {
            "id": pd.id,
            "version": pd.version,
            "status": pd.status.value,
            "gate_result": pd.gate_result.value if pd.gate_result else None,
            "requested_solution": pd.requested_solution,
            "symptoms": pd.symptoms,
            "root_problem": pd.root_problem,
            "evidence_refs": pd.evidence_refs,
            "intended_scope": _items(pd.intended_scope),
            "protected_actions": pd.protected_actions,
            "success_criteria": pd.success_criteria,
            "metric_ids": pd.metric_ids,
            "supersedes": pd.supersedes,
            "challenges": [
                {
                    "evidence": c.evidence_id,
                    "contradicted": c.contradicted,
                    "status": c.status.value,
                    "rationale": c.rationale,
                    "proposed_revisions": c.proposed_revisions,
                }
                for c in pd.challenges
            ],
        }
    if ps.meta.problem_definition_history:
        prev = ps.meta.problem_definition_history[-1]
        view["previous_problem"] = {
            "ref": prev.ref,
            "status": prev.status.value,
            "root_problem": prev.root_problem,
            "evidence_refs": prev.evidence_refs,
            "invalidated_by": prev.invalidated_by,
        }
    if ps.dependency_reviews:
        review = list(ps.dependency_reviews.values())[-1]
        view["dependency_review"] = {
            "id": review.id,
            "problem": review.problem_ref,
            "trigger": review.trigger_evidence,
            "items": [
                f"{i.object_type} {i.object_id}: {i.classification.value} ({i.reason})" for i in review.items
            ],
        }
    sd = ps.solution_design
    if sd is not None:
        view["solution_design"] = {
            "id": sd.id,
            "problem": f"{sd.problem_ref}@v{sd.problem_version}",
            "remedies": [
                {
                    "id": c.id,
                    "description": c.description,
                    "removes_root_cause": c.removes_root_cause,
                    "feasible_in_contest_time": c.feasible_in_contest_time,
                }
                for c in sd.structural_remedies
            ],
            "agent_roles": [r.value for r in sd.agent_roles],
            "release_scope": _items(sd.release_scope),
            "minimum_useful_scope": _items(sd.minimum_useful_scope),
            "unfinished_scope": sd.unfinished_scope,
            "scope_dependencies": sd.scope_dependencies,
        }
    if rt.current_plan is not None:
        view["plan"] = {
            "id": rt.current_plan.id,
            "work_items": [
                {
                    "id": w.id,
                    "description": w.description,
                    "class": w.work_class.value,
                    "status": w.status,
                    "scope": [str(i) for i in w.scope_items],
                }
                for w in rt.current_plan.work_items
            ],
        }
    return json.loads(json.dumps(view, ensure_ascii=False, default=str))  # a detached copy


def _short(payload: dict[str, Any]) -> Any:
    text = json.dumps(to_dict(payload), ensure_ascii=False, default=str)
    return text if len(text) <= 400 else text[:400] + "…"


# --------------------------------------------------------------------------- observation rendering


def render_records(tool_id: str, operation: str, records: list[dict[str, Any]], *, limit: int = 12) -> str:
    """Deterministic, lossless-for-small / summarised-for-large rendering of a tool result.

    This becomes Evidence.content (the *observation*). It is produced by the Core from the raw records,
    never by the Reasoner, so the observation cannot be hallucinated.
    """
    n = len(records)
    head = f"{tool_id}.{operation} → {n} record(s)"
    if n == 0:
        return f"{head}: none"
    if n <= limit:
        return f"{head}: " + "; ".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records)
    fields = sorted({k for r in records for k in r})
    parts = [head + f"; fields {fields}"]
    for f in fields:
        values = Counter(str(r.get(f)) for r in records)
        if len(values) <= 8:
            parts.append(f"{f}: " + ", ".join(f"{v}×{c}" for v, c in values.most_common()))
        else:
            parts.append(f"{f}: {len(values)} distinct values")
    parts.append("sample: " + json.dumps(records[0], ensure_ascii=False, sort_keys=True))
    return " | ".join(parts)

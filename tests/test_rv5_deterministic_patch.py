"""RV-5 deterministic stabilization patches (IDR-RV5-01..04).

A1 scope_target contract   — typed scope_kind + syntax-only normalization; never authorization inference
A2 framing typed repair    — the anti-anchoring refusal becomes a typed finding; Core validates by provenance
A3 premise → revision       — a Core-accepted premise invalidation cannot be downgraded by the revision step
A4 blocking-scope review    — one evidence-aware look at a critical unknown that blocks the entire scope
Prompt-tuning guard        — the new instructions / options are domain-agnostic.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from autonomous_fixtures import _remedy, ev_by, h_by, run, scenario_d, scope
from test_rv4_reasoning_stabilization import (
    _calls,
    _no_grant,
    _records,
    _repairing_define,
    _scenario_tokens,
    missed_contradiction,
    premise_judge,
)

from aitop_harness.core.events import EventType
from aitop_harness.core.scope import WILDCARD, ScopeItem
from aitop_harness.engine.autonomous import AutonomousConfig
from aitop_harness.engine.define_repair import FRAMING_FINDING, FRAMING_OPTIONS
from aitop_harness.engine.proposals import commit_revisions
from aitop_harness.engine.scope_contract import normalize_scope_target
from aitop_harness.reasoning.models import RevisionSetProposal
from aitop_harness.reasoning.prompts import INSTRUCTIONS

ACTION, RESOURCE = "push_pickup_schedule", "pickup-sched"


def _adjusted(orch: Any, skill: str) -> list[str]:
    return [
        x
        for e in orch.ctx.events.of_type(EventType.PROPOSAL_ADJUSTED)
        if e.payload["skill"] == skill
        for x in (e.payload["detail"] if isinstance(e.payload["detail"], list) else [e.payload["detail"]])
    ]


# =========================================================================== A1 scope_target contract


@pytest.mark.parametrize(
    ("kind", "raw", "expected"),
    [
        ("", "pickup-sched", "pickup-sched"),
        ("", f"{ACTION}:pickup-sched", "pickup-sched"),  # ScopeItem string form
        ("", f"pickup-sched/{ACTION}", "pickup-sched"),  # resource/action mixture
        ("", " 'Pickup-Sched' ", "pickup-sched"),  # quotes + case of a known id
        ("", "*", WILDCARD),
        ("", "", WILDCARD),
        ("RESOURCE", "", WILDCARD),  # RV-7: RESOURCE covers the action through this resource, any target
        ("RESOURCE", RESOURCE, WILDCARD),  # resource as scope_target still means ANY_TARGET
        ("ANY_TARGET", "", WILDCARD),
        ("INTENDED_TARGET", f"{ACTION}:DA-PICK", "DA-PICK"),
    ],
)
def test_equivalent_scope_syntax_normalizes_to_the_canonical_target(
    kind: str, raw: str, expected: str
) -> None:
    norm = normalize_scope_target(ACTION, RESOURCE, kind, raw, known_ids=["DA-PICK", "SH-CAR"])
    assert norm.refusal is None and norm.target == expected


@pytest.mark.parametrize(
    ("kind", "raw"),
    [
        ("", "pickup schedule of the carrier"),  # free text is not a scope
        ("INTENDED_TARGET", ""),  # a typed target needs an id
        ("INTENDED_TARGET", "the slots"),
        ("", f"{ACTION}:DA-PICK:SH-CAR"),  # two ids: ambiguous, never guessed
        ("WIDEST", "*"),
    ],
)
def test_normalization_never_reads_a_target_out_of_text(kind: str, raw: str) -> None:
    norm = normalize_scope_target(ACTION, RESOURCE, kind, raw, known_ids=["DA-PICK", "SH-CAR"])
    assert norm.target is None and norm.refusal


def test_normalization_does_not_widen_or_redirect_the_written_target() -> None:
    # the holder written as a target stays the holder (still refused by the Core rules, never mapped)
    norm = normalize_scope_target(ACTION, RESOURCE, "", f"{ACTION}:SH-CAR", known_ids=["SH-CAR"])
    assert norm.target == "SH-CAR"
    # an unknown id is kept as written, not replaced by the resource or '*'
    assert normalize_scope_target(ACTION, RESOURCE, "", "DA-OTHER").target == "DA-OTHER"


def _citing(target: str, kind: str = "") -> Any:
    def cite(out: dict[str, Any], data: dict[str, Any]) -> None:
        doc = data["repair_request"]["authority_context"][ACTION]["authoritative_documents"][0]["evidence"]
        cand = {
            "action": ACTION,
            "resource": RESOURCE,
            "authority_holder": "SH-CAR",
            "scope_target": target,
            "conditions": [],
            "evidence_ref": doc,
            "rationale": "contract §3",
        }
        out["authorization_candidates"] = [cand | ({"scope_kind": kind} if kind else {})]

    return cite


@pytest.mark.parametrize("target", [f"{ACTION}:pickup-sched", f"pickup-sched/{ACTION}"])
def test_repair_authorization_in_equivalent_syntax_is_accepted_on_the_canonical_scope(target: str) -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    seen = _repairing_define(handlers, _citing(target, ""))
    orch, _, _, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(seen) == 1  # accepted on the first repair, no refusal round
    auth = [a for a in orch.ctx.problem.domain_authorizations.values() if a.action == ACTION]
    assert len(auth) == 1 and str(auth[0].authorized_scope.items[0]) == f"{ACTION}:{RESOURCE}"
    assert len(orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1  # via the Human Gate only


def test_repair_authorization_scope_kind_resource_covers_any_target() -> None:
    """RV-7 (A-15 pattern): a RESOURCE grant must still match a request whose scope target is a data asset
    id, not the resource's own id — intended_scope normally targets a data asset / handoff, a different id
    space than the tool resource. Reading RESOURCE as target == resource made such a grant unmatchable."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    seen = _repairing_define(handlers, _citing("", "RESOURCE"))
    orch, _, _, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(seen) == 1
    auth = [a for a in orch.ctx.problem.domain_authorizations.values() if a.action == ACTION]
    assert len(auth) == 1
    assert auth[0].authorized_scope.covers(ScopeItem(ACTION, "DA-SOME-OTHER-ID"))
    assert len(orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1


@pytest.mark.parametrize("target", [f"{ACTION}:SH-CAR", "the carrier pickup schedule"])
def test_normalization_does_not_invent_authorization(target: str) -> None:
    """RV-4c A-08 pattern (action:holder, description): refused with the accepted canonical forms fed back."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _no_grant(handlers)
    seen = _repairing_define(handlers, _citing(target))
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert not [a for a in orch.ctx.problem.domain_authorizations.values() if a.action == ACTION]
    refused = seen[1]["refused_authorization_candidates"][0]
    assert "refused" in refused and "scope_kind RESOURCE" in refused and "ANY_TARGET" in refused
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


def test_integration_path_normalizes_syntax_only() -> None:
    public, world, handlers, human = scenario_d()
    base = handlers["interpret_evidence"]

    def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = base(req, data)
        for a in out.get("authorization_candidates", []):
            a["scope_target"] = f"{ACTION}:{RESOURCE}"
        return out

    handlers["interpret_evidence"] = interpret
    orch, _, _, _ = run(public, world, handlers, human=human)
    auth = [a for a in orch.ctx.problem.domain_authorizations.values() if a.action == ACTION]
    assert auth and str(auth[0].authorized_scope.items[0]) == f"{ACTION}:{RESOURCE}"
    assert any("normalized" in x for x in _adjusted(orch, "interpret_evidence"))


# =========================================================================== A2 framing typed repair


def _mislabel(handlers: dict[str, Any], *, independent_support: bool = True) -> None:
    """RV-4c C-01/C-02 pattern: hypothesis_init marks the actual cause as the requester's framing."""
    init = copy.deepcopy(handlers["hypothesis_init"])
    for h in init["hypotheses"]:
        h["origin"] = "REQUESTER_FRAMING" if h["key"] == "PICKUP" else "ALTERNATIVE"
    handlers["hypothesis_init"] = init
    if not independent_support:
        base = handlers["interpret_evidence"]

        def interpret(req: Any, data: dict[str, Any]) -> dict[str, Any]:
            out = base(req, data)
            if data["observation"]["source"] in ("order-db", "pickup-log"):
                out["hypothesis_effects"] = []
            return out

        handlers["interpret_evidence"] = interpret


def _framing_define(handlers: dict[str, Any], resolve: Any) -> list[dict[str, Any]]:
    base = handlers["define_problem"]
    seen: list[dict[str, Any]] = []

    def define(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(base(req, data))
        if "framing_repair" in data:
            seen.append(data)
            resolve(out, data)
        return out

    handlers["define_problem"] = define
    return seen


def _resolution(option: str, **kw: Any) -> Any:
    def resolve(out: dict[str, Any], data: dict[str, Any]) -> None:
        f = data["framing_repair"]
        out["framing_resolution"] = [
            {
                "hypothesis": f["hypothesis_ref"],
                "option": option,
                "statement": kw.get("statement", ""),
                "evidence_refs": kw.get("refs", lambda st: [])(data["state"]),
                "rationale": "fixture",
            }
        ]

    return resolve


def test_framing_rejection_becomes_a_typed_repair_finding() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers)
    seen = _framing_define(handlers, _resolution("RECLASSIFY_BY_PROVENANCE"))
    orch, _, _, _ = run(public, world, handlers, human=human)
    assert len(seen) == 1
    f = seen[0]["framing_repair"]
    assert f["finding_type"] == FRAMING_FINDING and f["expected_repair_type"]
    for key in ("proposal_ref", "hypothesis_ref", "reason", "evidence_refs", "repair_options"):
        assert f[key], key
    assert "previous_proposal_rejected" not in seen[0]  # typed, not free text
    assert f["hypothesis_ref"] == h_by(seen[0]["state"], "PICKUP")
    rec = _records(orch, "framing_repair")
    assert rec and rec[0]["accepted"] and "reclassified" in rec[0]["accepted"][0]
    pd = orch.ctx.problem.problem_definition
    assert pd is not None and pd.version >= 1 and pd.gate_result is not None


def test_framing_repair_preserves_evidence_provenance() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers)
    seen = _framing_define(handlers, _resolution("RECLASSIFY_BY_PROVENANCE"))
    orch, _, _, _ = run(public, world, handlers, human=human)
    refs = seen[0]["framing_repair"]["evidence_refs"]
    ps = orch.ctx.problem
    assert refs and all(r["source_type"] == ps.evidence[r["id"]].source_type.value for r in refs)
    assert {r["source_type"] for r in refs} >= {"TOOL", "STAKEHOLDER"}
    # the requester's statement stays a claim; the reclassified hypothesis keeps its own evidence links
    assert seen[0]["framing_repair"]["requester_claim"]
    assert any(c.is_initial_request for c in ps.claims.values())
    hid = seen[0]["framing_repair"]["hypothesis_ref"]
    assert {r["id"] for r in refs if r["relation"] == "SUPPORTS"} <= set(
        ps.hypotheses[hid].supporting_evidence
    )


def test_reclassification_without_independent_strong_support_is_refused() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers, independent_support=False)
    _framing_define(handlers, _resolution("RECLASSIFY_BY_PROVENANCE"))
    orch, result, _, _ = run(public, world, handlers, human=human)
    assert any("reclassification" in x and "refused" in x for x in _adjusted(orch, "define_problem"))
    assert result.halt_reason is not None and "DEFINE proposal rejected twice" in result.halt_reason
    assert not orch.ctx.events.of_type(EventType.DEFINE_GATE_RESULT)


def test_keep_as_claim_must_actually_drop_the_framing_premise() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers)
    _framing_define(handlers, _resolution("KEEP_AS_CLAIM"))  # claims it, keeps citing the framing
    _, result, _, _ = run(public, world, handlers, human=human)
    assert result.halt_reason is not None and "requester framing" in result.halt_reason


def test_separated_independent_hypothesis_carries_the_premise() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers)
    seen = _framing_define(
        handlers,
        _resolution(
            "SEPARATE_INDEPENDENT_HYPOTHESIS",
            statement="handover lateness follows the measured pickup delay",
            refs=lambda st: [ev_by(st, source="pickup-log")],
        ),
    )
    orch, _, _, _ = run(public, world, handlers, human=human)
    ps = orch.ctx.problem
    framing = seen[0]["framing_repair"]["hypothesis_ref"]
    new = [h for h in ps.hypotheses if h.endswith("INDEPENDENT")]
    assert new and ps.hypotheses[new[0]].status.value == "SUPPORTED"
    assert framing in orch.dctx.framing_hypotheses  # the framing hypothesis stays the requester's
    premise = [
        d["premise_hypotheses"] for d in _records(orch, "define_problem") if "premise_hypotheses" in d
    ][0]
    assert new[0] in premise and framing not in premise


def test_separation_citing_only_stakeholder_evidence_is_refused() -> None:
    public, world, handlers, human = scenario_d()
    _mislabel(handlers)
    _framing_define(
        handlers,
        _resolution(
            "SEPARATE_INDEPENDENT_HYPOTHESIS",
            statement="logistics says the carrier is late",
            refs=lambda st: [ev_by(st, source="SH-LOG")],
        ),
    )
    orch, result, _, _ = run(public, world, handlers, human=human)
    assert not [h for h in orch.ctx.problem.hypotheses if h.endswith("INDEPENDENT")]
    assert result.halt_reason is not None and "rejected twice" in result.halt_reason


# =========================================================================== A3 premise → revision


def test_accepted_premise_context_reaches_the_revision_step_immutably() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs")
    orch, _, provider, _ = run(public, world, handlers, human=human)
    payloads = [json.loads(c.input_json) for c in _calls(provider, "revise_evidence")]
    ctx = next(p["accepted_premise_check"] for p in payloads if "accepted_premise_check" in p)
    for key in (
        "accepted_problem_id",
        "accepted_problem_version",
        "accepted_premise_ids",
        "accepted_relation",
        "accepted_materiality",
        "accepted_problem_invalidating",
        "accepted_evidence_refs",
    ):
        assert key in ctx, key
    assert ctx["accepted_problem_invalidating"] is True and ctx["accepted_problem_version"] == 1


@pytest.mark.parametrize("mode", ["omitted", "provider_failure"])
def test_accepted_invalidation_survives_a_missing_revision(mode: str) -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs")
    revise = handlers["revise_evidence"]

    def broken(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        if "accepted_premise_check" not in data:
            return revise(req, data)
        if mode == "omitted":
            return {"revisions": []}
        raise RuntimeError("provider down")

    handlers["revise_evidence"] = broken
    orch, _, _, _ = run(public, world, handlers, human=human)
    assert orch.ctx.events.of_type(EventType.CANONICAL_PROBLEM_CHALLENGED)
    revs = list(orch.ctx.problem.evidence_revisions.values())
    assert revs and all(r.invalidates_problem for r in revs[:1])
    assert any("accepted premise-check rationale" in x for x in _adjusted(orch, "revise_evidence"))


def _mixed_judge(req: Any, data: dict[str, Any]) -> dict[str, Any]:
    """PR-ROOT accepted (problem premise), PR-CHAIN-1 rejected (hypothesis layer) on the decisive evidence."""
    out = premise_judge("failed_runs")(req, data)
    for p in out["premises"]:
        if p["premise_id"] == "PR-CHAIN-1" and p["problem_invalidating"]:
            p["affected_layer"] = "HYPOTHESIS"
            p["rationale"] = "REJECTED-CLAIM-TEXT"
        elif p["premise_id"] == "PR-ROOT" and p["problem_invalidating"]:
            p["rationale"] = "ACCEPTED-CLAIM-TEXT"
    return out


def test_rejected_premise_claim_never_leaks_into_the_revision() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = _mixed_judge
    orch, _, provider, _ = run(public, world, handlers, human=human)
    rec = next(r for r in _records(orch, "premise_check") if r["invalidating_claims"])
    assert "PR-CHAIN-1" in rec["rejected"] and "PR-ROOT" in rec["accepted"]
    texts = [
        c.input_json for c in _calls(provider, "revise_evidence") if "accepted_premise_check" in c.input_json
    ]
    assert texts and all("ACCEPTED-CLAIM-TEXT" in t and "REJECTED-CLAIM-TEXT" not in t for t in texts)


def test_rejected_premise_check_starts_no_revision() -> None:
    public, world, handlers, human = scenario_d()
    missed_contradiction(handlers)
    handlers["premise_check"] = premise_judge("failed_runs", layer="HYPOTHESIS")
    _, _, provider, _ = run(public, world, handlers, human=human)
    assert not [c for c in _calls(provider, "revise_evidence") if "accepted_premise_check" in c.input_json]


def test_accepted_context_bound_to_another_version_is_not_applied() -> None:
    public, world, handlers, human = scenario_d()
    orch, _, _, _ = run(public, world, handlers, human=human)
    ps = orch.ctx.problem
    pd = ps.problem_definition
    assert pd is not None
    eids = sorted(ps.evidence)
    accepted = {
        "accepted_problem_id": pd.id,
        "accepted_problem_version": pd.version + 7,
        "accepted_evidence_refs": [eids[0]],
        "rationale": {"PR-ROOT": "x"},
    }
    done = commit_revisions(
        orch.ctx,
        RevisionSetProposal(revisions=[]),
        "t",
        challenge_evidence=eids[-1],
        allowed=[eids[0]],
        accepted=accepted,
    )
    assert done == []
    assert any("another Problem version" in x for x in _adjusted(orch, "revise_evidence"))


# =========================================================================== A4 blocking-scope review


def _entire_block(handlers: dict[str, Any], *, feasible: bool = True) -> None:
    """RV-4c C-03 / B-06 pattern: a Reasoner-raised HIGH unknown blocks every intended item."""
    base = handlers["define_problem"]
    handlers["structural_remedy"] = lambda req, data: _remedy(feasible=feasible)

    def define(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(base(req, data))
        if out.get("protected_actions"):
            for u in out["unknowns"]:
                u["affects_scope"] = list(out["intended_scope"])
        return out

    handlers["define_problem"] = define


def _protected_action_only_block(handlers: dict[str, Any], *, feasible: bool = True) -> None:
    """RV-6: Human Gate 0/3 pattern — a Reasoner-raised HIGH unknown blocks only the protected action,
    not the entire intended scope (BEFORE_PROTECTED_ACTION VOB narrower than the whole solution)."""
    base = handlers["define_problem"]
    handlers["structural_remedy"] = lambda req, data: _remedy(feasible=feasible)

    def define(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = copy.deepcopy(base(req, data))
        if out.get("protected_actions"):
            for u in out["unknowns"]:
                u["affects_scope"] = [scope(a, RESOURCE) for a in out["protected_actions"]]
        return out

    handlers["define_problem"] = define


def _review(decision: str, *, narrowed: Any = None, refs: Any = None) -> Any:
    def handler(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        return {
            "reviews": [
                {
                    "vob": o["vob"],
                    "decision": decision,
                    "narrowed_scope": narrowed
                    if narrowed is not None
                    else [scope("slot_impact_report", "mgmt")],
                    "evidence_refs": (refs or (lambda s: [ev_by(s, source="pickup-log")]))(st),
                    "rationale": "only the impact report depends on the answer",
                    "needed_evidence": "",
                }
                for o in data["blocking_review"]["obligations"]
            ],
            "confidence": 0.7,
        }

    return handler


def test_entire_scope_block_gets_one_bounded_review_and_narrows_with_evidence() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _entire_block(handlers)
    handlers["review_blocking_scope"] = _review("NARROW_BLOCKING_SCOPE")
    orch, _, provider, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(_calls(provider, "review_blocking_scope")) == 1
    ev = orch.ctx.events
    narrowed = ev.of_type(EventType.VOB_SCOPE_NARROWED)
    assert len(narrowed) == 1
    vob = orch.ctx.problem.verification_obligations[narrowed[0].payload["vob"]]
    assert vob.status.value in ("OPEN", "DEFERRED")  # still an obligation, only its scope is narrower
    assert [str(i) for i in vob.blocking_scope.items] == ["slot_impact_report:mgmt"]
    sd = orch.ctx.problem.solution_design
    assert sd is not None and any(i.action == ACTION for i in sd.release_scope)
    # the protected action still goes through the Mandatory Human Gate; the open unknown is shown to the Human
    packets = ev.of_type(EventType.APPROVAL_PACKET_EMITTED)
    assert packets and any(vob.linked_unknown in json.dumps(p.payload) for p in packets)
    assert len(ev.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1


def test_protected_action_only_block_gets_a_bounded_review_and_opens_the_human_gate() -> None:
    """RV-6: a VOB that blocks only the protected action — not the entire intended scope — is now eligible
    for the same bounded, evidence-aware review (previously only Human Gate reachability was 0 because
    ``preview_release_scope`` dropped the protected action and the Harness never built a proposal for it)."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _protected_action_only_block(handlers)
    handlers["review_blocking_scope"] = _review("NARROW_BLOCKING_SCOPE", narrowed=[])
    orch, _, provider, _ = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    assert len(_calls(provider, "review_blocking_scope")) == 1
    ev = orch.ctx.events
    narrowed = ev.of_type(EventType.VOB_SCOPE_NARROWED)
    assert len(narrowed) == 1
    vob = orch.ctx.problem.verification_obligations[narrowed[0].payload["vob"]]
    assert vob.status.value in ("OPEN", "DEFERRED")  # still an obligation, only its scope is narrower
    assert vob.blocking_scope.items == []  # narrowed to verification-only: no intended item still blocked
    # the Mandatory Human Gate is reached and the action still goes through it (not bypassed)
    assert len(ev.of_type(EventType.PROTECTED_ACTION_PROPOSED)) == 1
    packets = ev.of_type(EventType.APPROVAL_PACKET_EMITTED)
    assert packets and any(vob.linked_unknown in json.dumps(p.payload) for p in packets)
    assert len(ev.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1


def test_protected_action_only_block_keep_entire_block_is_respected() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _protected_action_only_block(handlers)
    handlers["review_blocking_scope"] = _review("KEEP_ENTIRE_BLOCK")
    orch, _, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(_calls(provider, "review_blocking_scope")) == 1
    assert not orch.ctx.events.of_type(EventType.VOB_SCOPE_NARROWED)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_PROPOSED)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


def test_protected_action_only_block_without_review_still_leaves_the_gate_unreached() -> None:
    """Regression guard: without the RV-6 patch (no review call at all) the protected action is still
    dropped before any gate — proves the review, not some other path, is what opens the gate above."""
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _protected_action_only_block(handlers)
    config = AutonomousConfig(blocking_scope_review=False)
    orch, _, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3, config=config)
    assert not _calls(provider, "review_blocking_scope")
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_PROPOSED)


def test_keep_entire_block_is_respected() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _entire_block(handlers)
    handlers["review_blocking_scope"] = _review("KEEP_ENTIRE_BLOCK")
    orch, result, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(_calls(provider, "review_blocking_scope")) == 1
    assert not orch.ctx.events.of_type(EventType.VOB_SCOPE_NARROWED)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)
    assert result.halt_reason is not None and "no releasable scope" in result.halt_reason


@pytest.mark.parametrize("why", ["no_evidence", "stakeholder_evidence", "not_narrower", "outside_block"])
def test_unsupported_narrowing_is_refused(why: str) -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _entire_block(handlers)
    kw: dict[str, Any] = {
        "no_evidence": {"refs": lambda st: []},
        "stakeholder_evidence": {"refs": lambda st: [ev_by(st, source="SH-LOG")]},
        "not_narrower": {
            "narrowed": [
                scope("rank_late_slots", "DA-PICK"),
                scope(ACTION, RESOURCE),
                scope("slot_impact_report", "mgmt"),
            ]
        },
        "outside_block": {"narrowed": [scope("invented_action", "X")]},
    }[why]
    handlers["review_blocking_scope"] = _review("NARROW_BLOCKING_SCOPE", **kw)
    orch, _, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert not orch.ctx.events.of_type(EventType.VOB_SCOPE_NARROWED)
    assert any("narrowing of" in x and "refused" in x for x in _adjusted(orch, "review_blocking_scope"))
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


@pytest.mark.parametrize("why", ["safety_constraint", "infeasible", "robustness_variant"])
def test_narrow_scope_review_cannot_bypass_a_true_block(why: str) -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    _entire_block(handlers, feasible=why != "infeasible")
    if why == "safety_constraint":
        public["problem"]["constraints"]["K-SAFE"] = {
            "id": "K-SAFE",
            "type": "SAFETY",
            "description": "schedule pushes must not strand parcels",
            "actor": "SH-CAR",
            "protected_action": ACTION,
            "approval_required": True,
        }
    config = AutonomousConfig(ignore_unknown_scope_versions={1}) if why == "robustness_variant" else None
    handlers["review_blocking_scope"] = _review("NARROW_BLOCKING_SCOPE")
    orch, _, provider, _ = run(public, world, handlers, human=["승인합니다"] * 3, config=config)
    assert not _calls(provider, "review_blocking_scope")
    assert not orch.ctx.events.of_type(EventType.VOB_SCOPE_NARROWED)
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)


def test_no_review_when_nothing_blocks_the_entire_scope() -> None:
    public, world, handlers, human = scenario_d()
    handlers["review_blocking_scope"] = _review("NARROW_BLOCKING_SCOPE")
    orch, _, provider, _ = run(public, world, handlers, human=human)
    assert not _calls(provider, "review_blocking_scope")
    assert not _records(orch, "review_blocking_scope")  # nothing recorded: the event log is unchanged


# =========================================================================== prompt-tuning guard


@pytest.mark.parametrize(
    "skill", ["review_blocking_scope", "define_problem", "revise_evidence", "interpret_evidence"]
)
def test_rv5_instructions_are_domain_agnostic(skill: str) -> None:
    assert not _scenario_tokens(INSTRUCTIONS[skill])


def test_framing_repair_options_are_domain_agnostic_and_never_answers() -> None:
    assert not _scenario_tokens(" ".join(FRAMING_OPTIONS))
    assert not any("H-" in o for o in FRAMING_OPTIONS)  # no hypothesis is named for the Reasoner

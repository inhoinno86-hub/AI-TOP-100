"""Regression tests for the reliability-validation stabilization patches (RV-2 defects).

* IDR-REL-08 (RV-2 A-10): "1184" and 1184 are the same canonical assertion value — agreeing evidence must not
  become a premise contradiction / REDEFINE.
* IDR-REL-09 (RV-2 C-01, C-03, D3): when the DEFINE Gate blocks on an unknown protected-action authority, the
  Harness re-asks about committed authoritative documents (bounded) instead of re-proposing the Problem only.
"""

from __future__ import annotations

from typing import Any

from autonomous_fixtures import run, scenario_a, scenario_d

from aitop_harness.core.enums import EvidenceSourceType, SourceAuthority
from aitop_harness.core.events import EventType
from aitop_harness.engine.proposals import Observation, _value, integrate_observation
from aitop_harness.reasoning.models import PARSERS


def test_numeric_and_boolean_strings_are_canonical_values() -> None:
    assert _value("1184") == 1184 and isinstance(_value("1184"), int)
    assert _value("0.88") == 0.88 and _value("-3") == -3 and _value("1,184") == 1184
    assert _value("true") is True and _value("False") is False
    assert _value("ami_read_rejected") == "ami_read_rejected" and _value("v4.2") == "v4.2"
    assert _value("a free text sentence") is None and _value("") is None


def test_agreeing_numeric_string_is_not_a_conflict() -> None:
    orch, _, _, _ = run(*scenario_a())
    ctx = orch.ctx
    conflicts = len(ctx.problem.conflicts)

    def observe(value: Any, n: int) -> None:
        prop = PARSERS["interpret_evidence"](
            {
                "interpretation": "count",
                "assertion_key": "rejects.total_count",
                "assertion_value": value,
                "hypothesis_effects": [],
                "new_hypotheses": [],
                "fact_candidates": [],
                "unknown_resolutions": [],
                "authorization_candidates": [],
                "contradiction_assessment": {
                    "relation": "UNRELATED",
                    "target_type": "NONE",
                    "target_refs": [],
                    "materiality": "LOW",
                    "problem_invalidating": False,
                    "rationale": "x",
                },
                "vob_proposals": [],
                "follow_up_actions": [],
                "confidence": 0.8,
            }
        )
        integrate_observation(
            ctx,
            Observation(
                EvidenceSourceType.TOOL,
                "reject-log",
                f"count_{n}",
                f"total rejects: {value}",
                authority=SourceAuthority.AUTHORITATIVE,
            ),
            prop,
            f"R-test-{n}",
        )

    observe(1184, 1)
    observe("1184", 2)
    assert len(ctx.problem.conflicts) == conflicts
    assert not ctx.events.of_type(EventType.PROBLEM_INVALIDATED)


def test_define_gate_authority_block_triggers_bounded_document_recheck() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]  # contract only: the gate is decided by the Human
    original = handlers["interpret_evidence"]
    rechecks: list[dict[str, Any]] = []

    def forgetful(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = original(req, data)
        if data["observation"]["source"] == "carrier-contract":
            if "define_gate_findings" in data:
                rechecks.append(data)
            else:
                out["authorization_candidates"] = []  # first reading misses the grant (RV-2 C-01 pattern)
        return out

    handlers["interpret_evidence"] = forgetful
    orch, result, _, person = run(public, world, handlers, human=["왜 지금 승인해야 해?", "승인합니다"])
    ev = orch.ctx.events
    assert len(rechecks) == 1 and rechecks[0]["observation"]["already_committed_as"]
    assert any(a.action == "push_pickup_schedule" for a in orch.ctx.problem.domain_authorizations.values())
    assert (
        len(ev.of_type(EventType.PROTECTED_ACTION_EXECUTED)) == 1
    )  # gate → REQUEST_CONTEXT → APPROVE → once
    assert ev.of_type(EventType.HUMAN_CONTEXT_REQUESTED)
    assert result.release_decision is not None


def test_authority_recheck_is_bounded_and_never_grants_without_document() -> None:
    public, world, handlers, _ = scenario_d()
    world["inbox"] = world["inbox"][:1]
    original = handlers["interpret_evidence"]
    calls: list[int] = []

    def never(req: Any, data: dict[str, Any]) -> dict[str, Any]:
        out = original(req, data)
        if data["observation"]["source"] == "carrier-contract":
            calls.append(1)
            out["authorization_candidates"] = []
        return out

    handlers["interpret_evidence"] = never
    orch, result, _, _ = run(public, world, handlers, human=["승인합니다"] * 3)
    assert len(calls) == 2  # first reading + exactly one recheck
    assert not orch.ctx.problem.domain_authorizations
    assert not orch.ctx.events.of_type(EventType.PROTECTED_ACTION_EXECUTED)

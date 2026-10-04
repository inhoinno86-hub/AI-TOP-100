"""Scenario loader / CLI / Contest Adapter boundary."""

from __future__ import annotations

from pathlib import Path

from builders import grant, make_ctx, seed_org, tool_evidence

from aitop_harness.adapters.base import SubmissionExecutor
from aitop_harness.adapters.local import LocalDirectoryAdapter
from aitop_harness.cli import main
from aitop_harness.core.enums import HumanDecisionKind, ProtectedActionCategory, Reversibility
from aitop_harness.core.scope import Scope, ScopeItem
from aitop_harness.phases.discover import integrate_evidence
from aitop_harness.phases.human_gate import GateStatus, HumanDecision, decide, propose_protected_action
from aitop_harness.scenario import load_context
from aitop_harness.state.runtime import ProtectedActionProposal

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "rehearsal_scenario.json"


def test_cli_runs_example_scenario(capsys):
    assert main(["slice", str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "DEFINE Gate: PASS" in out and "RELEASE_WITH_KNOWN_LIMITATION" in out


def test_scenario_loader_builds_typed_problem_state():
    import json

    ctx = load_context(json.loads(EXAMPLE.read_text()))
    h = ctx.problem.process_handoffs["H-1"]
    assert h.semantic_validity.value == "BROKEN" and h.delivery_status.value == "HEALTHY"
    assert ctx.problem.metrics["M-1"].profile.value == "EXTENDED"
    assert ctx.problem.canonical_mappings == {}  # lazy: not needed in this scenario


def test_submission_goes_through_mandatory_human_gate(tmp_path):
    adapter = LocalDirectoryAdapter(EXAMPLE, tmp_path)
    pkg = adapter.package({"result.json": "{}"})
    executor = SubmissionExecutor(adapter, pkg)
    ctx = make_ctx()
    seed_org(ctx)
    integrate_evidence(ctx, tool_evidence("E-rules", "contest rules allow one submission per team"))
    grant(ctx, "DA-SUB", "submit", "contest", Scope.of(("submit", "package")), "E-rules")
    proposal = ProtectedActionProposal(
        "SUB-1",
        "submit",
        "final package",
        "contest",
        [ScopeItem("submit", "package")],
        ProtectedActionCategory.SUBMISSION_PUBLISH,
        why="release gate passed",
        reversibility=Reversibility.IRREVERSIBLE,
        idempotency_key="team-final",
        key_evidence=["E-rules"],
    )
    assert propose_protected_action(ctx, proposal, executor).status is GateStatus.WAITING_APPROVAL
    assert not (tmp_path / "submissions").exists()  # nothing submitted before approval
    out = decide(ctx, HumanDecision(HumanDecisionKind.APPROVE), executor)
    assert out.status is GateStatus.EXECUTED and out.action_record.read_back_verified
    assert (tmp_path / "submissions" / "team-final" / "result.json").exists()

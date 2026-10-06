"""Mock #6 Scenario Controller.

Owns tool behaviour, stakeholder responses and the evidence schedule. It never reads the sealed
hidden ground truth. The late authoritative evidence (MDMS export) is physically unavailable until
``provision_mdms`` is called, and that call refuses to run before the Phase-1 checkpoint
(canonical Problem v1 ACTIVE + at least one downstream dependency) — Mock #6 prompt §13.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aitop_harness.core.enums import (
    DefineGateResult,
    EvidenceSourceType,
    ProblemDefinitionStatus,
    ResultStatus,
    SourceAuthority,
)
from aitop_harness.core.provenance import Provenance
from aitop_harness.domain.epistemic import Evidence
from aitop_harness.engine.context import HarnessContext
from aitop_harness.tools.base import ToolRegistry, ToolResult, ToolSpec
from aitop_harness.tools.simulated import ScriptedTool

AUTH = SourceAuthority.AUTHORITATIVE


def _ok(records: list[dict[str, Any]], cost: float = 3.0, **kw: Any) -> ToolResult:
    kw.setdefault("expected_count", len(records))
    kw.setdefault("pagination_complete", True)
    return ToolResult(ResultStatus.SUCCESS, records=records, source_authority=AUTH, time_cost=cost, **kw)


def _affected_accounts() -> list[dict[str, Any]]:
    rows = []
    for i in range(1184):
        rows.append(
            {
                "account_id": f"AC-{10000 + i}",
                "firmware": "v4.2",
                "ami_read_ts": f"2026-09-{(i % 27) + 1:02d}T02:{i % 60:02d}:00",
                "import_status": "REJECTED_HIGH_CONSUMPTION",
                "bill_read_type": "ESTIMATED",
            }
        )
    return rows


@dataclass
class MdmsTool:
    """Read-only MDMS export. ACCESS_PENDING until the vendor provisions access."""

    controller: ScenarioController
    tool_id: str = "mdms-export"
    read_only: bool = True
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def call(self, operation: str, params: dict[str, Any]) -> ToolResult:
        self.calls.append((operation, dict(params)))
        if not self.controller.mdms_provisioned:
            return ToolResult(
                ResultStatus.ERROR,
                error_class="ACCESS_PENDING",
                retryable_hint=False,
                time_cost=1.0,
                message="export access not provisioned by vendor",
            )
        if operation == "read_events_for_disputed_estimated":
            return _ok(
                [
                    {"ami_read_before_cutoff": True, "exported_to_billing": True, "billing_import_status":
                     "REJECTED_HIGH_CONSUMPTION", "firmware": "v4.2", "read_channel": "AMI", "count": 1184},
                    {"ami_read_before_cutoff": False, "exported_to_billing": False, "billing_import_status":
                     "NO_READ_RECEIVED", "firmware": "mixed", "read_channel": "AMI", "count": 56},
                ],
                cost=4.0,
                coverage_period="2026-08..2026-09",
                required_coverage_period="2026-08..2026-09",
            )
        if operation == "meter_firmware_units":
            return _ok(
                [
                    {"firmware": "v4.2", "register_unit": "0.1 m3", "rollout": "2026-06"},
                    {"firmware": "v3.x", "register_unit": "m3"},
                ],
                cost=2.0,
            )
        if operation == "reads_for_accounts":
            return _ok(_affected_accounts(), cost=5.0)
        return ToolResult(ResultStatus.ERROR, error_class="UNSUPPORTED_OPERATION", retryable_hint=False)


class ScenarioController:
    def __init__(self) -> None:
        self.mdms_provisioned = False
        self.provisioned_at_minute: float | None = None
        self.mdms = MdmsTool(self)
        self.dispatch = ScriptedTool(
            "field-dispatch",
            read_only=False,
            script={"push_route_update": [ToolResult(ResultStatus.SUCCESS, is_mutation=True, time_cost=1.0)]},
        )

    # ------------------------------------------------------------------ tools

    def registry(self) -> ToolRegistry:
        reg = ToolRegistry()
        billing = ScriptedTool(
            "billing-db",
            script={
                "disputed_bills_by_read_type": [
                    _ok([{"read_type": "ESTIMATED", "count": 1240}, {"read_type": "ACTUAL", "count": 1785}])
                ],
                "tariff_change_log": [_ok([], cost=1.0, expected_count=0)],
                "accounts_estimated_last_cycle": [
                    _ok([{"account_id": f"AC-{20000 + i}", "route": f"R-{i % 40:02d}"} for i in range(320)])
                ],
                "import_status_estimated_disputed": [
                    _ok(
                        [
                            {"import_status": "REJECTED_HIGH_CONSUMPTION", "firmware": "v4.2", "count": 1184},
                            {"import_status": "NO_READ_RECEIVED", "firmware": "mixed", "count": 56},
                        ]
                    )
                ],
                "affected_accounts_v42": [_ok(_affected_accounts(), cost=5.0)],
            },
        )
        crm = ScriptedTool(
            "crm-tickets",
            script={
                "dispute_volume_monthly": [
                    _ok(
                        [
                            {"month": "2026-06", "disputes": 610},
                            {"month": "2026-07", "disputes": 590},
                            {"month": "2026-08", "disputes": 1180},
                            {"month": "2026-09", "disputes": 1260},
                        ]
                    )
                ],
                "dispute_response_times": [
                    _ok([{"median_days": 1.6, "p90_days": 2.8, "sla_days": 3.0, "tickets": 2440}])
                ],
            },
        )
        route = ScriptedTool(
            "route-log",
            script={
                "route_completion_aug_sep": [
                    _ok([{"period": "2026-08..09", "completion": 0.88, "target": 0.95, "manual_read_accounts": 9200}])
                ],
                "lagging_routes": [
                    _ok([{"route": f"R-{i:02d}", "completion": 0.70 + i / 100} for i in range(14)])
                ],
            },
        )
        config = ScriptedTool(
            "billing-config",
            script={
                "validation_rule_changes": [
                    _ok(
                        [
                            {"rule": "BV-17", "deployed": "2026-08-01",
                             "change": "high-consumption check compares raw register value with 12-month m3 history",
                             "unit_scaling": "none"},
                            {"rule": "BV-09", "deployed": "2026-03-02", "change": "label text"},
                        ]
                    )
                ]
            },
        )
        for tool, dep in ((billing, "billing"), (crm, "crm"), (route, "fieldco"), (config, "billing")):
            reg.register(tool, ToolSpec(tool.tool_id, dep, True, AUTH))
        reg.register(self.mdms, ToolSpec("mdms-export", "telemetrix", True, AUTH))
        reg.register(self.dispatch, ToolSpec("field-dispatch", "fieldco", False, AUTH))
        return reg

    # ------------------------------------------------------------------ stakeholders

    STAKEHOLDER_ANSWERS = {
        "SH-CS": "Customers wait too long for answers on disputes; an agent that answers instantly would fix it.",
        "SH-FIELD": "We are short three readers since July; routes run late, so those customers get estimated bills.",
        "SH-BILL": "There has been no tariff change this year.",
    }

    def interview(self, stakeholder_id: str) -> str:
        return self.STAKEHOLDER_ANSWERS[stakeholder_id]

    def contract_document(self) -> Evidence:
        return Evidence(
            id="E-CONTRACT",
            source_type=EvidenceSourceType.DOCUMENT,
            source_id="fieldco-service-contract",
            provenance=Provenance(EvidenceSourceType.DOCUMENT, "fieldco-service-contract", method="document review"),
            content="Service contract §4.2: utility may request route priority changes; executed after Field "
            "Operations Manager confirmation.",
            authority=AUTH,
        )

    # ------------------------------------------------------------------ late evidence gate

    def phase1_checkpoint(self, ctx: HarnessContext) -> dict[str, Any]:
        pd = ctx.problem.problem_definition
        downstream = {
            "solution_design": ctx.problem.solution_design is not None,
            "agent_spec": ctx.problem.agent_spec is not None,
            "vobs": sorted(ctx.problem.verification_obligations),
            "success_criteria": list(pd.success_criteria) if pd else [],
            "plan": ctx.runtime.current_plan.id if ctx.runtime.current_plan else None,
        }
        ok = (
            pd is not None
            and pd.status is ProblemDefinitionStatus.ACTIVE
            and pd.gate_result in (DefineGateResult.PASS, DefineGateResult.CONDITIONAL_PASS)
            and (downstream["solution_design"] or downstream["agent_spec"] or bool(downstream["vobs"]))
        )
        return {"ok": ok, "problem": f"{pd.id} v{pd.version} {pd.status.value}" if pd else None, **downstream}

    def provision_mdms(self, ctx: HarnessContext) -> str:
        cp = self.phase1_checkpoint(ctx)
        if not cp["ok"]:
            raise RuntimeError(f"late evidence refused: Phase-1 checkpoint not reached: {cp}")
        self.mdms_provisioned = True
        self.provisioned_at_minute = ctx.clock.now()
        return "MDMS export access for Lakeside is provisioned as of today (vendor ticket TX-4471)."

    # ------------------------------------------------------------------ probe-only decoy (replan-type evidence)

    @staticmethod
    def dispatch_api_notice() -> Evidence:
        """Authoritative but PATH-only evidence: invalidates how routes are pushed, not the Problem."""
        return Evidence(
            id="E-DISPATCH-API",
            source_type=EvidenceSourceType.DOCUMENT,
            source_id="fieldco-api-notice",
            provenance=Provenance(EvidenceSourceType.DOCUMENT, "fieldco-api-notice", method="vendor notice"),
            content="Field dispatch API notice: v2 route endpoint retired 10-01; route pushes must use v3.",
            target_assertion="dispatch.route_endpoint",
            value="v3",
            authority=AUTH,
        )

"""Golden autonomous scenarios (prompt §29) driven by the deterministic FakeProvider (prompt §28).

Each scenario = PUBLIC scenario (the only thing loaded into the Harness) + a simulated WORLD (tools,
stakeholder answers, inbox, catalog) + fake REASONING handlers (input pattern → structured proposal).
The fake handlers read only the request input (the detached state view), exactly like a real model.
Nothing here is passed to the Harness as Problem / design / revision content.
"""

from __future__ import annotations

from typing import Any

from aitop_harness.engine.autonomous import AutonomousConfig, AutonomousOrchestrator
from aitop_harness.engine.environment import ScenarioEnvironment, ScriptedHuman
from aitop_harness.reasoning.interface import ReasoningRequest
from aitop_harness.reasoning.providers.fake import FakeProvider
from aitop_harness.reasoning.reasoner import Reasoner
from aitop_harness.scenario import load_context

AUTH = "AUTHORITATIVE"


def ok(records: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return {
        "status": "SUCCESS",
        "records": records,
        "expected_count": len(records),
        "pagination_complete": True,
        "source_authority": AUTH,
        "time_cost": 2.0,
        **kw,
    }


def ev_by(state: dict[str, Any], *, source: str, method: str | None = None) -> str:
    for eid, e in state["evidence"].items():
        if e["source"] == source and (method is None or e["method"] == method):
            return eid
    raise KeyError(f"no evidence from {source}/{method}")


def h_by(state: dict[str, Any], word: str) -> str:
    return next(h for h, x in state["hypotheses"].items() if word in h)


def none_assessment() -> dict[str, Any]:
    return {
        "relation": "UNRELATED",
        "target_type": "NONE",
        "target_refs": [],
        "materiality": "LOW",
        "problem_invalidating": False,
        "rationale": "no canonical problem yet",
    }


def interp(
    text: str,
    *,
    key: str = "",
    value: Any = "",
    effects: list[tuple[str, str]] | None = None,
    claim: tuple[str, Any] | None = None,
    assessment: dict[str, Any] | None = None,
    follow: list[str] | None = None,
    auth: list[dict[str, Any]] | None = None,
    new: list[dict[str, Any]] | None = None,
    facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "interpretation": text,
        "hypothesis_effects": [
            {"hypothesis": h, "effect": e, "rationale": "fixture"} for h, e in effects or []
        ],
        "new_hypotheses": new or [],
        "fact_candidates": facts or [],
        "unknown_resolutions": [],
        "authorization_candidates": auth or [],
        "contradiction_assessment": assessment or none_assessment(),
        "vob_proposals": [],
        "follow_up_actions": follow or [],
        "confidence": 0.8,
    }
    if key:
        out["assertion_key"], out["assertion_value"] = key, value
    if claim:
        out["claim_assertion_key"], out["claim_assertion_value"] = claim
    return out


def action(
    ref: str,
    di: float,
    *,
    hyps: list[str] | None = None,
    addresses: list[str] | None = None,
    cost: float = 3.0,
) -> dict[str, Any]:
    return {
        "catalog_ref": ref,
        "question": f"what does {ref} show?",
        "decision_impact": di,
        "uncertainty": 0.6,
        "discriminative_power": 0.7,
        "answerability": 0.9,
        "process_data_handoff_impact": 0.4,
        "action_proximity": 0.3,
        "constraint_risk": 0.0,
        "estimated_cost_minutes": cost,
        "expected_information_gain": "fixture",
        "decision_impact_rationale": "fixture",
        "discriminates_hypotheses": hyps or [],
        "resolves_unknowns": [],
        "addresses": addresses or [],
        "why_now": "fixture",
    }


def scope(action_: str, target: str) -> dict[str, str]:
    return {"action": action_, "target": target}


def run(
    public: dict[str, Any],
    world: dict[str, Any],
    handlers: dict[str, Any],
    *,
    human: list[str | None] | None = None,
    config: AutonomousConfig | None = None,
) -> tuple[AutonomousOrchestrator, Any, FakeProvider, ScriptedHuman]:
    ctx = load_context({k: public[k] for k in ("scenario", "problem")})
    env = ScenarioEnvironment(world)
    provider = FakeProvider(handlers)
    reasoner = Reasoner(provider)
    person = ScriptedHuman(list(human or []))
    notes = {k: v for k, v in public.items() if k not in ("scenario", "problem")}
    orch = AutonomousOrchestrator(ctx, env, reasoner, person, public_notes=notes, config=config)
    result = orch.run()
    return orch, result, provider, person


# =========================================================================== Scenario A — simple, correct


def scenario_a() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    public = {
        "scenario": {
            "id": "A-REJECTS",
            "title": "Carrier rejects shipment notices",
            "initial_request": "Let an AI agent auto-fix rejected shipment notices and resubmit them",
            "requested_by": "SH-REQ",
        },
        "problem": {
            "organizations": {
                "ORG-A": {"id": "ORG-A", "name": "Shipper"},
                "ORG-B": {"id": "ORG-B", "name": "Carrier"},
            },
            "stakeholders": {
                "SH-REQ": {"id": "SH-REQ", "organization_id": "ORG-A", "role": "operations manager"},
                "SH-INT": {"id": "SH-INT", "organization_id": "ORG-B", "role": "interface owner"},
            },
            "processes": {
                "P-1": {
                    "id": "P-1",
                    "name": "shipment notice",
                    "organization_ids": ["ORG-A", "ORG-B"],
                    "handoff_ids": ["H-1"],
                }
            },
            "process_handoffs": {
                "H-1": {
                    "id": "H-1",
                    "process_id": "P-1",
                    "from_org": "ORG-A",
                    "to_org": "ORG-B",
                    "delivery_status": "HEALTHY",
                    "semantic_validity": "VALID",
                }
            },
            "data_assets": {
                "DA-REJ": {
                    "id": "DA-REJ",
                    "name": "carrier reject log",
                    "organization_id": "ORG-B",
                    "source": "reject-log",
                    "authority": AUTH,
                }
            },
        },
        "tool_surface": [
            {"tool_id": "reject-log", "read_only": True, "describes": "carrier business rejects"}
        ],
    }
    world = {
        "tools": [
            {
                "tool_id": "reject-log",
                "dependency": "carrier-api",
                "authority": AUTH,
                "describes": "carrier business rejects",
                "script": {
                    "rejects_by_reason": [
                        ok(
                            [
                                {"notice": "N-1", "reason": "LOC_UNKNOWN"},
                                {"notice": "N-2", "reason": "LOC_UNKNOWN"},
                                {"notice": "N-3", "reason": "EVENT_ORDER"},
                            ]
                        )
                    ]
                },
            }
        ],
        "interviews": {"SH-REQ": "The carrier system is flaky; just resubmit everything."},
    }

    def define(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        e_log = ev_by(st, source="reject-log")
        return {
            "root_problem": "Shipment notices are business-rejected: location codes and event ordering "
            "violate the carrier interface contract (2 of 3 rejects LOC_UNKNOWN).",
            "requested_solution": "AI agent auto-fixes and resubmits rejected notices",
            "symptoms": ["notices rejected after transport ACK"],
            "affected_process": "P-1",
            "causal_chain": ["sender uses unmapped location codes", "carrier validation rejects notice"],
            "premise_hypotheses": [h_by(st, "CONTRACT")],
            "evidence_refs": [e_log],
            "assumptions": [],
            "unknowns": [],
            "metrics": [
                {
                    "key": "REJECT_RATE",
                    "name": "business reject rate",
                    "metric_type": "RATE",
                    "numerator": "business rejects",
                    "denominator": "transport-accepted notices",
                    "owner": "ORG-A",
                    "target_value": 0.01,
                }
            ],
            "success_criteria": [
                {
                    "key": "REJECT_RATE",
                    "statement": "reject cause classified for every reject",
                    "kind": "MUST",
                    "metric": "REJECT_RATE",
                    "threshold": "100%",
                    "validation_method": "replay last week's rejects",
                }
            ],
            "intended_scope": [scope("detect_reject_cause", "H-1")],
            "protected_actions": [],
            "required_tools": ["reject-log"],
            "depends_on_handoffs": [],
            "constraint_refs": [],
            "rejected_framings": [
                {"hypothesis": h_by(st, "FLAKY"), "why": "reject log shows contract violations"}
            ],
            "confidence": 0.8,
        }

    handlers = {
        "hypothesis_init": {
            "framing_assertion": {"key": "reject.cause", "value": "carrier_flaky", "rationale": "request"},
            "hypotheses": [
                {
                    "key": "FLAKY",
                    "statement": "carrier system is flaky",
                    "origin": "REQUESTER_FRAMING",
                    "decision_impact": "MEDIUM",
                    "rationale": "requester",
                    "discriminating_evidence": ["reject log"],
                },
                {
                    "key": "CONTRACT",
                    "statement": "interface contract violations cause rejects",
                    "origin": "ALTERNATIVE",
                    "decision_impact": "HIGH",
                    "rationale": "rejects are business-level",
                    "discriminating_evidence": ["reject reasons"],
                },
            ],
            "confidence": 0.7,
        },
        "discover_actions": lambda req, data: {
            "actions": [
                action("reject-log:rejects_by_reason", 0.9, hyps=list(data["state"]["hypotheses"])),
                action("interview:SH-REQ", 0.3),
            ],
            "stop": False,
            "stop_reason": "",
        },
        "interpret_evidence": lambda req, data: (
            interp(
                "2 of 3 rejects are unknown location codes: interface contract problem",
                key="reject.cause",
                value="interface_contract",
                effects=[
                    (h_by(data["state"], "FLAKY"), "CONTRADICTS"),
                    (h_by(data["state"], "CONTRACT"), "SUPPORTS"),
                ],
            )
            if data["observation"]["source"] == "reject-log"
            else interp(
                "requester believes the carrier is flaky",
                claim=("reject.cause", "carrier_flaky"),
                effects=[(h_by(data["state"], "FLAKY"), "SUPPORTS")],
            )
        ),
        "assess_hypotheses": lambda req, data: {
            "updates": [
                {
                    "hypothesis": h_by(data["state"], "CONTRACT"),
                    "status": "SUPPORTED",
                    "rationale": "log",
                    "evidence_refs": [ev_by(data["state"], source="reject-log")],
                },
                {
                    "hypothesis": h_by(data["state"], "FLAKY"),
                    "status": "REJECTED",
                    "rationale": "log contradicts",
                    "evidence_refs": [ev_by(data["state"], source="reject-log")],
                },
            ],
            "ready_to_define": True,
            "rationale": "fixture",
        },
        "define_problem": define,
        "structural_remedy": {
            "root_cause": "contract mismatch",
            "remedies": [
                {
                    "key": "CONTRACT_V2",
                    "description": "versioned location / event contract",
                    "removes_root_cause": True,
                    "feasible_in_contest_time": False,
                    "constraint_feasible": True,
                    "feasibility_rationale": "partner release cycle",
                    "residual_gap": "legacy notices",
                }
            ],
            "why_agent_needed": "classify rejects until the contract lands",
            "confidence": 0.7,
        },
        "agent_design": {
            "deterministic_rules_cover_cases": True,
            "llm_reasoning_adds_value": True,
            "autonomous_iteration_adds_value": False,
            "residual_exceptions": True,
            "detection_needed": True,
            "why_agent": "explain ambiguous rejects",
            "bridge_sunset_condition": "contract v2 adopted",
            "deterministic_components": ["reason-code classifier"],
            "release_scope": [scope("detect_reject_cause", "H-1")],
            "minimum_useful_scope": [scope("detect_reject_cause", "H-1")],
            "scope_dependencies": [{"action": "detect_reject_cause", "depends_on": ["DA-REJ"]}],
            "role_suggestion": ["BRIDGE"],
            "capabilities": ["classify rejects"],
            "llm_required_for": [],
            "tools": ["reject-log"],
            "authority_boundary": ["read-only"],
            "human_gate": [],
            "termination": "single pass",
            "validation": ["replay"],
            "known_limitations": [],
            "vob_proposals": [],
            "confidence": 0.7,
        },
        "plan_execution": {
            "work_items": [
                {
                    "key": "CLASSIFY",
                    "description": "classify reject causes",
                    "work_class": "CORE_FEATURE",
                    "est_minutes": 20,
                    "scope_items": [scope("detect_reject_cause", "H-1")],
                    "root_problem_aligned": True,
                    "release_blocking": True,
                    "data_ops": ["reject-log:rejects_by_reason"],
                    "output_name": "reject_causes",
                    "output_key_fields": ["notice"],
                    "output_join": False,
                    "output_constant_fields": [],
                }
            ],
            "protected_actions": [],
            "rationale": "fixture",
        },
        "semantic_judge": {
            "checks": [{"name": "root_alignment", "status": "PASS", "detail": "ok", "refs": []}]
        },
        "release_summary": {"summary": "released", "key_points": [], "limitations_explained": []},
    }
    return public, world, handlers


# =========================================================================== shared fixture pieces


def _remedy(feasible: bool = False) -> dict[str, Any]:
    return {
        "root_cause": "fixture root cause",
        "remedies": [
            {
                "key": "FIX",
                "description": "structural fix of the root cause",
                "removes_root_cause": True,
                "feasible_in_contest_time": feasible,
                "constraint_feasible": True,
                "feasibility_rationale": "fixture",
                "residual_gap": "",
            }
        ],
        "why_agent_needed": "" if feasible else "bridge until the fix lands",
        "confidence": 0.7,
    }


def _agent(
    release: list[dict[str, str]],
    deps: dict[str, list[str]],
    *,
    gate: list[str] | None = None,
    tools: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "deterministic_rules_cover_cases": True,
        "llm_reasoning_adds_value": True,
        "autonomous_iteration_adds_value": False,
        "residual_exceptions": True,
        "detection_needed": True,
        "why_agent": "explain exceptions",
        "bridge_sunset_condition": "structural fix deployed",
        "deterministic_components": ["rule-based detector"],
        "release_scope": release,
        "minimum_useful_scope": release[:1],
        "scope_dependencies": [{"action": a, "depends_on": d} for a, d in deps.items()],
        "role_suggestion": [],
        "capabilities": ["detect"],
        "llm_required_for": ["explanations"],
        "tools": tools or [],
        "authority_boundary": ["read-only except gated actions"],
        "human_gate": gate or [],
        "termination": "single pass",
        "validation": ["replay"],
        "known_limitations": [],
        "vob_proposals": [],
        "confidence": 0.7,
    }


def _metric(key: str = "RATE") -> dict[str, Any]:
    return {
        "key": key,
        "name": "share of affected cases",
        "metric_type": "RATE",
        "numerator": "affected cases",
        "denominator": "all cases",
        "owner": "ORG-1",
        "target_value": 0.05,
    }


def _sc(key: str = "RATE", kind: str = "MUST") -> dict[str, Any]:
    return {
        "key": key,
        "statement": "affected share below 5% next cycle",
        "kind": kind,
        "metric": "RATE",
        "threshold": "< 0.05",
        "validation_method": "next-cycle extract",
    }


def _judge(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [{"name": "root_alignment", "status": "PASS", "detail": "fixture", "refs": []}]}


_SUMMARY = {"summary": "fixture summary", "key_points": [], "limitations_explained": []}


# ============================================================ Scenario B — misleading request


def scenario_b() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    public = {
        "scenario": {
            "id": "B-CHATBOT",
            "title": "Support backlog",
            "initial_request": "Build a chatbot so customers stop waiting for answers about refunds",
            "requested_by": "SH-SUP",
        },
        "problem": {
            "organizations": {"ORG-1": {"id": "ORG-1", "name": "Retailer"}},
            "stakeholders": {
                "SH-SUP": {
                    "id": "SH-SUP",
                    "organization_id": "ORG-1",
                    "role": "support lead",
                    "potential_bias": ["frames everything as response speed"],
                }
            },
            "processes": {"P-REF": {"id": "P-REF", "name": "refund", "organization_ids": ["ORG-1"]}},
            "data_assets": {
                "DA-TCK": {
                    "id": "DA-TCK",
                    "name": "tickets",
                    "organization_id": "ORG-1",
                    "source": "ticket-db",
                    "authority": AUTH,
                },
                "DA-PAY": {
                    "id": "DA-PAY",
                    "name": "refund payments",
                    "organization_id": "ORG-1",
                    "source": "payment-db",
                    "authority": AUTH,
                },
            },
        },
        "tool_surface": [
            {"tool_id": "ticket-db", "read_only": True, "describes": "tickets + response times"},
            {"tool_id": "payment-db", "read_only": True, "describes": "refund payments"},
        ],
    }
    world = {
        "tools": [
            {
                "tool_id": "ticket-db",
                "authority": AUTH,
                "script": {"response_times": [ok([{"median_hours": 2.0, "sla_hours": 24, "tickets": 900}])]},
            },
            {
                "tool_id": "payment-db",
                "authority": AUTH,
                "script": {
                    "refund_failures": [
                        ok([{"refund": f"R-{i}", "status": "FAILED_IBAN_FORMAT"} for i in range(5)])
                    ]
                },
            },
        ],
        "interviews": {"SH-SUP": "Customers wait forever; a chatbot would answer instantly."},
    }
    calls = {"define": 0}

    def define(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        calls["define"] += 1
        speed = h_by(st, "SPEED")
        pay = h_by(st, "PAYMENT")
        base = {
            "requested_solution": "chatbot",
            "symptoms": ["refund tickets"],
            "affected_process": "P-REF",
            "causal_chain": ["refund payment fails", "customer asks again"],
            "assumptions": [],
            "unknowns": [],
            "metrics": [_metric()],
            "success_criteria": [_sc()],
            "protected_actions": [],
            "required_tools": [],
            "depends_on_handoffs": [],
            "constraint_refs": [],
            "rejected_framings": [],
            "confidence": 0.7,
        }
        if calls["define"] == 1:  # anchored on the requester framing → the Core must refuse it
            return {
                **base,
                "root_problem": "Customers wait too long for answers; support responds too slowly.",
                "premise_hypotheses": [speed],
                "evidence_refs": [ev_by(st, source="SH-SUP")],
                "intended_scope": [scope("answer_tickets", "chatbot")],
            }
        if calls["define"] == 2:  # stakeholder-only evidence → the DEFINE Gate must FAIL it
            return {
                **base,
                "root_problem": "Refund payments fail and customers chase them (per support lead).",
                "premise_hypotheses": [],
                "evidence_refs": [ev_by(st, source="SH-SUP")],
                "intended_scope": [scope("detect_failed_refunds", "DA-PAY")],
            }
        return {
            **base,
            "root_problem": "Refund payments fail on IBAN format validation, so customers chase refunds "
            "through support; response time is within SLA.",
            "premise_hypotheses": [pay],
            "evidence_refs": [ev_by(st, source="payment-db"), ev_by(st, source="ticket-db")],
            "intended_scope": [scope("detect_failed_refunds", "DA-PAY")],
            "rejected_framings": [{"hypothesis": speed, "why": "median response 2h vs 24h SLA"}],
        }

    handlers = {
        "hypothesis_init": {
            "framing_assertion": {"key": "support.too_slow", "value": True, "rationale": "request"},
            "hypotheses": [
                {
                    "key": "SPEED",
                    "statement": "support answers too slowly",
                    "origin": "REQUESTER_FRAMING",
                    "decision_impact": "MEDIUM",
                    "rationale": "request",
                    "discriminating_evidence": [],
                },
                {
                    "key": "PAYMENT",
                    "statement": "refund payments fail",
                    "origin": "ALTERNATIVE",
                    "decision_impact": "HIGH",
                    "rationale": "refund topic",
                    "discriminating_evidence": [],
                },
            ],
            "confidence": 0.6,
        },
        "discover_actions": {
            "actions": [
                action("ticket-db:response_times", 0.8),
                action("payment-db:refund_failures", 0.9),
                action("interview:SH-SUP", 0.3),
            ],
            "stop": False,
            "stop_reason": "",
        },
        "interpret_evidence": lambda req, data: {
            "ticket-db": interp(
                "responses within SLA",
                key="support.too_slow",
                value=False,
                effects=[(h_by(data["state"], "SPEED"), "CONTRADICTS")],
            ),
            "payment-db": interp(
                "all sampled refunds failed IBAN validation",
                key="refund.failure_cause",
                value="iban_format",
                effects=[(h_by(data["state"], "PAYMENT"), "SUPPORTS")],
            ),
            "SH-SUP": interp(
                "support lead blames response speed",
                claim=("support.too_slow", True),
                effects=[(h_by(data["state"], "SPEED"), "SUPPORTS")],
            ),
        }[data["observation"]["source"]],
        "assess_hypotheses": lambda req, data: {
            "updates": [
                {
                    "hypothesis": h_by(data["state"], "SPEED"),
                    "status": "REJECTED",
                    "rationale": "SLA met",
                    "evidence_refs": [ev_by(data["state"], source="ticket-db")],
                },
                {
                    "hypothesis": h_by(data["state"], "PAYMENT"),
                    "status": "SUPPORTED",
                    "rationale": "payment log",
                    "evidence_refs": [ev_by(data["state"], source="payment-db")],
                },
            ],
            "ready_to_define": True,
            "rationale": "x",
        },
        "define_problem": define,
        "structural_remedy": _remedy(feasible=True),
        "agent_design": _agent(
            [scope("detect_failed_refunds", "DA-PAY")], {"detect_failed_refunds": ["DA-PAY"]}
        ),
        "plan_execution": {
            "work_items": [
                {
                    "key": "DETECT",
                    "description": "detect failed refunds",
                    "work_class": "CORE_FEATURE",
                    "est_minutes": 20,
                    "scope_items": [scope("detect_failed_refunds", "DA-PAY")],
                    "root_problem_aligned": True,
                    "release_blocking": True,
                    "data_ops": ["payment-db:refund_failures"],
                    "output_name": "failed_refunds",
                    "output_key_fields": ["refund"],
                    "output_join": False,
                    "output_constant_fields": [],
                }
            ],
            "protected_actions": [],
            "rationale": "x",
        },
        "semantic_judge": _judge,
        "release_summary": _SUMMARY,
    }
    return public, world, handlers


# =========================================================================== Scenario C — tool failure


def scenario_c() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    public, world, handlers = scenario_b()
    public["scenario"]["id"] = "C-TOOLFAIL"
    world["tools"][1]["script"]["refund_failures"] = [
        {"status": "ERROR", "error_class": "TIMEOUT", "retryable_hint": True, "time_cost": 1.0},
        ok([{"refund": f"R-{i}", "status": "FAILED_IBAN_FORMAT"} for i in range(5)]),
    ]
    world["tools"].append(
        {
            "tool_id": "bank-api",
            "authority": AUTH,
            "script": {
                "settlement_status": [
                    {
                        "status": "ERROR",
                        "error_class": "ACCESS_DENIED",
                        "retryable_hint": False,
                        "time_cost": 1.0,
                    }
                ]
            },
        }
    )
    handlers["discover_actions"] = {
        "actions": [
            action("bank-api:settlement_status", 0.9),
            action("ticket-db:response_times", 0.8),
            action("payment-db:refund_failures", 0.85),
            action("interview:SH-SUP", 0.3),
        ],
        "stop": False,
        "stop_reason": "",
    }
    calls = {"n": 0}
    base_define = handlers["define_problem"]

    def define(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        while calls["n"] < 3:  # skip scenario B's deliberately bad first proposals
            calls["n"] += 1
            base_define(req, data)
        return base_define(req, data)

    handlers["define_problem"] = define
    return public, world, handlers


# ============================================================ Scenario D — problem invalidation


def scenario_d() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[str | None]]:
    public = {
        "scenario": {
            "id": "D-LATE-SHIPMENTS",
            "title": "Late shipments",
            "initial_request": "Build a chatbot that tells customers why their parcel is late",
            "requested_by": "SH-CX",
        },
        "problem": {
            "organizations": {
                "ORG-1": {"id": "ORG-1", "name": "Shop", "data_assets": ["DA-ORD", "DA-WMS"]},
                "ORG-CAR": {"id": "ORG-CAR", "name": "Carrier", "data_assets": ["DA-PICK"]},
            },
            "stakeholders": {
                "SH-CX": {
                    "id": "SH-CX",
                    "organization_id": "ORG-1",
                    "role": "customer experience (requester)",
                },
                "SH-LOG": {"id": "SH-LOG", "organization_id": "ORG-1", "role": "logistics lead"},
                "SH-CAR": {"id": "SH-CAR", "organization_id": "ORG-CAR", "role": "carrier account manager"},
                "SH-WMS": {"id": "SH-WMS", "organization_id": "ORG-1", "role": "warehouse systems admin"},
            },
            "processes": {
                "P-SHIP": {
                    "id": "P-SHIP",
                    "name": "order to delivery",
                    "organization_ids": ["ORG-1", "ORG-CAR"],
                    "handoff_ids": ["H-PICK"],
                }
            },
            "process_handoffs": {
                "H-PICK": {
                    "id": "H-PICK",
                    "process_id": "P-SHIP",
                    "from_org": "ORG-1",
                    "to_org": "ORG-CAR",
                    "payload": "parcels",
                    "delivery_status": "UNKNOWN",
                    "semantic_validity": "UNKNOWN",
                }
            },
            "data_assets": {
                "DA-ORD": {
                    "id": "DA-ORD",
                    "name": "orders",
                    "organization_id": "ORG-1",
                    "source": "order-db",
                    "authority": AUTH,
                },
                "DA-PICK": {
                    "id": "DA-PICK",
                    "name": "pickup log",
                    "organization_id": "ORG-CAR",
                    "source": "pickup-log",
                    "authority": AUTH,
                },
                "DA-WMS": {
                    "id": "DA-WMS",
                    "name": "warehouse job log",
                    "organization_id": "ORG-1",
                    "source": "wms-jobs",
                    "authority": AUTH,
                },
            },
            "constraints": {
                "K-SCHED": {
                    "id": "K-SCHED",
                    "type": "HUMAN_APPROVAL",
                    "description": "pickup schedule changes need carrier confirmation",
                    "actor": "SH-CAR",
                    "protected_action": "push_pickup_schedule",
                    "approval_required": True,
                    "runtime_confirmation_required": True,
                }
            },
        },
        "tool_surface": [
            {"tool_id": t, "read_only": t != "pickup-sched", "describes": t}
            for t in ("order-db", "pickup-log", "wms-jobs", "pickup-sched")
        ],
    }
    world = {
        "tools": [
            {
                "tool_id": "order-db",
                "authority": AUTH,
                "script": {
                    "late_orders_by_stage": [ok([{"stage": "handover", "late": 300, "orders": 1000}])],
                    "orders_released_late": [
                        ok([{"order": f"O-{i}", "released_late": True} for i in range(30)])
                    ],
                },
            },
            {
                "tool_id": "pickup-log",
                "authority": AUTH,
                "script": {
                    "pickup_delays": [ok([{"median_delay_h": 2.0, "pickups": 60}])],
                    "pickup_by_slot": [ok([{"slot": f"S-{i}", "delay_h": 2.0} for i in range(6)])],
                },
            },
            {
                "tool_id": "wms-jobs",
                "authority": AUTH,
                "script": {
                    "release_batch_runs": [
                        {
                            "status": "ERROR",
                            "error_class": "ACCESS_PENDING",
                            "retryable_hint": False,
                            "time_cost": 1.0,
                        },
                        ok(
                            [
                                {
                                    "job": "RELEASE-BATCH",
                                    "failed_runs": 21,
                                    "runs": 30,
                                    "orders_released_after_pickup": 290,
                                }
                            ]
                        ),
                    ],
                    "batch_job_config": [
                        ok([{"job": "RELEASE-BATCH", "changed": "2026-08-01", "timeout_s": 30}])
                    ],
                },
            },
            {
                "tool_id": "pickup-sched",
                "read_only": False,
                "authority": AUTH,
                "script": {"push_pickup_schedule": [{"status": "SUCCESS", "is_mutation": True}]},
            },
        ],
        "interviews": {
            "SH-LOG": "The carrier picks up two hours late, that's why parcels are late.",
            "SH-CX": "Customers want to know where their parcel is.",
        },
        "inbox": [
            {
                "when": {"phase": "DEFINE"},
                "input": {
                    "source_type": "DOCUMENT",
                    "source_id": "carrier-contract",
                    "authority": AUTH,
                    "method": "document",
                    "content": "Carrier contract §3: pickup schedule changes run after SH-CAR confirms.",
                },
            },
            {
                "when": {"phase": "EXECUTE", "problem_version": 1, "waiting_approval": True},
                "input": {
                    "source_type": "STAKEHOLDER",
                    "source_id": "SH-WMS",
                    "method": "message",
                    "content": "WMS job log access is now granted.",
                },
            },
        ],
        "catalog": {
            "discover": [
                "order-db:late_orders_by_stage",
                "pickup-log:pickup_delays",
                "wms-jobs:release_batch_runs",
                "interview:SH-LOG",
            ],
            "reprofile": ["wms-jobs:batch_job_config"],
            "execute@v1": ["pickup-log:pickup_by_slot"],
            "execute@v2": ["order-db:orders_released_late"],
        },
    }

    def version(st: dict[str, Any]) -> int:
        pd = st.get("problem_definition")
        prev = st.get("previous_problem")
        if pd and pd["status"] != "INVALIDATED":
            return pd["version"]
        return 2 if prev or (pd and pd["status"] == "INVALIDATED") else 1

    def interpret(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st, src = data["state"], data["observation"]["source"]
        pickup = h_by(st, "PICKUP")
        if src == "order-db":
            if "orders_released_late" in data["observation"]["content"]:
                return interp("30 orders released late", key="orders.released_late_count", value=30)
            return interp(
                "30% of orders are late at handover",
                key="late.stage",
                value="handover",
                effects=[(pickup, "SUPPORTS")],
            )
        if src == "pickup-log":
            return interp(
                "pickups run 2h late", key="pickup.median_delay_h", value=2.0, effects=[(pickup, "SUPPORTS")]
            )
        if src == "SH-LOG":
            return interp(
                "logistics blames carrier pickups",
                claim=("late.cause", "carrier_pickup"),
                effects=[(pickup, "SUPPORTS")],
            )
        if src == "carrier-contract":
            return interp(
                "contract grants schedule change after SH-CAR confirmation",
                auth=[
                    {
                        "action": "push_pickup_schedule",
                        "resource": "pickup-sched",
                        "authority_holder": "SH-CAR",
                        "scope_target": "*",
                        "conditions": ["SH-CAR confirms"],
                        "rationale": "contract §3",
                    }
                ],
            )
        if src == "SH-WMS":
            return interp(
                "WMS access granted; deferred job-log query can run", follow=["wms-jobs:release_batch_runs"]
            )
        if src == "wms-jobs" and "failed_runs" in data["observation"]["content"]:
            pd = st.get("problem_definition") or {}
            return interp(
                "the release batch job failed in 21 of 30 runs; 290 orders were released after the pickup: "
                "parcels miss the pickup because they are not released, not because the carrier is late",
                key="late.cause",
                value="release_batch_failure",
                effects=[(pickup, "CONTRADICTS")],
                new=[
                    {
                        "key": "BATCH",
                        "statement": "the warehouse release batch job fails",
                        "decision_impact": "HIGH",
                        "rationale": "job log",
                    }
                ],
                assessment={
                    "relation": "CONTRADICTS",
                    "target_type": "PROBLEM_PREMISE",
                    "target_refs": [pickup] + list(pd.get("evidence_refs", []))[:1],
                    "materiality": "CRITICAL",
                    "problem_invalidating": True,
                    "rationale": "premise false",
                },
            )
        if src == "wms-jobs":
            return interp("batch job timeout reduced to 30s on 08-01", key="batch.timeout_s", value=30)
        if src == "dispatch-notice":
            return interp(
                "pickup API endpoint moved",
                key="pickup.api_endpoint",
                value="v3",
                assessment={
                    "relation": "CONTRADICTS",
                    "target_type": "SOLUTION_PATH",
                    "target_refs": [],
                    "materiality": "HIGH",
                    "problem_invalidating": False,
                    "rationale": "how we push changes, not why parcels are late",
                },
            )
        return interp("no decision-relevant content")

    def define(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        common = {
            "requested_solution": "chatbot explaining delays",
            "affected_process": "P-SHIP",
            "assumptions": [],
            "metrics": [_metric()],
            "success_criteria": [_sc()],
            "depends_on_handoffs": [],
            "constraint_refs": [],
            "rejected_framings": [],
            "confidence": 0.7,
        }
        if version(st) == 1:
            return {
                **common,
                "root_problem": "Carrier pickups run two hours late, so parcels miss same-day dispatch.",
                "symptoms": ["30% late at handover"],
                "causal_chain": ["late pickup", "late delivery"],
                "premise_hypotheses": [h_by(st, "PICKUP")],
                "evidence_refs": [ev_by(st, source="order-db"), ev_by(st, source="pickup-log")],
                "assumptions": [
                    {
                        "key": "PICKUP_DRIVES_LATENESS",
                        "statement": "pickup delay explains lateness",
                        "evidence_refs": [ev_by(st, source="pickup-log")],
                        "risk_if_wrong": "HIGH",
                    }
                ],
                "unknowns": [
                    {
                        "key": "SLOT_IMPACT",
                        "question": "Does moving pickup slots cut late handovers?",
                        "criticality": "HIGH",
                        "decision_impact": "decides the slot change",
                        "affects_scope": [scope("slot_impact_report", "*")],
                        "resolution_path": "compare next week",
                        "safe_placeholder": "ship ranking only",
                    }
                ],
                "intended_scope": [
                    scope("rank_late_slots", "DA-PICK"),
                    scope("push_pickup_schedule", "pickup-sched"),
                    scope("slot_impact_report", "mgmt"),
                ],
                "protected_actions": ["push_pickup_schedule"],
                "required_tools": ["pickup-log"],
            }
        return {
            **common,
            "root_problem": "The warehouse release batch job fails (timeout cut to 30s on 08-01), so "
            "orders are released after the pickup and miss it.",
            "symptoms": ["30% late at handover"],
            "causal_chain": ["batch timeout", "late release", "missed pickup"],
            "premise_hypotheses": [h_by(st, "BATCH")],
            "evidence_refs": [
                ev_by(st, source="wms-jobs", method="release_batch_runs"),
                ev_by(st, source="wms-jobs", method="batch_job_config"),
            ],
            "unknowns": [],
            "intended_scope": [scope("detect_late_release", "DA-ORD")],
            "protected_actions": [],
            "required_tools": ["order-db", "wms-jobs"],
        }

    def assess(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        return {
            "updates": [
                {
                    "hypothesis": h_by(st, "PICKUP"),
                    "status": "SUPPORTED",
                    "rationale": "data",
                    "evidence_refs": [ev_by(st, source="pickup-log")],
                },
                {
                    "hypothesis": h_by(st, "CHAT"),
                    "status": "REJECTED",
                    "rationale": "data",
                    "evidence_refs": [ev_by(st, source="order-db")],
                },
            ],
            "ready_to_define": True,
            "rationale": "x",
        }

    def agent(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        if version(data["state"]) == 1:
            return _agent(
                [scope("rank_late_slots", "DA-PICK"), scope("push_pickup_schedule", "pickup-sched")],
                {"rank_late_slots": ["DA-PICK"]},
                gate=["push_pickup_schedule"],
                tools=["pickup-log"],
            )
        return _agent(
            [scope("detect_late_release", "DA-ORD")], {"detect_late_release": ["DA-ORD"]}, tools=["order-db"]
        )

    def plan(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        st = data["state"]
        if version(st) == 1:
            return {
                "work_items": [
                    {
                        "key": "RANK",
                        "description": "rank late pickup slots",
                        "work_class": "CORE_FEATURE",
                        "est_minutes": 15,
                        "scope_items": [scope("rank_late_slots", "DA-PICK")],
                        "root_problem_aligned": True,
                        "release_blocking": True,
                        "data_ops": ["pickup-log:pickup_by_slot"],
                        "output_name": "late_slots",
                        "output_key_fields": ["slot"],
                        "output_join": False,
                        "output_constant_fields": [],
                    },
                    {
                        "key": "PUSH",
                        "description": "push new pickup schedule (gated)",
                        "work_class": "CORE_FEATURE",
                        "est_minutes": 5,
                        "scope_items": [scope("push_pickup_schedule", "pickup-sched")],
                        "root_problem_aligned": True,
                        "release_blocking": True,
                        "data_ops": [],
                    },
                ],
                "protected_actions": [
                    {
                        "key": "SCHED",
                        "action": "push_pickup_schedule",
                        "resource": "pickup-sched",
                        "subject": "earlier pickup slots",
                        "scope": [scope("push_pickup_schedule", "pickup-sched")],
                        "why": "pickups run late",
                        "side_effect": "carrier crews re-sequenced",
                        "reversibility": "REVERSIBLE",
                        "alternatives": ["manual"],
                        "key_evidence": [ev_by(st, source="pickup-log")],
                        "work_item": "PUSH",
                    }
                ],
                "rationale": "v1",
            }
        return {
            "work_items": [
                {
                    "key": "DETECT",
                    "description": "detect late-released orders",
                    "work_class": "CORE_FEATURE",
                    "est_minutes": 15,
                    "scope_items": [scope("detect_late_release", "DA-ORD")],
                    "root_problem_aligned": True,
                    "release_blocking": True,
                    "data_ops": ["order-db:orders_released_late"],
                    "output_name": "late_released",
                    "output_key_fields": ["order"],
                    "output_join": False,
                    "output_constant_fields": [],
                }
            ],
            "protected_actions": [],
            "rationale": "v2",
        }

    def revise(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        return {
            "revisions": [
                {
                    "evidence": e["id"],
                    "revised_interpretation": f"{e['id']} still shows the observation, but it is caused "
                    "by late order release, not by the carrier",
                    "revision_kind": "INTERPRETATION_ONLY",
                    "problem_invalidating": True,
                    "affected_objects": [],
                    "reason": "job log",
                }
                for e in data["proposed_for_revision"]
            ]
        }

    def transition(req: ReasoningRequest, data: dict[str, Any]) -> dict[str, Any]:
        trig = data["trigger"]["challenge"]["evidence_id"]
        return {
            "transition_candidate": "REDEFINE",
            "trigger_evidence_refs": [trig],
            "rationale": "the canonical premise (carrier lateness) is false",
            "affected_scope": [],
            "confidence": 0.8,
            "reprofile_targets": ["DA-WMS"],
            "reprofile_reason": "confirm batch mechanism",
            "reprofile_required_evidence": ["batch job config"],
            "reprofile_expected_decision_impact": "v2 cause",
        }

    handlers = {
        "hypothesis_init": {
            "framing_assertion": {
                "key": "late.cause",
                "value": "lack_of_information",
                "rationale": "request",
            },
            "hypotheses": [
                {
                    "key": "CHAT",
                    "statement": "customers lack status information",
                    "origin": "REQUESTER_FRAMING",
                    "decision_impact": "LOW",
                    "rationale": "request",
                    "discriminating_evidence": [],
                },
                {
                    "key": "PICKUP",
                    "statement": "carrier pickups are late",
                    "origin": "ALTERNATIVE",
                    "decision_impact": "MEDIUM",
                    "rationale": "logistics",
                    "discriminating_evidence": [],
                },
            ],
            "confidence": 0.6,
        },
        "discover_actions": lambda req, data: {
            "actions": [
                action(a["ref"], 0.9 - 0.1 * i, addresses=list(data["reprofile_targets"]))
                for i, a in enumerate(data["catalog"])
            ],
            "stop": False,
            "stop_reason": "",
        },
        "interpret_evidence": interpret,
        "assess_hypotheses": assess,
        "define_problem": define,
        "structural_remedy": lambda req, data: _remedy(feasible=False),
        "agent_design": agent,
        "plan_execution": plan,
        "revise_evidence": revise,
        "propose_transition": transition,
        "semantic_judge": _judge,
        "release_summary": _SUMMARY,
    }
    human = ["why do I need to approve this now?"] + [None] * 6
    return public, world, handlers, human

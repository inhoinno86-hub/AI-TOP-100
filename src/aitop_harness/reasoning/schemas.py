"""Structured Reasoning Contract — JSON schemas per skill + a stdlib validator.

Every Reasoner output is validated against its skill schema before anything else looks at it
(prompt §25). The schemas are plain JSON Schema (draft-07 subset) so a real provider can enforce them
natively (e.g. ``claude -p --json-schema``) and the Harness re-validates them independently.

Supported keywords: type (incl. list of types), enum, properties, required, additionalProperties
(bool), items, minItems, maxItems, minimum, maximum, minLength, maxLength.
"""

from __future__ import annotations

from typing import Any

SCHEMA_VERSION = "1.0"

CRITICALITY = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
SCALAR = ["string", "number", "boolean"]
# typed authorization scope (IDR-RV5-01, engine.scope_contract)
SCOPE_KINDS = ["RESOURCE", "INTENDED_TARGET", "ANY_TARGET"]


# --------------------------------------------------------------------------- builders


def s_str(min_length: int = 0, max_length: int = 4000) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length, "maxLength": max_length}


def s_enum(values: list[str]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values)}


def s_num(minimum: float | None = None, maximum: float | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "number"}
    if minimum is not None:
        out["minimum"] = minimum
    if maximum is not None:
        out["maximum"] = maximum
    return out


def s_unit() -> dict[str, Any]:
    return s_num(0.0, 1.0)


def s_bool() -> dict[str, Any]:
    return {"type": "boolean"}


def s_scalar() -> dict[str, Any]:
    return {"type": list(SCALAR)}


def s_arr(item: dict[str, Any], min_items: int = 0, max_items: int = 40) -> dict[str, Any]:
    return {"type": "array", "items": item, "minItems": min_items, "maxItems": max_items}


def s_ids(max_items: int = 30) -> dict[str, Any]:
    return s_arr(s_str(1, 120), 0, max_items)


def s_obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(props) if required is None else list(required),
        "additionalProperties": False,
    }


SCOPE_ITEM = s_obj({"action": s_str(1, 120), "target": s_str(1, 120)})


# --------------------------------------------------------------------------- validator


def _type_ok(value: Any, t: str) -> bool:
    if t == "string":
        return isinstance(value, str)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "null":
        return value is None
    return False


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return a list of schema violations (empty = valid)."""
    errors: list[str] = []
    types = schema.get("type")
    if types is not None:
        allowed = types if isinstance(types, list) else [types]
        if not any(_type_ok(value, t) for t in allowed):
            return [f"{path}: expected {'/'.join(allowed)}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in {schema['enum']}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: {value} > {schema['maximum']}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: more than {schema['maxItems']} items")
        item_schema = schema.get("items")
        if item_schema is not None:
            for i, item in enumerate(value):
                errors.extend(validate(item, item_schema, f"{path}[{i}]"))
    if isinstance(value, dict):
        props: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required '{key}'")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                errors.append(f"{path}: unexpected properties {extra}")
        for key, sub in props.items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
    return errors


# --------------------------------------------------------------------------- shared fragments

_HYPOTHESIS = s_obj(
    {
        "key": s_str(1, 40),
        "statement": s_str(5, 600),
        "origin": s_enum(["REQUESTER_FRAMING", "ALTERNATIVE"]),
        "decision_impact": s_enum(CRITICALITY),
        "rationale": s_str(1, 800),
        "discriminating_evidence": s_arr(s_str(1, 300), 0, 6),
    }
)

_NEW_HYPOTHESIS = s_obj(
    {
        "key": s_str(1, 40),
        "statement": s_str(5, 600),
        "decision_impact": s_enum(CRITICALITY),
        "rationale": s_str(1, 800),
    }
)

_VOB_PROPOSAL = s_obj(
    {
        "unresolved_question": s_str(5, 600),
        "decision_impact": s_enum(CRITICALITY),
        "required_before": s_enum(
            ["BEFORE_DESIGN_FINALIZATION", "BEFORE_PROTECTED_ACTION", "BEFORE_RELEASE", "BEFORE_PRODUCTION"]
        ),
        "blocking_scope": s_arr(SCOPE_ITEM, 0, 10),
        "entire_solution": s_bool(),
        "validation_method": s_str(1, 600),
        "required_evidence": s_arr(s_str(1, 300), 0, 8),
        "linked_unknown": s_str(0, 60),
        "rationale": s_str(1, 800),
    }
)

_TRANSITIONS = ["RETRY", "REPLAN", "REPROFILE", "REDEFINE", "CONTINUE"]
_PREMISE_LAYERS = ["HYPOTHESIS", "CLAIM", "PROBLEM_PREMISE", "SOLUTION_PATH", "METRIC", "ASSUMPTION"]

# --------------------------------------------------------------------------- skill schemas

SKILL_SCHEMAS: dict[str, dict[str, Any]] = {
    # DISCOVER — initial Unknown / Hypothesis proposal from the public scenario only
    "hypothesis_init": s_obj(
        {
            "framing_assertion": s_obj(
                {"key": s_str(1, 80), "value": s_scalar(), "rationale": s_str(1, 600)}
            ),
            "hypotheses": s_arr(_HYPOTHESIS, 2, 8),
            "confidence": s_unit(),
        }
    ),
    # DISCOVER — Information Value inputs for catalog actions (Core ranks and selects)
    "discover_actions": s_obj(
        {
            "actions": s_arr(
                s_obj(
                    {
                        "catalog_ref": s_str(1, 160),
                        "question": s_str(1, 400),
                        "decision_impact": s_unit(),
                        "uncertainty": s_unit(),
                        "discriminative_power": s_unit(),
                        "answerability": s_unit(),
                        "process_data_handoff_impact": s_unit(),
                        "action_proximity": s_unit(),
                        "constraint_risk": s_unit(),
                        "estimated_cost_minutes": s_num(0.0, 120.0),
                        "expected_information_gain": s_str(1, 600),
                        "decision_impact_rationale": s_str(1, 600),
                        "discriminates_hypotheses": s_ids(),
                        "resolves_unknowns": s_ids(),
                        "addresses": s_ids(),
                        "why_now": s_str(1, 600),
                    }
                ),
                0,
                30,
            ),
            "stop": s_bool(),
            "stop_reason": s_str(0, 600),
        }
    ),
    # Evidence interpretation (+ semantic contradiction assessment)
    "interpret_evidence": s_obj(
        {
            "interpretation": s_str(1, 1500),
            "assertion_key": s_str(0, 80),
            "assertion_value": s_scalar(),
            "claim_assertion_key": s_str(0, 80),
            "claim_assertion_value": s_scalar(),
            "hypothesis_effects": s_arr(
                s_obj(
                    {
                        "hypothesis": s_str(1, 60),
                        "effect": s_enum(["SUPPORTS", "CONTRADICTS", "NEUTRAL"]),
                        "rationale": s_str(1, 800),
                    }
                ),
                0,
                12,
            ),
            "new_hypotheses": s_arr(_NEW_HYPOTHESIS, 0, 4),
            "fact_candidates": s_arr(
                s_obj(
                    {
                        "statement": s_str(5, 600),
                        "assertion_key": s_str(1, 80),
                        "value": s_scalar(),
                        "evidence_refs": s_ids(10),
                    }
                ),
                0,
                6,
            ),
            "unknown_resolutions": s_arr(s_obj({"unknown": s_str(1, 60), "resolution": s_str(1, 800)}), 0, 6),
            "authorization_candidates": s_arr(
                s_obj(
                    {
                        "action": s_str(1, 120),
                        "resource": s_str(1, 120),
                        "authority_holder": s_str(1, 60),
                        "scope_kind": s_enum(SCOPE_KINDS),
                        "scope_target": s_str(0, 120),
                        "conditions": s_arr(s_str(1, 400), 0, 6),
                        "rationale": s_str(1, 800),
                    },
                    required=[
                        "action",
                        "resource",
                        "authority_holder",
                        "scope_target",
                        "conditions",
                        "rationale",
                    ],
                ),
                0,
                4,
            ),
            "contradiction_assessment": s_obj(
                {
                    "relation": s_enum(["SUPPORTS", "CONTRADICTS", "UNRELATED", "PARTIAL_CONTRADICTION"]),
                    "target_type": s_enum(
                        ["CLAIM", "HYPOTHESIS", "PROBLEM_PREMISE", "SOLUTION_PATH", "NONE"]
                    ),
                    "target_refs": s_ids(12),
                    "materiality": s_enum(CRITICALITY),
                    "problem_invalidating": s_bool(),
                    "rationale": s_str(1, 1200),
                }
            ),
            "vob_proposals": s_arr(_VOB_PROPOSAL, 0, 3),
            "follow_up_actions": s_ids(6),
            "confidence": s_unit(),
        },
        required=[
            "interpretation",
            "hypothesis_effects",
            "new_hypotheses",
            "fact_candidates",
            "unknown_resolutions",
            "authorization_candidates",
            "contradiction_assessment",
            "vob_proposals",
            "follow_up_actions",
            "confidence",
        ],
    ),
    # Hypothesis update / rejection explanation (Core validates against linked evidence)
    "assess_hypotheses": s_obj(
        {
            "updates": s_arr(
                s_obj(
                    {
                        "hypothesis": s_str(1, 60),
                        "status": s_enum(["CANDIDATE", "SUPPORTED", "REJECTED", "CONFIRMED"]),
                        "rationale": s_str(1, 800),
                        "evidence_refs": s_ids(),
                    }
                ),
                0,
                12,
            ),
            "ready_to_define": s_bool(),
            "rationale": s_str(1, 1200),
        }
    ),
    # DEFINE — Problem Definition proposal (Core DEFINE Gate decides)
    "define_problem": s_obj(
        {
            "root_problem": s_str(20, 1500),
            "requested_solution": s_str(1, 600),
            "symptoms": s_arr(s_str(1, 400), 1, 8),
            "affected_process": s_str(0, 60),
            "causal_chain": s_arr(s_str(1, 500), 1, 8),
            "premise_hypotheses": s_ids(6),
            "evidence_refs": s_ids(),
            "assumptions": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "statement": s_str(5, 600),
                        "evidence_refs": s_ids(10),
                        "risk_if_wrong": s_enum(CRITICALITY),
                    }
                ),
                0,
                8,
            ),
            "unknowns": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "question": s_str(5, 600),
                        "criticality": s_enum(CRITICALITY),
                        "decision_impact": s_str(1, 600),
                        "affects_scope": s_arr(SCOPE_ITEM, 0, 8),
                        "resolution_path": s_str(0, 600),
                        "safe_placeholder": s_str(0, 600),
                    }
                ),
                0,
                8,
            ),
            "metrics": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "name": s_str(1, 300),
                        "metric_type": s_enum(
                            [
                                "COUNT",
                                "DURATION",
                                "RATE",
                                "POPULATION_RATE",
                                "WINDOWED_TREND",
                                "HANDOFF_FRESHNESS",
                                "OTHER",
                            ]
                        ),
                        "numerator": s_str(0, 300),
                        "denominator": s_str(0, 300),
                        "population": s_str(0, 300),
                        "start_event": s_str(0, 300),
                        "end_event": s_str(0, 300),
                        "measurement_window": s_str(0, 120),
                        "aggregation": s_str(0, 120),
                        "owner": s_str(0, 60),
                        "current_value": s_num(),
                        "current_value_evidence_refs": s_ids(10),
                        "target_value": s_num(),
                    },
                    required=["key", "name", "metric_type"],
                ),
                1,
                6,
            ),
            "success_criteria": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "statement": s_str(5, 600),
                        "kind": s_enum(["MUST", "TARGET", "KNOWN_LIMITATION"]),
                        "metric": s_str(0, 40),
                        "threshold": s_str(0, 120),
                        "validation_method": s_str(1, 600),
                    }
                ),
                1,
                8,
            ),
            "intended_scope": s_arr(SCOPE_ITEM, 1, 12),
            "protected_actions": s_ids(6),
            "required_tools": s_ids(10),
            "depends_on_handoffs": s_ids(6),
            "constraint_refs": s_ids(10),
            "rejected_framings": s_arr(s_obj({"hypothesis": s_str(1, 60), "why": s_str(1, 800)}), 0, 6),
            "vob_reevaluation": s_arr(
                s_obj(
                    {
                        "vob": s_str(1, 60),
                        "decision": s_enum(["KEEP", "RETIRE"]),
                        "rationale": s_str(1, 800),
                        "evidence_refs": s_ids(10),
                    }
                ),
                0,
                12,
            ),
            "confidence": s_unit(),
            # DEFINE repair (only meaningful when the request carried a `repair_request`)
            "repair_resolution": s_arr(
                s_obj({"finding": s_str(1, 60), "option": s_str(1, 200), "change": s_str(1, 600)}), 0, 12
            ),
            "authorization_candidates": s_arr(
                s_obj(
                    {
                        "action": s_str(1, 120),
                        "resource": s_str(1, 120),
                        "authority_holder": s_str(1, 60),
                        "scope_kind": s_enum(SCOPE_KINDS),
                        "scope_target": s_str(0, 120),
                        "conditions": s_arr(s_str(1, 300), 0, 6),
                        "evidence_ref": s_str(1, 60),
                        "rationale": s_str(1, 800),
                    },
                    required=[
                        "action",
                        "resource",
                        "authority_holder",
                        "scope_target",
                        "conditions",
                        "evidence_ref",
                        "rationale",
                    ],
                ),
                0,
                4,
            ),
            # typed framing repair (IDR-RV5-02; only meaningful when the request carried a `framing_repair`)
            "framing_resolution": s_arr(
                s_obj(
                    {
                        "hypothesis": s_str(1, 60),
                        "option": s_enum(
                            ["KEEP_AS_CLAIM", "RECLASSIFY_BY_PROVENANCE", "SEPARATE_INDEPENDENT_HYPOTHESIS"]
                        ),
                        "statement": s_str(0, 600),
                        "evidence_refs": s_ids(10),
                        "rationale": s_str(1, 800),
                    }
                ),
                0,
                3,
            ),
        },
        required=[
            "root_problem",
            "requested_solution",
            "symptoms",
            "affected_process",
            "causal_chain",
            "premise_hypotheses",
            "evidence_refs",
            "assumptions",
            "unknowns",
            "metrics",
            "success_criteria",
            "intended_scope",
            "protected_actions",
            "required_tools",
            "depends_on_handoffs",
            "constraint_refs",
            "rejected_framings",
            "confidence",
        ],
    ),
    # DESIGN step 1 — Structural Remedy (asked before any agent question; Freeze §15)
    "structural_remedy": s_obj(
        {
            "root_cause": s_str(5, 1200),
            "remedies": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "description": s_str(5, 800),
                        "removes_root_cause": s_bool(),
                        "feasible_in_contest_time": s_bool(),
                        "constraint_feasible": s_bool(),
                        "feasibility_rationale": s_str(1, 800),
                        "residual_gap": s_str(0, 800),
                    }
                ),
                1,
                5,
            ),
            "why_agent_needed": s_str(0, 800),
            "confidence": s_unit(),
        }
    ),
    # DESIGN step 2 — Agent Role / Agentification inputs (after Core recorded feasibility)
    "agent_design": s_obj(
        {
            "deterministic_rules_cover_cases": s_bool(),
            "llm_reasoning_adds_value": s_bool(),
            "autonomous_iteration_adds_value": s_bool(),
            "residual_exceptions": s_bool(),
            "detection_needed": s_bool(),
            "why_agent": s_str(0, 800),
            "bridge_sunset_condition": s_str(0, 600),
            "deterministic_components": s_arr(s_str(1, 300), 0, 10),
            "release_scope": s_arr(SCOPE_ITEM, 0, 12),
            "minimum_useful_scope": s_arr(SCOPE_ITEM, 0, 12),
            "scope_dependencies": s_arr(s_obj({"action": s_str(1, 120), "depends_on": s_ids(8)}), 0, 12),
            "role_suggestion": s_arr(
                s_enum(["PRIMARY_SOLUTION", "BRIDGE", "CONTROL_DETECTION", "EXCEPTION_HANDLER"]), 0, 4
            ),
            "capabilities": s_arr(s_str(1, 300), 0, 10),
            "llm_required_for": s_arr(s_str(1, 300), 0, 8),
            "tools": s_ids(10),
            "authority_boundary": s_arr(s_str(1, 400), 0, 8),
            "human_gate": s_ids(6),
            "termination": s_str(1, 600),
            "validation": s_arr(s_str(1, 400), 0, 8),
            "known_limitations": s_arr(s_str(1, 400), 0, 6),
            "vob_proposals": s_arr(_VOB_PROPOSAL, 0, 3),
            "confidence": s_unit(),
        }
    ),
    # EXECUTE — work plan over catalog data operations + protected action proposals
    "plan_execution": s_obj(
        {
            "work_items": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "description": s_str(1, 400),
                        "work_class": s_enum(
                            [
                                "RELEASE_BLOCKING_VERIFICATION",
                                "AUTHORITY_SAFETY_CHECK",
                                "PACKAGING",
                                "SUBMISSION",
                                "CORE_FEATURE",
                                "NICE_TO_HAVE",
                                "LOW_VALUE_EXPLORATION",
                                "BROAD_REFACTOR",
                                "NON_BLOCKING_FEATURE",
                            ]
                        ),
                        "est_minutes": s_num(0.0, 240.0),
                        "scope_items": s_arr(SCOPE_ITEM, 0, 6),
                        "root_problem_aligned": s_bool(),
                        "release_blocking": s_bool(),
                        "data_ops": s_ids(6),
                        "output_name": s_str(0, 80),
                        "output_key_fields": s_ids(4),
                        "output_join": s_bool(),
                        "output_constant_fields": s_arr(
                            s_obj({"field": s_str(1, 60), "value": s_str(0, 120)}), 0, 4
                        ),
                    },
                    required=[
                        "key",
                        "description",
                        "work_class",
                        "est_minutes",
                        "scope_items",
                        "root_problem_aligned",
                        "release_blocking",
                        "data_ops",
                    ],
                ),
                1,
                12,
            ),
            "protected_actions": s_arr(
                s_obj(
                    {
                        "key": s_str(1, 40),
                        "action": s_str(1, 120),
                        "resource": s_str(1, 120),
                        "subject": s_str(1, 400),
                        "scope": s_arr(SCOPE_ITEM, 1, 6),
                        "why": s_str(1, 800),
                        "side_effect": s_str(1, 600),
                        "reversibility": s_enum(
                            ["REVERSIBLE", "PARTIALLY_REVERSIBLE", "IRREVERSIBLE", "UNKNOWN"]
                        ),
                        "alternatives": s_arr(s_str(1, 300), 0, 4),
                        "key_evidence": s_ids(8),
                        "work_item": s_str(0, 40),
                    }
                ),
                0,
                3,
            ),
            "rationale": s_str(1, 1200),
        }
    ),
    # Recovery — Evidence Revision wording (Core decides kind / links / commit)
    "revise_evidence": s_obj(
        {
            "revisions": s_arr(
                s_obj(
                    {
                        "evidence": s_str(1, 60),
                        "revised_interpretation": s_str(5, 1200),
                        "revision_kind": s_enum(
                            ["INTERPRETATION_ONLY", "OBSERVATION_INVALIDATED", "SCOPE_REVISED"]
                        ),
                        "problem_invalidating": s_bool(),
                        "affected_objects": s_ids(),
                        "reason": s_str(1, 1200),
                    }
                ),
                0,
                10,
            )
        }
    ),
    # Recovery — transition candidate (+ targeted reprofile) proposal; Core validator decides
    "propose_transition": s_obj(
        {
            "transition_candidate": s_enum(_TRANSITIONS),
            "trigger_evidence_refs": s_ids(10),
            "rationale": s_str(1, 1500),
            "affected_scope": s_ids(),
            "confidence": s_unit(),
            "reprofile_targets": s_ids(6),
            "reprofile_reason": s_str(0, 800),
            "reprofile_required_evidence": s_arr(s_str(1, 300), 0, 6),
            "reprofile_expected_decision_impact": s_str(0, 600),
        }
    ),
    # VERIFY Layer 2 — semantic judge (can never override Layer 1)
    "semantic_judge": s_obj(
        {
            "checks": s_arr(
                s_obj(
                    {
                        "name": s_str(1, 60),
                        "status": s_enum(["PASS", "FAIL", "WARN"]),
                        "detail": s_str(1, 1200),
                        "refs": s_ids(10),
                    }
                ),
                0,
                6,
            )
        }
    ),
    # Final explanation / summary for the Human (non-authoritative)
    "release_summary": s_obj(
        {
            "summary": s_str(1, 2000),
            "key_points": s_arr(s_str(1, 600), 0, 8),
            "limitations_explained": s_arr(s_str(1, 600), 0, 8),
        }
    ),
    # Premise Check (IDR-RV4-01): canonical premises vs one new authoritative observation (advisory)
    "premise_check": s_obj(
        {
            "problem_id": s_str(1, 60),
            "problem_version": s_num(1),
            "premises": s_arr(
                s_obj(
                    {
                        "premise_id": s_str(1, 60),
                        "relation": s_enum(
                            ["SUPPORTS", "CONTRADICTS", "PARTIALLY_CONTRADICTS", "NOT_ADDRESS"]
                        ),
                        "materiality": s_enum(CRITICALITY),
                        "affected_layer": s_enum(_PREMISE_LAYERS),
                        "problem_invalidating": s_bool(),
                        "evidence_refs": s_ids(10),
                        "rationale": s_str(1, 800),
                    }
                ),
                0,
                20,
            ),
            "overall_assessment": s_enum(["STABLE", "CHALLENGED", "INVALIDATED", "UNCERTAIN"]),
            "rationale": s_str(1, 1200),
            "confidence": s_unit(),
        }
    ),
    # Bounded protected-action reconsideration (IDR-RV4-05): the Core decides eligibility and scope
    "reconsider_protected_action": s_obj(
        {
            "decision": s_enum(["KEEP_EXCLUDED", "INCLUDE_WITH_HUMAN_GATE", "NEEDS_MORE_EVIDENCE"]),
            "rationale": s_str(1, 1200),
            "evidence_refs": s_ids(10),
            "risks": s_arr(s_str(1, 400), 0, 6),
            "needed_evidence": s_str(0, 600),
            "confidence": s_unit(),
        }
    ),
    # Bounded blocking-scope review (IDR-RV5-04): the Core decides eligibility and validates any narrowing
    "review_blocking_scope": s_obj(
        {
            "reviews": s_arr(
                s_obj(
                    {
                        "vob": s_str(1, 60),
                        "decision": s_enum(
                            ["KEEP_ENTIRE_BLOCK", "NARROW_BLOCKING_SCOPE", "NEEDS_MORE_EVIDENCE"]
                        ),
                        "narrowed_scope": s_arr(SCOPE_ITEM, 0, 12),
                        "evidence_refs": s_ids(10),
                        "rationale": s_str(1, 1200),
                        "needed_evidence": s_str(0, 600),
                    }
                ),
                0,
                6,
            ),
            "confidence": s_unit(),
        }
    ),
}


def schema_for(skill: str) -> dict[str, Any]:
    return SKILL_SCHEMAS[skill]

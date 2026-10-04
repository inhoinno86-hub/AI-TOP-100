# v0.3 Implementation Decisions & Traceability

This file records how frozen v0.3 semantics map to code, and the implementation-flexible choices
(Design Freeze §36.2) made along the way. Nothing here changes the frozen design.

## 1. Frozen design → implementation mapping

| Frozen semantic (Freeze §) | Code | Tests |
|---|---|---|
| Phase flow DISCOVER→…→RELEASE (§2) | `core/enums.py:Phase`, `engine/controller.py:PhaseController.advance` | `test_phase_b_vertical_slice.py` |
| ProblemState / RuntimeState / SupervisionState (§3-4) | `state/problem.py`, `state/runtime.py`, `state/supervision.py`, `engine/context.py:CANONICAL_STATES` | `test_phase_a_state.py` |
| Recovery inside RuntimeState, no 4th state (§4, v0.2.5 P30) | `state/runtime.py:RecoveryRuntime` | `test_exactly_three_canonical_states…` |
| Event Log / Provenance | `core/events.py`, `core/provenance.py` | `test_event_log_is_append_only`, `test_provenance_…` |
| Fact / Claim / Evidence / Hypothesis / Assumption / Unknown / Conflict (§5) | `domain/epistemic.py`, `phases/discover.py` | `test_phase_c_discover_data.py`, Mock #1 |
| Evidence Revision (§5) | `phases/discover.py:revise_evidence`, `ProblemState.evidence_revisions` | `test_evidence_revision_…`, Mock #6 readiness |
| Information Value (§6) | `phases/discover.py:rank_actions/select_next_action` | `test_information_value_…` |
| Organization / Stakeholder / BusinessProcess / ProcessHandoff (§7-8) | `domain/organization.py`, `phases/handoff.py` | Mock #1, #4 |
| delivery ≠ semantic validity ≠ freshness, lazy freshness (§8) | `ProcessHandoff`, `phases/handoff.py:evaluate_freshness` | `test_handoff_…_independent`, Mock #2 |
| EntityIdentity / CanonicalMapping lazy (§9) | `domain/identity.py`, `phases/identity.py:propose_mapping` | `test_identity_mapping_rules`, Mock #4 |
| Metric MINIMAL / EXTENDED (§10) | `domain/metric.py`, DEFINE metric check | `test_metric_promotion_keeps_id`, Mock #2 |
| Constraint / Authority (§11) | `domain/authority.py` | Mock #3 |
| DOMAIN_AUTHORIZATION ≠ RUNTIME_EXECUTION_CONFIRMATION (§12) | `DomainAuthorization` (ProblemState) vs `RuntimeExecutionConfirmation` (RuntimeState) | `test_missing_domain_authorization_blocks_and_approve_cannot_repair` |
| DEFINE Gate (§13) | `phases/define.py` | `test_phase_de_define_design.py` |
| VOB + required_before + blocking_scope (§14) | `domain/verification.py`, `core/scope.py` | `test_vob_…`, `test_open_vob_outside_release_scope…` |
| Structural Remedy before Agent (§15) | `phases/design.py:DesignSession` (order enforced) | `test_design_order_is_enforced` |
| Agent Role / Agentification Gate (§16-17) | `phases/design.py:classify_roles`, `agentification_gate` | `test_role_classification_deterministic_first` |
| AgentSpec incl. failure_handling / budget_policy (§18, v0.2.5 §16) | `domain/design.py:AgentSpec` | design tests |
| ToolHealth / partial result (§19, §22) | `phases/execute.py` | `test_success_is_not_complete`, `test_tool_health_…` |
| retry / replan / reprofile / redefine (§20-21) | `phases/recovery.py:decide_recovery`, `PhaseController.retry/replan/reprofile/redefine` | `test_phase_fg_execute_budget.py`, Mock #5, #6 |
| Fallback (§23) | `phases/recovery.py:activate_fallback/fallback_permits` | `test_fallback_authority_and_lazy_freshness` |
| Budget Awareness / Release Reserve (§24-25) | `phases/budget.py` | `test_release_reserve_entry_reduces_scope`, Mock #5 |
| Monitoring Importance / Throttling (§26) | `supervision/monitoring.py` | `test_never_throttle_…`, `test_retry_noise_…` |
| State Diff (§27) | `supervision/state_diff.py`, `HarnessContext.commit` | `test_state_diff_…` |
| Safe Point (§28) | `HarnessContext.safe_point` (+ calls in execute / gate / controller) | gate flow test |
| Mandatory Human Gate / ApprovalPacket (§29-30) | `phases/human_gate.py`, `supervision/approval.py` | `test_phase_hi_supervision_gate.py` |
| REQUEST_CONTEXT (§31, §38) | `phases/human_gate.py:request_context` | `test_request_context_regression.py` |
| VERIFY layers (§32) | `phases/verify.py` | `test_phase_j_verify_release.py` |
| Release Gate (§33) | `phases/release.py:evaluate_release_gate` | `test_phase_j_verify_release.py` |
| Minimum Useful Release (§34) | `phases/release.py:assess_minimum_useful_release` | `test_panic_scope_collapse…`, Mock #5 |
| Contest Adapter separation (§36.3) | `adapters/base.py` (interface only), `adapters/local.py` (rehearsal) | `test_cli_adapter.py` |

## 2. Implementation-flexible decisions

1. **Schemas**: stdlib `dataclasses` + `StrEnum`; JSON-compatible serialization in `core/serialization.py`.
   No runtime dependencies (contest environment may be restricted).
2. **ProblemState collections** `domain_authorizations` and `evidence_revisions` were added as id-keyed
   collections. They are the storage of the frozen concepts "Constraint / Authority" and "Evidence Revision";
   they are part of ProblemState, not new canonical states.
3. **Scope model** (`core/scope.py`): scopes are `(action, target)` items with `*` wildcards in patterns.
   A VOB with unspecified `blocking_scope` defaults to `ENTIRE_SOLUTION` (conservative). Narrowing a blocking
   scope requires committed evidence + rationale (`HarnessContext.narrow_vob_scope`), preventing artificial
   narrowing (Freeze §35 #18).
4. **"Used by released action"** (Release Gate §33) is evaluated from explicit reliance:
   `SolutionDesign.scope_dependencies[action]` plus CanonicalMappings that are themselves released targets.
   Targeting a handoff to *detect* its breakage is not reliance on it (found via the rehearsal CLI run).
5. **Commit**: `HarnessContext.commit()` is the only ProblemState commit path; it bumps `meta.version`,
   computes a hash-fingerprint State Diff (no full-state duplication in the diff), emits `state_committed`
   and records an `AFTER_STATE_COMMIT` safe point. On exception it restores a deep copy and re-raises.
6. **Retry bound**: `FailureHandlingPolicy.repeated_failure_threshold` (default 2) is a *policy* value in
   `AgentSpec.failure_handling`, not an architecture constant. Failure signature =
   `tool | dependency | operation_family | error_class` (parameters excluded).
7. **Information Value formula**: weighted sum in the frozen factor order, scaled by tool reliability and
   divided by budget-pressure-scaled time cost. Zero decision impact ⇒ excluded.
   Safety/authority checks (`constraint_risk ≥ 0.7`) may use Release Reserve time; other exploration is
   dropped while the reserve is active.
8. **Recovery outcome kinds** = `RETRY / REPLAN / REPROFILE / REDEFINE / REDUCE_SCOPE / HOLD`, matching
   Freeze §2 "Tool Failure → retry / replan / reprofile / reduce scope / HOLD". `REDEFINE` is returned only
   for committed, active, authoritative, non-fallback evidence — never for tool failure.
9. **Mutation uncertainty**: a possible partial side effect yields `HOLD` with `next_action = READ_BACK`
   before any re-attempt; executed protected actions carry an idempotency key and are read-back verified.
10. **Human input interpretation**: any question or ambiguous input maps to `REQUEST_CONTEXT`; only an
    explicit approve/reject phrase maps to `APPROVE`/`REJECT`.
11. **MODIFY**: a narrower scope (⊆ presented request, ⊆ authorized) executes after re-checks; a scope
    beyond the authorized scope is BLOCKED (gate stays pending); a scope wider than presented but within
    authorization opens a new gate.
12. **REQUEST_CONTEXT read-only reprofile**: a `context_probe` may add Evidence (ProblemState knowledge)
    when context is insufficient. Runtime execution state (pending action, confirmation, execution status,
    execution record) and domain authorization stay unchanged — this is how "canonical execution state
    unchanged" is interpreted.
13. **Event naming**: `runtime_confirmation_granted` is represented as `approval_granted` with
    `approval_kind = RUNTIME_EXECUTION_CONFIRMATION` (explicitly allowed by v0.2.4 §26).
14. **VERIFY Layer 2**: deterministic proxies (problem/solution version consistency, ApprovalPacket
    evidence fidelity) always run; an optional `SemanticJudge` may add checks but cannot override any
    Layer 1 result.
15. **Release Reserve KEEP/DROP**: `CORE_FEATURE` work is kept only if `release_blocking`; adding droppable
    work while the reserve is active raises `ReserveViolation`.
16. **Budget defaults**: verification floor 20 min, packaging 15 min, reserve 30 min, approach window
    15 min (Freeze §24-25 fix only the soft schedule and the 30-min reserve).
17. **SupervisionState** is rebuilt by `supervision/projection.py:refresh` and is never read as truth.
    `live_summary` holds immediate notices; `pending_digest` holds throttled/NORMAL signals.
18. **Contest Adapter**: only an abstract interface plus a local rehearsal adapter. No official format is
    assumed.

## 3. Known limitations

- `HarnessContext.restore()` rebuilds the three states; the Event Log is persisted separately
  (not yet serialized to disk).
- Layer 2 semantic judging with an actual LLM is a protocol hook only (`SemanticJudge`).
- The CLI runs the thin vertical slice; EXECUTE / Human Gate are exercised through the Python API and tests,
  not yet through an interactive supervision CLI (Freeze roadmap Stage 12).
- Mock #1~#5 are encoded as assertion-level regressions reconstructed from the v0.2.x documents, not
  replays of the original mock transcripts (which are not in the repository).
- Mock #6 has a readiness test of the redefine mechanics; the full Mock #6 scenario still has to be authored.

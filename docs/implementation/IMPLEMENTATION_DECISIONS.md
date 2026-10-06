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
| Replan / Reprofile / Redefine (§21) — canonical Problem lifecycle (Mock #6 patch) | `phases/redefine.py`, `engine/controller.py:PhaseController.redefine`, `phases/define.py:define_problem/apply_define_gate` | `test_mock6_patch_regression.py`, `mocks/mock6/` |
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
   when the Harness validates that committed, active, authoritative, non-fallback evidence materially
   contradicts a premise of the ACTIVE canonical Problem (§4 IDR-REDEFINE-01/02) — never for tool failure,
   never on the caller's label alone.
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

- `HarnessContext.snapshot()` / `restore()` now carry the Event Log (Mock #6 patch, D16); writing the
  snapshot to disk remains the caller's responsibility (the Harness has no storage layer).
- Layer 2 semantic judging with an actual LLM is a protocol hook only (`SemanticJudge`).
- The CLI runs the thin vertical slice; EXECUTE / Human Gate are exercised through the Python API and tests,
  not yet through an interactive supervision CLI (Freeze roadmap Stage 12).
- Mock #1~#5 are encoded as assertion-level regressions reconstructed from the v0.2.x documents, not
  replays of the original mock transcripts (which are not in the repository).
- Mock #6 is authored under `mocks/mock6/` (untracked rehearsal pack). The baseline runner (`run_mock6.py`)
  still uses the operator stand-in (`OPERATOR_REASONER`); the autonomous rerun
  (`mocks/mock6/autonomous/run_mock6_autonomous.py`) uses the Skill / Reasoning Layer (§5) instead.

## 4. Mock #6 patch — normative implementation decisions (IDR-REDEFINE-01..08)

Source: `MOCK6_IMPLEMENTATION_REGRESSION_RESULT.md` (defects D1–D16). These decisions implement Freeze §21
("redefine = canonical Problem invalidated by new authoritative Evidence") inside the frozen three-state
model. **No canonical state was added**: challenges live on `ProblemDefinition.challenges`, Dependency
Reviews in `ProblemState.dependency_reviews`, the REDEFINE candidate and pending-action revalidation flag in
`RuntimeState`.

- **IDR-REDEFINE-01 — Canonical Problem invalidation detection is Harness-owned.**
  On every evidence integration / problem-invalidating revision, `assess_canonical_challenge` checks the
  ACTIVE canonical Problem's premises. A *material* contradiction is one of (a) strong evidence asserting a
  different value for the same assertion as evidence the Problem cites, (b) strong evidence contradicting a
  SUPPORTED/CONFIRMED HIGH/CRITICAL hypothesis that rests on cited evidence, (c) a problem-invalidating /
  observation-invalidating revision of cited evidence. It yields a `CanonicalChallenge`, a CRITICAL
  `canonical_problem_challenged` event + never-throttled signal, a REDEFINE transition candidate, escalation
  of the premise conflict to CRITICAL, and `EVIDENCE_REVISION_PROPOSED` for cited evidence whose
  interpretation depends on the contradicted premise. `conflict_detected ≠ redefine`: a conflict not
  touching a premise does nothing. A challenge is not an invalidation; it is resolved by `redefine` or by an
  explicit, rationale-carrying `dismiss_canonical_challenge`.
- **IDR-REDEFINE-02 — Only an ACTIVE canonical Problem may be redefined; only ACTIVE unchallenged Problems
  progress.** `redefine` and `decide_recovery(REDEFINE)` require `status == ACTIVE` and a passed DEFINE Gate
  (DRAFT ⇒ hypothesis_changed / continue DEFINE) and a validated premise contradiction (path-only evidence ⇒
  REPLAN; the rejected assertion is quoted in the recovery rationale). Advancing into DESIGN / EXECUTE /
  VERIFY / RELEASE, `finish`, protected action proposal and APPROVE/MODIFY execution all require an ACTIVE,
  unchallenged canonical Problem (`problem_reasons`). Retry / replan are refused while a challenge is open.
- **IDR-REDEFINE-03 — Redefine is atomic with the Runtime transition and pending protected-action
  handling.** Validation runs before any mutation; the mutation runs in `HarnessContext.atomic`, which
  restores all three states on any exception and records `transition_rolled_back`. A WAITING_APPROVAL action
  is *cancelled* (`protected_action_cancelled`, decision log `CANCEL …`) inside the same unit — the
  transition is never refused after the Problem was invalidated (the D4 split-brain).
- **IDR-REDEFINE-04 — Redefine triggers a downstream Dependency Review.** `build_dependency_review` classifies
  Problem-dependent objects as STILL_VALID / NEEDS_REEVALUATION / INVALIDATED / SUPERSEDED (Hypothesis,
  Assumption, Evidence interpretation, StructuralRemedyCandidate, SolutionDesign, AgentRole, AgentSpec,
  VerificationObligation, linked Unknown, SuccessCriterion, Metric, ExecutionPlan / WorkItem,
  PendingProtectedAction, ReleaseCandidate, premise Conflict) and counts preserved organisation / authority /
  data / evidence facts. `redefine ≠ full reset`. Applied effects: contradicted hypotheses → REJECTED,
  hypotheses whose support was reinterpreted → CANDIDATE, assumptions resting on invalidated interpretations
  → INVALIDATED (others resting on cited evidence: NEEDS_REEVALUATION only), solution-path work items →
  `INVALIDATED`, premise conflicts → RESOLVED.
  *VOB lifecycle:* VOBs carry `problem_definition_id / problem_version`; statuses add INVALIDATED /
  SUPERSEDED (`is_open` = OPEN/DEFERRED). A VOB bound to the invalidated version is INVALIDATED when its
  blocking scope lies only on the invalidated solution path or is `ENTIRE_SOLUTION` — a blocking scope is
  expressed against the solution of the version it was bound to, so "entire" means the entire *invalidated*
  solution. Its linked Unknown is listed NEEDS_REEVALUATION and surfaced as an INFO finding at the
  successor's DEFINE Gate ("re-raise if it still matters"), so it is not silently lost. Other bound VOBs stay
  OPEN (NEEDS_REEVALUATION) and at the successor's passing gate are rebound to the new version if their scope
  intersects its intended scope, otherwise SUPERSEDED (`bind_successor`). `AgentSpec.verification_obligations`
  contains only VOBs that apply to the active Problem version (D9).
- **IDR-REDEFINE-05 — Problem version and lineage are Harness-owned and monotonic.** `define_problem`
  assigns v1 for the first definition, keeps the version when replacing a DRAFT, and assigns
  `max(previous, history) + 1` after an invalidation, setting `supersedes = "PD@vN"`; the caller's version
  is ignored (`problem_version_assigned` records it). An ACTIVE canonical Problem cannot be replaced except
  through `redefine`. History entries are deep-copy snapshots; the only later edit is the `superseded_by`
  lineage link set when the successor passes its gate. Solution designs are stale unless both
  `problem_ref` and `problem_version` match; a VERIFY run only opens RELEASE for the Problem version it
  verified (`verify_runs[*].problem_ref`).
- **IDR-REDEFINE-06 — Evidence observation validity and interpretation revision are distinct.**
  `EvidenceRevision.revision_kind ∈ {INTERPRETATION_ONLY, OBSERVATION_INVALIDATED, SCOPE_REVISED}`. The Harness
  infers OBSERVATION_INVALIDATED only when strong revising evidence asserts a different value for the same
  assertion; otherwise the observation stays ACTIVE and citable, and the DEFINE Gate adds an INFO finding
  ("observation only, read as …"). Revisions record `affected_objects`
  (problem_definitions / hypotheses / assumptions / designs / vobs / plans), `proposed_by_harness`, and the
  `dependency_review_id` that consumed them.
- **IDR-REDEFINE-07 — Old runtime approval does not survive a problem-invalidating redefine.** Pending
  actions record the `problem_ref` they were proposed under; APPROVE/MODIFY re-check that it equals the
  active Problem and that no revalidation is pending. A challenge marks the pending action
  `revalidation_required` (APPROVE blocked, REJECT / REQUEST_CONTEXT still possible); redefine cancels it. A
  re-proposal is a new gate with new scope validation, ApprovalPacket and runtime confirmation.
- **IDR-REDEFINE-08 — Transition precedence prevents REDEFINE from being overwritten.**
  `RuntimeState.propose_transition` enforces `ABORT > REDEFINE > REPROFILE > REPLAN > RETRY > ADVANCE/FINISH`
  (`core/enums.py:TRANSITION_PRECEDENCE`); recovery decisions and Human REJECT use it.

Supporting decisions:

- **Idempotent redefine (D7):** same Problem version + same evidence ⇒ `redefine_noop` (LOW) and no
  mutation, history entry, invalidation event or signal.
- **Monitoring (D14):** one CRITICAL `PROBLEM_INVALIDATED` signal carries Problem id/version, trigger
  evidence, `REDEFINE: <from> → DEFINE`, affected downstream scope, pending-action status and the next
  re-evaluation action; the REDEFINE transition does not additionally emit a NORMAL digest checkpoint.
  `CANONICAL_PROBLEM_CHALLENGED` is never-throttled CRITICAL with the same fields.
- **Projection (D15):** `refresh` shows `CHALLENGED by …` on the current Problem and the latest Dependency
  Review (non-STILL_VALID items) in `SupervisionState.dependency_review`; rejected hypotheses are not current.
- **Targeted reprofile (D12):** while in DISCOVER with `reprofile_targets`, ranking excludes actions that do
  not serve a target. An action serves a target via its id / target / tool / `addresses` /
  `resolves_unknowns` / `discriminates_hypotheses`, a DataAsset's `source`, or the data-asset sources of a
  ProcessHandoff's *sending* organisation (where the payload originates). `prerequisite_for` admits an
  explicit prerequisite with the rationale recorded in the ranking reason.
- **Assumption basis:** `Assumption.evidence_refs` is explicit; for existing records, committed evidence
  ids named in `basis` are also treated as references.
- **Fixture updates required by the new guards:** `test_cli_adapter.py` now defines an ACTIVE Problem before
  proposing the submission; `test_phase_fg_execute_budget.py::test_redefine_on_authoritative_…` now records
  the premise relation (a revision of the cited evidence) and asserts that authoritative evidence *without*
  such a relation does not yield REDEFINE.

## 5. Autonomous Skill / Reasoning Layer — IDR-REASON-01..08

Source: `intent-docs/AI_TOP_100_Harness_v0.3_Autonomous_Reasoning_Layer_Claude_Code_Prompt.md`. The Skill Layer
is the frozen architecture's "Skill Layer" box (Freeze §2). **No canonical state was added**: reasoning
provenance lives in the Event Log (`reasoning_completed / reasoning_failed / reasoning_skipped`,
`proposal_accepted / adjusted / rejected`, `external_input_received`); proposals are records, not state.

- **IDR-REASON-01 — Reasoning Layer proposes; Core validates and commits.** `reasoning/` returns typed
  proposals (`reasoning/models.py`); `engine/proposals.py` validates them and commits only through
  `ctx.commit` / existing `phases.*` functions. The orchestrator (`engine/autonomous.py`) is Core.
- **IDR-REASON-02 — Reasoner cannot directly mutate canonical state.** The Reasoner receives a detached JSON
  view (`engine/views.py:state_view`), never a `HarnessContext`; `reasoning/` imports no engine / phases /
  state module (enforced by `test_reasoning_layer_cannot_reach_canonical_state`).
- **IDR-REASON-03 — All state-changing semantic outputs use typed proposals.** One JSON schema per skill
  (`reasoning/schemas.py`, schema_version 1.0), validated by the Harness even when the provider enforces it.
  Invalid output → `INVALID_SCHEMA` → bounded repair prompt → fallback provider → deterministic fallback →
  manual escalation (HOLD). Raw output is never committed.
- **IDR-REASON-04 — Factual assertions need evidence references or explicit assumption / unknown status.**
  Evidence.content (the observation) is rendered by the Core from raw tool results; Reasoner text is stored only
  as an interpretation entry. Unknown refs are dropped and recorded; a definition with no committed evidence is
  rejected; Facts only through `establish_fact` (strong evidence); metric values without evidence are flagged
  speculative; ids are Harness-assigned.
- **IDR-REASON-05 — Semantic contradiction assessment may trigger Core challenge evaluation but cannot bypass
  transition validation.** The assessment is translated into structured relations (hypothesis contradiction,
  assertion key, problem-invalidating revision) that the existing `assess_canonical_challenge` /
  `validate_problem_invalidation` judge. A problem-invalidating claim must be consistent (PROBLEM_PREMISE,
  CONTRADICTS, HIGH+ materiality, strong evidence, premise targets) or it is recorded as not trusted. A
  SOLUTION_PATH contradiction can only yield a REPLAN candidate. Conflict impact is the Core default; premise
  conflicts are escalated by the Core's challenge, not by the Reasoner's materiality.
- **IDR-REASON-06 — Validated transition candidates are executed by the Harness Controller, not by the LLM.**
  REDEFINE requires two keys: a Core-validated premise contradiction (`decide_recovery` →
  `validate_problem_invalidation`) **and** the Reasoner's REDEFINE proposal with confidence ≥ 0.5. Then
  `PhaseController.redefine` runs (atomic, cancels the pending gate). Disagreement, low confidence or a missing
  proposal escalates to the Human (HOLD); the Reasoner can never dismiss a challenge. Reprofile targets are
  validated (known ids, ≤ 4, never every data asset) and executed with `PhaseController.reprofile`.
- **IDR-REASON-07 — Human Gate remains authoritative in autonomous mode.** Protected actions go through
  `propose_protected_action`; only `HumanInterface` answers; the text is interpreted by
  `interpret_human_input` (ambiguity ≠ approval); no skill produces a Human response.
- **IDR-REASON-08 — Deterministic logic remains preferred.** The Reasoner estimates Information Value
  factors; `rank_actions` decides. Retry / fallback / VOB intersection / gates / versioning / idempotency /
  release mechanics / data inspection / output assembly (join) stay deterministic. Inside the Release Reserve
  non-essential skills (`discover_actions`, `assess_hypotheses`, `semantic_judge`, `release_summary`,
  `hypothesis_init`) are skipped and replaced by deterministic fallbacks.

Supporting decisions:

- **Premise hypothesis materiality:** a SUPPORTED hypothesis adopted as the canonical premise is raised to HIGH
  decision impact by the Core (recorded as an adjustment), so its later contradiction is material.
- **Release scope vs open critical VOBs:** at DESIGN, release-scope items intersecting an open critical VOB
  (not BEFORE_PRODUCTION, not ENTIRE) are moved to unfinished scope with the VOB id (Freeze §14 "Open VOB ≠ Global
  HOLD", §34 Minimum Useful Release); an empty release scope defaults to the intended scope.
- **KNOWN_LIMITATION success criteria** are not PD success criteria; they become explicit unfinished scope.
- **Same key ⇒ same object** across Problem versions for metrics / success criteria (carry-over); invalidated
  assumptions are never overwritten.
- **Deferred access-failed queries:** a message from the organisation that owns the data of a deferred
  (access-failed) tool makes that query eligible for one re-attempt (deterministic), in addition to Reasoner
  follow-ups (validated: read-only catalog refs only).
- **Affordance catalog** (`Environment.catalog`) lists which read-only operations / interviews are reachable per
  stage. It is environment knowledge, not reasoning; choosing, valuing and interpreting them is the Reasoner's.
- **Real provider** = `claude -p --json-schema` (no SDK dependency), isolated (no tools / MCP / settings /
  parent-session env, explicit effort). Runs are recorded (`RecordingProvider`) and replayable (`ReplayProvider`).
- **Mock #6 robustness variant B** (`u1_default_scope`) = Core knob `ignore_unknown_scope_versions={1}` with the
  scoped run's reasoning replayed, so the variant isolates Core behaviour from model variance.
- **Additional Core-validated paths added during the Mock #6 autonomous rerun** (all R2/R3 fixes, no frozen change):
  assertion values are compared only when canonical (number / boolean / snake_case token); follow-up actions only
  re-attempt deferred (access-failed) queries and only on new external input; a deferred unknown can be resolved
  only with strong evidence and its VOB is resolved with it (`vob_resolved`); at a successor DEFINE the Reasoner may
  propose KEEP / RETIRE for VOBs bound to the invalidated version (RETIRE needs a rationale); an empty release scope
  after VOB blocking triggers one re-proposal, then HOLD; a join is driven only by operations carrying the key;
  relied data assets are inspected from collected results before VERIFY.

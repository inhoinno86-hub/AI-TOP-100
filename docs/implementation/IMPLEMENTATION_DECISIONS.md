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

## 6. Autonomous Stabilization & Reliability Validation — IDR-REL-01..07

지시: `intent-docs/AI_TOP_100_Harness_Autonomous_Stabilization_Reliability_Validation_Claude_Code_Prompt.md`.
결과: `AUTONOMOUS_RELIABILITY_VALIDATION_RESULT.md`. Core semantics / phases / state / domain 변경 없음.

- **IDR-REL-01 — Independent API provider = one OpenAI-compatible HTTP adapter.**
  `reasoning/providers/openai_compat.py` (`OpenAICompatibleProvider`) implements the unchanged
  `ReasoningProvider` protocol over `/chat/completions` (stdlib `urllib`, no SDK). It covers OpenAI, NVIDIA NIM,
  OpenRouter, vLLM / Ollama. Structured output: `response_format=json_schema` (native constrained decoding),
  `json_object` or `prompt` mode; the Reasoner re-validates every output regardless. Transient HTTP (408/409/425/
  429/5xx) gets a bounded provider-local backoff (`max_http_retries`, `Retry-After` honoured, capped); everything
  else is returned as `PROVIDER_ERROR` / `INVALID_SCHEMA` / raised `ProviderTimeout` so the existing Reasoner chain
  (bounded repair → fallback provider → deterministic fallback → HOLD) decides.
- **IDR-REL-02 — Configuration, not hard-coding.** `reasoning/providers/config.py` builds a provider from a
  runtime config dict / JSON or `AITOP_REASONER_*` environment (`.env.example`). Presets `nvidia-nim`, `openai`,
  `claude-cli`. A config naming the key itself (`api_key`) is rejected: only the environment-variable *name*
  (`api_key_env`) is configuration; the key is read at call time and never stored, logged or recorded (tested).
  CLI: `aitop-harness autonomous <scenario> --provider api [--provider-config f.json]`.
- **IDR-REL-03 — Provider failures are recorded.** `RecordingProvider` now writes TIMEOUT / PROVIDER_ERROR entries
  for exceptions raised by the inner provider and re-raises them (before: timeouts left no transcript line).
  Replay uses SUCCESS entries only, so replay semantics are unchanged.
- **IDR-REL-04 — Controlled fault injection** (`reasoning/providers/fault.py`, `FaultInjectingProvider`):
  timeout / invalid_json / schema_mismatch / rate_limit / provider_error by call ordinal, skill, attempt or count.
  It changes only what the Reasoner receives; probes in the Mock #6 runner keep the clean provider.
- **IDR-REL-05 — Freeze = hashes, verified per run.** `mocks/reliability/freeze.py` hashes scenario packs, hidden
  ground truth, evaluators + classifier + aggregator, runners + batch plan, golden fixtures and every
  `src/aitop_harness/**/*.py`, plus derived ids (rubric, C1–C8 source, safety-8 source, REQUEST_CONTEXT source).
  `run_batch.py` re-verifies before every run and at the end; any drift = VALIDATION INVALIDATED.
- **IDR-REL-06 — Frozen evaluators are not edited; their gaps are classified.** The autonomous Mock #6 evaluator
  needs a redefine to evaluate (it reads `inventory_after_redefine`); on EARLY_CORRECT runs it raises and C1–C8 /
  safety-8 are recorded NOT_EXERCISED. Those runs are judged by the frozen classifier (`classify.py`:
  `names_mechanism`, generic Core safety S1–S5, hidden `ideal_release`) and never enter the qualified-redefine
  denominator.
- **IDR-REL-07 — Human Gate E2E scenario is a new public scenario, not a fixture gate.**
  `mocks/reliability/human_gate/scenario.json`: the root-cause fix (re-enable capture idempotency on
  `gateway-config`) is a protected mutation under constraint K-GW (actor SH-OPS) and an authoritative runbook; the
  Reasoner must derive it. The Human answers only from the explicit operator script (`OperatorHuman`); duplicate
  approval (H9) is probed on forks after the run. The scenario was calibrated on one pre-freeze pilot (see result
  doc §4).
- **IDR-REL-08 — One canonical form per assertion value (S-R3 patch, RV-2 A-10).** `engine/proposals._value`
  maps numeric strings (`"1184"`, `"0.88"`, `"1,184"`) to numbers and `"true"`/`"false"` to booleans before the
  equality comparison that detects conflicts / premise contradictions. Before: E-12 `'1184'` vs premise E-11
  `1184` was a "contradiction" and the Controller executed a second, invalid REDEFINE (v2 → v3; frozen safety #5
  failed). Free text stays non-comparable (unchanged trade-off).
- **IDR-REL-09 — Bounded authority recheck at the DEFINE Gate (S-R3 patch, RV-2 C-01/C-03/D3).** When the DEFINE
  Gate FAILs with a BLOCKING `authority` finding (protected action whose authority is unknown), the orchestrator
  re-asks `interpret_evidence` about each already committed authoritative DOCUMENT/POLICY evidence item once
  (`define_gate_findings` in the payload, `already_committed_as` id). Only `authorization_candidates` are taken,
  through the unchanged `_authorization` rules (`commit_document_authorizations`); no new evidence, no other
  semantics. If an authorization was added the same draft is re-evaluated; otherwise the Problem is re-proposed
  as before. Before: the Reasoner missed the runbook grant once, the loop only re-asked `define_problem` (which
  cannot create authority) and the run HOLD after three FAILs.
- **Batch history:** RV-1 VALIDATION INVALIDATED (S-R6 import-order defect in `run_general.py`; Batch B never ran).
  RV-2 completed, then superseded by IDR-REL-08/09. RV-3 = the reported batch (all batches restarted).

## 7. RV-4 Reasoning Stabilization — IDR-RV4-01..08

Source: `intent-docs/AI_TOP_100_Harness_RV4_Reasoning_Stabilization_Claude_Code_Prompt.md`. Scope = P1 evaluator v2,
P2 premise check, P3 DEFINE repair, P4 bounded protected-action reconsideration. The frozen Core (phases/, domain/,
state/, core/) is unchanged: every patch sits in the Reasoning Layer integration (`engine/`, `reasoning/`) and feeds
the existing Core validators. Result: `docs/implementation/RV4_REASONING_STABILIZATION_RESULT.md`.

- **IDR-RV4-01 — Authoritative evidence against an active canonical Problem triggers a dedicated premise-check
  skill.** `engine/premise.py`, skill `premise_check` (`reasoning/skills/premise.py`). Trigger, all of: ACTIVE
  canonical Problem without an open challenge; the evidence is new for that Problem version (not one of its
  premise evidence, checked at most once per version); authority ≥ `AutonomousConfig.premise_check_authority`
  (default `STRONG` = authoritative, complete, non-fallback, non-stakeholder — the Core's `is_strong`); the
  observation is decision-relevant (asserts something, bears on a hypothesis or premise). The Core enumerates the
  premises (root problem, causal chain and premise hypotheses as proposed at DEFINE — kept in
  `DefineContext.premise_records`, premise evidence readings, assumptions resting on premise evidence); the
  Reasoner returns `PremiseCheckProposal` (per premise: relation SUPPORTS / CONTRADICTS / PARTIALLY_CONTRADICTS /
  NOT_ADDRESS, materiality, affected_layer, problem_invalidating, evidence_refs, rationale; overall_assessment).
  It runs *after* `interpret_evidence` has committed the evidence semantics; `interpret_evidence` is unchanged.
  The instruction is domain-neutral (guarded by `tests/test_rv4_reasoning_stabilization.py`).
- **IDR-RV4-02 — Premise-check output is advisory; Core canonical challenge validation remains authoritative.**
  `validate_premise_check` accepts an invalidation claim only if relation ∈ {CONTRADICTS, PARTIALLY_CONTRADICTS},
  materiality ≥ HIGH, affected_layer = PROBLEM_PREMISE, the evidence is strong and the premise rests on committed
  premise evidence; a stale Problem version is ignored. Accepted claims only *nominate* premise evidence for the
  existing Evidence Revision path (`revise_evidence` skill → `commit_revisions` → `revise_evidence` →
  `assess_canonical_challenge`); then the existing `propose_transition` → `evaluate_transition` →
  `validate_problem_invalidation` → Controller chain decides. A REDEFINE still needs every existing key (invalidating
  revision, Core challenge, Reasoner REDEFINE proposal, Core validation). Hypothesis-layer, solution-path and
  non-material claims are recorded as rejected; nothing else is committed from the proposal. Every check is
  recorded (`proposal_accepted`, skill `premise_check`: relations, claims, accepted / rejected with reason, targets,
  challenge_raised). Provider failure → deterministic fallback (all NOT_ADDRESS, no claim).
- **IDR-RV4-03 — DEFINE failures return typed repair findings rather than only free-text rejection.**
  `engine/define_repair.py`. Each BLOCKING / CONDITIONAL Gate finding is typed deterministically from the Gate's own
  check + message (UNAUTHORIZED_ACTION_IN_PROBLEM, UNKNOWN_ACTION, UNSUPPORTED_CAUSAL_CLAIM, MISSING_METRIC,
  INVALID_METRIC, BLOCKING_UNKNOWN, MISSING_AUTHORITY, SCOPE_EXCEEDS_AUTHORIZATION, STALE_EVIDENCE,
  INSUFFICIENT_EVIDENCE + UNAVAILABLE_TOOL, UNMODELED_DEPENDENCY, CRITICAL_CONFLICT, BUDGET_INFEASIBLE, OTHER) and
  carries the repair *option types* the Core accepts (e.g. "remove the action from the canonical Problem", "complete
  the metric's type semantics") — never the fix itself. The `DefineRepairRequest` (payload key `repair_request` of
  `define_problem`) holds the findings, a summary of the previous proposal, `authority_context` (constraints,
  authorization status and the committed authoritative documents for each action an authority finding names),
  open unknowns / VOBs / constraints and the attempt history. `define_problem` may answer with `repair_resolution`
  (advisory) and, for "identify the authorized actor", `authorization_candidates` with an `evidence_ref`: accepted
  only during a repair, only if the cited committed authoritative document names the holder (id or role), and then
  only through the unchanged `_authorization` rules (`commit_repair_authorizations`). Order (§7.2): Gate FAIL →
  IDR-REL-09 authority recheck (kept) → re-run Gate → still FAIL → repair request.
- **IDR-RV4-04 — DEFINE repair retries are bounded.** `AutonomousConfig.max_define_repair_attempts = 3` (prompt:
  2 or 3; a pre-freeze pilot showed repairs still converging — 1 then 2 findings resolved — when a bound of 2 ran
  out; the repetition rule below still stops any repair that makes no progress). Per attempt the Core records (`proposal_accepted`, skill `define_repair`)
  the Core-computed diff (`what changed`), the findings resolved / remaining / new and the Gate result. A repair
  that resolves none of its blocking findings is not retried blindly: one targeted reprofile per Problem draft if
  the repeated findings are evidence-answerable (BLOCKING_UNKNOWN / INSUFFICIENT_EVIDENCE / CRITICAL_CONFLICT,
  valid reprofile targets, unexecuted reprofile catalog actions), otherwise HOLD ("DEFINE Gate FAIL: repair
  resolved none of the blocking findings (same findings repeated)").
- **IDR-RV4-05 — Feasible protected structural remedies may receive one bounded reconsideration before exclusion
  from release scope.** `proposals.reconsideration_candidates` + `AutonomousOrchestrator._reconsider`, skill
  `reconsider_protected_action`. Eligible only if: a structural remedy removing the root cause is feasible; a
  protected action of the canonical Problem's intended scope is missing from the proposed release scope; its domain
  authorization is effective; no SAFETY / PRIVACY constraint on it is unresolved; a mutating tool exists; and no open
  critical VOB blocks it (the `preview_release_scope` rule, tried with the action included). At most one call per
  Problem version. KEEP_EXCLUDED leaves the design unchanged; NEEDS_MORE_EVIDENCE records a known limitation;
  INCLUDE_WITH_HUMAN_GATE adds the intended-scope items to the release scope (re-validated by the Core). The protected
  action then follows the unchanged path (plan → ApprovalPacket → WAITING_APPROVAL → Human). The Reasoner never
  answers the gate. Ineligibility is recorded with its reason (bounded reconsideration ≠ force gate).
- **IDR-RV4-06 — Human Gate reachability and Human Gate mechanics are measured separately.** Evaluator
  `evaluate_human_gate.py` hg-2.0: `reachability` (H1, H2, H4: the autonomous path reached the gate) and `mechanics`
  (H3, H5-H10 when reached; NOT_REACHED otherwise). The combined H1-H10 verdict is kept for continuity.
- **IDR-RV4-07 — EARLY_CORRECT is a valid autonomous success path and redefine-specific metrics are
  NOT_APPLICABLE.** Evaluator `evaluate_mock6_autonomous.py` m6-auto-2.0: a run without a REDEFINE is evaluated
  (no KeyError); C2, C3, C5-C8 and the redefine-specific safety items are NOT_APPLICABLE, C1 / C4 stay applicable.
  Safety #5 distinguishes `no_release_because` (PROVIDER_FAILURE / DEFINE_HOLD / HUMAN_PENDING / STALE_VOB /
  VALID_RELEASE_GATE_HOLD / NOT_REACHED) and fails only for STALE_VOB (the RV-3 D1 S-R6 report). Classifier cls-2.0
  (same mechanism rule) treats NOT_APPLICABLE safety items as not-failed and adds "v2 names the mechanism" to the
  qualified-success rule; aggregator agg-2.0 adds the RV-4 verdicts. All are frozen in the RV-4 manifest.
- **IDR-RV4-08 — RV-4 uses the same primary model as RV-3 to isolate implementation effects.** `batch_plan.json`
  RV-4 = the RV-3 plan unchanged: `nvidia-nim` `nvidia/nemotron-3-super-120b-a12b`, json_schema, temperature 0.2,
  max_tokens 8192, timeout 240 s, the same batch composition (A 10, B 8, C 3, D 6) and fault schedule, fallback
  provider (claude-cli sonnet) only in D4. A stronger-model A/B comparison is a separate later step.
- **RV-4 defect patches (R4-S3 / R4-S2, before RV-4b).** (a) *Repair framing lock* — RV-4 A-04: a repair whose
  findings were only INVALID_METRIC / UNAUTHORIZED_ACTION let the Reasoner rewrite a mechanism-naming root problem
  into a generic one. Now, unless a blocking finding concerns the framing (UNSUPPORTED_CAUSAL_CLAIM /
  INSUFFICIENT_EVIDENCE / STALE_EVIDENCE), `repair_request.locked_fields` = root_problem, causal_chain,
  premise_hypotheses and the Core keeps the previous proposal's values (`define_repair.keep_locked`; the Reasoner's
  own earlier text, recorded as an adjustment). (b) *Premise-check staleness by version* — RV-4 A-02 / A-04: a
  `problem_id` mislabelled with a premise id (`PR-ROOT`) but the right version was discarded as stale
  (outcome-neutral there); now only a version mismatch is stale, an id mismatch is noted. RV-4 was invalidated and
  every batch restarted as RV-4b (prompt §17).
- **RV-4b defect patch (R4-S3, before RV-4c).** RV-4b C-03: the repair-path authorization accepted
  `scope_target` = the action name, producing a grant that could never cover the protected action (the Human Gate
  pre-check correctly BLOCKED it: "SCOPE: requested ⊄ authorized"). `commit_repair_authorizations` now requires
  the scope_target to be the action's resource, one of the Problem's intended targets for the action, or `*`;
  refusals are returned in the next `repair_request.refused_authorization_candidates`, and a repair attempt that
  produced such Core feedback is not counted as a blind repetition (still bounded by
  `max_define_repair_attempts`). RV-4b was invalidated and every batch restarted as RV-4c.

## 8. RV-5 Deterministic Stabilization + Evaluator v3 + Model A/B — IDR-RV5-01..08

Instruction: `intent-docs/AI_TOP_100_Harness_RV5_Deterministic_Patch_EvaluatorV3_Model_AB_Claude_Code_Prompt.md`.
Result: `RV5_MODEL_AB_RESULT.md`. Frozen Core (`phases/`, `domain/`, `state/`, `core/`) unchanged.

- **IDR-RV5-01 — Authorization scope syntax is normalized separately from authorization semantics.** Authorization
  candidates (interpret_evidence and DEFINE repair) carry a typed `scope_kind` (RESOURCE / INTENDED_TARGET /
  ANY_TARGET) next to `scope_target` (`engine/scope_contract.py`). `normalize_scope_target` only rewrites spellings:
  the ScopeItem form `action:target` (prefix = the candidate's own action), `resource/action` mixtures, quotes and
  case variants of a committed id. Free text, two ids, or an unknown kind is never read as a target; nothing is
  widened or redirected (`action:holder` stays the holder and is then refused by the unchanged Core rules). Repair-path
  refusals feed back the accepted canonical forms (the contract), never which one to use. RV-4c A-03/A-07/A-08
  (`action:target`, descriptions) motivated it.
- **IDR-RV5-02 — Requester-framing rejection is a typed repair finding.** The anti-anchoring refusal of
  `commit_problem_definition` raises `FramingRejected`; the next `define_problem` request carries
  `framing_repair` = FRAMING_CLASSIFICATION_CONFLICT (proposal_ref, hypothesis_ref, reason, evidence_refs with
  provenance, expected_repair_type, repair options, requester claim, independent hypotheses) instead of free text.
  The Reasoner answers in `framing_resolution`; the Core validates (`apply_framing_resolution`): KEEP_AS_CLAIM (the
  proposal must not rest on it — checked at commit), RECLASSIFY_BY_PROVENANCE (only with the Core's CONFIRMED-grade
  independence: strong non-stakeholder support, no contradicting evidence, not the initial request) or
  SEPARATE_INDEPENDENT_HYPOTHESIS (a new hypothesis distinct from framing and request, citing strong non-stakeholder
  evidence; the premise reference moves to it). The requester's claim is always kept; the total attempt bound (2)
  is unchanged. RV-4c A-05 / C-01 / C-02 motivated it.
- **IDR-RV5-03 — Core-accepted premise invalidation cannot be semantically downgraded by a later revision step.**
  When `validate_premise_check` accepts an invalidation claim, `revise_evidence` receives `accepted_premise_check`
  (problem id / version, premise ids, relation, materiality, problem_invalidating = true, evidence refs, accepted
  rationales only). `commit_revisions` keeps `problem_invalidating = true` for those evidence ids (a downgrade is
  refused and recorded) and writes an omitted accepted target from the accepted premise-check rationale (also when
  the revision call fails). A context bound to another Problem version is not applied; rejected claims never reach
  the revision step. This supersedes the RV-4 behaviour tested in `test_premise_check_is_advisory_…` (RV-4b A-04).
  The REDEFINE still needs the Reasoner's transition proposal and Core validation (two keys).
- **IDR-RV5-04 — Entire-scope critical unknown blocking receives at most one evidence-aware scope review.** At
  DESIGN, after structural remedies: an open critical VOB (not BEFORE_PRODUCTION) deferring a Reasoner-raised
  unknown, covering every intended item of the ACTIVE Problem, with a feasible root-cause remedy, no SAFETY /
  PRIVACY constraint on the blocked actions and no open material conflict on the scope, gets one
  `review_blocking_scope` call per Problem version (KEEP_ENTIRE_BLOCK / NARROW_BLOCKING_SCOPE / NEEDS_MORE_EVIDENCE).
  A narrowing is accepted only to a strict subset of the blocked intended items (empty = verification-only), with a
  rationale and strong non-stakeholder committed evidence, through `HarnessContext.narrow_vob_scope`; the VOB stays
  open, the approval packet still lists it and the unknown, protected actions still stop at the Mandatory Human
  Gate. Core-made obligations and the robustness-variant versions (`ignore_unknown_scope_versions`) are never
  reviewed. RV-4c A-02 / C-03 / B-04-D / B-06-B motivated it.
- **IDR-RV5-05 — Evaluator recognizes both structured-interpretation and premise-check redefine paths.** Evaluator
  v3 (`m6-auto-3.0`): C2's P4 differential check passes on the probe differential (path A) or on a Core-accepted
  premise check of the late evidence that raised the canonical challenge (path B); C5 counts a revision as
  Harness-proposed when the Core nominated it (challenge proposed revision or accepted premise-check target) and
  accepts premise-check rationale wording; runs record `redefine_path`. Mechanism keyword matching normalizes
  notation only (`classify.canon_text`: Unicode hyphens / dashes / whitespace / case; `-` / `_` / space as one
  separator) with the keyword list unchanged (`cls-3.0`).
- **IDR-RV5-06 — Evaluator uses NOT_APPLICABLE for legitimately absent downstream roles.** C6 role checks (dependent
  hypothesis / assumption, v1-only VOB, still-valid VOB) and C8 "final AgentSpec has no v1-only VOB" are
  NOT_APPLICABLE when the role has no instance in the run and are excluded from the verdict; a missing object that
  must exist (late evidence, v2 design / AgentSpec, revisions) stays None / False. Validated on scratch copies of
  RV-3 / RV-4 / RV-4b / RV-4c before any A/B run (`artifacts/reliability/RV-5/evaluator_v3_dry_run.json`).
- **IDR-RV5-07 — A/B model comparison freezes skill, prompt, evaluator, scenario and rubric.** One freeze manifest
  for both arms (`artifacts/model_ab/freeze_manifest.json`, copied into each arm), verified before every run. Plans
  `mocks/model_ab/plan_model_{a,b}.json` are generated from one template and differ only in the provider block
  (tested). Model A = nvidia-nim nemotron-3-super (RV-3/4 settings); Model B = Claude Sonnet via `claude -p`
  (user-selected; no API keys present). The CLI has no temperature / max-token setting — recorded caveat; both arms
  share the JSON schemas that bound output size, the Harness budget / release reserve and the wall-clock timeouts.
  *Outcome (2026-10-08):* the Model B arm (r1) was invalidated by the Claude subscription session limit after ~80
  calls; the user deferred Model B (a full arm does not fit the Pro plan). Model A was reported under the same freeze
  (`cb353e9bdec99268`) and stays reusable as the comparison arm while that freeze is kept. A define-isolation Sonnet
  proxy was recorded as a non-binding signal (`report_single_arm.py`: Model B NOT_MEASURED → NO_CLEAR_WINNER).
- **IDR-RV5-08 — Model selection uses reasoning quality + safety + Human Gate reachability + latency, not overall
  accuracy alone.** `mocks/model_ab/compare.py` (ab-1.0, frozen): a model wins only if overall correct is ≥ 0.15
  higher, qualified redefine higher (or not needed because v1 was already right), golden not worse, Core safety
  100 % and OPERATOR_REASONER 0, Human Gate reachability not worse, latency acceptable (no TIMEOUT, per-call p95 ≤
  240 s, mean Mock #6 run ≤ 75 min) and provider failures acceptable (≤ 5 % errors, ≤ 10 % PROVIDER_FAILURE runs).
  The Final Reliability Batch runs only for a winner whose A/B reliability meets every §29 threshold.

## 9. RV-6 Human Gate Reachability Patch — IDR-RV6-01

Instruction: user request following RV-5 Model B measurement (both models showed Human Gate reachability
0/3; organizational policy restricts the model to Claude Sonnet 5, so the fix had to be structural, not a
model swap). Result: `RV6_HUMAN_GATE_REACHABILITY_RESULT.md`. Frozen Core semantics unchanged (§36.1: VOB
blocking_scope, Mandatory Human Gate, ApprovalPacket); justified under §37 condition B (a repeatable
structural failure observed in RV-5, reproduced in both Model A and Model B arms).

- **IDR-RV6-01 — A4 blocking-scope review eligibility extends to VOBs that block only a protected action,
  not only VOBs that block the entire intended scope.** `engine/proposals.py:blocking_review_candidates`
  gained a second trigger alongside IDR-RV5-04's `_covers_all` (entire scope): `_covers_any_protected_action`
  — an open critical, non-BEFORE_PRODUCTION VOB that blocks at least one protected action of the ACTIVE
  Problem's intended scope. Root cause: `commit_plan` silently drops a protected action whose scope an open
  VOB still blocks (`pa.action not in release_actions`), so `propose_protected_action` is never called and
  the Mandatory Human Gate never opens — and `reconsideration_candidates` (IDR-RV4-05) only admits actions a
  VOB does *not* block, so it cannot rescue this case either. All existing safety gates are unchanged: Core
  obligations (no `linked_unknown`) and safety/privacy-constrained or conflict-backed blocks are still never
  reviewed; narrowing still requires `HarnessContext.narrow_vob_scope`'s strong non-stakeholder evidence; a
  narrowed VOB stays OPEN and is still shown in the ApprovalPacket; `propose_protected_action`'s own
  `_precheck` (`blocking_vobs_for`) remains a second, independent gate the action must still clear. A rejected
  alternative — loosening `reconsideration_candidates` itself to admit VOB-blocked protected actions — was
  investigated and dropped: it would bypass that second gate and contradict §29's intent that a
  BEFORE_PROTECTED_ACTION VOB must be resolved (or narrowed on evidence) before the action it blocks can even
  be proposed.
- **Prompt guidance (not a frozen-semantics change):** `define_problem` now tells the Reasoner not to raise
  an unknown whose only content is "will the Human who must approve this protected action approve it, and
  when" — that confirmation is the Mandatory Human Gate itself, raised as a separate unknown it can never be
  reached (observed in live replay: an unknown named `ops_confirmation_timing` blocked the very action whose
  Human Gate would answer it). `review_blocking_scope` was revised twice after live Claude Sonnet 5
  verification: the first revision (narrow when reversibility/rollback evidence exists) was wrong and
  reverted — the Core's own `semantic_judge` VERIFY check caught it inventing a narrowing rationale that
  evidence didn't support (reversibility answers "what if we're wrong", not "are we wrong") and HELD the
  release. The second, kept revision requires narrowing evidence to directly answer or moot the
  `unresolved_question` itself; reversibility/rollback evidence alone is explicitly insufficient.
- **Verification:** 3 new unit tests on the deterministic `FakeProvider` fixture (`scenario_d` variant with a
  protected-action-only block) — review called once, Core-validated narrowing opens the gate end to end
  (proposed → approved → executed), `KEEP_ENTIRE_BLOCK` leaves the gate unreached, and disabling the review
  config leaves the gate unreached without any review call (regression guard). 319/319 tests pass (316 + 3),
  ruff / ruff format / mypy clean. Live re-verification replayed the recorded RV-5 Model B Human Gate E2E
  transcripts (C-01/C-02/C-03) through `ReplayProvider` with a live Claude Sonnet 5 fallback for the newly
  reachable `review_blocking_scope` call and every digest-mismatched step after it (`mocks/reliability/
  human_gate/run_human_gate.py` needed a fix first: `--provider replay` silently ignored `--fallback` —
  recorded as a reliability-tooling defect, not a Core change). Result: in all 3 runs the review is now
  called (0/3 → 3/3) and the model correctly answers `KEEP_ENTIRE_BLOCK` with a specific evidentiary reason
  each time (e.g. "gateway-config tool_health is UNKNOWN", "no evidence addresses present latency
  conditions") — Human Gate reachability stays 0/3 for these three scenarios, but the cause changed from "no
  review opportunity existed" (a structural defect) to "the scenario has no committed evidence that resolves
  the unknown" (the Harness correctly staying conservative). No session-limit recurrence across the live
  calls. Final Reliability Batch not rerun (this patch changes the frozen implementation group, invalidating
  freeze `cb353e9bdec99268`; rerunning both A/B arms needs separate user approval).

## 10. RV-7 Release Gate HOLD Patches — IDR-RV7-01/02

Instruction: user request to pursue §28 limitation 2 ("Release Gate HOLD on a completeness-dependent
asset") and limitation 4 ("INVALID_METRIC repetition") toward Model B reliability, continuing without
pausing for approval between fix→verify→reassess cycles. Result: `RV7_RELEASE_GATE_HOLD_RESULT.md`.

A systematic re-audit of every Model B HOLD (6 runs: A-07, A-10, A-11, A-15, B-03-C, B-11-C) found the two
named limitations actually covered **four independent mechanisms**, not one each:

1. **IDR-RV7-01 — a multi-tool output without a shared join key silently concatenates, so most rows are
   missing most fields.** (A-07, B-03-C, B-11-C — 3/6, the most common pattern.) `plan_execution`'s own
   `output_join`/`output_key_fields` contract was fine; the Reasoner just never chose it when combining an
   aggregate-statistic op with an individual-record op from a different tool (no shared key exists between
   them). Fix: `reasoning/prompts.py`'s `plan_execution` instruction now says explicitly that multi-tool
   data_ops need a shared `output_key_fields` to join on, and when no such key exists the ops must become
   separate outputs rather than one concatenated one. No Core change — Reasoner guidance only.
2. **IDR-RV7-02a — a join's row-count drop (the join doing its job) was scored as a completeness failure.**
   (A-10.) `AutonomousOrchestrator.outputs()` compared a joined output's row count against its *driving*
   operation's `expected_count`, but an inner join on key fields keeps only matching rows — strictly ≤ the
   smaller side, by design, even when every feeding operation itself paginated completely. Fix: new
   `engine/proposals.py:output_completeness_check` — for a real join (>1 feeding op), completeness is judged
   by whether every feeding op's own pagination was COMPLETE (`complete_by_op`), skipping the row-count-based
   check entirely when it was; a short-of-COMPLETE op still raises it (as UNKNOWN). Non-join outputs keep the
   original rule unchanged.
3. **IDR-RV7-02b — a `RESOURCE`-scoped domain authorization could not match a request whose scope target
   is a data asset id.** (A-15.) `engine/scope_contract.py:normalize_scope_target` read `scope_kind=RESOURCE`
   as "target == resource" (the tool/system id) — but `intended_scope` / `requested_scope` normally target a
   data asset or handoff id, a different id space than the resource. Such a grant could never match any real
   request for that action. Fix: `RESOURCE` now normalizes to `WILDCARD` (the action through this resource,
   on any target) — matching the prompt's own documented meaning ("RESOURCE: the action on that resource");
   `DomainAuthorization.resource` already enforces the resource constraint independently, so this does not
   broaden what the grant covers, only which target spellings it can match.
4. **A-11 (Core-made VOB, `removes and feasible` unmet) — investigated and NOT a defect.** The existing
   `removes and feasible` gate on `blocking_review_candidates` (A4/RV-6) is deliberately shared with
   `phases/design.py:DesignSession.feasibility()`'s agent-role classification, and an existing RV-5 test
   (`test_narrow_scope_review_cannot_bypass_a_true_block[infeasible]`) requires exactly this behavior: when
   no feasible root-cause remedy exists, the Problem's structural footing itself is in question, and a VOB
   asking whether a *different* candidate remedy is even relevant to the symptom population is not safely
   narrowable scope-review material — kept as-is.
5. **INVALID_METRIC repetition (§28 limitation 4, originally observed only in RV-4/Model A) — confirmed NOT
   reproduced in Model B.** All 20 Model B Mock #6 runs show `repair_success=1` with `same_finding_repetition
   = 0` on every DEFINE Gate failure (`artifacts/model_ab/model_b/runs.json`) — the model swap itself already
   resolved this limitation; no patch needed or applied for it.

**Verification:** 6 new unit tests (`tests/test_rv7_release_hold_patches.py`) plus 3 existing tests in
`tests/test_rv5_deterministic_patch.py` corrected (they asserted `RESOURCE → target == resource`, which was
the bug, not a requirement — scenario_d's `push_pickup_schedule` happened to have `intended_scope` target ==
resource, masking it). 325/325 total tests pass, ruff / ruff format / mypy clean. Live re-verification with
Claude Sonnet 5 (not replay — fresh runs against the live reasoning loop): golden scenario C run twice
(matching both B-03-C's and B-11-C's recorded HOLD) and one fresh Mock #6 "scoped" run (matching A-10's
dependency shape) — all three completed with `VERIFY run failed=[]` and `release=RELEASE_WITH_KNOWN_LIMITATION,
halt=None`, where the equivalent pre-patch runs HELD. A-15's authorization fix was verified at the unit level
only (the construct is deterministic and not provider-dependent — `ScopeItem` matching does not call the
Reasoner); A-07's specific multi-tool shape was not independently re-run live (same code path as B-03-C/
B-11-C, verified there).

## 11. RV-8 Release Scope Recovery — IDR-RV8-01

Instruction: re-auditing the live re-measurement of the RV-7 patches surfaced a fifth, more fundamental
mechanism behind Release Gate HOLD, found by tracing a fresh A-04-shaped HOLD in a new 35-run attempt
(aborted once this was found, since it changes the Core and would need a clean re-measurement anyway).
Result: `RV8_RELEASE_SCOPE_RECOVERY_RESULT.md`.

- **IDR-RV8-01 — a critical VOB discovered during EXECUTE, after DESIGN already fixed release_scope, gets
  one bounded chance to drop just the items it blocks instead of HOLDing outright.** Root cause:
  `preview_release_scope` only runs once, at DESIGN time; nothing re-checks release_scope against VOBs
  created later. In A-04/A-07/A-11/A-15 the Reasoner discovered the blocking fact only once EXECUTE actually
  queried the relevant data (interpret_evidence on a previously-unseen tool/operation) — a VOB whose
  existence DESIGN had no way to anticipate. `evaluate_release_gate` would HOLD the whole run even though
  only one or two items were actually implicated.
  - `phases/release.py:ReleaseGateResult` gained a structured `vob_blocked_items: list[ScopeItem]` field
    (the exact items a critical, non-BEFORE_PRODUCTION VOB intersects in the current release scope) so a
    recovery can act on exact items instead of parsing `hold_reasons` text.
  - `engine/autonomous.py:AutonomousOrchestrator._try_release_scope_recovery` fires once per run (bounded by
    `self.release_scope_recovered`), only when every hold reason is a "critical ... intersects release
    scope" message (any other HOLD cause — a protected action still WAITING_APPROVAL, a failed completeness
    check, an unresolved conflict — is untouched and still HOLDs), and only when none of the blocked items is
    a protected action (a protected action needs its own Human Gate / reconsideration path, not a silent
    scope cut). It drops exactly the blocked items from `release_scope` / `minimum_useful_scope`, records
    each as a `known limitation` in `unfinished_scope` (never hidden), and re-runs VERIFY/RELEASE once on the
    narrowed scope via a new `_run_verify_checks()` helper (the VERIFY body factored out of `_verify()` so
    the recovery can re-verify without illegally re-advancing the phase controller out of RELEASE). If
    dropping the blocked items would leave `release_scope` empty, recovery gives up and the run HOLDs as
    before — it never releases an empty scope. **The VOB itself is never narrowed or resolved** — it stays
    OPEN, stays visible in the ApprovalPacket / known limitations, and the Mandatory Human Gate for any
    protected action is completely unaffected; this only decides what else can still ship around it.
  - New config flag `AutonomousConfig.release_scope_recovery` (default `True`) can disable it for an exact
    pre-RV-8 comparison run.
- **Verification:** 2 new unit tests directly on `evaluate_release_gate` (`vob_blocked_items` populated
  correctly / empty when nothing critical intersects, `test_phase_j_verify_release.py`) plus 4 new end-to-end
  tests on `scenario_d` (`test_rv7_release_hold_patches.py`): a VOB discovered mid-EXECUTE that blocks a
  non-protected release item is dropped and the run still releases with the VOB visibly still open; a VOB
  that blocks a protected action is refused (falls through to a plain HOLD, `release_scope_recovered`
  stays `False`); and two give-up paths (nothing left after the drop) confirmed both end-to-end and by
  calling `_try_release_scope_recovery()` directly against a hand-built `ReleaseGateResult`. 330/330 total
  tests pass, ruff / ruff format / mypy clean. Not yet re-verified live or against the full 35-run batch —
  the in-progress Model B re-measurement (freeze `5bcc9611ebf1c962`, RV-7-only) was stopped before IDR-RV8-01
  landed, specifically so the next full re-measurement reflects RV-6 + RV-7 + RV-8-01 together rather than
  needing a second rerun.

## 12. RV-9 Reliability Re-measurement + discover_actions guidance — IDR-RV9-01

Instruction: continuing the "no approval pauses until Model B reliability" directive. Result:
`RV9_RELIABILITY_REMEASURE_RESULT.md`.

Full 35-run Model B re-measurement under freeze `904fb0c238d46dd0` (RV-6+RV-7+RV-8 applied): Release Gate
HOLD dropped from 6/35 to **0/35**; Golden A–D reached **100%** (first §29 PASS, up from 75%); Mock #6
overall rose 50%→60% and qualified redefine 10%→18.2% (both still below the 80%/90% §29 thresholds); Human
Gate reachability stayed 0/3 as predicted in RV-6 (scenario evidence gap, not a defect). Core safety and
OPERATOR_REASONER unchanged (PASS / 0). No session-limit recurrence.

- **IDR-RV9-01 — `discover_actions` guidance against stopping before checking every live hypothesis
  against its most directly-matching catalog item.** Root cause of all 7 Mock #6 `REASONING_FAILURE` runs
  (A-03/05/06/09/17/19/20): each run's `hypothesis_init` correctly raised a hypothesis naming the right
  mechanism family (a changed import/validation rule), but `discover_actions` never proposed the one catalog
  item whose description directly names that mechanism (`billing-config:validation_rule_changes` — "billing
  validation rule change log") — it queried a differently-named, topically-adjacent item instead
  (`billing-db:tariff_change_log` — tariff, not rule, changes) and then set `stop=true`, treating the
  hypothesis as checked. The two runs that did query the matching item (A-13, A-15) both had
  `qualified_redefine_success=True`, one (A-15) landing within one sentence of the hidden ground truth. This
  is not a Core defect — the catalog item was present and visibly described the whole time — it is a
  domain-agnostic gap in the stop-condition the Reasoner applies.
  `reasoning/prompts.py`'s `discover_actions` instruction now requires checking every still-live hypothesis
  by name against every remaining catalog item's description before `stop=true`, and treats the item whose
  description most directly names a hypothesis's claimed mechanism as the one with the highest
  answerability / discriminative_power for it — even when a topically-adjacent item was already queried.
  No hypothesis names, tool names, or domain terms are referenced; the instruction is phrased purely in
  terms of "a hypothesis about a changed rule/config" vs. "a catalog item describing that rule/config's
  change log" as an illustrative pattern, not a rule tied to this scenario.
- **Verification:** ruff / ruff format / mypy clean, 330/330 existing tests pass (no regression). Live
  re-verification (fresh Mock #6 "scoped" run under the new prompt) was in progress when this entry was
  written; see `RV9_RELIABILITY_REMEASURE_RESULT.md` §4 and any later RV-10 entry for the outcome.

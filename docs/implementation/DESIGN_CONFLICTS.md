# v0.3 DESIGN_CONFLICTS

Status: **none raised.**

No case was found where frozen semantics contradict each other in code, cannot be represented in the
current structure, would break safety/authority correctness, or where mock-validated behaviors could not be
satisfied simultaneously (kickoff §6).

Interpretation notes that were resolved without changing the frozen design are recorded in
`IMPLEMENTATION_DECISIONS.md` §2 — notably #4 ("used by released action" = explicit reliance) and
#12 (what "canonical execution state unchanged" covers during a REQUEST_CONTEXT read-only reprofile).
If either interpretation is judged wrong, it is an implementation change, not a freeze exception.

## Mock #6 patch (IDR-REDEFINE-01..08)

Status: **none raised.** Every Mock #6 defect (D1–D16) was expressible inside the frozen three-state
model: challenges on `ProblemDefinition`, Dependency Review records in ProblemState, candidate precedence and
pending-action revalidation in RuntimeState. The two vocabulary gaps noted in the regression result (S3:
downstream classification words; who detects canonical invalidation) are resolved as implementation
decisions in `IMPLEMENTATION_DECISIONS.md` §4, not as freeze exceptions.

## Autonomous Reasoning Layer (IDR-REASON-01..08)

Status: **none raised.** The Skill Layer is part of the frozen architecture; all reasoning output enters through
existing Core paths (commit, DEFINE Gate, Agentification Gate, recovery / redefine validation, Human Gate,
Release Gate). "Transition execution owner" (prompt §18) is an implementation decision (IDR-REASON-06), not a
freeze exception: the Controller executes only Core-validated transitions.

## Autonomous Stabilization & Reliability Validation (IDR-REL-01..09)

Status: **none raised.** Defects found in the reliability batches were S-R1 (reasoning quality variance), S-R3
(reasoning/Core integration — patched: canonical numeric/boolean assertion values IDR-REL-08, bounded authority recheck
IDR-REL-09), S-R4 (real provider timeouts) and S-R6 (tooling / evaluator gaps). None needs a frozen-design exception; the
frozen 3-state model, gates and Human Gate semantics were unchanged. See `AUTONOMOUS_RELIABILITY_VALIDATION_RESULT.md` §17–§21.

## RV-4 Reasoning Stabilization (IDR-RV4-01..08)

Status: **none raised.** P2-P4 add Reasoning-Layer skills and Core-side validation in `engine/` only; every outcome
still enters through the existing Core paths (Evidence Revision → canonical challenge → transition validation →
Controller; DEFINE Gate; `_authorization`; `preview_release_scope`; Mandatory Human Gate). `phases/`, `domain/`,
`state/` and `core/` are unchanged. P1 changes only the evaluator. See `RV4_REASONING_STABILIZATION_RESULT.md` §26.

## RV-5 Deterministic Stabilization + Evaluator v3 + Model A/B (IDR-RV5-01..08)

Status: **none raised.** A1-A4 change only `engine/` (Proposal Gate, DEFINE loop, revision commit, DESIGN review)
and the Reasoning Layer (`reasoning/`: one new skill, two new optional output fields, prompt wording). Every
outcome still enters through existing Core paths: `_authorization` (unchanged acceptance rules after syntax
normalization), the anti-anchoring rule of `commit_problem_definition` (the requester framing is still never a
premise unless the Core's CONFIRMED-grade independence is shown), `revise_evidence` → `assess_canonical_challenge`
→ transition validation → Controller (two keys kept), `HarnessContext.narrow_vob_scope` (committed evidence +
rationale) and the Mandatory Human Gate. `phases/`, `domain/`, `state/` and `core/` are unchanged. Evaluator v3
changes only `mocks/` evaluation code. See `RV5_MODEL_AB_RESULT.md` §29.

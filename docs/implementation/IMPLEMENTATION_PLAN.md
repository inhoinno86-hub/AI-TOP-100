# AI TOP 100 Harness v0.3 — Implementation Plan

Source of truth: `docs/AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md` (frozen).
Supporting reference: `docs/AI_TOP_100_Harness_v0.2.5_설계문서.md` (runtime recovery / budget schema),
and v0.2.1~v0.2.4 for field-level detail that v0.3 inherits without restating
(DataIssue types, Conflict types, Metric EXTENDED fields, ApprovalPacket fields, Supervision modes).

This document records the implementation mapping. It does **not** modify the frozen design.

## 1. Repository assessment (at start)

| Item | Observation |
|---|---|
| Branch / tree | `main`, clean, single commit `Initial commit` |
| Source code | none |
| Schemas / models | none (design docs only) |
| Orchestration / phase flow | none |
| Tool abstraction | none |
| Event / provenance | none |
| Tests | none |
| CLI / entrypoint | none |
| Packaging | none; system Python 3.14, pytest 9 available, no pydantic |
| Docs | v0.1 ~ v0.2.5 design docs, v0.3 Design Freeze, kickoff prompt |

Consequence: there is no existing structure to preserve or conflict with. Every v0.3 component is a
green-field implementation. Runtime dependencies are kept to the Python standard library
(`dataclasses` + `enum`) so the harness runs in a restricted contest environment.

## 2. Gap analysis

Current state for every row is **absent** (no code). Columns: v0.3 requirement → implementation action → risk → test strategy.

| Component | v0.3 Requirement | Implementation Action | Risk | Test Strategy |
|---|---|---|---|---|
| ProblemState | world/problem knowledge, frozen field list | `state/problem.py` dataclass, id-keyed collections | god object | separation + roundtrip tests |
| RuntimeState | execution/recovery/budget, v0.2.5 schema | `state/runtime.py` | recovery leaking into a 4th state | assert only 3 canonical states |
| SupervisionState | human visibility/intervention | `state/supervision.py`, refreshed as projection | used as truth source | projection rebuilt from P/R state |
| Event Log | append-only, typed events | `core/events.py` | silent mutation | append-only + ordering tests |
| Provenance | evidence/data/mapping provenance | `core/provenance.py` | lost on serialization | roundtrip test |
| Organization / Stakeholder / BusinessProcess | frozen fields | `domain/organization.py` | — | roundtrip |
| ProcessHandoff | acknowledgments[], delivery ≠ semantic ≠ freshness, lazy freshness | `domain/organization.py` | collapsing into one status | independence test |
| EntityIdentity / CanonicalMapping | lazy, evidence-bound, no textual-equality resolve | `domain/identity.py` | forced mapping | lazy-absence test, non-unique source test |
| DataAsset | quality + issue semantics (STATUS_PROGRESSION ≠ duplicate) | `domain/data.py`, `phases/data_inspection.py` | naive dedupe | Mock #4 regression |
| Metric | MINIMAL / EXTENDED, promotion keeps id | `domain/metric.py` | — | promotion test |
| Constraint / Authority | constraint + DomainAuthorization | `domain/authority.py` | approval collapsing | Mock #3 regression |
| VerificationObligation / blocking_scope | required_before + blocking_scope, conservative default | `domain/verification.py`, `core/scope.py` | global HOLD / artificial narrowing | intersection tests |
| ToolRuntime / ToolHealth | HEALTHY/DEGRADED/UNAVAILABLE/UNKNOWN | `state/runtime.py`, `phases/execute.py` | health ≡ authority | separation test |
| RecoveryRuntime | failure_signature, retry history/cost, fallback, partial | `state/runtime.py`, `phases/recovery.py` | hidden retry by param variation | Mock #5 regression |
| BudgetRuntime / ReleaseRuntime | soft budget, variance, reserve status | `state/runtime.py`, `phases/budget.py` | countdown-only budget | budget affects selection/retry |
| Phase Controller | explicit DISCOVER→…→RELEASE + conditional transitions | `engine/controller.py` | implicit transitions | illegal transition tests |
| DISCOVER | Information Value ordering, Claim ≠ Fact, conflicts | `phases/discover.py` | claim promoted to fact | Mock #1 regression |
| DEFINE Gate | PASS / CONDITIONAL_PASS / FAIL, unknown → VOB | `phases/define.py` | PASS with critical unknown | gate tests |
| DESIGN / Agentification Gate | ordered trace, role classification, deterministic-first | `phases/design.py` | agent before remedy | order-enforcement test |
| EXECUTE | ToolHealth, partial result, bounded retry, retry/replan/reprofile/redefine | `phases/execute.py`, `phases/recovery.py` | false redefine | Mock #5 / Mock #6-readiness |
| VERIFY | Layer 1 deterministic, Layer 2 judge (lower authority), Layer 3 human | `phases/verify.py` | LLM overriding deterministic | layer authority test |
| Release Gate | RELEASE / RWKL / HOLD, VOB ∩ release scope | `phases/release.py` | global HOLD on any VOB | partial release tests |
| Safe Point / Mandatory Human Gate / ApprovalPacket / REQUEST_CONTEXT | flow + decisions; packet = projection | `phases/human_gate.py`, `supervision/approval.py` | REQUEST_CONTEXT treated as approval | targeted regression |
| retry / replan / reprofile / redefine | distinct semantics | `phases/recovery.py`, `engine/controller.py` | semantic mixing | per-kind tests |
| Monitoring Importance / State Diff | throttle rules, NEW/CHANGED/RESOLVED/DEFERRED/DROPPED_FOR_BUDGET | `supervision/monitoring.py`, `supervision/state_diff.py` | throttling critical signal | never-throttle test |
| Release Reserve | KEEP/DROP scope reduction | `phases/budget.py` | nice-to-have kept | Mock #5 regression |
| Contest Adapter | separated, nothing guessed | `adapters/` (abstract + local file adapter) | hard-coded contest format | none in core |

## 3. Implementation order (incremental, each step tested)

1. PHASE A — core state foundation (states, event log, provenance, state diff, domain objects, runtime sub-structures).
2. PHASE B — thin vertical slice: scenario → init → DISCOVER → evidence integration → diff → DEFINE Gate → minimal DESIGN → minimal VERIFY → RELEASE/HOLD.
3. PHASE C — DISCOVER + DATA (Information Value, data inspection, conflicts).
4. PHASE D — DEFINE Gate (full checks, unknown → VOB).
5. PHASE E — DESIGN (structural remedy → agent role → Agentification Gate).
6. PHASE F — EXECUTE + recovery (ToolHealth, partial result, bounded retry, retry/replan/reprofile/redefine).
7. PHASE G — Budget + Release Reserve.
8. PHASE H — Human supervision (importance, throttling, digest).
9. PHASE I — Safe Point + Mandatory Human Gate + ApprovalPacket + REQUEST_CONTEXT.
10. PHASE J — VERIFY layers + Release Gate.
11. Mock #1~#5 regression + REQUEST_CONTEXT targeted regression + Mock #6 readiness test.

## 4. Package layout

```text
src/aitop_harness/
  core/        enums, serialization, provenance, events, scope, clock, errors
  domain/      ProblemState domain objects (organization, identity, data, metric,
               epistemic, authority, verification, design)
  state/       ProblemState, RuntimeState (+ Tool/Recovery/Budget/Release runtime), SupervisionState
  supervision/ monitoring, state diff, approval packet projection
  phases/      discover, data_inspection, define, design, execute, recovery, budget,
               human_gate, verify, release
  engine/      HarnessContext (3 states + event log + commit), PhaseController, vertical slice
  tools/       ToolAdapter protocol, ToolResult, registry, simulated tools for tests
  adapters/    ContestAdapter boundary (abstract) + local file adapter
  scenario.py  scenario input → initial ProblemState
  cli.py
tests/
```

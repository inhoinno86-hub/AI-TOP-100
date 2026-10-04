# AI TOP 100 Harness v0.3 — Design Freeze 설계 문서

**Version:** v0.3  
**Status:** CORE DESIGN FREEZE  
**Freeze Basis:** v0.2 ~ v0.2.5 + Mock #1 ~ Mock #5  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Purpose:** Mock #1~#5에서 검증된 Core Architecture와 핵심 state / transition / supervision semantics를 동결하고 구현 단계의 기준선으로 사용한다.  
**Structural Change after Freeze:** 원칙적으로 금지. 명확한 implementation evidence 또는 Mock #6 이상의 regression에서 structural failure가 확인될 때만 해제한다.

---

# 0. Design Freeze 선언

v0.3는 새로운 기능을 추가하기 위한 버전이 아니다.

v0.3의 목적은 다음이다.

```text
Stop redesigning the core.
Start implementing the core.
```

Mock #1~#5에서 다음 핵심 질문이 충분히 검증되었다.

- conflicting stakeholder evidence를 다룰 수 있는가?
- misleading initial request에 anchoring되지 않는가?
- hidden critical constraint를 발견할 수 있는가?
- cross-organization handoff failure를 구조화할 수 있는가?
- identity / event semantics를 잘못 join하지 않는가?
- tool failure와 time pressure에서 retry/replan/reprofile을 구분할 수 있는가?
- release reserve를 지킬 수 있는가?
- unresolved VOB가 safe scope 전체를 과도하게 막지 않는가?
- protected action 전 Human Gate가 동작하는가?
- structural remedy와 Agent 역할을 구분할 수 있는가?

현재까지 구조적 failure는 발견되지 않았다.

따라서 v0.3부터 Core Architecture를 Freeze한다.

---

# 1. Freeze Scope

다음은 **FROZEN CORE**다.

```text
1. High-level phase architecture
2. ProblemState / RuntimeState / SupervisionState separation
3. Evidence / Fact / Claim / Hypothesis distinction
4. Information Value-driven discovery
5. Organization / Stakeholder / Process / ProcessHandoff model
6. Handoff delivery / semantic validity / lazy freshness
7. EntityIdentity / CanonicalMapping lazy model
8. Metric MINIMAL / EXTENDED profiles
9. Constraint / Authority semantics
10. DOMAIN_AUTHORIZATION / RUNTIME_EXECUTION_CONFIRMATION separation
11. DEFINE Gate
12. VerificationObligation + required_before + blocking_scope
13. Structural Remedy before Agent
14. Agent Role Classification
15. Agentification Gate
16. retry / replan / reprofile / redefine semantics
17. Runtime recovery / ToolHealth / fallback / partial-result semantics
18. Budget Awareness / Release Reserve
19. Human Supervision Plane
20. Monitoring Importance / Throttling
21. Safe Point
22. Mandatory Human Gate
23. ApprovalPacket
24. REQUEST_CONTEXT semantics
25. VERIFY layers
26. Release Gate
```

---

# 2. High-level Frozen Architecture

```text
CONTEST ENVIRONMENT
        ↓
Contest Adapter
        ↓
HARNESS CORE
 ├─ Phase Controller
 ├─ Problem Workspace
 ├─ Skill Layer
 ├─ Data Workspace
 ├─ Tool Registry
 ├─ Budget / Runtime / Event Log
 └─ Human Supervision Plane
        ↓
OUTPUTS
```

Core execution flow:

```text
DISCOVER
  ↓
DEFINE
  ↓
DESIGN
  ↓
EXECUTE
  ↓
VERIFY
  ↓
RELEASE
```

Conditional runtime flows:

```text
Tool Failure
→ retry / replan / reprofile / reduce scope / HOLD

Protected Action
→ Mandatory Human Gate

New authoritative evidence invalidates canonical Problem
→ redefine
```

---

# 3. Canonical State Model — FROZEN

## 3.1 ProblemState

```text
ProblemState
= 세상과 문제에 대해 Harness가 알고 있는 것
```

포함:

```text
scenario
organizations
stakeholders
processes
process_handoffs
entity_identities
canonical_mappings
data_assets
metrics
facts
claims
hypotheses
evidence
unknowns
conflicts
assumptions
goals
constraints
risks
success_criteria
verification_obligations
problem_definition
solution_design
agent_spec
execution
validation
budget
decision_log
```

---

## 3.2 RuntimeState

```text
RuntimeState
= Harness가 지금 무엇을 하고 있으며
  execution / recovery / budget 측면에서 어떤 상태에 있는가
```

최소 구조:

```text
phase
execution_status
current_plan
current_task
current_action
next_action
current_tool
tool_runtime
recovery
budget_runtime
release_runtime
pending_protected_action
safe_point
transition_candidate
event_refs
```

---

## 3.3 SupervisionState

```text
SupervisionState
= Human이 무엇을 보고 있으며
  언제 개입해야 하는가
```

포함:

```text
mode
live_summary
current_problem
top_hypotheses
critical_unknowns
critical_conflicts
data_quality_warnings
key_evidence
evidence_revisions
state_diff
decision_rationale
gate_rationale
pending_verification_obligations
current_action
next_action
monitoring_policy
pending_digest
intervention
human_control
```

---

# 4. Frozen State Separation Rule

다음 separation은 v0.3 이후 기본적으로 변경하지 않는다.

```text
World / Problem Knowledge
→ ProblemState

Execution / Recovery / Budget
→ RuntimeState

Human Visibility / Intervention
→ SupervisionState
```

금지:

```text
- ApprovalPacket을 canonical state로 승격
- RecoveryState를 별도 canonical state로 추가
- Gate마다 ProblemState 복제
- SupervisionState를 execution truth source로 사용
```

---

# 5. Evidence Semantics — FROZEN

구분:

```text
Fact
Claim
Evidence
Hypothesis
Assumption
Unknown
Conflict
```

원칙:

- stakeholder 말은 자동 Fact가 아니다.
- tool result는 completeness / authority를 검토한다.
- hidden ground truth를 runtime reasoning에 사용하지 않는다.
- new evidence가 기존 evidence를 무효화하면 Evidence Revision을 남긴다.
- speculative 숫자를 확정 performance로 만들지 않는다.
- missing evidence를 LLM inference로 대체하지 않는다.

---

# 6. Information Value — FROZEN

Action selection 우선순위:

```text
Decision Impact
Uncertainty
Discriminative Power
Answerability
Process/Data/Handoff Impact
Action Proximity
Constraint Risk
Time Cost
Tool Reliability
Remaining Budget
```

핵심 질문:

```text
이 Evidence가 없으면 다음 결정이 실제로 달라지는가?

남은 시간에 비해 이 Action이 가치가 있는가?
```

모든 Unknown을 해결하는 것이 목표가 아니다.

---

# 7. Organization / Process / Handoff — FROZEN

## Organization

```text
Organization
├── id
├── name
├── role
├── objectives
├── stakeholders
├── processes
├── process_handoffs
├── data_assets
├── external_dependencies
└── relations
```

## Stakeholder

```text
Stakeholder
├── id
├── organization_id
├── role
├── responsibilities
├── process_steps
├── knowledge_scope
├── authority_scope
├── incentives
├── potential_bias
├── interview_status
└── information_topics
```

## BusinessProcess

```text
BusinessProcess
├── id
├── organization_ids
├── name
├── purpose
├── trigger
├── inputs
├── outputs
├── steps
├── actors
├── systems
├── data_assets
├── handoff_ids
├── wait_points
├── manual_steps
├── duplicate_steps
├── failure_points
├── metrics
└── pain_points
```

---

# 8. ProcessHandoff — FROZEN

```text
ProcessHandoff
├── id
├── process_id
├── from_org
├── from_actor
├── to_org
├── to_actor
├── accountable_owner
├── trigger
├── payload
├── payload_schema
├── entity_identity_refs
├── channel
├── cadence
├── acknowledgments[]
├── delivery_status
├── semantic_validity
├── expected_latency
├── actual_latency
├── freshness_requirement
├── observed_data_age
├── version_lag
├── freshness_status
├── manual_or_automated
├── authority_boundary
├── failure_modes
├── evidence_refs
├── metric_refs
└── status
```

세 dimension은 독립적이다.

```text
DELIVERY
≠
SEMANTIC VALIDITY
≠
FRESHNESS
```

Freshness는 lazy semantics를 유지한다.

---

# 9. EntityIdentity / CanonicalMapping — FROZEN

Identity ambiguity가 decision/action에 영향을 줄 때만 사용한다.

```text
CanonicalMapping
├── id
├── entity_type
├── source_namespace
├── source_identifiers
├── target_namespace
├── target_identifiers
├── confidence
├── authority
├── provenance
├── validity
├── conflicts
└── status
```

원칙:

- textual equality ≠ canonical identity
- non-unique source identifier는 자동 resolve하지 않는다.
- composite key 허용
- authority / provenance 보존
- mapping irrelevant scenario에서는 생성하지 않는다.

---

# 10. Metric Model — FROZEN

기본:

```text
MINIMAL
```

필요할 때:

```text
EXTENDED
```

Promotion trigger:

- Problem Definition
- DEFINE Gate
- Success Criteria
- Release threshold
- cross-org metric semantic distinction

Metric ID는 유지한다.

---

# 11. Constraint / Authority — FROZEN

핵심 rule:

```text
Available Tool
≠ Authorized Action

Readable Data
≠ Exportable Data

Stakeholder Request
≠ Stakeholder Authority

Existing Practice
≠ Approved Policy

Technically Possible
≠ Allowed
```

---

# 12. Authorization Separation — FROZEN

두 개를 분리한다.

```text
DOMAIN_AUTHORIZATION
```

과

```text
RUNTIME_EXECUTION_CONFIRMATION
```

금지:

```text
Domain authorization exists
→ therefore no runtime gate
```

그리고:

```text
Human APPROVE
→ therefore missing domain authorization repaired
```

둘 다 금지.

---

# 13. DEFINE Gate — FROZEN

결과:

```text
PASS
CONDITIONAL_PASS
FAIL
```

평가 범위:

- Organization / Actor
- Process
- relevant Handoff
- Data
- relevant Identity / Mapping
- Problem
- Evidence
- Unknown
- Conflict
- Metric
- Constraint / Authority
- Success Criteria
- Tool dependency / fallback readiness
- Budget feasibility
- Verification readiness

Critical unknown이 release/action scope와 겹치고 resolution path가 없으면 PASS하지 않는다.

---

# 14. VerificationObligation — FROZEN

```text
VerificationObligation
├── id
├── unresolved_question
├── source_phase
├── reason_deferred
├── decision_impact
├── linked_assumption
├── linked_success_criterion
├── validation_method
├── required_evidence
├── instrumentation_needed
├── owner
├── required_before
├── blocking_scope
├── status
└── resolution
```

핵심:

```text
Open VOB
≠ Global HOLD
```

Release Gate는 다음 교집합을 본다.

```text
VOB blocking_scope
∩
current release scope
```

교집합이 critical하면 HOLD.

교집합이 없으면 safe partial release 가능.

---

# 15. Structural Remedy Before Agent — FROZEN

순서:

```text
Root Problem
↓
Structural Remedy Candidate
↓
Can process/interface/data contract remove root cause?
↓
Constraint / Time feasibility
↓
Why Agent?
↓
Agent Role
↓
Agentification Gate
```

Time pressure는 structural remedy consideration을 생략할 근거가 아니다.

---

# 16. Agent Role — FROZEN

```text
PRIMARY_SOLUTION
BRIDGE
CONTROL_DETECTION
EXCEPTION_HANDLER
```

Agent가 항상 PRIMARY일 필요는 없다.

Bridge라면 sunset condition을 가능하면 명시한다.

---

# 17. Agentification Gate — FROZEN

```text
Can structural/process/integration change remove root cause?
        ↓
Can it be implemented in contest time?
        ↓
Can deterministic rules solve covered cases?
        ↓
Does LLM reasoning add value?
        ↓
Does autonomous iteration add value?
```

Deterministic-first.

Tool failure 때문에 더 agentic하게 확장하지 않는다.

---

# 18. Agent Specification — FROZEN

최소 구조:

```text
AgentSpec
├── identity
├── problem_reference
├── organization_context
├── process_context
├── handoff_context
├── interface
├── required_data
├── validation_rules
├── allowed_transformations
├── entity_identity
├── state
├── capabilities
├── tools
├── workflow
├── decision_rules
├── constraints
├── authority_boundary
├── structural_role
├── human_gate
├── failure_handling
├── termination
├── validation
├── success_criteria
├── verification_obligations
└── budget_policy
```

---

# 19. ToolHealth / Recovery — FROZEN

Tool health:

```text
HEALTHY
DEGRADED
UNAVAILABLE
UNKNOWN
```

중요 Tool failure observation:

```text
tool_id
operation
attempt
error_class
retryable_hint
partial_side_effect_possible
result_completeness
time_cost
evidence_ref
```

ToolHealth는 Data Authority와 동일하지 않다.

---

# 20. Retry — FROZEN

```text
retry
=
Problem valid
+
Action/path valid
+
Failure plausibly transient
+
Expected value > retry cost
+
Minimum verify/release budget preserved
```

bounded여야 한다.

동일 dependency failure를 parameter variation으로 숨기지 않는다.

---

# 21. Replan / Reprofile / Redefine — FROZEN

```text
retry
= same strategy remains valid

replan
= Problem valid, current path no longer suitable

reprofile
= new critical information / owner / policy / data needed

redefine
= canonical Problem invalidated by new authoritative Evidence
```

Tool failure alone is not redefine.

---

# 22. Partial Result — FROZEN

검사 후보:

```text
expected record count
returned count
pagination completeness
missing fields
coverage period
source authority
snapshot age if relevant
```

`SUCCESS` ≠ `COMPLETE`.

---

# 23. Fallback — FROZEN

Primary vs fallback에서 decision-relevant한 것만 비교한다.

```text
coverage
freshness
schema
semantic meaning
authority
completeness
latency
cost
```

stale fallback이 historical baseline에는 충분할 수 있지만,
current protected action에는 부족할 수 있다.

---

# 24. Budget Awareness — FROZEN

기준 Soft Budget:

```text
00:00~00:15  Environment / inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

Budget은 action selection에 영향을 줘야 한다.

phase variance 시:

```text
budget_variance
reason
recovery_action
release_reserve_impact
```

---

# 25. Release Reserve — FROZEN

기본 마지막 30분 보호.

진입 시:

```text
KEEP
- release-blocking verification
- safety/authority checks
- packaging
- submission

DROP
- nice-to-have
- low-value exploration
- broad refactor
- non-critical feature
```

절대 throttle하지 않는 signal:

```text
RELEASE_RESERVE_ENTERED
RELEASE_BLOCKING_VOB
PACKAGING_AT_RISK
SUBMISSION_AT_RISK
```

---

# 26. Human Supervision Plane — FROZEN

Monitoring Importance:

```text
CRITICAL
HIGH
NORMAL
LOW
```

기본 emission:

```text
CRITICAL → immediate
HIGH     → immediate or next safe point
NORMAL   → digest / phase checkpoint
LOW      → on-demand / audit
```

반복 retry detail은 digest 가능.

strategy-changing failure는 throttle 금지.

---

# 27. State Diff — FROZEN

전체 state 반복 대신 변화 중심.

```text
NEW
CHANGED
RESOLVED
DEFERRED
DROPPED_FOR_BUDGET
IMPORTANCE
```

Human이 빠르게 이해할 수 있어야 한다.

---

# 28. Safe Point — FROZEN

```text
Before Action
After Tool Result
After Validation
After State Commit
Before Transition
Before Irreversible / Protected Action
```

Human interrupt는 safe point에서 state corruption 없이 처리한다.

---

# 29. Mandatory Human Gate — FROZEN

대상:

- irreversible external write
- submission / publish
- protected mutation
- sensitive export
- action outside Agent authority
- high-impact ambiguous action
- explicit runtime confirmation-required operation

Flow:

```text
Proposed Protected Action
↓
Domain Authorization Check
↓
Scope Validation
↓
Runtime Confirmation Required?
↓
Canonical State Commit
↓
Safe Point
↓
ApprovalPacket
↓
WAITING_APPROVAL
↓
APPROVE / MODIFY / REJECT / REQUEST_CONTEXT
```

---

# 30. ApprovalPacket — FROZEN

필요한 decision-support projection.

최소 표시:

```text
WHAT
WHY
WHO / RESOURCE
REQUESTED SCOPE
AUTHORIZED SCOPE
SCOPE DELTA
DOMAIN AUTHORIZATION
WHY HUMAN NOW
SIDE EFFECT
REVERSIBILITY
CONSEQUENCE IF APPROVED
CONSEQUENCE IF REJECTED
ALTERNATIVES
UNRESOLVED ITEMS
OPEN VOB + BLOCKING_SCOPE
TIME / RELEASE IMPACT
KEY EVIDENCE
```

raw policy dump 금지.

---

# 31. REQUEST_CONTEXT — FROZEN

```text
WAITING_APPROVAL
↓
REQUEST_CONTEXT
↓
human_context_requested
↓
protected action remains BLOCKED
↓
committed Evidence-based explanation
↓
targeted read-only reprofile if needed
↓
same WAITING_APPROVAL gate
```

중요:

```text
REQUEST_CONTEXT ≠ APPROVE
```

Mock #3에서 도입되었고 Mock #4/#5에서는 실제 Human 선택으로 exercise되지 않았다.

이는 Design Freeze blocker가 아니다.

Implementation regression에서 targeted test를 반드시 수행한다.

---

# 32. VERIFY — FROZEN

## Layer 1 — Deterministic

- schema
- missing
- type
- completeness
- pagination / coverage
- duplicate/event semantics
- mapping uniqueness
- timestamp
- freshness if relevant
- handoff delivery / semantic validity
- retry termination
- fallback trigger
- constraint enforcement
- authority boundary
- VOB blocking_scope
- approval trace
- REQUEST_CONTEXT not treated as approval
- duplicate mutation prevention

## Layer 2 — Semantic Judge

필요한 경우:

- root problem / solution consistency
- exception explanation
- policy/interface summary
- fallback interpretation
- ApprovalPacket evidence fidelity

LLM은 authoritative Tool/Data/Policy보다 높은 authority를 갖지 않는다.

## Layer 3 — Human Review

- protected mutation
- high-impact ambiguity
- unresolved authority
- release decision if required

---

# 33. Release Gate — FROZEN

확인:

- Problem Definition
- Agent contract
- required Data
- ToolHealth / fallback
- Data validation
- transformation validation
- Metric ↔ test
- deterministic tests
- retry/replan history
- unresolved critical Conflict
- unresolved critical Constraint
- unresolved critical Mapping/Handoff issue
- VOB blocking_scope intersection
- domain authorization
- runtime confirmation
- approval/context trace
- known limitations
- remaining time
- release reserve
- packaging/submission feasibility

결과:

```text
RELEASE
RELEASE_WITH_KNOWN_LIMITATION
HOLD
```

Known limitation으로 덮을 수 없는 것:

- destructive transformation
- authority violation
- protected mutation without required confirmation
- unresolved critical mapping used by released action
- unresolved semantic mismatch used by released action
- completeness unknown while release assumes completeness
- critical VOB intersects release scope
- minimum safety verification not executed

---

# 34. Minimum Useful Release — FROZEN

Full requested solution을 못 만들었다고 자동 실패가 아니다.

좋은 scope reduction:

```text
Root Problem alignment
+
operational value
+
safety predicate preserved
+
verification possible
+
unfinished scope explicit
```

예:

```text
Requested:
fully autonomous repair + submit

Safe minimum:
detection
+ classification
+ deterministic correction where proven
+ manual escalation
```

---

# 35. Frozen Failure Modes

다음 anti-pattern을 금지한다.

1. Initial request anchoring
2. Stakeholder claim = Fact
3. Tool success = complete result
4. Retry loop
5. Broad rediscovery after tool failure
6. Fallback blind trust
7. Time pressure → verification sacrifice
8. Release Reserve violation
9. Panic scope collapse
10. Agent workaround hiding structural cause
11. Human approval replacing domain authorization
12. REQUEST_CONTEXT misclassified as approval
13. Giant ApprovalPacket dump
14. CanonicalMapping forced when irrelevant
15. freshness modeled everywhere
16. ACK layering forced when semantics identical
17. Open VOB causing unnecessary global HOLD
18. blocking_scope artificially narrowed to bypass risk
19. duplicate mutation after uncertain write
20. Tool failure causing false redefine

---

# 36. Freeze Boundary

## 36.1 FROZEN

구조적으로 변경하지 않는 것:

- canonical state separation
- phase flow
- transition semantics
- ProcessHandoff health dimensions
- CanonicalMapping concept
- Metric profile concept
- VOB blocking_scope
- authorization separation
- Agent Role model
- Human Gate semantics
- ApprovalPacket semantics
- REQUEST_CONTEXT semantics
- Release Gate semantics
- budget/release reserve principles

## 36.2 IMPLEMENTATION-FLEXIBLE

구현 단계에서 바꿀 수 있는 것:

```text
exact class names
module paths
serialization format
dataclass vs pydantic
event metadata shape
CLI command spelling
internal enum names
storage backend
tool adapter abstraction
logging format
cache strategy
exact retry scoring formula
exact Information Value scoring formula
```

단, frozen semantics를 바꾸면 안 된다.

## 36.3 CONTEST-ADAPTER FLEXIBLE

10/23 이후 실제 대회 안내에 따라 변경 가능:

```text
submission format
problem page adapter
input/output contract
allowed tools
API auth
hidden test interface
artifact format
runtime launch command
network restrictions
```

Core architecture와 분리한다.

---

# 37. Design Change Policy after Freeze

v0.3 이후 structural change는 다음 중 하나가 있어야 한다.

```text
A. implementation cannot represent a frozen semantic without contradiction

B. Mock #6 or later reveals a repeatable structural failure

C. official contest rules make a frozen assumption invalid

D. safety/authority correctness requires architectural change
```

단순 편의, 코드 스타일, 새로운 아이디어만으로 core를 다시 설계하지 않는다.

변경이 필요하면:

```text
Observed Structural Failure
Evidence
Why current frozen design cannot represent it
Proposed change
Backward compatibility
Risk
Freeze exception decision
```

을 남긴다.

---

# 38. REQUEST_CONTEXT Targeted Regression

Design Freeze는 진행하되 implementation 초기 단계에 다음 short regression을 수행한다.

Scenario:

```text
protected publish proposal
→ ApprovalPacket
→ Human: "왜 이걸 지금 승인해야 해?"
→ REQUEST_CONTEXT
```

Pass criteria:

```text
WAITING_APPROVAL remains
protected action not executed
domain authorization unchanged
canonical execution state unchanged
explanation uses committed Evidence
safe read-only reprofile allowed if needed
same gate resumes
```

이 테스트가 실패해도 먼저 implementation defect인지 확인한다.

현재 frozen architecture 자체의 known structural flaw로 보지 않는다.

---

# 39. Mock #6 Position after Freeze

Mock #6:

```text
New Evidence Invalidates Problem
```

검증 목표:

- redefine
- state versioning
- Evidence Revision
- monitoring of problem invalidation
- rollback/replan after redefinition

v0.3에서는 Mock #6을 다음으로 위치시킨다.

```text
Core Design Freeze
↓
Core implementation
↓
Mock #6 implementation regression
```

Mock #6에서 redefine semantics가 구조적으로 표현 불가능함이 확인될 때만 freeze exception을 검토한다.

---

# 40. Implementation Roadmap

```text
Stage 1  Core State Models
Stage 2  Event Log / Provenance
Stage 3  Runtime / ToolHealth / Recovery
Stage 4  Human Supervision State
Stage 5  DISCOVER
Stage 6  Data Inspection / Evidence Integration
Stage 7  DEFINE Gate
Stage 8  DESIGN / Agentification Gate
Stage 9  EXECUTE / Tool Failure Recovery
Stage 10 VERIFY
Stage 11 Release Gate / Release Reserve
Stage 12 Human Supervision CLI
Stage 13 REQUEST_CONTEXT targeted regression
Stage 14 Mock #6
Stage 15 Contest Adapter
Stage 16 10/23 official rule adaptation
Stage 17 10/31 contest readiness
```

---

# 41. v0.3 Implementation Acceptance Criteria

구현은 최소 다음을 증명해야 한다.

1. ProblemState / RuntimeState / SupervisionState가 분리된다.
2. State Diff가 full dump 없이 동작한다.
3. Evidence provenance가 남는다.
4. ToolHealth를 추적할 수 있다.
5. partial result completeness를 표현할 수 있다.
6. bounded retry가 가능하다.
7. repeated failure에서 replan 가능하다.
8. targeted reprofile이 가능하다.
9. tool failure alone이 redefine을 발생시키지 않는다.
10. canonical Problem invalidation 시 redefine 가능하다.
11. fallback authority/freshness를 필요할 때만 검사한다.
12. Release Reserve 진입 시 scope reduction이 가능하다.
13. VOB blocking_scope가 partial release를 지원한다.
14. Structural Remedy Candidate가 Agentification보다 먼저 기록된다.
15. Agent Role이 분류된다.
16. protected action 전 Safe Point가 존재한다.
17. domain authorization과 runtime confirmation이 분리된다.
18. ApprovalPacket을 projection으로 생성한다.
19. REQUEST_CONTEXT에서 action이 실행되지 않는다.
20. APPROVE 이후 scope/authorization을 재검사한다.
21. read-back/idempotency validation을 지원한다.
22. Release Gate가 release scope와 VOB 교집합을 검사한다.
23. minimum useful release로 수렴할 수 있다.
24. monitoring이 critical signal과 retry noise를 구분한다.
25. 5시간 contest budget에서 state richness가 실행 cost를 압도하지 않는다.

---

# 42. Non-Goals of v0.3

v0.3 Freeze에서 하지 않는 것:

- 실제 대회 문제 정답 예측
- 특정 산업 domain hardcoding
- 새로운 multi-agent hierarchy
- automatic self-modifying framework
- full production-grade distributed orchestration
- generic memory system redesign
- arbitrary long-running research planner
- unnecessary ontology expansion
- all-purpose enterprise workflow platform

목표는 contest용 범용 problem-solving harness다.

---

# 43. v0.3 Frozen Definition

> **AI TOP 100 Harness v0.3는 5시간 제한의 현장형 문제 해결 상황에서 조직, 사람, 프로세스, handoff, identity, data, evidence, constraint를 필요한 범위에서 구조화하고, Information Value와 budget을 기준으로 실제 문제를 발견·정의한 뒤, Structural Remedy와 Agent Role을 분리하여 minimum useful Agent/solution을 설계하고, Tool failure에서는 bounded retry / replan / reprofile / reduced scope로 수렴하며, protected action 전에는 domain authorization과 runtime execution confirmation을 분리한 Human Gate를 거치고, VerificationObligation blocking_scope와 Release Reserve를 이용해 검증 가능한 범위만 안전하게 Release하는 범용 Agentic Problem-Solving Harness다.**

핵심 문장:

```text
Understand the operation.
Ask only what changes decisions.
Model only what matters.
Find the real problem.
Prefer structural remedy before agent workaround.
Use deterministic logic where sufficient.
Use the Agent where reasoning or exception handling adds value.
Bound retry by evidence and budget.
Treat partial results as partial.
Respect authority.
Keep Humans at protected boundaries.
Protect verification and release reserve.
Release only the scope that is actually proven.
```

---

# 44. Final Freeze Decision

```text
v0.2.5
= Final Minor Patch Baseline

v0.3
= CORE DESIGN FREEZE
```

결론:

```text
No further core redesign before implementation.

REQUEST_CONTEXT:
targeted regression required,
but not a freeze blocker.

Mock #6:
implementation regression after freeze,
not a mandatory pre-freeze blocker.

Next:
IMPLEMENT.
```

본 문서를 **AI TOP 100 Harness Core Architecture Design Freeze 기준선**으로 사용한다.

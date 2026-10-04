# AI TOP 100 Harness v0.2.5 설계 문서

**Version:** v0.2.5  
**Status:** Mock #5 반영 Final Minor Patch / v0.3 Design Freeze 직전 Baseline  
**Previous:** v0.2.4  
**Purpose:** Mock #5 — Severe Time Pressure + Tool Failure 결과에서 확인된 Runtime recovery / budget execution 명시성 gap을 최소 범위로 보강한다.  
**Architecture Change:** 없음  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Design Intent:** v0.2.4의 구조를 유지하고, 구현 전에 반드시 필요한 Runtime 실행 상태와 recovery policy 표현만 명시한다.

---

# 0. v0.2.5의 목적

v0.2.5는 새로운 Architecture를 추가하는 버전이 아니다.

Mock #5에서 v0.2.4의 핵심 구조는 다음을 정상적으로 수행했다.

```text
DISCOVER
  ↓
DEFINE
  ↓
DESIGN
  ↓
EXECUTE
  ↓
bounded retry / replan / reprofile
  ↓
VERIFY
  ↓
RELEASE RESERVE
  ↓
MANDATORY HUMAN GATE if required
  ↓
RELEASE
```

특히 다음이 검증되었다.

1. 5시간 budget이 실제 investigation/build scope를 줄였다.
2. 첫 transient failure에서는 bounded retry가 사용되었다.
3. repeated failure에서는 같은 dependency에 무한 retry하지 않고 replan했다.
4. fallback source를 authoritative source와 동일 취급하지 않았다.
5. partial result를 complete result로 취급하지 않았다.
6. fallback freshness는 decision-relevant한 경우에만 검사했다.
7. missing critical owner evidence가 필요할 때 targeted reprofile을 사용했다.
8. Tool failure만으로 canonical Problem을 redefine하지 않았다.
9. Release Reserve에서 low-value work를 실제로 중단했다.
10. VerificationObligation의 blocking_scope가 partial safe release를 허용했다.
11. Structural Remedy를 Agent workaround보다 먼저 검토했다.
12. Agent Role을 PRIMARY에서 CONTROL_DETECTION / EXCEPTION_HANDLER로 축소했다.
13. protected action 전 Mandatory Human Gate가 발생했다.
14. APPROVE 이후 domain authorization / scope re-check 후 atomic action만 수행했다.
15. read-back verification으로 protected action 결과를 검증했다.
16. final release는 RELEASE_WITH_KNOWN_LIMITATION으로 수렴했다.

그러나 Mock #5에서 Architecture flaw가 아니라 다음 local explicitness gap이 확인되었다.

```text
RuntimeState에
- ToolHealth
- retry attempt history
- cumulative retry cost
- partial result completeness
- retry eligibility
- fallback state
- release reserve state
를 어떤 구조로 보존할지 명시성이 부족함
```

따라서 v0.2.5는 이 부분만 patch한다.

핵심 원칙:

```text
Do not add a new state machine.
Do not change ProblemState / RuntimeState / SupervisionState separation.
Do not create a RecoveryState as a fourth canonical state.
Do not make every Tool call heavy-weight.
Do not over-model retry details that do not affect decisions.
Patch only runtime recovery and budget execution semantics.
```

---

# 1. v0.2.4 → v0.2.5 변경 요약

| 영역 | v0.2.4 | v0.2.5 |
|---|---|---|
| Core Architecture | 유지 | 유지 |
| ProblemState | 유지 | 유지 |
| RuntimeState | 개념 중심 | recovery/budget execution 최소 schema 명시 |
| SupervisionState | 유지 | 유지 |
| ToolHealth | Mock에서 operational use | RuntimeState first-class field로 명시 |
| Retry | semantics 존재 | attempt/cost/stop evidence 구조 보강 |
| Partial result | 원칙 존재 | result_completeness runtime field 명시 |
| Fallback | 원칙 존재 | fallback trigger/status/runtime risk 명시 |
| Release Reserve | budget rule 존재 | RuntimeState reserve status 명시 |
| Agent failure handling | generic | policy reference 구조 명시 |
| REQUEST_CONTEXT | 유지 | 여전히 architecture 유지, 별도 targeted regression 권장 |
| v0.3 readiness | pending | minor patch 후 freeze 가능 |

---

# 2. Design Principles v0.2.5

v0.2.4의 모든 Design Principle을 상속한다.

추가 원칙은 세 개다.

## P30. Recovery Is Runtime State, Not a New Architecture

Tool failure / retry / fallback / reserve 상태는 `RuntimeState` 내부에 존재한다.

```text
ProblemState
= world/problem knowledge

RuntimeState
= execution/recovery/budget status

SupervisionState
= what the Human sees and controls
```

Recovery를 위해 별도의 canonical state machine을 만들지 않는다.

---

## P31. Retry Must Be Evidence-Bounded and Budget-Bounded

retry는 다음을 동시에 본다.

```text
same problem still valid
+
same action/path still valid
+
failure plausibly transient
+
expected value > retry cost
+
remaining budget preserves minimum verification/release
```

단순히 `retryable=true`가 있다고 계속 retry하지 않는다.

---

## P32. Runtime Detail Is Lazy

모든 Tool call에 거대한 recovery object를 강제하지 않는다.

다음 조건에서만 상세 recovery tracking을 활성화한다.

- important dependency failure
- repeated failure
- partial result
- mutation uncertainty
- fallback activation
- release reserve impact
- verification/release blocking risk

정상적인 low-value read는 compact state만 유지할 수 있다.

---

# 3. High-level Architecture

v0.2.4 Architecture를 그대로 유지한다.

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

v0.2.5는 새로운 layer를 추가하지 않는다.

---

# 4. Canonical State Separation

변경 없음.

```text
ProblemState
= 세상과 문제에 대해 Harness가 알고 있는 것

RuntimeState
= Harness가 지금 무엇을 하고 있으며,
  어떤 execution / recovery / budget 상태에 있는가

SupervisionState
= 사람이 무엇을 보고 있고,
  개입이 필요한가
```

`ApprovalPacket`은 canonical state가 아니라 projection이다.

`Recovery` 역시 별도 canonical state가 아니라 `RuntimeState`의 하위 구조다.

---

# 5. ProblemState

v0.2.4를 그대로 유지한다.

```text
ProblemState
├── meta
├── scenario
├── organizations
├── stakeholders
├── processes
├── process_handoffs
├── entity_identities
├── canonical_mappings
├── data_assets
├── metrics
├── facts
├── claims
├── hypotheses
├── evidence
├── unknowns
├── conflicts
├── assumptions
├── goals
├── constraints
├── risks
├── success_criteria
├── verification_obligations
├── problem_definition
├── solution_design
├── agent_spec
├── execution
├── validation
├── budget
└── decision_log
```

Tool failure 자체를 ProblemState의 canonical Problem invalidation으로 취급하지 않는다.

---

# 6. NEW EXPLICIT — RuntimeState v0.2.5

## 6.1 목적

RuntimeState는 현재 실행 위치뿐 아니라 contest-time recovery와 budget pressure를 판단할 수 있어야 한다.

```text
RuntimeState
├── phase
├── execution_status
├── current_plan
├── current_task
├── current_action
├── next_action
├── current_tool
├── tool_runtime
├── recovery
├── budget_runtime
├── release_runtime
├── pending_protected_action
├── safe_point
├── transition_candidate
└── event_refs
```

---

## 6.2 ToolRuntime

```text
ToolRuntime
├── tool_id
├── operation
├── health
├── attempt
├── last_result_status
├── last_error_class
├── retryable_hint
├── partial_side_effect_possible
├── result_completeness
├── result_authority
├── time_cost
├── cumulative_cost
└── evidence_ref
```

### health

```text
HEALTHY
DEGRADED
UNAVAILABLE
UNKNOWN
```

ToolHealth는 capability availability / reliability를 표현한다.

다음과 동일하지 않다.

```text
ToolHealth
≠ Data Authority
≠ Data Freshness
≠ Semantic Validity
≠ Domain Authorization
```

---

# 7. NEW EXPLICIT — Recovery Runtime

```text
RecoveryRuntime
├── active
├── failure_signature
├── retry_count
├── cumulative_retry_cost
├── retry_eligible
├── retry_stop_reason
├── fallback_available
├── fallback_status
├── fallback_authority
├── fallback_freshness_status
├── partial_result_status
├── mutation_uncertainty
├── candidate_transition
├── decision_rationale
└── linked_vob_ids
```

모든 field를 항상 채울 필요는 없다.

현재 decision에 relevant한 field만 활성화한다.

---

# 8. Failure Signature

동일 failing dependency를 다른 parameter로 호출하여 새 action처럼 보이게 만들지 않는다.

필요 시 lightweight failure signature를 사용한다.

```text
failure_signature
≈
tool_id
+
dependency
+
operation_family
+
error_class
```

목적:

- repeated identical failure 식별
- hidden infinite retry 방지
- parameter variation을 retry count 회피 수단으로 사용하지 못하게 함

정밀 hashing implementation은 설계 freeze 범위가 아니다.

---

# 9. Retry Semantics v0.2.5

v0.2.4 의미를 유지한다.

```text
retry
=
Problem remains valid
+
Action/path remains valid
+
Failure plausibly transient
+
Expected value exceeds retry cost
+
Minimum verify/release budget remains protected
```

## Retry Record

중요 retry만 다음을 기록한다.

```text
RetryRecord
├── tool_id
├── operation
├── attempt
├── failure_signature
├── prior_error
├── retry_reason
├── estimated_retry_cost
├── actual_retry_cost
├── cumulative_retry_cost
├── result
└── stop_after_this
```

정상 retry detail은 Supervision에서 digest할 수 있다.

---

# 10. Retry Stop Conditions

다음 중 하나면 동일 strategy retry를 중단할 수 있다.

```text
- repeated same dependency failure
- expected value <= retry cost
- fallback/replan path has higher EV/time
- result completeness cannot be established
- mutation uncertainty requires read-back first
- remaining budget threatens minimum verification
- release reserve would be violated
```

`max_retry = N`을 architecture constant로 고정하지 않는다.

상황별 evidence와 budget으로 결정한다.

---

# 11. Replan / Reprofile / Redefine

의미 변경 없음.

```text
retry
= 동일 action/strategy가 여전히 유효

replan
= canonical Problem은 유효하지만
  current solution/action path가 더 이상 적절하지 않음

reprofile
= 새로운 critical owner / policy / data / authority /
  identity / handoff evidence가 필요

redefine
= canonical Problem Definition 자체가
  새로운 authoritative Evidence로 무효화됨
```

Tool failure만으로 redefine하지 않는다.

---

# 12. Partial Result Handling

중요 Tool 결과는 필요 시 다음을 본다.

```text
expected_count
returned_count
pagination completeness
missing fields
coverage period
source authority
snapshot age if relevant
```

RuntimeState에는 최소 다음을 보존한다.

```text
result_completeness:
  COMPLETE
  PARTIAL
  UNKNOWN
  NOT_APPLICABLE
```

`200 OK`, `SUCCESS`, `transport ACK SUCCESS`만으로 COMPLETE를 선언하지 않는다.

---

# 13. Fallback Runtime Policy

Fallback 사용 시 필요한 범위에서 다음을 기록한다.

```text
FallbackRuntime
├── source
├── trigger
├── coverage
├── authority
├── completeness
├── freshness_status
├── semantic_difference
├── allowed_usage
└── prohibited_usage
```

예:

```text
allowed:
- historical baseline
- pattern diagnosis
- read-only supporting evidence

prohibited:
- current protected mutation
- authoritative final action
```

Freshness는 decision-relevant할 때만 활성화한다.

---

# 14. Budget Runtime

## 14.1 Soft Budget

유지:

```text
00:00~00:15  Environment / inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

## 14.2 BudgetRuntime

```text
BudgetRuntime
├── total_budget
├── elapsed
├── remaining
├── phase_budget
├── phase_variance
├── variance_reason
├── recovery_action
├── verification_budget_remaining
├── packaging_budget_remaining
└── release_reserve_impact
```

Budget은 display-only countdown이 아니다.

Action selection에 실제 영향을 줘야 한다.

---

# 15. Release Runtime

```text
ReleaseRuntime
├── reserve_threshold
├── reserve_status
├── reserve_entered_at
├── release_blocking_risks
├── dropped_scope
├── kept_scope
├── packaging_status
├── submission_status
└── projected_finish
```

### reserve_status

```text
NOT_ACTIVE
APPROACHING
ACTIVE
AT_RISK
```

Release Reserve 진입 시:

```text
DROP
- NICE_TO_HAVE
- low-value investigation
- broad refactor
- non-blocking feature

KEEP
- release-blocking verification
- authority/safety checks
- packaging
- submission
```

---

# 16. Agent Specification v0.2.5

v0.2.4를 유지하면서 `failure_handling`과 `budget_policy` reference를 명시한다.

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

## failure_handling

```text
failure_handling
├── tool_health_policy
├── retry_policy
├── retry_stop_policy
├── fallback_policy
├── partial_result_policy
├── stale_data_policy
├── mutation_uncertainty_policy
└── replan_reprofile_policy
```

## budget_policy

```text
budget_policy
├── soft_phase_budget
├── verification_floor
├── release_reserve
├── reserve_entry_rule
├── scope_reduction_rule
└── packaging_protection_rule
```

---

# 17. VerificationObligation

v0.2.4 유지.

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

Release Gate는 open VOB의 존재가 아니라 다음 교집합을 본다.

```text
required_before
+
blocking_scope
+
current release scope
```

---

# 18. ProcessHandoff / CanonicalMapping

v0.2.4를 그대로 유지한다.

## ProcessHandoff

필요한 경우만:

```text
acknowledgments[]
delivery_status
semantic_validity
freshness_status
```

## CanonicalMapping

identity resolution이 실제 decision/action에 영향을 줄 때만 사용한다.

Mock #5처럼 identity ambiguity가 없으면 생성하지 않는 것이 정상이다.

---

# 19. Human Supervision

v0.2.4 유지.

Monitoring Importance:

```text
CRITICAL
HIGH
NORMAL
LOW
```

다음은 throttle하지 않는다.

- repeated failure causing strategy change
- release-blocking VOB
- Release Reserve entry
- packaging/submission risk
- Mandatory Human Gate
- authority/safety violation
- canonical Problem invalidation
- Release Gate result

반면 동일 transient failure의 상세 retry log는 digest할 수 있다.

---

# 20. Mandatory Human Gate / ApprovalPacket / REQUEST_CONTEXT

v0.2.4를 유지한다.

```text
Protected Action
→ Domain Authorization Check
→ Scope Validation
→ Runtime Confirmation Required?
→ Safe Point
→ ApprovalPacket
→ WAITING_APPROVAL
→ APPROVE / MODIFY / REJECT / REQUEST_CONTEXT
```

REQUEST_CONTEXT:

```text
REQUEST_CONTEXT
→ WAITING_APPROVAL 유지
→ protected action remains blocked
→ committed Evidence 기반 설명
→ 필요 시 targeted read-only reprofile
→ same gate decision 대기
```

Mock #5에서는 사용자 선택이 APPROVE였기 때문에 REQUEST_CONTEXT는 다시 NOT EXERCISED였다.

이는 Architecture blocker로 보지 않는다.

다만 v0.3 implementation 전 또는 초기 regression에서 짧은 targeted test를 권장한다.

---

# 21. Release Gate v0.2.5

확인:

- Problem Definition PASS / CONDITIONAL_PASS
- required Data availability
- ToolHealth / fallback sufficiency
- Data completeness
- Metric / Success Criteria ↔ test
- retry history / stop semantics
- unresolved critical conflict
- unresolved critical constraint
- VOB blocking_scope intersection
- authority compliance
- runtime confirmation compliance
- REQUEST_CONTEXT trace if exercised
- remaining verification time
- Release Reserve status
- packaging feasibility

결과:

```text
RELEASE
RELEASE_WITH_KNOWN_LIMITATION
HOLD
```

---

# 22. Mock #5 Design Review 반영

## KEEP AS-IS

- ProblemState / RuntimeState / SupervisionState separation
- Information Value
- ProcessHandoff
- layered acknowledgment
- delivery_status / semantic_validity
- freshness lazy semantics
- CanonicalMapping lazy activation
- Metric MINIMAL / EXTENDED
- VerificationObligation + blocking_scope
- Structural Remedy before Agent
- Agent Role Classification
- Agentification Gate
- retry / replan / reprofile / redefine semantics
- Human Supervision Plane
- Monitoring importance / throttling
- Safe Point / Mandatory Human Gate
- ApprovalPacket
- Domain Authorization / Runtime Confirmation separation
- Release Gate

## MODIFY

- RuntimeState recovery/budget execution explicit schema

## ADD

- ToolRuntime
- RecoveryRuntime
- BudgetRuntime
- ReleaseRuntime
- Agent failure_handling policy references
- budget_policy reference

## REMOVE / SIMPLIFY

없음.

---

# 23. v0.2.5 Acceptance Criteria

다음 질문에 답할 수 있어야 한다.

1. 현재 ToolHealth를 RuntimeState에서 표현할 수 있는가?
2. retry attempt history와 cumulative retry cost를 추적할 수 있는가?
3. 동일 failing dependency를 parameter variation으로 숨기지 않는가?
4. partial result completeness를 표현할 수 있는가?
5. retry stop condition을 evidence와 budget으로 설명할 수 있는가?
6. fallback activation trigger를 표현할 수 있는가?
7. fallback authority / freshness / allowed usage를 분리할 수 있는가?
8. release reserve 상태를 RuntimeState에 표현할 수 있는가?
9. budget variance와 recovery action을 기록할 수 있는가?
10. retry/replan/reprofile/redefine 의미가 변하지 않는가?
11. Tool failure가 Problem redefine으로 오인되지 않는가?
12. Release Reserve가 실제 scope reduction을 유도하는가?
13. minimum verification budget이 보호되는가?
14. VOB blocking_scope가 safe partial release를 지원하는가?
15. Human Gate state semantics가 유지되는가?
16. APPROVE 이후 scope / authorization을 다시 확인하는가?
17. REQUEST_CONTEXT가 approval로 오인되지 않는가?
18. Runtime recovery explicitness가 새 state machine을 만들지 않는가?
19. 5시간 contest에서 runtime tracking overhead가 과도하지 않은가?
20. v0.3 Design Freeze baseline으로 사용할 수 있는가?

---

# 24. v0.3 Design Freeze 준비 판단

Mock #5 결과:

```text
core architecture flaw        NONE
retry semantics               PASS
replan semantics              PASS
reprofile semantics           PASS
redefine misuse               NONE
budget behavior               PASS
release reserve               PASS
VOB blocking_scope            PASS
human gate                    PASS
REQUEST_CONTEXT               NOT EXERCISED
local runtime explicitness    MINOR PATCH NEEDED
```

따라서 v0.2.5 적용 후:

```text
→ v0.3 Core Design Freeze 진행 가능
```

REQUEST_CONTEXT는 short targeted regression으로 별도 검증할 수 있으며,
이 항목 하나만으로 structural freeze를 막지 않는다.

---

# 25. Development Roadmap v0.2.5

```text
Stage 0  v0.2 baseline                  DONE
Stage 1  Mock #1                        DONE
Stage 2  v0.2.1                         DONE
Stage 3  Mock #2                        DONE
Stage 4  v0.2.2                         DONE
Stage 5  Mock #3                        DONE
Stage 6  v0.2.3                         DONE
Stage 7  Mock #4                        DONE
Stage 8  v0.2.4                         DONE
Stage 9  Mock #5                        DONE
Stage 10 v0.2.5 Final Minor Patch       CURRENT
Stage 11 REQUEST_CONTEXT short regression
Stage 12 v0.3 DESIGN FREEZE
Stage 13 Core State / Event / Runtime implementation
Stage 14 DISCOVER + DATA
Stage 15 DEFINE
Stage 16 DESIGN
Stage 17 EXECUTE
Stage 18 VERIFY / RELEASE
Stage 19 Human Supervision CLI
Stage 20 Mock #6 implementation regression
Stage 21 Contest Adapter
```

Mock #6은 freeze 전 structural blocker가 아니라,
frozen design의 `redefine / state versioning / Evidence Revision` implementation regression으로 수행할 수 있다.

---

# 26. v0.2.5 최종 정의

> **AI TOP 100 Harness v0.2.5는 v0.2.4의 Core Architecture를 그대로 유지하면서, Severe Time Pressure + Tool Failure 상황에서 필요한 Runtime recovery와 budget execution semantics를 명시적으로 보강한 마지막 minor design baseline이다. ToolHealth, retry history/cost, partial result completeness, fallback 상태, budget variance, Release Reserve 상태를 RuntimeState 내부의 lightweight 구조로 관리하며, 새로운 state machine을 추가하지 않는다. 이를 통해 retry / replan / reprofile / redefine 구분, minimum useful release, VOB blocking_scope, Human Gate, verification/packaging 보호를 구현 단계에서도 재현할 수 있도록 한다.**

핵심:

```text
Keep the architecture.
Make recovery explicit.
Bound retry by evidence and budget.
Treat partial success as partial until proven complete.
Use fallback only within its authority.
Protect verification and release reserve.
Do not redefine the problem because a tool failed.
Do not create a fourth canonical state.
Freeze after this patch.
```

---

# 27. Version Decision

```text
v0.2.4 유지
→ Runtime recovery explicitness 부족

v0.2.5 minor patch
→ 선택

v0.3 수준 structural redesign
→ 필요 없음

v0.3 Design Freeze
→ v0.2.5 반영 후 진행
```

본 문서를 **v0.3 Design Freeze 직전 최종 Minor Patch Baseline**으로 사용한다.

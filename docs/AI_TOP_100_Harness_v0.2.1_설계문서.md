# AI TOP 100 Harness v0.2.1 설계 문서

**Version:** v0.2.1  
**Status:** Mock #1 반영 Design Patch / Mock #2 전 Baseline  
**Previous:** v0.2  
**Purpose:** AI TOP 100 [2026] 예선에서 주어진 현장 상황을 빠르게 이해하고, 관계자 인터뷰와 획득 데이터를 통해 실제 문제를 정의한 뒤, 문제특화 AI Agent를 설계·구축·검증할 수 있도록 지원하는 범용 Harness 설계  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Important:** 실제 제출 형식, 실행 API, hidden test 구조, 허용 Tool 세부 규칙 등은 아직 확정 정보로 취급하지 않는다.  
**Patch Basis:** Mock #1 — Conflicting Stakeholders + Dirty Data 수동/하네스 주도 시뮬레이션 결과

---

# 0. v0.2.1의 목적

v0.2.1은 v0.2의 전체 Architecture를 재설계하는 버전이 아니다.

Mock #1 결과 다음 핵심 구조는 실제 문제 해결 과정에서 유효했다.

```text
DISCOVER
   ↓
DEFINE
   ↓
DESIGN
   ↓
EXECUTE
   ↓
VERIFY / RELEASE
```

또한 다음 설계 철학도 유지한다.

- Organization / Stakeholder / Business Process / DataAsset을 분리한다.
- Fact / Claim / Evidence / Hypothesis를 혼합하지 않는다.
- Data는 전 Phase를 가로지르는 Workspace로 관리한다.
- Raw Data를 보존한다.
- 중요한 판단은 Evidence 또는 명시적 Assumption과 연결한다.
- deterministic automation이 가능한 것은 LLM에 맡기지 않는다.
- 제한시간 안에 검증 가능한 최소 Agent를 만든다.
- Human은 모든 행동을 승인하는 operator가 아니라, Harness를 실시간 감시하고 필요할 때 개입하는 supervisor가 된다.

v0.2.1의 목표는 Mock #1에서 발견된 schema / monitoring / deferred verification / cross-organization handling의 gap을 보강하는 것이다.

---

# 1. Mock #1에서 확인된 핵심 결론

Mock #1은 다음 문제 구조를 사용했다.

```text
Two Organizations
+
Conflicting Stakeholder Claims
+
Cross-Organization Process
+
Dirty / Inconsistent Data
+
Hidden Root Problem
```

초기 표면 문제는 외부 서비스 조직의 처리 시간이 느리다는 것이었으나, 실제 분석 과정에서는 다음 요소가 dominant problem으로 나타났다.

```text
Cross-organization handoff
+
heterogeneous identifiers
+
registry inconsistency
+
manual reconciliation
+
manual status synchronization
```

Mock #1 결과 v0.2의 큰 흐름은 유효했으나 다음 7개 개선이 필요하다고 판단했다.

1. Metric Semantics 강화
2. ProcessHandoff first-class 구조화
3. EntityIdentity / CanonicalMapping 추가
4. VerificationObligation 추가
5. Duplicate / Event Semantics 세분화
6. DEFINE Gate / Authority / Success Criteria / Transition 의미 보강
7. Human Supervision Plane — Real-time Monitoring + Interrupt / Override

따라서 v0.2.1은 `v0.3 수준 구조 변경`이 아니라 `v0.2.x Design Patch`로 정의한다.

---

# 2. v0.2 → v0.2.1 변경 요약

| 영역 | v0.2 | v0.2.1 |
|---|---|---|
| 전체 Flow | DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY | 유지 |
| Data Workspace | 전 Phase 횡단 | 유지 |
| Metric | definition/current/target/source 중심 | start/end event, population, window, denominator, aggregation, exclusions, owner 추가 |
| Process Handoff | BusinessProcess.handoffs 내부 비정형 | `ProcessHandoff` first-class state |
| Entity Identity | DataAsset/Transformation으로 간접 표현 | `EntityIdentity`, `Identifier`, `CanonicalMapping` 추가 |
| Deferred Unknown | Assumption/Unknown으로만 유지 | `VerificationObligation` 명시 |
| Duplicate | generic duplicate | exact duplicate / business-key collision / event version / status progression 구분 |
| Authority Constraint | generic constraint | protected action / approval / enforcement 명시 |
| Success Criteria | ProblemDefinition에 존재 | DEFINE Gate에서 target/predicate 존재 여부 검사 |
| redefine | root problem invalidation | ProblemDefinition 생성 이후에만 redefine 사용 |
| Observability | current state 위주 | State Diff / Decision Rationale / Evidence Revision / Gate Rationale 추가 |
| Human Control | Human-controllable 원칙 | `Human Supervision Plane` + pause / interrupt / step / override / resume |
| Mock execution | Human operator 중심 가능 | Harness-driven + Human-on-the-loop를 기본 모드로 권장 |

---

# 3. Executive Summary

AI TOP 100 Harness v0.2.1의 목표는 다음과 같다.

> **주어진 현장 Scenario에서 조직, 사람, 업무 프로세스, 데이터, 조직 간 handoff와 entity identity를 함께 구조화하고, 관계자 인터뷰와 데이터 검증을 통해 실제 문제를 정의한 뒤, 제한시간 안에 검증 가능한 최소 AI Agent를 설계·구축·검증하고, 사람이 그 과정을 실시간으로 감시·중단·수정할 수 있게 하는 것.**

핵심 실행 Flow는 유지한다.

```text
DISCOVER
   ↓
DEFINE
   ↓
DESIGN
   ↓
EXECUTE
   ↓
VERIFY / RELEASE
```

모든 Phase를 두 개의 cross-cutting plane이 가로지른다.

```text
                     ┌──────────────────────┐
                     │    DATA WORKSPACE    │
                     │ Acquire              │
                     │ Inspect              │
                     │ Validate             │
                     │ Clean                │
                     │ Normalize            │
                     │ Transform            │
                     │ Trace                │
                     └──────────▲───────────┘
                                │
DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY
    │          │        │         │         │
    └──────────┴────────┴─────────┴─────────┘
                                │
                     ┌──────────▼───────────┐
                     │ HUMAN SUPERVISION    │
                     │ Live State           │
                     │ State Diff           │
                     │ Evidence Basis       │
                     │ Decision Rationale   │
                     │ Interrupt / Override │
                     └──────────────────────┘
```

Data Workspace는 문제와 데이터를 지속적으로 추적한다.

Human Supervision Plane은 Harness의 자율 수행을 방해하지 않으면서, 사람이 실시간으로 현재 판단·근거·다음 행동을 확인하고 필요할 때 개입할 수 있게 한다.

---

# 4. Design Principles v0.2.1

## P1. Zero-base
기존 CareerGround, intent-loop, loop-engine의 코드를 재사용하지 않는다. 개념만 참고한다.

## P2. Domain-agnostic
특정 농산물/수산물/재고/판매 schema를 Core에 넣지 않는다.

## P3. Minimal Core
Core는 Phase, State, Transition, Budget, Event, Contract, Tool Policy, Supervision control을 담당한다.

## P4. Evidence-driven
중요한 판단은 Evidence 또는 명시적 Assumption과 연결한다.

## P5. Process-aware
문제를 사람의 불편함이 아니라 실제 Process 병목으로 구조화한다.

## P6. Data-aware
DataAsset의 출처, 품질, 변환 이력, 사용처를 1급 상태로 관리한다.

## P7. Provenance-first
Fact, Claim, Evidence, DataAsset, Mapping, Transformation, Recommendation 모두 source traceability를 유지한다.

## P8. State-driven
대화 transcript 자체를 system state로 사용하지 않는다.

## P9. Platform-independent
Core와 Contest Adapter를 분리한다.

## P10. Human-controllable
사람이 현재 판단, 실패 이유, 다음 행동을 이해하고 개입할 수 있어야 한다.

## P11. Deterministic-first Verification
기계적으로 검증 가능한 것은 LLM에 맡기지 않는다.

## P12. Fail-visible
실패를 숨기거나 성공으로 포장하지 않는다.

## P13. Budget-aware
5시간 안에 제출 가능한 결과를 만드는 것이 최우선이다.

## P14. Local Loop over Universal Loop
Discovery loop와 Execution loop의 목적을 분리한다.

## P15. Append History, Derive Current View
이력을 삭제하지 않고 current view를 projection으로 생성한다.

## P16. Identity before Join
조직 간 데이터를 결합하기 전에 identifier의 namespace, uniqueness, mapping confidence를 확인한다.

## P17. Defer Explicitly, Never Forget
CONDITIONAL_PASS로 미룬 Unknown은 VerificationObligation으로 승계한다.

## P18. Autonomous by Default, Interruptible by Design
Harness는 정상 상황에서 자율적으로 진행하되, 사람은 실시간으로 상태를 보고 안전하게 pause / interrupt / override할 수 있어야 한다.

## P19. Safe Interrupt
Human interrupt는 state corruption을 만들지 않는 safe point에서 적용한다.

---

# 5. High-level Architecture v0.2.1

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│                          CONTEST ENVIRONMENT                                 │
│ Scenario / Stakeholders / Files / Tables / Media / Interfaces / Rules       │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                             Contest Adapter
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                             HARNESS CORE                                     │
│                                                                              │
│ ┌───────────────────┐      ┌──────────────────────────────────────────────┐   │
│ │ Phase Controller  │◄────►│ Problem Workspace                            │   │
│ └─────────┬─────────┘      │ Canonical State / Versions / Events          │   │
│           │                └──────────────────────────────────────────────┘   │
│           │                                                                  │
│ ┌─────────▼──────────────────────────────────────────────────────────────┐   │
│ │ Skill Layer                                                           │   │
│ │ DISCOVER      DEFINE       DESIGN       EXECUTE        VERIFY          │   │
│ │ profile       synthesize   strategy     action         tests           │   │
│ │ interview     gate         agent spec   failure route  judge           │   │
│ │ process map   metric       trace        execution      release         │   │
│ └─────────┬──────────────────────────────────────────────────────────────┘   │
│           │                                                                  │
│ ┌─────────▼──────────────────────────────────────────────────────────────┐   │
│ │ Data Workspace                                                        │   │
│ │ Inventory / Inspect / Validate / Clean / Normalize / Transform         │   │
│ │ Entity Identity / Canonical Mapping / Provenance / Quality             │   │
│ └─────────┬──────────────────────────────────────────────────────────────┘   │
│           │                                                                  │
│ ┌─────────▼──────────────┐  ┌───────────────────────────────────────────┐    │
│ │ Tool Registry         │  │ Budget / Runtime / Event Log              │    │
│ │ LLM/file/web/python   │  │ time / safe point / failure / reserve     │    │
│ │ shell/API/coding      │  │ verification obligations                  │    │
│ └───────────────────────┘  └───────────────────────────────────────────┘    │
│                                                                              │
│ ┌────────────────────────────────────────────────────────────────────────┐   │
│ │ HUMAN SUPERVISION PLANE                                                │   │
│ │ Live Monitor / State Diff / Decision Rationale / Evidence Basis        │   │
│ │ Gate Rationale / Pending Obligations / Pause / Interrupt / Override    │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                                OUTPUTS                                       │
│ Problem Definition Package                                                  │
│ Process / Handoff / Data Understanding Package                              │
│ Agent Specification                                                         │
│ Contest Agent                                                               │
│ Verification Report                                                         │
│ Human-readable Audit / Trace                                                 │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

# 6. Canonical State Separation

v0.2.1은 문제 상태와 실행/감시 상태를 분리한다.

```text
ProblemState
= 세상과 문제에 대해 Harness가 알고 있는 것

RuntimeState
= Harness가 지금 무엇을 하고 있는가

SupervisionState
= 사람이 무엇을 보고 있고, 개입이 필요한가
```

이 셋은 연결되지만 동일 객체로 합치지 않는다.

---

# 7. ProblemState v0.2.1

```text
ProblemState
├── meta
├── scenario
├── organizations
├── stakeholders
├── processes
├── process_handoffs
├── entity_identities
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

---

# 8. Organization

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

원칙:

- Organization과 Stakeholder를 분리한다.
- 동일 Process가 여러 조직을 가로지를 수 있다.
- 조직 간 handoff 자체가 bottleneck일 수 있다.
- 동일 entity가 조직마다 다른 identifier를 가질 수 있다.

---

# 9. Stakeholder

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

중요 원칙:

> **Authority ≠ Accuracy**

관리자라는 이유로 현장 직원보다 정확하다고 가정하지 않는다.

---

# 10. BusinessProcess

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

## 10.1 ProcessStep

```text
ProcessStep
├── id
├── sequence
├── action
├── actor
├── accountable_owner
├── system
├── input_data
├── output_data
├── duration
├── wait_time
├── error_rate
├── manual_or_automated
├── authority_required
└── observed_issue
```

`actor`와 `accountable_owner`를 분리한다.

```text
actor
= 실제 수행자

accountable_owner
= 결과에 최종 책임을 갖는 주체
```

---

# 11. NEW — ProcessHandoff

Mock #1에서 Root Problem은 조직 내부 step보다 조직 사이 handoff에서 더 강하게 나타났다.

따라서 v0.2.1에서 ProcessHandoff를 first-class state로 추가한다.

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
├── acknowledgment
├── expected_latency
├── actual_latency
├── manual_or_automated
├── authority_boundary
├── failure_modes
├── evidence_refs
├── metric_refs
└── status
```

예:

```text
HRC
  ↓ batch service request
ProcessHandoff H-01
  ↓
AMP Dispatch
```

다음 질문에 답할 수 있어야 한다.

- 누가 누구에게 넘기는가?
- 무엇을 넘기는가?
- 어떤 identifier를 사용하는가?
- 즉시인가 batch인가?
- 수신자가 받았음을 확인하는가?
- handoff latency는 얼마인가?
- failure 시 누가 책임지는가?

---

# 12. DataAsset

```text
DataAsset
├── id
├── name
├── organization_id
├── source
├── source_type
├── format
├── acquisition
├── raw_reference
├── schema
├── quality
├── issues
├── transformations
├── normalized_reference
├── validation
├── provenance
└── used_by
```

## 12.1 Data Quality

```text
DataQuality
├── completeness
├── validity
├── consistency
├── uniqueness
├── timeliness
└── interpretability
```

초기 값:

```text
GOOD
ACCEPTABLE
PROBLEMATIC
UNKNOWN
```

---

# 13. MODIFY — Data Issue Semantics

v0.2의 generic `duplicate`는 실제 운영 event를 손상시킬 위험이 있다.

v0.2.1에서는 다음과 같이 구분한다.

```text
DataIssueType
├── MISSING
├── INVALID
├── INCONSISTENT
├── MALFORMED
├── STALE
├── OUTLIER
├── AMBIGUOUS
├── UNEXPECTED_TYPE
├── JOIN_FAILURE
├── CONTRADICTORY_RECORD
├── EXACT_RECORD_DUPLICATE
├── DUPLICATE_BUSINESS_KEY
├── KEY_COLLISION
├── EVENT_VERSION
└── STATUS_PROGRESSION
```

예:

```text
동일 row가 두 번 존재
→ EXACT_RECORD_DUPLICATE

같은 job_id가 in_progress → completed
→ STATUS_PROGRESSION

같은 serial이 서로 다른 asset에 존재
→ KEY_COLLISION
```

단순 dedupe는 금지한다.

---

# 14. Transformation History

```text
Transformation
├── id
├── operation
├── reason
├── input_reference
├── output_reference
├── deterministic
├── reversible
├── affected_rows
├── affected_fields
└── validation_result
```

원칙:

```text
RAW
 ↓
INSPECT
 ↓
VALIDATE
 ↓
CLEAN / NORMALIZE
 ↓
TRANSFORMED
```

Raw Data는 덮어쓰지 않는다.

---

# 15. NEW — EntityIdentity / CanonicalMapping

조직 간 데이터를 결합할 때 physical/logical entity를 identifier와 분리한다.

## 15.1 EntityIdentity

```text
EntityIdentity
├── id
├── entity_type
├── canonical_id
├── organization_ids
├── identifiers
├── mapping_ids
├── conflicts
├── status
└── provenance
```

## 15.2 Identifier

```text
Identifier
├── value
├── namespace
├── organization_id
├── source_id
├── valid_from
├── valid_to
├── normalized_value
├── uniqueness
└── quality
```

예:

```text
canonical asset: HW-1003

identifiers:
- HRC asset_id: HW-1003
- AMP service_alias: AS-003
- observed variant: AS003
- serial_no: SN-A-003
```

## 15.3 CanonicalMapping

```text
CanonicalMapping
├── id
├── source_identifier
├── target_entity_id
├── method
├── deterministic
├── confidence
├── evidence_refs
├── conflict_refs
├── validated
└── status
```

`confidence` 예:

```text
HIGH
MEDIUM
LOW
UNRESOLVED
```

규칙:

```text
exact unique mapping
→ HIGH

normalized exact mapping
→ HIGH if deterministic rule validated

unique serial mapping
→ allowed

non-unique serial
→ UNRESOLVED

stakeholder free-text only
→ candidate mapping, not final mapping
```

---

# 16. MODIFY — Metric Semantics

Mock #1에서 동일한 `turnaround`라는 용어가 조직마다 다른 clock을 의미했다.

v0.2.1 Metric은 다음으로 확장한다.

```text
Metric
├── id
├── name
├── related_process
├── related_handoff
├── definition
├── unit
├── start_event
├── end_event
├── population
├── denominator
├── aggregation
├── measurement_window
├── exclusions
├── current_value
├── target_value
├── measurement_source
├── owner
└── reliability
```

예:

```text
Metric A
name: return_to_bookable
start_event: return / needs_service
end_event: available

Metric B
name: service_turnaround
start_event: job_opened
end_event: job_completed
```

둘 다 turnaround라고 불러도 동일 Metric이 아니다.

---

# 17. Evidence Model

```text
Evidence
├── id
├── source_type
├── source_id
├── provenance
├── content
├── target_assertion
├── relation
├── reliability
├── extraction_confidence
└── interpretation_history
```

`interpretation_history`를 추가한다.

같은 Evidence가 새로운 Process/Event 정보로 인해 다르게 해석될 수 있기 때문이다.

예:

```text
E-09
initial interpretation:
possible admin delay

new evidence:
physical return occurred late

revised interpretation:
admin delay cannot be isolated
```

---

# 18. Data-to-Evidence Traceability

```text
Raw Data
   ↓
Transformation
   ↓
Validated Data
   ↓
Entity Mapping
   ↓
Evidence
   ↓
Hypothesis
   ↓
Problem Definition
   ↓
Agent Capability
   ↓
Verification
```

---

# 19. DISCOVER v0.2.1

DISCOVER는 다음 네 축을 유지한다.

```text
PEOPLE
PROCESS
DATA
OUTCOME
```

그리고 v0.2.1에서는 다음 두 질문을 명시적으로 추가한다.

```text
IDENTITY
- 여러 조직이 같은 entity를 어떤 identifier로 부르는가?

HANDOFF
- 조직 경계를 넘을 때 무엇이, 누구에게, 어떤 cadence로 전달되는가?
```

따라서 실제 탐색은 다음처럼 본다.

```text
PEOPLE
PROCESS
HANDOFF
DATA
IDENTITY
OUTCOME
```

---

# 20. Interview Framework v0.2.1

기존 다섯 질문 유형을 유지한다.

1. Problem Questions
2. Process Questions
3. Data Questions
4. Constraint Questions
5. Success Questions

v0.2.1에서 두 범주를 추가한다.

## F. Handoff Questions

- 앞 단계 결과를 누구에게 전달하는가?
- 즉시 전달하는가, 일정량을 모아 전달하는가?
- 수신 확인이 있는가?
- 전달 실패를 어떻게 아는가?
- handoff가 완료됐다고 누가 판단하는가?

## G. Identity Questions

- 동일 asset/customer/order를 조직별로 어떤 key로 식별하는가?
- alias나 serial이 있는가?
- identifier가 항상 unique한가?
- 동일 identifier가 재사용될 수 있는가?
- mapping table은 누가 관리하는가?

---

# 21. Information Value

질문 우선순위 기준은 유지한다.

1. Decision Impact
2. Uncertainty
3. Discriminative Power
4. Answerability
5. Cost
6. Process Impact
7. Data Impact

v0.2.1 Human Supervision에서는 Question Selector의 결과에 `Decision Rationale`을 함께 생성한다.

예:

```text
NEXT ACTION
Interview HRC Data Analyst

WHY
Decision Impact     HIGH
Uncertainty         HIGH
Discriminative      HIGH
Process Impact      HIGH
Data Impact         HIGH
Cost                LOW
```

정밀 numeric scoring은 사용하지 않는다.

---

# 22. Epistemic Loop

```text
Unknown / Hypothesis
        ↓
Select Highest-Value Question / Data Action
        ↓
Ask Stakeholder / Inspect Data
        ↓
Extract Claim / Evidence
        ↓
Update Process / Handoff / Identity / Data / Belief
        ↓
Detect Conflict
        ↓
Create State Diff
        ↓
Assess Sufficiency
        ↺
```

Harness-driven mode에서는 위 loop를 Harness가 수행한다.

Human은 기본적으로 개별 질문을 직접 선택하지 않는다.

---

# 23. Conflict v0.2.1

```text
ConflictType
├── CLAIM_CONFLICT
├── DATA_CONFLICT
├── PROCESS_CONFLICT
├── HANDOFF_CONFLICT
├── IDENTITY_CONFLICT
├── CONSTRAINT_CONFLICT
├── GOAL_CONFLICT
└── METRIC_CONFLICT
```

Conflict는 반드시 다음을 가진다.

```text
Conflict
├── id
├── type
├── side_a
├── side_b
├── decision_impact
├── gate_blocking
├── evidence_refs
├── resolution_strategy
└── status
```

모든 Conflict를 해결해야 DEFINE Gate를 통과하는 것은 아니다.

`decision_impact`가 낮고 Verification/Exception handling으로 안전하게 관리할 수 있으면 CONDITIONAL_PASS 가능하다.

---

# 24. MODIFY — Constraint / Authority

Generic Constraint를 다음처럼 강화한다.

```text
Constraint
├── id
├── type
├── description
├── actor
├── protected_action
├── enforcement
├── approval_required
├── violation_behavior
├── evidence_refs
└── status
```

`type` 예:

```text
AUTHORITY
PRIVACY
TOOL_ACCESS
NETWORK
TIME
DATA_EXPORT
HUMAN_APPROVAL
SAFETY
```

예:

```text
Constraint
 type: AUTHORITY
 protected_action: inventory_write
 actor: authorized_branch_coordinator
 approval_required: true
 violation_behavior: block
```

---

# 25. Problem Definition Gate v0.2.1

## Organization
- 해결 대상 조직이 명확한가?

## Actor
- 영향을 받는 Stakeholder가 명확한가?

## Process
- 문제와 연결된 Business Process가 식별되었는가?
- 문제 Step을 설명할 수 있는가?

## Handoff
- cross-org handoff가 있다면 from/to/payload가 최소한 알려져 있는가?
- 중요한 handoff failure가 식별되었는가?

## Identity
- 여러 조직 데이터를 연결해야 한다면 entity identity 전략이 있는가?
- critical identity ambiguity가 관리 가능한가?

## Data
- 필요한 DataAsset이 알려져 있는가?
- 품질을 최소한 평가했는가?
- 데이터 자체가 문제 원인인지 구분했는가?

## Problem
- symptom과 root problem이 구분되었는가?

## Evidence
- 핵심 Problem statement가 Evidence와 연결되었는가?

## Unknown
- critical Unknown이 남아 있는가?

## Conflict
- unresolved critical Conflict가 있는가?

## Metric
- baseline 또는 성공 판단 방법이 있는가?
- Metric의 start/end event 또는 scope가 충분히 정의됐는가?

## Constraint
- 주요 실행/권한 제약이 알려져 있는가?

## Success Criteria
- target 또는 pass/fail predicate가 존재하는가?
- 없으면 명시적 VerificationObligation으로 승계했는가?

---

# 26. Gate Result

## PASS
Solution 설계에 필요한 정보가 충분하다.

## CONDITIONAL_PASS
불확실성이 남아 있지만 다음 조건을 만족한다.

- Assumption 또는 Unknown으로 명시됨
- 실패 시 영향 이해
- 추가 Discovery 가치가 제한적
- Verification 방법 존재
- 필요한 경우 VerificationObligation이 생성됨

## FAIL
추가 DISCOVER가 필요하다.

---

# 27. NEW — VerificationObligation

CONDITIONAL_PASS에서 미룬 Unknown을 잊지 않도록 하는 구조다.

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
├── status
└── resolution
```

`status` 예:

```text
OPEN
IN_PROGRESS
PARTIALLY_VERIFIED
CLOSED
ACCEPTED_LIMITATION
```

Flow:

```text
Unknown
 ↓
CONDITIONAL_PASS
 ↓
VerificationObligation 생성
 ↓
DESIGN
 ↓
EXECUTE
 ↓
VERIFY
 ↓
Release Gate에서 obligation 검사
```

원칙:

> **Deferred does not mean forgotten.**

---

# 28. Problem Definition Package v0.2.1

```text
ProblemDefinition
├── organizations
├── affected_stakeholders
├── affected_process
├── affected_handoffs
├── current_state
├── observed_gap
├── root_problem
├── supporting_evidence
├── contradictory_evidence
├── relevant_data_assets
├── entity_identity_notes
├── data_quality_notes
├── desired_state
├── metrics
├── constraints
├── assumptions
├── risks
├── success_criteria
├── verification_obligation_ids
└── non_goals
```

---

# 29. DESIGN v0.2.1

Planner의 목표:

> **현재 Process, Handoff, Identity, Data, Authority를 이해한 상태에서 Success Criteria를 만족하는 최소 Agent를 설계한다.**

---

# 30. Agentification Gate

```text
Can deterministic automation solve this subtask?
        ↓ yes
Deterministic component
        ↓ no
Does LLM reasoning add value?
        ↓ yes
LLM Skill
        ↓
Does autonomous iteration add value?
        ↓ yes
Agent Loop
```

Agent라는 제출물이 요구되더라도 모든 내부 step을 agentic하게 만들지 않는다.

---

# 31. Solution Strategy

```text
strategy
├── addressed_problem
├── affected_process
├── affected_handoffs
├── required_data
├── entity_identity_requirements
├── agent_capabilities
├── deterministic_components
├── llm_components
├── tools
├── authority_boundary
├── expected_benefit
├── implementation_cost
├── validation_method
├── verification_obligations
└── risks
```

전략 후보는 1~3개로 제한한다.

---

# 32. Agent Specification v0.2.1

```text
AgentSpec
├── identity
│   ├── name
│   ├── purpose
│   └── problem_reference
├── organization_context
├── process_context
├── handoff_context
├── interface
│   ├── inputs
│   ├── outputs
│   └── contracts
├── data
│   ├── required_assets
│   ├── validation_rules
│   └── allowed_transformations
├── entity_identity
│   ├── namespaces
│   ├── normalization_rules
│   ├── mapping_rules
│   └── ambiguity_policy
├── state
├── capabilities
├── tools
├── workflow
├── decision_rules
├── constraints
├── authority_boundary
├── failure_handling
├── termination
├── validation
├── verification_obligations
└── success_criteria
```

---

# 33. Traceability v0.2.1

필수 연결:

```text
Problem Definition
      ↓
Affected Process / Handoff
      ↓
Success Criteria
      ↓
Agent Capability
      ↓
Required Data / Identity
      ↓
Task / Tool
      ↓
Validation Test
```

또한:

```text
DataAsset
   ↓
Transformation
   ↓
Canonical Mapping
   ↓
Evidence
   ↓
Hypothesis
```

그리고 CONDITIONAL_PASS에서는:

```text
Unknown
   ↓
VerificationObligation
   ↓
Instrumentation / Test
   ↓
Verification Result
```

---

# 34. EXECUTE — Action Loop

```text
Current Execution State
        ↓
Decide Next Action
        ↓
[SAFE POINT]
        ↓
Execute Tool / Skill
        ↓
Observe
        ↓
[SAFE POINT]
        ↓
Validate
        ↓
Update State / Data
        ↓
Create State Diff
        ↓
[SAFE POINT]
        ↓
Transition
```

---

# 35. Transition Rules v0.2.1

## retry
같은 전략과 action이 유효하고 transient failure일 때.

## replan
Problem은 맞지만 Solution path / decision rule / task path가 잘못됐을 때.

## reprofile
정보가 부족하거나 새로운 critical Unknown이 발견되었을 때.

재탐색은 필요한 범위로 제한한다.

## redefine
**이미 canonical Problem Definition이 존재한 이후**, 새로운 Evidence가 root problem 자체를 무효화할 때.

Problem Definition 이전 dominant hypothesis 변경은 `hypothesis_changed`로 처리한다.

## abort
최소 제출 가능 결과조차 만들 수 없을 때.

## finish
Release Gate 통과 시.

---

# 36. Data Failure Routing

```text
Data missing
    ↓
Can alternative source answer?
    ├─ yes → acquire
    └─ no  → assumption / redesign / VerificationObligation

Data invalid
    ↓
Can deterministic cleaning fix?
    ├─ yes → clean + validate
    └─ no  → reprofile / redesign

Join failure
    ↓
Check entity identity / namespace
    ↓
Resolve mapping or mark unavailable

Conflicting records
    ↓
Create conflict
    ↓
Determine decision impact

Non-unique identifier
    ↓
Do not auto-resolve
    ↓
Human review / alternative evidence
```

---

# 37. Verification Architecture v0.2.1

## Layer 1 — Deterministic Validation

항상 우선한다.

- schema validity
- required files
- row count
- missing values
- duplicate semantics
- invalid types
- transformation result
- canonical mapping validity
- timestamp order
- rule compliance
- threshold
- authority boundary
- provenance completeness

## Layer 2 — LLM-as-a-Judge

semantic quality에만 사용한다.

- exception explanation 품질
- stakeholder 요청 충족 여부
- context 누락 여부
- Problem Definition 정합성

## Layer 3 — Human Review

다음에 사용한다.

- high-impact ambiguity
- unresolved identity mapping
- protected write/action
- final release decision when required

---

# 38. Verification Obligation Handling

VERIFY 시작 시 모든 OPEN obligation을 inventory한다.

```text
OPEN obligations
      ↓
Can verify now?
  ├─ yes → test / evidence
  └─ no
      ↓
Can instrument future measurement?
  ├─ yes → instrumentation requirement
  └─ no  → ACCEPTED_LIMITATION or HOLD
```

Release Gate에서 OPEN obligation을 무시할 수 없다.

---

# 39. Synthetic Test v0.2.1

최소 test 유형:

- happy path
- missing field
- exact duplicate
- duplicate business key
- status progression
- invalid type
- contradictory data
- ambiguous stakeholder instruction
- unavailable tool
- timeout
- unsupported request
- cross-organization mismatch
- stale data
- constraint violation
- non-unique identifier
- conflicting identity mapping
- event-order reversal
- outdated event overriding newer state
- human interrupt during execution
- resume after safe pause

---

# 40. Release Gate v0.2.1

다음을 확인한다.

- Problem Definition PASS 또는 명시적 CONDITIONAL_PASS
- Agent I/O contract 동작
- 필요한 DataAsset 접근 가능
- Data validation 수행
- critical transformation 검증
- Entity mapping policy 검증
- Success Criteria와 test 연결
- deterministic tests 통과
- unresolved critical conflict 없음
- authority boundary 준수
- VerificationObligation 처리 상태 확인
- known limitation 기록
- Contest Adapter packaging 가능
- 남은 시간 내 제출 가능

결과:

```text
RELEASE
RELEASE_WITH_KNOWN_LIMITATION
HOLD
```

`RELEASE_WITH_KNOWN_LIMITATION`은 남은 obligation이 명시적으로 limitation으로 전환되고 안전한 경우에만 가능하다.

---

# 41. NEW — RuntimeState

```text
RuntimeState
├── phase
├── execution_status
├── current_plan
├── current_task
├── current_action
├── next_action
├── current_tool
├── current_safe_point
├── last_tool_result
├── failure_reason
├── transition_reason
├── elapsed_time
├── time_remaining
├── release_reserve_state
└── validation_status
```

`execution_status` 예:

```text
IDLE
RUNNING
PAUSE_REQUESTED
PAUSED
INTERRUPTED
WAITING_APPROVAL
FAILED
FINISHED
```

---

# 42. NEW — Human Supervision Plane

Human Supervision Plane은 UI 자체가 아니라 Harness core operational capability다.

목적:

> **Harness가 자율적으로 작업하는 동안 사람이 현재 판단·근거·변화를 실시간으로 확인하고, 필요한 순간에만 안전하게 개입한다.**

## 42.1 SupervisionState

```text
SupervisionState
├── mode
├── live_summary
├── current_problem
├── top_hypotheses
├── critical_unknowns
├── critical_conflicts
├── data_quality_warnings
├── key_evidence
├── evidence_revisions
├── state_diff
├── decision_rationale
├── gate_rationale
├── pending_verification_obligations
├── current_action
├── next_action
├── intervention
└── human_control
```

## 42.2 mode

```text
AUTO
STEP
PAUSED
HUMAN_REVIEW
```

기본은 `AUTO`다.

---

# 43. Live Monitoring View

사람은 최소 다음을 실시간으로 볼 수 있어야 한다.

## A. Current Execution

```text
PHASE
TIME REMAINING
STATUS
CURRENT ACTION
CURRENT TOOL
NEXT ACTION
```

## B. Current Problem Understanding

```text
CURRENT PROBLEM
TOP HYPOTHESIS
CONFIDENCE
CRITICAL UNKNOWN
CRITICAL CONFLICT
```

## C. Evidence / Conclusion Basis

```text
CURRENT CONCLUSION
SUPPORTING EVIDENCE
CONTRADICTORY EVIDENCE
CONFIDENCE
PROVENANCE
```

## D. State Diff

```text
NEW
CHANGED
RESOLVED
DEFERRED
INVALIDATED
```

## E. Decision Rationale

```text
NEXT ACTION
WHY
EXPECTED INFORMATION
ESTIMATED COST
```

## F. Intervention Status

```text
HUMAN INTERVENTION REQUIRED
SAFE TO INTERRUPT
BLOCKING DECISION
PENDING APPROVAL
```

---

# 44. State Diff

전체 State를 매번 다시 보여주지 않는다.

다음 projection을 생성한다.

```text
StateDiff
├── added
├── changed
├── resolved
├── invalidated
├── deferred_to_verification
└── rationale
```

예:

```text
CHANGED
H-03 MEDIUM → LOW
Reason: valid service-duration evidence

NEW
CF-02 registry / operational state conflict

DEFERRED
U-07 exact exception prevalence
→ VOB-01
```

---

# 45. Evidence Revision Monitoring

Evidence 자체는 삭제하지 않고 해석 이력을 유지한다.

```text
EvidenceRevision
├── evidence_id
├── previous_interpretation
├── new_evidence
├── revised_interpretation
├── confidence_change
└── reason
```

이는 사람이 “왜 결론이 바뀌었는지” 이해하기 위해 필요하다.

---

# 46. Gate Rationale

Gate 결과는 단순 PASS/FAIL만 보여주지 않는다.

```text
GateRationale
├── result
├── satisfied_conditions
├── unresolved_items
├── blocking_items
├── non_blocking_items
├── assumptions
├── created_verification_obligations
└── reason_to_continue
```

---

# 47. Human Control Commands

v0.2.1에서 지원할 최소 Human Control semantics:

```text
PAUSE
현재 atomic action을 안전하게 마친 뒤 정지

INTERRUPT
가까운 safe point에서 auto loop를 중단하고 HUMAN_REVIEW 진입

STEP
다음 action 하나만 수행

OVERRIDE_NEXT
Harness가 선택한 다음 action을 사람이 교체

ADD_CONSTRAINT
새로운 제약을 ProblemState에 추가

ADD_EVIDENCE
사람이 알고 있는 Evidence를 provenance와 함께 주입

REQUEST_REPROFILE
추가 Discovery를 요구

REQUEST_REPLAN
현재 Solution path 재검토를 요구

RESUME
AUTO mode 재개

ABORT
현재 작업 종료
```

사람이 `retry/replan/reprofile/redefine` 내부 transition을 직접 조작하는 것보다, Human instruction을 Harness가 해석하여 적절한 transition을 발생시키는 것을 기본으로 한다.

---

# 48. Safe Point / Interrupt Semantics

강제 interrupt로 partial state를 만들지 않는다.

Safe Point 후보:

```text
Before Action
After Tool Result
After Validation
After State Commit
Before Transition
Before Irreversible Action
```

Flow:

```text
Human presses PAUSE
        ↓
pause_requested = true
        ↓
current atomic action finishes
        ↓
nearest safe point
        ↓
RuntimeState = PAUSED
```

`INTERRUPT`는 가능한 가장 가까운 safe point에서 `HUMAN_REVIEW`로 전환한다.

---

# 49. Mandatory Human Gate

다음 action은 AUTO mode에서도 사전 Human approval이 필요할 수 있다.

- irreversible external write
- submission / publish
- protected system mutation
- high-impact ambiguous action
- action forbidden by authority constraint without override

```text
proposed action
      ↓
approval_required?
  ├─ no  → execute
  └─ yes → WAITING_APPROVAL
                ↓
       APPROVE / MODIFY / REJECT
```

---

# 50. Event Log v0.2.1

기존 event에 다음을 추가한다.

```text
phase_changed
organization_added
stakeholder_added
process_added
process_handoff_added
entity_identity_added
canonical_mapping_created
data_asset_added
data_issue_detected
data_transformed
question_asked
claim_added
evidence_added
evidence_interpretation_changed
hypothesis_changed
conflict_detected
metric_defined
constraint_added
verification_obligation_created
verification_obligation_updated
verification_obligation_closed
gate_evaluated
gate_rationale_created
plan_created
decision_made
decision_rationale_added
action_started
action_finished
state_diff_created
tool_failed
validation_failed
retry
replan
reprofile
redefine
human_pause_requested
human_interrupt_requested
human_override_applied
human_resume
approval_requested
approval_granted
approval_rejected
release
```

---

# 51. Monitoring Projection Architecture

```text
Append-only Event Log
        ↓
ProblemState Projection
RuntimeState Projection
SupervisionState Projection
        ↓
CLI / TUI / future UI
```

Monitoring UI는 Event Log를 직접 수정하지 않는다.

Human control은 command/event를 생성하고 Core가 이를 처리한다.

---

# 52. Initial Monitoring Implementation Recommendation

v0.2.1에서는 Web UI를 만들지 않는다.

권장 순서:

```text
Stage A
Event + Runtime + Supervision State

Stage B
CLI Live Monitor

Stage C
TUI if useful

Stage D
Contest rules confirmed
→ Web UI only if justified
```

예시 CLI:

```text
┌─ AI TOP 100 HARNESS ──────────────────────┐
│ PHASE          DISCOVER                   │
│ TIME LEFT      03:41:22                   │
│ STATUS         RUNNING                    │
│                                           │
│ CURRENT ACTION                            │
│ Inspect service job lifecycle             │
│                                           │
│ TOP HYPOTHESIS                            │
│ Cross-org reconciliation failure          │
│                                           │
│ NEW EVIDENCE                              │
│ E-17 identity conflict                    │
│                                           │
│ STATE CHANGE                              │
│ H-02 MEDIUM → HIGH                        │
│                                           │
│ NEXT                                      │
│ Re-evaluate mapping rule                  │
│                                           │
│ HUMAN OVERRIDE   NOT REQUIRED             │
└───────────────────────────────────────────┘

[p] pause [i] interrupt [s] step
[o] override [r] resume [q] abort
```

---

# 53. Observability v0.2.1

최소 표시:

```text
PHASE
TIME REMAINING
EXECUTION STATUS
CURRENT ORGANIZATION
CURRENT PROCESS
CURRENT HANDOFF
CURRENT PROBLEM
TOP HYPOTHESES
CRITICAL UNKNOWNS
CRITICAL CONFLICTS
DATA ASSETS
DATA QUALITY WARNINGS
IDENTITY WARNINGS
CURRENT PLAN
CURRENT TASK
CURRENT ACTION
NEXT ACTION
DECISION RATIONALE
LAST TOOL RESULT
FAILURE REASON
TRANSITION REASON
STATE DIFF
EVIDENCE REVISION
GATE RATIONALE
OPEN VERIFICATION OBLIGATIONS
VALIDATION STATUS
HUMAN INTERVENTION REQUIRED
SAFE TO INTERRUPT
```

---

# 54. Budget Awareness

실전 기준 유지:

```text
09:00 Problem Page Open
10:00 Contest Start
15:00 Contest End
```

Soft Budget:

```text
00:00~00:15  Environment / Scenario / Data inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

Mock #1은 Budget stress test를 충분히 하지 못했으므로 수치는 변경하지 않는다.

---

# 55. Release Reserve

최종 약 30분을 release reserve 후보로 둔다.

reserve 진입 시:

- 저가치 인터뷰 중단
- optional feature 제거
- 추가 architecture 탐색 중단
- minimum useful Agent 유지
- OPEN VerificationObligation 중 release-blocking 우선 처리
- verification 우선
- packaging 우선
- known limitation 기록

---

# 56. Failure Modes v0.2.1

v0.2 Failure Mode를 유지한다.

- F1 Wrong Problem Definition
- F2 Infinite Interview
- F3 Wrong Stakeholder
- F4 Evidence Contradiction
- F5 LLM Hallucination
- F6 Planner Loop
- F7 Tool Failure
- F8 Coding Failure
- F9 Judge Inconsistency
- F10 Context Overflow
- F11 Time Shortage
- F12 API / Model Failure
- F13 Prompt Injection / Untrusted Input
- F14 Wrong Process Mapping
- F15 Bad Data Quality
- F16 Cleaning-induced Distortion
- F17 Cross-organization Mismatch
- F18 Data Availability Assumption

v0.2.1에서 추가한다.

## F19. Identity Collision

징후:
- 하나의 identifier가 여러 entity에 연결
- 조직별 namespace 혼재

대응:
- EntityIdentity / CanonicalMapping
- ambiguity → human review

## F20. Handoff Blind Spot

징후:
- 조직 내부 Process는 맞지만 조직 경계에서 delay/error 발생

대응:
- ProcessHandoff explicit modeling
- latency / payload / acknowledgment 추적

## F21. Deferred Unknown Forgotten

징후:
- CONDITIONAL_PASS에서 미룬 Unknown이 VERIFY에서 사라짐

대응:
- VerificationObligation
- Release Gate obligation inventory

## F22. Unsafe Human Interrupt

징후:
- tool 실행 중 강제 중단
- partial transformation/state corruption

대응:
- safe point
- atomic action boundary

## F23. Invisible Autonomous Drift

징후:
- Harness가 결론을 바꿨으나 Human이 이유를 알 수 없음

대응:
- State Diff
- Decision Rationale
- Evidence Revision
- Gate Rationale

---

# 57. Skill Architecture v0.2.1

```text
skills/
├── discover/
│   ├── scenario_profiler
│   ├── organization_profiler
│   ├── stakeholder_profiler
│   ├── process_mapper
│   ├── handoff_mapper
│   ├── identity_profiler
│   ├── question_selector
│   ├── interview
│   └── evidence_integrator
├── data/
│   ├── inventory
│   ├── inspector
│   ├── quality_checker
│   ├── duplicate_classifier
│   ├── cleaner
│   ├── normalizer
│   ├── identity_resolver
│   └── transformation_validator
├── define/
│   ├── metric_definer
│   ├── problem_synthesizer
│   ├── verification_obligation_builder
│   └── definition_gate
├── design/
│   ├── solution_planner
│   ├── task_decomposer
│   └── agent_spec_builder
├── execute/
│   ├── action_decider
│   ├── safe_point_controller
│   └── failure_router
├── verify/
│   ├── test_generator
│   ├── obligation_checker
│   ├── deterministic_validator
│   └── semantic_judge
└── supervision/
    ├── live_state_projector
    ├── state_diff_builder
    ├── rationale_builder
    ├── interrupt_controller
    └── human_override_handler
```

---

# 58. Tool Architecture

```text
tools/
├── llm
├── file
├── web
├── python
├── shell
├── spreadsheet
├── external_api
└── coding_agent
```

Tool contract에는 다음을 추가한다.

```text
interruptibility
atomicity
side_effect_level
approval_required
retry_policy
```

---

# 59. Contest Adapter

실제 제출 형식은 확정 전까지 추측하지 않는다.

```text
ContestAdapter
├── ingest_environment()
├── normalize_input()
├── expose_stakeholder_interface()
├── expose_allowed_tools()
├── expose_data_assets()
├── expose_human_control()
├── package_agent()
├── validate_package()
└── submit_or_export()
```

---

# 60. Mock Execution Mode v0.2.1

앞으로 Mock은 기본적으로 **Harness-driven + Human-on-the-loop**로 수행한다.

```text
Public Scenario
      ↓
Harness initial profile
      ↓
Harness Question / Data Action Selection
      ↓
Stakeholder / Data Simulator
      ↓
Evidence Integration
      ↓
State Diff / Monitoring
      ↓
Human Override only if needed
      ↓
DEFINE Gate
      ↓
DESIGN
      ↓
Paper Execution
      ↓
VERIFY
      ↓
RELEASE
      ↓
Hidden Ground Truth
      ↓
Design Gap Review
```

Human이 모든 질문과 transition을 수동으로 결정하는 방식은 Harness 자체의 question_selector / epistemic loop를 검증하기 어렵기 때문에 기본 모드로 사용하지 않는다.

---

# 61. Recommended Mock Set v0.2.1

## Mock 01 — Conflicting Stakeholders + Dirty Data
**완료**  
검증: Claim vs Fact, Data Quality, Conflict, Process, Handoff, Identity, Monitoring

## Mock 02 — Misleading Initial Request
검증: symptom vs root problem, question efficiency, redefine boundary, Human Supervision

## Mock 03 — Hidden Critical Constraint
검증: privacy/tool/authority constraint, Human Gate, DEFINE Gate

## Mock 04 — Cross-Organization Handoff Failure
검증: ProcessHandoff, shared data, semantic mismatch, identity mapping

## Mock 05 — Severe Time Pressure + Tool Failure
검증: Budget, retry/replan, release reserve, pause/interrupt safety

## Mock 06 — New Evidence Invalidates Problem
검증: redefine, state versioning, evidence history, Evidence Revision monitoring

---

# 62. Mock Evaluation Rubric v0.2.1

```text
Problem Discovery
Process Understanding
Handoff Understanding
Question Efficiency
Evidence Quality
Data Quality Handling
Entity Identity Handling
Conflict Handling
Root Cause Accuracy
Definition Gate Quality
Verification Obligation Handling
Agent Design
Validation Quality
Transition Correctness
Budget Usage
Observability
Human Supervision / Interruptibility
```

목적은 정답 점수가 아니라 Harness 설계 gap 발견이다.

---

# 63. Development Roadmap v0.2.1

## Stage 0 — v0.2 Design Baseline
완료.

## Stage 1 — Mock 01
완료.

## Stage 2 — v0.2.1 Design Patch
현재 문서.

## Stage 3 — Mock 02~03
v0.2.1 기반으로 수행.

특히 검증:

- VerificationObligation
- Human Supervision Plane
- Metric semantics
- redefine boundary
- Authority gate

## Stage 4 — v0.3 Design Freeze
Mock 02~03 결과를 반영하여 최소 구현 전 설계 freeze.

## Stage 5 — Core State + Event + Supervision Model 구현

- ProblemState
- RuntimeState
- SupervisionState
- Event Log
- provenance
- Organization
- Process
- ProcessHandoff
- EntityIdentity
- Metric
- VerificationObligation
- Budget

## Stage 6 — DISCOVER + DATA 최소 구현

- profiling
- interview
- process / handoff mapping
- data inspection
- identity resolution
- evidence integration

## Stage 7 — DEFINE

- metric semantics
- synthesis
- gate
- verification obligations

## Stage 8 — DESIGN

- strategy
- task decomposition
- AgentSpec

## Stage 9 — EXECUTE

- action loop
- tool registry
- safe point
- transition

## Stage 10 — VERIFY / RELEASE

- deterministic validation
- obligation checker
- semantic judge
- release gate

## Stage 11 — Human Supervision CLI

- live monitor
- state diff
- decision rationale
- pause/interrupt/step/override/resume

## Stage 12 — Remaining Mock
Mock 04~06를 실제 구현으로 수행.

## Stage 13 — Contest Adapter
10/23 안내 이후 실제 제출 형식에 맞춰 구현.

---

# 64. 10/23 사전 안내 확인 체크리스트

기존 체크리스트를 유지하고 Human Supervision 관련 항목을 추가한다.

## Submission
- source code 여부
- URL/API 여부
- Docker 여부
- 파일 업로드 형식
- Agent platform 존재 여부
- 제출 횟수
- 마감 직전 수정 가능 여부

## Runtime
- 실행 환경
- 인터넷
- package install
- local/cloud execution
- port/API 제한
- file size

## AI / Tool
- 외부 LLM
- API
- Coding Agent
- web
- custom scripts
- external database
- automation

## Data
- format
- download/upload
- 외부 전송 제한
- 개인정보/민감정보

## Interview
- UI
- 질문 횟수
- timeout
- 동일 인물 재질문
- history

## Evaluation
- hidden test
- Agent 실행 횟수
- evaluation metric
- action 평가
- human evaluation
- deterministic test

## Operational
- 인증 방식
- allowed browser
- network policy
- 1인 참가 확인
- background process 허용 여부
- terminal/TUI 사용 가능 여부
- 사람이 실행 중 Agent를 중단/재시작할 수 있는지
- submission 전 interactive supervision 허용 여부

---

# 65. v0.2.1 Design Acceptance Criteria

다음 질문에 답할 수 있어야 한다.

1. 두 조직을 어떻게 표현하는가?
2. 조직별 Stakeholder는 어떻게 연결하는가?
3. 실제 업무 Process는 어떻게 저장하는가?
4. 조직 간 handoff는 누가 누구에게 무엇을 전달하는지 표현 가능한가?
5. Process Step의 actor와 accountable owner를 구분하는가?
6. Process Step과 Data는 어떻게 연결하는가?
7. 동일 physical entity를 여러 조직 identifier와 연결 가능한가?
8. non-unique identifier를 자동으로 잘못 join하지 않는가?
9. Stakeholder Claim과 Data가 충돌하면 어떻게 하는가?
10. Raw Data와 Cleaned Data를 구분하는가?
11. exact duplicate와 status progression을 구분하는가?
12. Transformation 이유와 이력이 남는가?
13. 어떤 Data/Mapping이 Problem Definition을 지지했는지 추적 가능한가?
14. 필요한 데이터가 없을 때 어떻게 하는가?
15. Metric의 start/end event와 population을 표현 가능한가?
16. 질문을 언제 그만두는가?
17. Definition Gate가 왜 PASS인지 설명 가능한가?
18. CONDITIONAL_PASS의 Assumption/Unknown이 VerificationObligation으로 남는가?
19. Success Criteria에 target/predicate가 존재하는가?
20. Authority / Human approval constraint를 Agent가 위반하지 않는가?
21. Agent Capability가 Process/Handoff 문제와 연결되는가?
22. Agent가 사용하는 Data와 Identity Mapping이 검증되었는가?
23. retry와 replan을 구분하는가?
24. reprofile이 전체 Discovery를 무조건 다시 하지 않는가?
25. redefine이 canonical Problem Definition 이후에만 사용되는가?
26. 남은 시간이 부족할 때 scope를 줄이는가?
27. Open VerificationObligation을 Release Gate에서 확인하는가?
28. 사람이 현재 State 변화와 판단 근거를 실시간으로 볼 수 있는가?
29. Harness가 다음 행동을 선택한 이유를 볼 수 있는가?
30. 사람이 safe point에서 pause / interrupt / override / resume할 수 있는가?
31. Human interrupt가 partial state corruption을 만들지 않는가?
32. 최종 제출 전에 최소 E2E 검증이 가능한가?
33. 실제 제출 형식이 달라져도 Core는 유지되는가?

---

# 66. Final Recommended Flow v0.2.1

```text
┌────────────────────┐
│      SCENARIO      │
└──────────┬─────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│ DISCOVER                                     │
│                                              │
│ Organization                                 │
│ Stakeholder                                  │
│ Business Process                             │
│ Process Handoff                              │
│ Entity Identity                              │
│ Data Assets                                  │
│ Claims / Facts                               │
│ Hypotheses                                   │
│ Unknowns                                     │
│                                              │
│           Epistemic Loop ↺                  │
└───────────────────┬──────────────────────────┘
                    │
          ┌─────────▼──────────┐
          │ DATA WORKSPACE     │
          │ Inspect            │
          │ Validate           │
          │ Normalize          │
          │ Canonical Map      │
          │ Transform          │
          │ Trace              │
          └─────────┬──────────┘
                    │
                    ▼
┌──────────────────────────────────────────────┐
│ DEFINE                                       │
│                                              │
│ Root Problem                                 │
│ Process / Handoff                            │
│ Relevant Data / Identity                     │
│ Goal                                         │
│ Metric semantics                             │
│ Constraint / Authority                       │
│ Assumption                                   │
│ Risk                                         │
│ Success Criteria                             │
│ Verification Obligations                     │
│                                              │
│ PASS / CONDITIONAL_PASS / FAIL               │
└───────────────┬───────────────────────┬──────┘
                │                       │ FAIL
                │                       └──────► DISCOVER
                ▼
┌──────────────────────────────────────────────┐
│ DESIGN                                       │
│                                              │
│ Solution Strategy                            │
│ Agentification Gate                          │
│ Task Decomposition                           │
│ Required Data / Identity                     │
│ Authority Boundary                           │
│ Tool Selection                               │
│ Agent Specification                          │
│ Validation Plan                              │
└───────────────────┬──────────────────────────┘
                    │
                    ▼
┌──────────────────────────────────────────────┐
│ EXECUTE                                      │
│                                              │
│ Decide                                       │
│ Safe Point                                   │
│ Execute                                      │
│ Observe                                      │
│ Validate                                     │
│ State Diff                                   │
│ Update State / Data                          │
│                                              │
│             Action Loop ↺                   │
└───────┬──────────────────────────────────────┘
        │
        ├── retry ─────────────► EXECUTE
        ├── replan ────────────► DESIGN
        ├── reprofile ─────────► DISCOVER
        ├── redefine ──────────► DEFINE / DISCOVER
        └── candidate complete
                    │
                    ▼
┌──────────────────────────────────────────────┐
│ VERIFY / RELEASE                             │
│                                              │
│ Data Validation                              │
│ Identity / Mapping Validation                │
│ Deterministic Checks                         │
│ Verification Obligation Check                │
│ Semantic Judge if Needed                     │
│ Synthetic Tests                              │
│ Known Limitations                            │
│ Release Gate                                 │
└───────────────────┬──────────────────────────┘
                    │
                    ▼
               Contest Agent
                    +
            Verification Report
                    +
                  Package
```

이 전체 Flow를 Human Supervision Plane이 가로지른다.

```text
Human Supervision Plane

Live State
State Diff
Evidence Basis
Decision Rationale
Gate Rationale
Verification Obligations
Budget
Interrupt / Override / Resume
```

---

# 67. v0.2.1 최종 정의

> **AI TOP 100 Harness v0.2.1은 주어진 현장 Scenario에서 조직, 사람, 업무 프로세스, 조직 간 handoff, entity identity, 데이터를 함께 구조화하고, 관계자 인터뷰와 데이터 검증을 통해 실제 문제를 발견·정의하며, 제한된 시간 안에 검증 가능한 최소 문제특화 AI Agent를 설계·구축·검증하는 범용 Agentic Problem-Solving Harness다. 또한 Harness가 자율적으로 문제를 해결하는 동안 사람은 실시간으로 현재 State, 판단 근거, Evidence 변화, 다음 행동을 모니터링하고 필요할 때 안전하게 interrupt / override할 수 있다.**

핵심 목표는 Framework 완성도가 아니다.

```text
Understand the operation.
Map the handoffs.
Resolve the identity.
Find the real problem.
Verify the data.
Build the minimum useful agent.
Keep deferred unknowns visible.
Let humans supervise without micromanaging.
Prove that it works.
```

---

# 68. v0.2.1 다음 검증 목표

v0.2.1은 아직 구현 Freeze가 아니다.

다음은 Mock #2 — Misleading Initial Request에서 반드시 확인한다.

1. Harness-driven Question Selection이 표면 요청에 anchoring되지 않는가?
2. State Diff가 실제 Human monitoring에 충분한가?
3. Decision Rationale이 너무 장황하지 않고 interrupt 판단에 유용한가?
4. Human interrupt / override semantics가 자연스러운가?
5. VerificationObligation이 실제로 Phase를 넘어 유지되는가?
6. Metric semantics 확장이 과도한 complexity를 만들지 않는가?
7. EntityIdentity가 domain-agnostic하게 동작하는가?
8. ProcessHandoff 모델이 실제 bottleneck 표현에 충분한가?
9. redefine boundary가 명확하게 작동하는가?
10. v0.2.1 추가 state가 5시간 contest에서 과도한 cognitive/runtime cost를 만들지 않는가?

Mock #2~03 결과까지 반영한 뒤 v0.3 Design Freeze 여부를 결정한다.

---

# 69. Version Decision

Mock #1 기준 최종 판단:

```text
v0.2 유지                → 부족
v0.2.x patch 권장        → 선택
v0.3 수준 구조 변경 필요 → 아직 아님
```

따라서 본 문서를 **v0.2.1 Mock #2 Source of Truth**로 사용한다.

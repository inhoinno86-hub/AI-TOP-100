# AI TOP 100 Harness v0.2 설계 문서

**Version:** v0.2  
**Status:** Design Baseline / Mock Test 전  
**Previous:** v0.1  
**Purpose:** AI TOP 100 [2026] 예선에서 주어진 현장 상황을 빠르게 이해하고, 관계자 인터뷰와 획득 데이터를 통해 실제 문제를 정의한 뒤, 문제특화 AI Agent를 설계·구축·검증할 수 있도록 지원하는 범용 Harness 설계  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Important:** 실제 제출 형식, 실행 API, hidden test 구조, 허용 Tool 세부 규칙 등은 아직 확정 정보로 취급하지 않는다.

---

# 0. v0.2에서 새로 반영된 미션 정보

현재까지 확인된 미션 브리프의 핵심은 다음과 같다.

- 참가자는 AX(AI Transformation) 전문가 역할을 한다.
- 배경에는 최소 두 개의 운영 주체가 존재한다.
  - 제철 농산물이 자라는 `교동마을`
  - 싱싱한 수산물의 `갯마을`
- 참가자는 마을 관계자들과 대화한다.
- 현장의 문제를 발굴해야 한다.
- 획득한 데이터를 수집해야 한다.
- 데이터를 검증해야 한다.
- 데이터를 정제해야 한다.
- 두 마을 조합의 업무를 개선할 AI Agent를 구축해야 한다.
- 예선은 2026-10-31 10:00~15:00, 온라인으로 진행된다.
- 문제 페이지는 09:00부터 열리며 사전 준비가 필요하다.

이 정보는 v0.1의 큰 방향을 뒤집지는 않는다. 그러나 다음 요소를 **v0.2의 1급 설계 개념**으로 추가한다.

1. `Organization`
2. `Business Process`
3. `DataAsset`
4. `Data Quality`
5. `Transformation / Cleaning History`
6. `Metric`
7. `Cross-Organization Relationship`
8. `Operational Improvement`
9. `Data-to-Evidence Traceability`

---

# 1. v0.1 → v0.2 핵심 변경 요약

| 영역 | v0.1 | v0.2 |
|---|---|---|
| 전체 Flow | DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY | 동일 유지 |
| 조직 구조 | 명시적 모델 없음 | `Organization` 추가 |
| 업무 흐름 | 간접 표현 | `Business Process` 1급 개념화 |
| 데이터 | Evidence 중심 | `DataAsset / Quality / Transformation` 추가 |
| Metric | Success Criteria 일부 | 독립적 `Metric` 구조 추가 |
| Evidence | Claim/Hypothesis 연결 | DataAsset과도 연결 |
| 인터뷰 | Problem/Unknown 중심 | Problem + Process + Data + Constraint + Success |
| Data 처리 | 별도 구조 없음 | 전 Phase를 가로지르는 Data Workspace |
| 조직 간 연계 | 고려 가능 | Cross-org handoff / shared data 명시 |
| Mock Test | 일반 구조 | 두 조직 + 데이터 품질 + 현장업무 구조 반영 |
| Budget | time-aware | 09:00 입장, 10:00~15:00 실전 운영까지 반영 |
| 제출 대응 | Contest Adapter | 유지, 실제 형식 확정 전 구현 금지 |

---

# 2. Executive Summary

AI TOP 100 Harness v0.2의 목표는 다음과 같다.

> **주어진 현장 Scenario에서 관계자와 데이터로부터 문제를 발견하고, 업무 프로세스와 데이터 흐름을 구조화하여 실제 병목을 정의한 뒤, 제한시간 안에 검증 가능한 최소 AI Agent를 설계·구현·검증하는 것.**

기본 흐름은 v0.1을 유지한다.

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

다만 모든 Phase를 가로지르는 `Data Workspace`를 추가한다.

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
```

Data를 별도의 고정 Phase로 만들지 않는 이유는 다음과 같다.

- Scenario 시작 시 데이터가 주어질 수 있다.
- 인터뷰 도중 데이터가 추가로 제공될 수 있다.
- Problem Definition에 데이터 품질 자체가 영향을 줄 수 있다.
- Agent 실행 중 운영 데이터를 사용할 수 있다.
- Verification에서도 원본/정제 데이터가 필요할 수 있다.

따라서 Data는 **전 Phase를 가로지르는 지속적 Workspace**로 관리한다.

---

# 3. Project Goal

## 3.1 무엇을 만드는가

AI TOP 100 Harness v0.2는 다음을 수행할 수 있는 범용 문제해결 Harness다.

1. Scenario 구조화
2. Organization 식별
3. Stakeholder 식별
4. Business Process 구조화
5. DataAsset 식별 및 획득
6. Data Quality 평가
7. 데이터 정제/정규화/변환
8. Fact / Claim / Evidence / Hypothesis 구조화
9. Unknown / Conflict 관리
10. 정보 가치가 높은 질문 선택
11. 인터뷰 수행
12. Root Problem 정의
13. Goal / Constraint / Success Criteria 설정
14. Solution Strategy 설계
15. Agent Specification 생성
16. Contest Agent 구축/실행
17. 검증
18. 실패 원인에 따른 retry / replan / reprofile / redefine
19. 제출 가능한 형태로 package

## 3.2 무엇을 만들지 않는가

v0.2에서도 다음은 만들지 않는다.

- 농산물/수산물 문제의 예상 정답
- 특정 재고/판매/물류 Agent 사전 완제품
- 특정 조합 업무에 특화된 hard-coded workflow
- 특정 DB schema 사전 고정
- AutoGPT류 범용 autonomous framework
- 복잡한 Multi-agent hierarchy
- Graph DB
- Microservice
- Kubernetes
- Web UI
- 대형 Data Platform
- 범용 ETL Platform
- 실제 제출 형식이 확정되지 않은 상태에서의 Docker/Web/API 구현

---

# 4. 핵심 설계 철학

> **Do not solve before understanding.**  
> **Do not build before defining.**  
> **Do not trust before verifying.**  
> **Do not pursue certainty beyond its decision value.**  
> **Do not automate a process you have not mapped.**

마지막 문장은 v0.2에서 중요하다.

AI Agent를 어디에 넣을지 정하기 전에 먼저 확인한다.

```text
현재 업무는 실제로 어떻게 흘러가는가?
어디서 데이터가 생기는가?
어디로 전달되는가?
어디서 기다리는가?
어디서 사람이 반복 입력하는가?
어디서 오류가 발생하는가?
```

---

# 5. Design Principles

## P1. Zero-base
기존 CareerGround, intent-loop, loop-engine의 코드를 재사용하지 않는다. 개념만 참고한다.

## P2. Domain-agnostic
`농산물`, `수산물`, `재고`, `판매` 같은 도메인 명칭을 Core schema에 넣지 않는다.

## P3. Minimal Core
Core는 Phase, State, Transition, Budget, Event, Contract, Tool policy만 담당한다.

## P4. Evidence-driven
중요한 판단은 Evidence 또는 명시적 Assumption과 연결한다.

## P5. Process-aware
현장 문제를 사람의 불편함뿐 아니라 **업무 Process의 병목**으로 구조화할 수 있어야 한다.

## P6. Data-aware
획득 데이터의 존재, 출처, 품질, 변환 이력을 1급 상태로 관리한다.

## P7. Provenance-first
Fact, Claim, Evidence, DataAsset 모두 source traceability를 유지한다.

## P8. State-driven
대화 transcript 자체가 system state가 되지 않는다.

## P9. Platform-independent
실제 제출형식과 Core를 분리한다.

## P10. Human-controllable
사람이 현재 판단과 실패 이유를 빠르게 이해하고 개입할 수 있어야 한다.

## P11. Deterministic-first Verification
기계적으로 확인할 수 있는 것은 LLM에 맡기지 않는다.

## P12. Fail-visible
실패를 감추지 않는다.

## P13. Budget-aware
5시간 안에 제출 가능한 결과를 만드는 것이 최우선이다.

## P14. Local Loop over Universal Loop
Discovery와 Execution의 Loop 목적을 분리한다.

## P15. Append History, Derive Current View
이력은 유지하고 현재 view만 갱신한다.

---

# 6. High-level Architecture v0.2

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CONTEST ENVIRONMENT                                 │
│ Scenario / Stakeholders / Files / Tables / Media / Interfaces / Rules      │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                           Contest Adapter
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HARNESS CORE                                      │
│                                                                             │
│  ┌───────────────────┐        ┌──────────────────────────────────────────┐   │
│  │  Phase Controller │◄──────►│         Problem Workspace              │   │
│  └─────────┬─────────┘        │ Canonical State / Versions / Events     │   │
│            │                  └──────────────────────────────────────────┘   │
│            │                                                                │
│  ┌─────────▼──────────────────────────────────────────────────────────────┐  │
│  │                            Skill Layer                               │  │
│  │ DISCOVER       DEFINE         DESIGN        EXECUTE       VERIFY      │  │
│  │ profile        synthesize     strategy      action        tests       │  │
│  │ interview      gate           agent spec    build         judge       │  │
│  │ process map                                                            │  │
│  └──────────┬─────────────────────────────────────────────────────────────┘  │
│             │                                                               │
│  ┌──────────▼─────────────────────────────────────────────────────────────┐  │
│  │                         DATA WORKSPACE                                │  │
│  │ Inventory / Inspect / Validate / Clean / Normalize / Transform        │  │
│  │ Provenance / Quality / Data-to-Evidence links                         │  │
│  └──────────┬─────────────────────────────────────────────────────────────┘  │
│             │                                                               │
│  ┌──────────▼──────────────────┐   ┌────────────────────────────────────┐   │
│  │       Tool Registry        │   │ Budget / Observability            │   │
│  │ LLM / file / web / python  │   │ time / events / failure / state  │   │
│  │ shell / coding-agent / API │   │ release reserve                   │   │
│  └─────────────────────────────┘   └────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              OUTPUTS                                        │
│ Problem Definition Package                                                 │
│ Process / Data Understanding Package                                       │
│ Agent Specification                                                        │
│ Contest Agent                                                              │
│ Verification Report                                                        │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

# 7. Problem State Schema v0.2

```text
ProblemState
├── meta
├── scenario
├── organizations
├── stakeholders
├── processes
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

`Organization`은 Stakeholder와 분리한다.

```text
Organization
├── id
├── name
├── role
├── objectives
├── stakeholders
├── processes
├── data_assets
├── external_dependencies
└── relations
```

필요한 이유:

- 두 운영 주체가 존재할 수 있음
- 동일 Process가 여러 조직을 가로지를 수 있음
- 같은 Data를 서로 다른 조직이 사용할 수 있음
- 조직 간 handoff 자체가 bottleneck일 수 있음

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

관리자의 주장이 현장 작업자의 실제 업무보다 정확하다고 가정하지 않는다.

---

# 10. Business Process

v0.2에서 새롭게 가장 중요한 구조 중 하나다.

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
├── handoffs
├── wait_points
├── manual_steps
├── duplicate_steps
├── failure_points
├── metrics
└── pain_points
```

각 Process Step:

```text
ProcessStep
├── id
├── sequence
├── action
├── actor
├── system
├── input_data
├── output_data
├── duration
├── wait_time
├── error_rate
├── manual_or_automated
└── observed_issue
```

인터뷰 결과를 단순 Problem statement로 합치지 않고 Process에 연결한다.

```text
Stakeholder Claim
       ↓
Process Step
       ↓
Observed Delay / Error
       ↓
Data Evidence
       ↓
Problem Hypothesis
```

---

# 11. DataAsset

v0.2의 핵심 추가 항목이다.

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

## 11.1 Acquisition

```text
acquisition
├── method
├── acquired_from
├── stakeholder
├── timestamp
├── access_scope
└── completeness
```

## 11.2 Data Quality

```text
DataQuality
├── completeness
├── validity
├── consistency
├── uniqueness
├── timeliness
└── interpretability
```

초기 상태는 정밀 수치보다 다음 정도로 관리한다.

```text
GOOD
ACCEPTABLE
PROBLEMATIC
UNKNOWN
```

## 11.3 Data Issues

- missing
- duplicate
- invalid
- inconsistent
- malformed
- stale
- outlier
- ambiguous
- unexpected type
- join failure
- contradictory record

## 11.4 Transformation History

```text
Transformation
├── id
├── operation
├── reason
├── input_reference
├── output_reference
├── deterministic
├── reversible
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

Raw data는 보존한다.

---

# 12. Metric

Metric을 Success Criteria와 분리한다.

```text
Metric
├── id
├── name
├── related_process
├── definition
├── unit
├── current_value
├── target_value
├── measurement_source
└── reliability
```

예:

- 평균 처리 시간
- 오류율
- 재입력 횟수
- 대기 시간
- 누락 건수
- 자동화 비율

---

# 13. Evidence Model v0.2

Evidence source는 Stakeholder뿐 아니라 DataAsset도 포함한다.

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
└── extraction_confidence
```

`source_type` 예:

```text
scenario
stakeholder
data_asset
process_observation
tool_result
system_log
synthetic_mock
```

---

# 14. Data-to-Evidence Traceability

```text
Raw Data
   ↓
Transformation
   ↓
Validated Data
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

Agent 설계가 어떤 데이터에 의존했는지 추적 가능해야 한다.

---

# 15. DISCOVER v0.2

DISCOVER는 네 축을 탐색한다.

```text
PEOPLE
PROCESS
DATA
OUTCOME
```

세부 State:

```text
Organization
Stakeholder
Business Process
DataAsset
Metric
Claim
Fact
Unknown
Hypothesis
Conflict
```

---

# 16. Interview Framework v0.2

질문을 다섯 종류로 구분한다.

## A. Problem Questions

- 무엇이 가장 불편한가?
- 어떤 문제가 반복되는가?
- 가장 시간이 많이 드는 일은 무엇인가?

## B. Process Questions

- 업무는 어떤 순서로 진행되는가?
- 앞 단계의 결과는 누구에게 전달되는가?
- 대기하는 단계가 있는가?
- 사람이 반복 입력하는 단계가 있는가?

## C. Data Questions

- 어떤 데이터를 사용하는가?
- 어디에 저장되어 있는가?
- 누가 입력하는가?
- 얼마나 정확한가?
- 누락/중복이 있는가?
- 서로 다른 파일/시스템 간 key가 일치하는가?

## D. Constraint Questions

- 반드시 지켜야 하는 규칙은 무엇인가?
- 외부 서비스로 보낼 수 없는 정보가 있는가?
- 사람이 최종 승인해야 하는 단계가 있는가?
- Tool/API 접근이 제한되는가?

## E. Success Questions

- 무엇이 개선되면 성공이라고 볼 수 있는가?
- 현재 값은 얼마인가?
- 목표 값은 얼마인가?
- 누가 그 결과를 확인할 수 있는가?

---

# 17. Information Value v0.2

질문 우선순위 기준:

1. Decision Impact
2. Uncertainty
3. Discriminative Power
4. Answerability
5. Cost
6. Process Impact
7. Data Impact

Question priority:

```text
CRITICAL
HIGH
MEDIUM
LOW
SKIP
```

정밀 numeric scoring은 사용하지 않는다.

---

# 18. Epistemic Loop v0.2

```text
Unknown / Hypothesis
        ↓
Select Highest-Value Question
        ↓
Ask Stakeholder / Inspect Data
        ↓
Extract Claim / Evidence
        ↓
Update Process / Data / Belief State
        ↓
Detect Conflict
        ↓
Assess Sufficiency
        ↺
```

DISCOVER에서 정보 획득 수단은 Interview뿐만이 아니다.

```text
Interview
File inspection
Table analysis
Cross-data comparison
Tool result
Process observation
```

---

# 19. Conflict v0.2

Conflict 유형:

```text
CLAIM_CONFLICT
DATA_CONFLICT
PROCESS_CONFLICT
CONSTRAINT_CONFLICT
GOAL_CONFLICT
METRIC_CONFLICT
```

예:

```text
Manager Claim:
"입력은 하루 한 번 한다."

Data:
동일 항목이 하루 여러 번 수정됨.

→ CLAIM_DATA_CONFLICT
```

---

# 20. Problem Definition Gate v0.2

## Organization
- 해결 대상 조직/조직들이 명확한가?

## Actor
- 영향을 받는 Stakeholder가 명확한가?

## Process
- 문제와 연결된 Business Process가 식별되었는가?
- 문제 단계가 어느 지점인지 설명 가능한가?

## Data
- 필요한 DataAsset이 알려져 있는가?
- 품질이 최소한 평가되었는가?
- 데이터 자체가 문제의 원인인지 구분했는가?

## Problem
- symptom과 root problem이 구분되었는가?

## Evidence
- 핵심 Problem statement가 Evidence와 연결되었는가?

## Unknown
- critical Unknown이 남아 있는가?

## Conflict
- unresolved critical Conflict가 있는가?

## Metric
- baseline 또는 성공 판단 방법이 존재하는가?

## Constraint
- 주요 실행 제약이 알려져 있는가?

---

# 21. Gate Result

## PASS
Solution 설계에 필요한 정보가 충분하다.

## CONDITIONAL_PASS
일부 불확실성이 남아 있지만 다음 조건을 만족한다.

- Assumption으로 명시 가능
- 실패 시 영향 이해
- Verification에서 검사 가능
- 제한시간상 추가 Discovery 가치가 낮음

## FAIL
추가 DISCOVER가 필요하다.

---

# 22. Problem Definition Package v0.2

```text
ProblemDefinition
├── organizations
├── affected_stakeholders
├── affected_process
├── current_state
├── observed_gap
├── root_problem
├── supporting_evidence
├── contradictory_evidence
├── relevant_data_assets
├── data_quality_notes
├── desired_state
├── metrics
├── constraints
├── assumptions
├── risks
├── success_criteria
└── non_goals
```

---

# 23. DESIGN v0.2

Planner의 목표:

> **현재 Process와 Data를 이해한 상태에서 Success Criteria를 만족하는 최소 Agent를 설계한다.**

---

# 24. Agentification Gate

모든 문제를 Agent로 만들지 않는다.

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

Contest 제출물이 Agent라고 해서 내부의 모든 step이 agentic일 필요는 없다.

---

# 25. Solution Strategy

전략 후보는 최대 1~3개로 제한한다.

```text
strategy
├── addressed_problem
├── affected_process
├── required_data
├── agent_capabilities
├── deterministic_components
├── llm_components
├── tools
├── expected_benefit
├── implementation_cost
├── validation_method
└── risks
```

---

# 26. Agent Specification v0.2

```text
AgentSpec
├── identity
│   ├── name
│   ├── purpose
│   └── problem_reference
├── organization_context
├── process_context
├── interface
│   ├── inputs
│   ├── outputs
│   └── contracts
├── data
│   ├── required_assets
│   ├── validation_rules
│   └── allowed_transformations
├── state
├── capabilities
├── tools
├── workflow
├── decision_rules
├── constraints
├── failure_handling
├── termination
├── validation
└── success_criteria
```

---

# 27. Traceability v0.2

필수 연결:

```text
Problem Definition
      ↓
Affected Process
      ↓
Success Criteria
      ↓
Agent Capability
      ↓
Required Data
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
Evidence
   ↓
Problem Hypothesis
```

---

# 28. EXECUTE — Action Loop

```text
Current Execution State
        ↓
Decide Next Action
        ↓
Execute Tool / Skill
        ↓
Observe
        ↓
Validate
        ↓
Update State / Data
        ↓
Transition
```

---

# 29. Transition Rules

## retry
같은 전략과 Action은 유효하고 transient failure일 때.

## re-plan
Problem은 맞지만 Solution path가 잘못되었을 때.

## re-profile
정보가 부족하거나 새로운 critical Unknown이 발견되었을 때.

## re-define
새로운 Evidence가 Root Problem 자체를 무효화할 때.

## abort
제출 가능한 최소 결과조차 만들 수 없을 때.

## finish
Release Gate 통과 시.

---

# 30. Data Failure Routing

```text
Data missing
    ↓
Can alternative source answer?
    ├─ yes → acquire
    └─ no  → assumption / redesign

Data invalid
    ↓
Can deterministic cleaning fix?
    ├─ yes → clean + validate
    └─ no  → re-profile / redesign

Join failure
    ↓
Check key semantics
    ↓
Resolve mapping or mark unavailable

Conflicting records
    ↓
Create conflict
    ↓
Determine decision impact
```

---

# 31. Verification Architecture v0.2

## Layer 1 — Deterministic Validation

항상 우선한다.

예:

- schema validity
- required files
- row count
- missing values
- duplicate keys
- invalid types
- transformation result
- calculation
- rule compliance
- test pass/fail
- latency
- exact threshold

## Layer 2 — LLM-as-a-Judge

semantic quality에만 사용한다.

예:

- output이 stakeholder 요청을 의미적으로 만족하는가?
- 주요 context가 빠졌는가?
- response가 Problem Definition에 부합하는가?

## Layer 3 — Human Review

high-impact ambiguity나 최종 release에서 필요 시 사용한다.

---

# 32. Data Verification

Agent 결과뿐 아니라 Data pipeline도 검증한다.

```text
Raw Data
   ↓
Schema Check
   ↓
Quality Check
   ↓
Transformation Check
   ↓
Output Data
```

최소 확인 항목:

- 원본이 보존되어 있는가?
- 어떤 행/열이 변했는가?
- transformation 이유가 있는가?
- cleaning으로 데이터 의미가 훼손되지 않았는가?
- downstream Agent가 어떤 버전을 사용했는가?

---

# 33. Synthetic Test v0.2

최소 test 유형:

- happy path
- missing field
- duplicate record
- invalid type
- contradictory data
- ambiguous stakeholder instruction
- unavailable tool
- timeout
- unsupported request
- cross-organization mismatch
- stale data
- constraint violation

---

# 34. Release Gate v0.2

다음 조건을 확인한다.

- Problem Definition이 PASS 또는 명시적 CONDITIONAL_PASS
- Agent I/O contract 동작
- 필요한 DataAsset 접근 가능
- Data validation 수행
- critical transformation 검증
- Success Criteria와 테스트 연결
- deterministic test 통과
- unresolved critical conflict 없음
- known limitation 기록
- Contest Adapter packaging 가능
- 남은 시간 내 제출 가능

결과:

```text
RELEASE
RELEASE_WITH_KNOWN_LIMITATION
HOLD
```

---

# 35. Tool / Skill Architecture v0.2

```text
skills/
├── discover/
│   ├── scenario_profiler
│   ├── organization_profiler
│   ├── stakeholder_profiler
│   ├── process_mapper
│   ├── question_selector
│   ├── interview
│   └── evidence_integrator
├── data/
│   ├── inventory
│   ├── inspector
│   ├── quality_checker
│   ├── cleaner
│   ├── normalizer
│   └── transformation_validator
├── define/
│   ├── problem_synthesizer
│   └── definition_gate
├── design/
│   ├── solution_planner
│   ├── task_decomposer
│   └── agent_spec_builder
├── execute/
│   ├── action_decider
│   └── failure_router
└── verify/
    ├── test_generator
    ├── deterministic_validator
    └── semantic_judge
```

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

실제 repository 구조는 구현 단계에서 다시 결정한다.

---

# 36. Data Toolbelt v0.2

목표는 대형 Data Platform이 아니라 **빠른 Inspection / Validation / Cleaning**이다.

## CSV / Excel

- sheet/list inspection
- row / column count
- schema inference
- missing value
- duplicate
- type inconsistency
- summary statistics
- invalid date/number
- key uniqueness
- join candidate
- simple filtering
- normalized export

## JSON

- parse validation
- nested schema inspection
- missing key
- unexpected type
- flatten
- normalization

## Text

- encoding inspection
- line/block separation
- structured extraction
- table candidate extraction
- entity extraction
- normalization

## Cross-data

- join key candidate
- unmatched record
- duplicate entity
- inconsistent naming
- conflicting value
- coverage comparison

---

# 37. Contest Adapter

제출 형식은 확정 전까지 추측하지 않는다.

```text
ContestAdapter
├── ingest_environment()
├── normalize_input()
├── expose_stakeholder_interface()
├── expose_allowed_tools()
├── expose_data_assets()
├── package_agent()
├── validate_package()
└── submit_or_export()
```

---

# 38. Observability v0.2

대회 중 사람이 수초 내 현재 상태를 이해할 수 있어야 한다.

```text
PHASE
TIME REMAINING
CURRENT ORGANIZATION
CURRENT PROCESS
CURRENT PROBLEM
TOP HYPOTHESIS
CRITICAL UNKNOWNS
CRITICAL CONFLICTS
DATA ASSETS
DATA QUALITY WARNINGS
CURRENT PLAN
CURRENT TASK
CURRENT ACTION
LAST TOOL RESULT
FAILURE REASON
TRANSITION REASON
VALIDATION STATUS
```

---

# 39. Event Log v0.2

최소 event:

```text
phase_changed
organization_added
stakeholder_added
process_added
data_asset_added
data_issue_detected
data_transformed
question_asked
claim_added
evidence_added
hypothesis_changed
conflict_detected
gate_evaluated
plan_created
action_started
action_finished
tool_failed
validation_failed
retry
replan
reprofile
redefine
release
```

---

# 40. Budget Awareness v0.2

실전 기준:

```text
09:00 Problem Page Open
10:00 Contest Start
15:00 Contest End
```

09:00~10:00은 사전 준비시간으로 별도 취급한다.

---

# 41. Pre-start Operational Checklist

- 문제 페이지 입장
- 사전 준비 절차 완료
- 필요한 계정 로그인 상태 확인
- 브라우저 동작 확인
- Harness repository 확인
- Python/runtime 확인
- 사용할 LLM/Coding tool 확인
- 필요한 credential 정상 여부 확인
- local workspace 초기화
- system clock / timer 준비

실제 인증 방식과 허용 환경은 10/23 사전 안내 이후 다시 확인한다.

---

# 42. 5-hour Soft Budget

초기 Mock용 가이드:

```text
00:00~00:15  Environment / Scenario / Data inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

이 값은 최종 규칙이 아니다. Mock 결과를 통해 조정한다.

---

# 43. Release Reserve

최종 30분 정도를 release reserve 후보로 둔다.

reserve 진입 시:

- 저가치 인터뷰 중단
- optional feature 제거
- 추가 architecture 탐색 중단
- minimum viable Agent 유지
- verification 우선
- packaging 우선
- known limitation 기록

정확한 reserve 시간은 Mock 후 조정한다.

---

# 44. Failure Modes v0.2

기존 v0.1의 다음 Failure Mode를 유지한다.

- F1. Wrong Problem Definition
- F2. Infinite Interview
- F3. Wrong Stakeholder
- F4. Evidence Contradiction
- F5. LLM Hallucination
- F6. Planner Loop
- F7. Tool Failure
- F8. Coding Failure
- F9. Judge Inconsistency
- F10. Context Overflow
- F11. Time Shortage
- F12. API / Model Failure
- F13. Prompt Injection / Untrusted Input

v0.2에서 추가한다.

## F14. Wrong Process Mapping

징후:
- 실제 업무 순서와 다른 Process를 전제로 Agent 설계
- 병목 위치 오판

대응:
- 서로 다른 Stakeholder cross-check
- 실제 Data/Event 순서 확인
- Process step에 Evidence 연결

## F15. Bad Data Quality

징후:
- missing/duplicate/inconsistent 데이터 기반 자동화

대응:
- quality gate
- raw preservation
- validation
- data limitation 명시

## F16. Cleaning-induced Distortion

징후:
- 정제 과정에서 실제 의미가 사라짐

대응:
- transformation trace
- before/after 비교
- deterministic validation
- irreversible transformation 최소화

## F17. Cross-organization Mismatch

징후:
- 동일 필드/용어의 의미가 조직마다 다름
- handoff 과정에서 데이터 단위가 달라짐

대응:
- semantic mapping
- explicit schema
- organization-specific source trace

## F18. Data Availability Assumption

징후:
- Agent 설계는 좋지만 실제 필요한 데이터 접근 불가

대응:
- DEFINE Gate에서 data availability 확인
- fallback design
- human input 경로
- minimal viable data path

---

# 45. v0.2 Scope

## Must Have

- Canonical Problem State
- Organization
- Stakeholder
- Business Process
- DataAsset
- Data Quality
- Transformation History
- Metric
- Fact / Claim / Evidence / Hypothesis
- provenance
- Unknown / Conflict / Assumption
- Information Value 질문 선택
- Interview integration
- Process mapping
- Data inspection
- Problem Definition Gate
- PASS / CONDITIONAL_PASS / FAIL
- Solution Planner
- Agent Specification
- Phase Controller
- Action Loop
- retry / replan / reprofile / redefine
- deterministic validation
- minimal semantic judge
- budget state
- release reserve
- event log
- Contest Adapter interface
- Mock Scenarios
- end-to-end simulation

## Should Have

- coding agent integration
- lightweight tabular data toolbelt
- synthetic test generator
- model/tool fallback
- simple parallel execution
- human override
- state snapshot/export
- reusable validation rubric
- data diff / before-after report

## Later

- dynamic model routing
- cost optimization
- richer parallel scheduler
- specialized reviewer agents
- benchmark suite
- dashboard
- reusable domain packs
- automatic prompt optimization
- advanced semantic schema matching

## Do Not Build Yet

- graph DB
- microservices
- Kubernetes
- distributed queue
- generic workflow DSL
- drag-and-drop UI
- agent marketplace
- complex multi-agent hierarchy
- LLM jury
- persistent vector DB
- autonomous self-modifying architecture
- elaborate async framework
- Docker unless contest requires
- Web App unless contest requires
- full ETL platform
- domain-specific agriculture/fisheries solution library

---

# 46. Mock Scenario Strategy v0.2

이제 Mock은 일반 고객지원 예제보다 실제 대회 **문제 구조**와 유사하게 설계한다.

단, 실제 문제를 예측하거나 정답을 준비하지 않는다.

Mock 구조:

```text
Two Organizations
       +
Multiple Stakeholders
       +
Operational Process
       +
Multiple Data Assets
       +
Data Quality Problems
       +
Conflicting Claims
       +
Hidden Root Problem
       +
Time Pressure
```

---

# 47. Mock Scenario Pack Structure

```text
mock_01/
├── public_scenario.md
├── stakeholder_simulator.md
├── data/
│   ├── asset_01.csv
│   ├── asset_02.xlsx
│   └── ...
├── hidden_ground_truth.md
├── evaluation_rubric.md
└── expected_traps.md
```

Harness 실행자는 `public_scenario.md`와 실제 제공되는 data만 본다.

`hidden_ground_truth.md`는 테스트 종료 후 공개한다.

---

# 48. Recommended Mock Set

## Mock 01 — Conflicting Stakeholders + Dirty Data
검증: Claim vs Fact, Data quality, Conflict resolution, Process mapping

## Mock 02 — Misleading Initial Request
검증: symptom vs root problem, 질문 효율, Problem Definition

## Mock 03 — Hidden Critical Constraint
검증: data/privacy/tool constraint, DEFINE Gate

## Mock 04 — Cross-Organization Handoff Failure
검증: Organization, Process handoff, shared data, semantic mismatch

## Mock 05 — Severe Time Pressure + Tool Failure
검증: Budget, retry/replan, release reserve, CONDITIONAL_PASS

## Mock 06 — New Evidence Invalidates Problem
검증: redefine, state versioning, evidence history

---

# 49. Mock 실행 방식

```text
Public Scenario
      ↓
DISCOVER
      ↓
State Snapshot
      ↓
Question
      ↓
Stakeholder Simulator Response
      ↓
Data Inspection
      ↓
State Update
      ↓
DEFINE Gate
      ↓
DESIGN
      ↓
Paper Execution
      ↓
Verification
      ↓
Hidden Ground Truth 공개
      ↓
Design Gap 분석
```

---

# 50. Mock Evaluation Rubric

각 Mock은 다음을 평가한다.

```text
Problem Discovery
Process Understanding
Question Efficiency
Evidence Quality
Data Quality Handling
Conflict Handling
Root Cause Accuracy
Definition Gate Quality
Agent Design
Validation Quality
Budget Usage
Transition Correctness
Observability
```

목적은 “정답 점수”보다 **Harness 설계 gap 발견**이다.

---

# 51. Development Roadmap v0.2

## Stage 0 — v0.2 Design Baseline
현재 문서.

## Stage 1 — Mock 01
코드 작성 전 수동 실행.

## Stage 2 — v0.2.x Design Patch
Mock에서 발견한 schema/transition gap 수정.

## Stage 3 — Mock 02~03
Problem discovery와 constraint 검증.

## Stage 4 — v0.3 Design Freeze
최소 구현 전 설계 freeze.

## Stage 5 — Problem State + Event Model 구현
- state
- provenance
- organization
- process
- data asset
- budget
- event

## Stage 6 — DISCOVER + DATA 최소 구현
- profiling
- interview
- process mapping
- data inspection
- evidence integration

## Stage 7 — DEFINE
- synthesis
- gate
- assumption/risk

## Stage 8 — DESIGN
- strategy
- task decomposition
- Agent Spec

## Stage 9 — EXECUTE
- action loop
- tool registry
- transition

## Stage 10 — VERIFY / RELEASE
- deterministic validation
- semantic judge
- test
- release gate

## Stage 11 — Remaining Mock
Mock 04~06를 실제 구현으로 수행.

## Stage 12 — Contest Adapter
10/23 안내 이후 실제 제출 형식이 확인되면 구현.

---

# 52. 10/23 사전 안내 메일 확인 체크리스트

사전 안내가 도착하면 다음을 확인한다.

## Submission

- 정확한 제출 대상
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
- local execution 허용
- cloud execution 허용
- port/API 제한
- file size 제한

## AI / Tool

- 외부 LLM 허용 범위
- API 사용 범위
- Coding Agent
- web
- custom scripts
- external database
- automation

## Data

- 파일 format
- 다운로드 가능 여부
- upload 가능 여부
- 데이터 외부 전송 제한
- 개인정보/민감정보 규정

## Interview

- interaction UI
- 질문 횟수
- 횟수 제한
- timeout
- 동일 인물 재질문
- 답변 history

## Evaluation

- hidden test 여부
- Agent 실행 횟수
- 평가 metric
- 실제 action 평가 여부
- human evaluation 여부
- deterministic test 존재 여부

## Operational

- 인증 방식
- allowed browser
- network policy
- 사전 준비 항목
- 문제 페이지 조작 규칙
- 1인 참가 확인 방식

이 정보가 확인되면 `Contest Adapter`, Budget, Verification 전략을 즉시 업데이트한다.

---

# 53. v0.2 Design Acceptance Criteria

다음 질문에 모두 답할 수 있어야 한다.

1. 두 조직을 어떻게 표현하는가?
2. 조직별 Stakeholder는 어떻게 연결하는가?
3. 실제 업무 Process는 어떻게 저장하는가?
4. Process Step과 Data는 어떻게 연결하는가?
5. Stakeholder Claim과 Data가 충돌하면 어떻게 하는가?
6. Raw Data와 Cleaned Data를 구분하는가?
7. Transformation 이유와 이력이 남는가?
8. 어떤 Data가 Problem Definition을 지지했는지 추적 가능한가?
9. 필요한 데이터가 없을 때 어떻게 하는가?
10. Success Metric은 어떻게 정의하는가?
11. 질문을 언제 그만두는가?
12. Definition Gate가 왜 PASS인지 설명할 수 있는가?
13. CONDITIONAL_PASS의 Assumption이 기록되는가?
14. Agent Capability가 Process 문제와 연결되는가?
15. Agent가 사용하는 Data가 검증되었는가?
16. retry와 replan을 구분하는가?
17. 새로운 Evidence가 Root Problem을 깨면 redefine 하는가?
18. 남은 시간이 부족할 때 scope를 줄이는가?
19. 최종 제출 전에 최소 E2E 검증이 가능한가?
20. 실제 제출 형식이 달라져도 Core는 유지되는가?

---

# 54. Final Recommended Flow v0.2

```text
┌──────────────────┐
│     SCENARIO     │
└────────┬─────────┘
         │
         ▼
┌────────────────────────────────────────────┐
│ DISCOVER                                   │
│                                            │
│ Organization                              │
│ Stakeholders                              │
│ Business Process                          │
│ Data Assets                               │
│ Claims / Facts                            │
│ Hypotheses                                │
│ Unknowns                                  │
│ Questions                                 │
│                                            │
│         Epistemic Loop ↺                  │
└─────────────────┬──────────────────────────┘
                  │
          ┌───────▼────────┐
          │ DATA WORKSPACE │
          │ Inspect        │
          │ Validate       │
          │ Clean          │
          │ Normalize      │
          │ Trace          │
          └───────┬────────┘
                  │
                  ▼
┌────────────────────────────────────────────┐
│ DEFINE                                     │
│                                            │
│ Root Problem                               │
│ Affected Process                           │
│ Relevant Data                              │
│ Goal                                       │
│ Metric                                     │
│ Constraint                                 │
│ Assumption                                 │
│ Risk                                       │
│ Success Criteria                           │
│                                            │
│ PASS / CONDITIONAL_PASS / FAIL             │
└────────────┬───────────────────────┬───────┘
             │                       │ FAIL
             │                       └────────► DISCOVER
             ▼
┌────────────────────────────────────────────┐
│ DESIGN                                     │
│                                            │
│ Solution Strategy                          │
│ Agentification Gate                        │
│ Task Decomposition                         │
│ Required Data                              │
│ Tool Selection                             │
│ Agent Specification                        │
│ Validation Plan                            │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌────────────────────────────────────────────┐
│ EXECUTE                                    │
│                                            │
│ Decide                                     │
│ Execute                                    │
│ Observe                                    │
│ Validate                                   │
│ Update State / Data                        │
│                                            │
│          Action Loop ↺                    │
└───────┬────────────────────────────────────┘
        │
        ├── retry ─────────────► EXECUTE
        ├── replan ────────────► DESIGN
        ├── reprofile ─────────► DISCOVER
        ├── redefine ──────────► DEFINE / DISCOVER
        └── candidate complete
                       │
                       ▼
┌────────────────────────────────────────────┐
│ VERIFY / RELEASE                           │
│                                            │
│ Data Validation                            │
│ Deterministic Checks                       │
│ Semantic Judge if Needed                   │
│ Synthetic Tests                            │
│ Known Limitations                          │
│ Release Gate                               │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
            Contest Agent
                  +
         Verification Report
                  +
             Package
```

---

# 55. v0.2 최종 정의

> **AI TOP 100 Harness v0.2는 주어진 현장 Scenario에서 조직, 사람, 업무 프로세스, 데이터를 함께 구조화하고, 관계자 인터뷰와 데이터 검증을 통해 실제 문제를 발견·정의하며, 제한된 시간 안에 검증 가능한 최소 문제특화 AI Agent를 설계·구축·검증하여 제출 가능한 형태로 만드는 범용 Agentic Problem-Solving Harness이다.**

핵심 목표는 Framework 완성도가 아니다.

최종 목표는 다음이다.

> **Understand the operation.  
> Find the real problem.  
> Verify the data.  
> Build the minimum useful agent.  
> Prove that it works.**

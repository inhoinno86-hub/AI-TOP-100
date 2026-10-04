# AI TOP 100 Harness v0.1 설계 문서

**Version:** v0.1  
**Status:** Design Baseline / 구현 전 검토본  
**Purpose:** AI TOP 100 예선과 유사한 제한시간 환경에서, 주어진 상황을 빠르게 이해하고 실제 문제를 정의한 뒤 문제별 Agent를 설계·구축·검증하기 위한 범용 Harness 설계  
**Scope note:** 본 문서는 제공된 요구사항과 현재 가정만을 기준으로 한다. 실제 AI TOP 100 제출 형식, 실행 환경, API, hidden test, 평가 지표, 외부 Tool 허용 범위는 아직 확정 정보로 취급하지 않는다.

---

## 0. Executive Summary

AI TOP 100 Harness v0.1의 목적은 **대회 문제의 답을 미리 준비하는 것**이 아니라, 새로운 Scenario가 주어졌을 때 다음 과정을 안정적으로 수행하도록 돕는 범용 문제해결 Harness를 만드는 것이다.

> **Discover → Define → Design → Execute → Verify / Release**

핵심 설계 결정은 다음과 같다.

1. 기존 CareerGround, intent-loop, loop-engine의 **코드와 구조는 재사용하지 않는다.**
2. 기존 경험에서 검증된 개념만 가져오되, AI TOP 100의 제한시간 환경에 맞게 다시 설계한다.
3. 하나의 거대한 범용 Agent loop를 만들지 않는다.
4. 대신 두 개의 국소 Loop를 둔다.
   - **Epistemic Loop:** 무엇을 모르고 있으며 무엇을 더 물어봐야 하는가?
   - **Action Loop:** 현재 상태에서 다음 행동은 무엇이며 결과는 유효한가?
5. 전체 흐름은 얇은 **Phase Controller**가 관리한다.
6. 인터뷰 답변은 자동으로 사실이 되지 않는다. `Fact / Claim / Hypothesis / Evidence / Unknown / Conflict / Assumption`을 구분한다.
7. 모든 핵심 판단은 가능한 범위에서 **Evidence와 provenance**로 추적 가능해야 한다.
8. “완벽한 이해”를 목표로 하지 않는다. 제한시간 내 의사결정에 필요한 **충분한 이해**를 목표로 한다.
9. Definition Gate는 `PASS / CONDITIONAL PASS / FAIL`을 지원한다.
10. 검증은 항상 **Deterministic check 우선**, 필요한 경우에만 LLM-as-a-Judge를 사용한다.
11. Multi-agent, graph DB, microservice, 복잡한 workflow framework는 v0.1의 목표가 아니다.
12. Harness의 최종 산출물은 단순 답변이 아니라 다음 네 가지다.
    - Problem Definition Package
    - Agent Specification
    - Contest Agent
    - Verification Report
13. 실제 제출 규격은 아직 불확실하므로 Core와 Contest Adapter를 분리한다.
14. 제한시간이 가까워질수록 자동으로 탐색 범위를 줄이고 최소 제출 가능한 Agent를 우선하도록 **Budget-aware policy**를 둔다.

---

# 1. 현재 방향에 대한 구조적 평가

## 1.1 유지할 가치가 높은 방향

현재 제안의 중심 철학은 매우 적합하다.

> Do not solve before understanding.  
> Do not build before defining.  
> Do not trust before verifying.

특히 다음 요소는 v0.1의 핵심으로 유지한다.

- Zero-base 구현
- Domain-agnostic 설계
- Harness와 Contest Agent의 분리
- Evidence 기반 Problem Profiling
- Unknown과 Conflict의 명시적 관리
- Problem Definition Gate
- Tool과 Skill의 책임 분리
- 검증 우선 설계
- 플랫폼 독립적 Core
- Fail-visible observability
- 제한시간을 고려한 최소 구조

## 1.2 수정이 필요한 부분

### A. 하나의 Universal Loop Engine을 중심 구조로 두지 않는다

`State → Reason → Action → Observe → Update → Repeat`는 실행 단계에서는 유효하지만, 문제 발견과 인터뷰까지 동일한 loop로 표현하면 지나치게 추상적이 된다.

Discovery와 Execution은 본질적으로 다른 문제다.

**Discovery의 핵심 질문**
- 무엇을 모르는가?
- 어떤 가설을 검증해야 하는가?
- 누구에게 무엇을 물어야 하는가?
- 추가 정보가 실제 의사결정을 바꿀 가능성이 있는가?

**Execution의 핵심 질문**
- 현재 목표를 위해 다음 행동은 무엇인가?
- Tool 결과가 성공인가?
- 같은 행동을 retry할 것인가?
- plan 자체를 바꿔야 하는가?

따라서 v0.1에서는 하나의 거대한 loop 대신 아래 두 개의 국소 loop를 둔다.

```text
Epistemic Loop
Unknown / Hypothesis
      ↓
Select Question
      ↓
Ask / Observe
      ↓
Extract Evidence
      ↓
Update Belief State
      ↓
Assess Sufficiency
      ↺
```

```text
Action Loop
Current Execution State
      ↓
Decide Next Action
      ↓
Execute
      ↓
Observe
      ↓
Validate
      ↓
Update State
      ↺
```

이 두 loop를 상위 `Phase Controller`가 연결한다.

---

### B. UNDERSTAND보다 DISCOVER가 더 적합하다

`UNDERSTAND`는 수동적인 상태처럼 보일 수 있다. 실제 과정에는 stakeholder identification, 질문 생성, 인터뷰, conflict resolution이 포함되므로 v0.1에서는 다음 용어를 권장한다.

```text
DISCOVER
→ DEFINE
→ DESIGN
→ EXECUTE
→ VERIFY / RELEASE
```

기존 `PLAN`은 단순 작업계획만이 아니라 Solution Strategy와 Agent Specification을 포함하므로 `DESIGN`으로 확장한다.

기존 `ACT`는 Agent를 만드는 행위와 Agent가 문제를 수행하는 행위가 혼재될 수 있으므로 `EXECUTE`로 명확히 한다.

---

### C. “DEFINE 실패 시 무조건 DISCOVER”만 허용하면 교착될 수 있다

제한시간 환경에서는 모든 Unknown과 Conflict를 완전히 제거할 수 없다.

따라서 Definition Gate는 다음 세 결과를 가져야 한다.

- `PASS` — 계획 진행에 필요한 정보가 충분함
- `CONDITIONAL_PASS` — 일부 불확실성이 남지만 명시적 Assumption/Risk로 관리하며 진행 가능
- `FAIL` — 핵심 문제 자체가 정의되지 않아 추가 Discovery 필요

`CONDITIONAL_PASS`는 시간 제약 환경에서 매우 중요하다.

---

### D. Multi-agent는 기본값이 아니어야 한다

v0.1의 기본 실행 주체는 **Single orchestrator + Skills + Tools**로 한다.

Multi-agent가 필요한 조건은 다음과 같은 경우로 한정한다.

- 독립적인 작업을 병렬 처리했을 때 시간 절감이 큰 경우
- 서로 다른 관점의 독립 검토가 실제 품질을 높이는 경우
- 특정 전문 Agent의 context 분리가 명확한 이점이 있는 경우

그 외에는 orchestration 비용, context 중복, judge 비용, failure surface만 증가한다.

---

# 2. 놓치기 쉬운 중요한 설계 포인트

## 2.1 Provenance가 Confidence보다 먼저다

`Confidence = HIGH`만 저장하면 왜 높은지 설명할 수 없다.

모든 Fact, Claim, Evidence에는 최소한 다음 provenance가 필요하다.

- source type
- source identifier
- stakeholder
- 원문 또는 원문 reference
- 획득 시점/turn
- 직접 관찰인지, stakeholder 주장인지, LLM 추론인지
- 어떤 Assertion을 support / contradict하는지

Confidence는 provenance와 evidence 관계를 바탕으로 계산되거나 판단되어야 한다.

---

## 2.2 Interview Answer는 Fact가 아니다

Stakeholder가 말한 내용은 기본적으로 `Claim`이다.

예:

```text
Stakeholder A:
"보고서 작성에 시간이 너무 많이 걸립니다."
```

이것은 다음처럼 저장한다.

```text
Claim C-17
source: Stakeholder A
content: 보고서 작성 시간이 주요 지연 원인이다.
status: unverified
```

다른 측정 데이터나 독립 증거가 확인될 때 Fact로 승격할 수 있다.

특히 mock test에서 LLM이 만들어낸 가상 답변은 실제 대회 환경에서 획득한 응답과 반드시 구분해야 한다.

---

## 2.3 State는 “모든 대화 기록”이 아니라 “의사결정에 필요한 canonical state”여야 한다

전체 transcript를 매번 context에 넣으면 context overflow와 noise가 빠르게 증가한다.

권장 구조:

```text
Raw Transcript / Tool Results
        ↓
Evidence Extraction
        ↓
Canonical Problem State
        ↓
Current Decision Context
```

LLM에는 현재 판단에 필요한 최소 State만 제공하고, 원문은 필요할 때 reference로 다시 불러온다.

---

## 2.4 완전한 자동화보다 Human Control Plane이 중요하다

5시간 대회에서 사람이 시스템 내부를 이해하지 못하면 자동화가 오히려 위험하다.

Human은 모든 step을 승인할 필요는 없지만 최소한 다음은 즉시 볼 수 있어야 한다.

- 현재 phase
- 현재 root problem hypothesis
- critical unknown
- unresolved conflict
- current plan
- remaining budget
- 현재 action
- 실패 원인
- 다음 transition 이유

필요 시 다음 제어가 가능해야 한다.

- approve
- override
- skip
- force re-profile
- force re-plan
- abort action
- continue with assumption

---

## 2.5 Harness의 품질보다 Contest Agent의 품질이 최종 목표다

Harness 자체가 정교해지는 것이 목표가 아니다.

아래 질문을 모든 기능에 적용한다.

> 이 기능이 제한시간 내에 더 정확한 Problem Definition, 더 적절한 Agent, 더 높은 검증 성공률을 만드는가?

답이 명확하지 않다면 v0.1에서는 제외한다.

---

# 3. Project Goal

## 3.1 무엇을 만드는가

AI TOP 100 Harness v0.1은 새로운 Scenario를 입력받아 다음 작업을 보조 또는 자동화하는 범용 Agentic Problem-Solving Harness다.

1. Scenario 구조화
2. Stakeholder와 정보원 식별
3. Fact / Claim / Evidence / Unknown / Conflict 관리
4. 가치 있는 질문 선택
5. Interview 수행
6. Evidence 통합
7. Root Problem 정의
8. Goal / Constraint / Success Criteria 정의
9. Solution Strategy 설계
10. Agent Specification 생성
11. 필요한 Tool을 사용하여 Agent 구축/실행
12. 결과 검증
13. 문제 원인에 따라 retry / replan / reprofile / redefine
14. 최종 Contest Agent 패키징

---

## 3.2 무엇을 만들지 않는가

v0.1은 다음을 목표로 하지 않는다.

- 특정 산업 문제의 사전 Solution library
- 대회 답안 template 모음
- 범용 AutoGPT 대체 Framework
- 복잡한 Multi-agent Society
- 범용 workflow SaaS
- 자체 Web IDE
- Graph DB 기반 Knowledge Platform
- Kubernetes / distributed runtime
- 모든 Tool을 자동 탐색하는 Plugin ecosystem
- 완전 무인 autonomous software factory

---

## 3.3 AI TOP 100에서의 역할

```text
          ┌──────────────────────┐
          │    AI TOP 100 Task   │
          │ Scenario / Interview │
          └──────────┬───────────┘
                     │
                     ▼
          ┌──────────────────────┐
          │ AI TOP 100 Harness   │
          │ Problem Solving OS   │
          └──────────┬───────────┘
                     │
              generates / builds
                     │
                     ▼
          ┌──────────────────────┐
          │    Contest Agent     │
          │ Problem-specific AI  │
          └──────────┬───────────┘
                     │
                     ▼
              Contest Evaluation
```

`Harness != Contest Agent`

Harness는 대회 전 준비하는 범용 Layer이며, Contest Agent는 실제 Scenario가 주어진 뒤 Harness를 통해 정의·구축되는 문제특화 Layer다.

---

# 4. Design Principles

## P1. Zero-base

기존 코드, package layout, loop 구조를 그대로 가져오지 않는다.

검증된 것은 **개념**이지 **구현 구조**가 아니다.

---

## P2. Domain-agnostic

State와 workflow에 특정 산업, 직무, 데이터 형태를 hard-code하지 않는다.

---

## P3. Minimal Core

Core에는 다음만 둔다.

- State
- Phase transition
- Budget
- Contracts
- Event log

실제 reasoning 기능은 Skill로 분리한다.

---

## P4. Evidence-driven

핵심 판단은 Evidence 또는 명시적 Assumption과 연결한다.

---

## P5. State-driven

대화 문맥 자체가 system state가 되지 않는다.

구조화된 canonical state가 판단의 기준이다.

---

## P6. Provenance-first

Fact, Claim, Evidence의 source를 추적할 수 있어야 한다.

---

## P7. Platform-independent

Contest 제출 형식과 Core를 분리한다.

---

## P8. Human-controllable

자동화된 판단은 사람이 관찰하고 override할 수 있어야 한다.

---

## P9. Deterministic-first Verification

기계적으로 검증할 수 있는 것은 LLM에게 맡기지 않는다.

---

## P10. Fail-visible

실패를 숨기지 않는다.

실패 이유와 다음 전이 이유가 명시되어야 한다.

---

## P11. Budget-aware

완전성을 추구하다 제출을 놓치는 것을 방지한다.

---

## P12. Local Loop over Universal Loop

각 문제 유형에 맞는 작은 loop를 사용하고 거대한 abstraction을 피한다.

---

## P13. Append History, Derive Current View

Evidence history를 파괴적으로 rollback하지 않는다.

과거 event는 유지하고 현재 유효한 state view를 갱신한다.

---

# 5. Recommended High-level Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│                        Contest Environment                           │
│ Scenario / Stakeholder Interface / Files / APIs / Evaluation        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                        Contest Adapter
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         HARNESS CORE                                 │
│                                                                      │
│  ┌───────────────────┐       ┌───────────────────────────────────┐   │
│  │  Phase Controller │◄─────►│       Problem Workspace          │   │
│  └─────────┬─────────┘       │ Canonical State / Versions       │   │
│            │                 └───────────────────────────────────┘   │
│            │                                                        │
│  ┌─────────▼──────────────────────────────────────────────────────┐  │
│  │                        Skill Layer                            │  │
│  │                                                              │  │
│  │ DISCOVER     DEFINE        DESIGN       EXECUTE      VERIFY   │  │
│  │ profiler  definition   solution/agent   runner      verifier  │  │
│  │ interview     gate          spec          builder      tests   │  │
│  │ evidence                                                    │  │
│  └─────────┬──────────────────────────────────────────────────────┘  │
│            │                                                        │
│  ┌─────────▼───────────────────┐  ┌──────────────────────────────┐  │
│  │       Tool Registry        │  │ Budget / Observability      │  │
│  │ LLM / file / web / shell   │  │ time / iteration / events  │  │
│  │ python / coding agent ...  │  │ failures / decisions       │  │
│  └─────────────────────────────┘  └──────────────────────────────┘  │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           OUTPUTS                                    │
│  Problem Definition Package                                         │
│  Agent Specification                                                │
│  Contest Agent                                                      │
│  Verification Report                                                │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                        Contest Adapter
                               │
                               ▼
                         Submission Form
```

---

# 6. Component Boundary

## 6.1 Core

Core는 “무엇을 생각할지”보다 “상태와 제어”를 담당한다.

책임:

- current phase
- state version
- transition rules
- retry count
- iteration budget
- time budget
- event recording
- Skill invocation
- Tool access policy
- termination

Core 안에 복잡한 domain reasoning을 넣지 않는다.

---

## 6.2 Skill

Skill은 특정 reasoning task를 수행한다.

예:

- profile scenario
- identify unknowns
- generate interview questions
- integrate evidence
- define problem
- generate solution strategy
- produce agent spec
- analyze failure
- judge semantic output

Skill은 가능한 한 아래 형태를 따른다.

```text
Structured State
      +
Explicit Objective
      +
Allowed Tools
      ↓
Structured State Delta / Artifact
```

---

## 6.3 Tool

Tool은 외부 capability다.

예:

- LLM
- web
- file
- python
- shell
- API
- coding agent

Tool은 “문제를 왜 풀어야 하는지”를 판단하지 않는다.

---

## 6.4 Adapter

Adapter는 Harness와 외부 환경 간 translation layer다.

예:

```text
Contest Scenario
      ↓
Input Adapter
      ↓
Canonical Harness Input
```

```text
Contest Agent / Artifact
      ↓
Output Adapter
      ↓
Python / API / Docker / Workflow / URL / 기타 제출 형식
```

---

# 7. Problem State Schema

v0.1에서 가장 중요한 구조다.

## 7.1 State의 Top-level 구성

```text
ProblemState
├── meta
├── scenario
├── stakeholders
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

## 7.2 Scenario

Scenario는 원문과 정규화된 해석을 분리한다.

포함 개념:

- raw scenario
- source
- explicit task
- environment description
- known interfaces
- available artifacts
- known submission constraints
- unresolved environment questions

---

## 7.3 Stakeholder

최소 속성:

- id
- role
- relation to problem
- authority scope
- knowledge scope
- potential bias / limitation
- interview status
- information topics

`authority`와 `reliability`는 동일하지 않다.

---

## 7.4 Fact

정의:

> 현재 시스템이 검증된 것으로 취급하는 proposition.

Fact는 반드시 source가 있어야 한다.

예:

```text
F-12
content: 데이터 취합 작업은 매일 수동 수행된다.
source: process log / official scenario
verification: direct
```

---

## 7.5 Claim

정의:

> 특정 stakeholder 또는 source가 주장하지만 아직 객관적 사실로 확정하지 않은 proposition.

예:

```text
C-08
speaker: Stakeholder A
content: 보고서 작성 단계가 가장 오래 걸린다.
```

---

## 7.6 Hypothesis

정의:

> 여러 Fact / Claim / Evidence를 바탕으로 시스템이 검증하려는 잠정 설명.

예:

```text
H-03
content: 실제 bottleneck은 보고서 작성이 아니라 데이터 취합이다.
```

---

## 7.7 Evidence

Evidence는 단순 텍스트가 아니라 **어떤 assertion과 어떤 관계인지**를 가진다.

최소 속성:

- id
- source
- source_type
- provenance reference
- content
- target assertion
- relation: `support / contradict / contextual / neutral`
- reliability
- extraction confidence

예:

```text
E-21
source: Stakeholder B
target: H-03
relation: support
content: 매일 데이터 취합에 평균 3시간이 걸린다.
```

---

## 7.8 Unknown

정의:

> Problem Definition, Solution Architecture, Success Criteria, Risk 중 하나 이상에 영향을 줄 수 있으나 현재 값이 알려지지 않은 정보.

추가 속성:

- importance
- decision impact
- answerability
- owner / best source
- status
- linked hypotheses
- question candidates

---

## 7.9 Conflict

Conflict는 단순히 두 문장이 다르다는 의미가 아니다.

다음 조건에서 생성한다.

- 동일 사실에 대해 상충하는 Claim
- Evidence가 같은 Hypothesis를 동시에 강하게 support / contradict
- Constraint와 Goal이 양립하기 어려움
- Success Criteria 간 trade-off가 존재함

속성:

- related items
- severity
- impact
- resolution method
- resolved / unresolved

---

## 7.10 Assumption

정의:

> 확인되지 않았지만 제한시간 또는 접근 제한 때문에 임시로 채택한 전제.

모든 Assumption에는 다음이 필요하다.

- why needed
- impact if false
- mitigation
- validation opportunity
- expiry / revisit condition

---

## 7.11 Goal

Goal은 해결 후 도달해야 할 상태다.

Problem과 Solution을 혼동하지 않는다.

---

## 7.12 Constraint

예:

- 시간
- 사용 가능한 Tool
- 개인정보
- 시스템 접근 범위
- 실행환경
- latency
- 비용
- 사람이 반드시 승인해야 하는 단계

---

## 7.13 Risk

Risk는 `probability` 정밀 추정 대신 v0.1에서는 다음만으로 충분하다.

- severity
- likelihood: low / medium / high / unknown
- trigger
- mitigation
- owner

숫자 점수는 false precision을 만들 수 있으므로 기본값으로 사용하지 않는다.

---

## 7.14 Success Criteria

Success Criteria는 가능한 한 testable해야 한다.

각 항목:

- criterion
- measurement
- threshold 또는 pass rule
- validation method
- source

---

## 7.15 Current Problem Definition

최소 구성:

```text
Affected Actor / System
Current State
Observed Gap
Root Cause Hypothesis
Evidence
Desired State
Constraints
Critical Assumptions
Success Criteria
Non-goals
```

---

## 7.16 Plan / Solution Design

Plan은 단순 Todo list가 아니다.

각 task:

- objective
- dependency
- input
- expected output
- selected skill/tool
- success check
- failure route
- parallelizable
- budget

---

## 7.17 Execution State

- current task
- attempt number
- action
- tool
- input reference
- output reference
- result
- failure type
- next transition

---

## 7.18 Validation Result

- target artifact
- validation type
- criterion
- result
- evidence
- judge output if used
- final decision
- unresolved issue

---

# 8. Epistemic State Rules

v0.1에서는 정보의 종류를 명확히 승격/변경한다.

```text
Stakeholder Answer
       ↓
      Claim
       ↓
 Evidence collection / cross-check
       ↓
 ┌───────────────┐
 │ sufficiently  │
 │ verified?     │
 └───────┬───────┘
     Yes │ No
         │
   Fact  │ remains Claim
```

Hypothesis는 Evidence 상태에 따라 다음과 같이 변한다.

- active
- strengthened
- weakened
- rejected
- accepted_for_now

`accepted_for_now`는 Fact가 아니다.

---

# 9. Profiling / Interview Loop

## 9.1 목적

질문을 많이 하는 것이 아니라, **의사결정 가치가 높은 질문만 하는 것**이 목적이다.

---

## 9.2 Question Candidate 생성 기준

Question은 최소 하나를 바꿀 가능성이 있어야 한다.

- Root Problem Definition
- Solution Architecture
- Success Criteria
- Risk
- Constraint
- Tool choice
- Agent behavior

아무것도 바꾸지 않는 질문은 하지 않는다.

---

## 9.3 Information Value

v0.1에서는 정밀한 수치 공식보다 간단한 rubric을 사용한다.

평가 항목:

1. **Decision Impact**
   - 답이 달라지면 Problem/Solution이 바뀌는가?

2. **Uncertainty**
   - 현재 정보가 얼마나 부족한가?

3. **Discriminative Power**
   - 경쟁 Hypothesis를 구분할 수 있는가?

4. **Answerability**
   - 실제로 답을 얻을 가능성이 있는가?

5. **Cost**
   - 시간과 interaction 비용이 얼마인가?

권장 priority:

```text
CRITICAL
HIGH
MEDIUM
LOW
SKIP
```

숫자 score를 핵심 의사결정으로 사용하지 않는다.

---

## 9.4 누구에게 질문할 것인가

Stakeholder는 다음 기준으로 선택한다.

- 해당 Unknown에 대한 직접 경험
- 정보 authority
- 관찰 가능성
- 다른 source와 독립성
- 접근 비용

같은 질문을 여러 사람에게 묻는 것은 conflict validation에 가치가 있을 때만 수행한다.

---

## 9.5 Follow-up 조건

Follow-up은 다음 중 하나일 때 생성한다.

- 답변이 모호함
- 새로운 critical Unknown이 생김
- 기존 Hypothesis를 뒤집을 수 있음
- Conflict가 발생함
- Success Criteria가 불명확함
- Constraint가 새롭게 발견됨

---

## 9.6 Stop Condition

Discovery는 다음 중 하나가 충족되면 종료한다.

### Normal Stop

- Root Problem 후보가 충분히 Evidence로 지지됨
- critical Unknown이 없음
- critical Conflict가 없음
- Success Criteria 정의 가능
- Solution 선택에 영향을 주는 Unknown이 없음

### Budget Stop

- 남은 시간 대비 추가 질문의 Information Value가 낮음
- Definition에 필요한 최소 정보는 확보됨
- 남은 Unknown을 Assumption/Risk로 명시 가능

### Forced Stop

- stakeholder 접근 불가
- interface failure
- time reserve 침범 위험

Forced Stop 시 `CONDITIONAL_PASS` 또는 `ABORT` 판단으로 이동한다.

---

## 9.7 Hallucination 방지

Interview Skill은 다음을 금지한다.

- 답을 얻지 않았는데 stakeholder 답변을 생성해서 실제 Evidence처럼 저장
- 모호한 답을 임의로 구체화
- LLM inference를 stakeholder Claim으로 위장
- source 없는 Fact 생성

Mock mode에서 생성된 synthetic answer에는 반드시 다음 marker가 필요하다.

```text
source_type: synthetic_mock
```

---

# 10. Problem Definition Gate

## 10.1 Gate 목적

Plan을 만들 수 있는지를 판단하는 것이 아니라,

> **현재 정의된 문제를 기반으로 Solution을 설계해도 되는가?**

를 판단한다.

---

## 10.2 Gate Checklist

### Problem

- 해결 대상 Actor/System이 명확한가?
- 현재 상태와 Desired State가 명확한가?
- symptom과 root problem이 구분되어 있는가?

### Evidence

- 핵심 Problem statement가 Evidence와 연결되어 있는가?
- 단일 stakeholder의 주장만으로 확정하지 않았는가?

### Unknown

- critical Unknown이 남아 있는가?
- 남아 있다면 Assumption으로 관리 가능한가?

### Conflict

- 해결되지 않은 critical Conflict가 있는가?

### Criteria

- Success Criteria가 testable한가?

### Constraints

- 주요 실행 제약이 알려져 있는가?

---

## 10.3 Gate Result

### PASS

Solution 설계에 필요한 정보가 충분하다.

### CONDITIONAL_PASS

진행은 가능하지만 일부 불확실성이 있다.

필수 동작:

- Assumption 등록
- Risk 등록
- Agent Spec에 해당 제약 반영
- 가능하면 Verification에서 해당 assumption을 검증

### FAIL

다음 중 하나 수행:

- re-profile
- targeted interview
- evidence validation

---

# 11. DESIGN — Solution Planner

## 11.1 Planner의 목표

“해야 할 일 목록”이 아니라

> **최소 비용으로 Success Criteria를 만족할 수 있는 Contest Agent 구조**

를 설계한다.

---

## 11.2 Solution Strategy 생성

가능하면 1개의 답을 즉시 확정하지 않고 소수의 전략 후보를 만든다.

권장:

- 1~3개 전략
- 각 전략의 장점/제약
- 필요한 Tool
- 구현 난이도
- 검증 가능성
- 시간 비용

복잡한 tournament나 multi-agent debate는 사용하지 않는다.

---

## 11.3 Agentification Gate

Contest 제출물이 Agent여야 하더라도 내부 모든 기능을 Agent로 구현할 필요는 없다.

각 작업마다 먼저 판단한다.

```text
Can deterministic logic solve this?
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

---

## 11.4 Task Decomposition

각 Task는 다음을 가져야 한다.

- objective
- input contract
- output contract
- dependency
- validation
- failure policy
- time budget

---

## 11.5 Sequential vs Parallel

Parallel 실행은 다음을 모두 만족할 때만 고려한다.

- 서로 독립적
- 결과 병합이 단순함
- 병렬화가 실제 시간을 절약함
- 추가 context/coordination 비용보다 이점이 큼

v0.1에서는 general parallel scheduler를 만들지 않는다.

---

## 11.6 Human Intervention

다음 조건에서 human checkpoint를 권장한다.

- Problem Definition이 CONDITIONAL_PASS
- irreversible external action
- high-impact assumption
- Judge와 deterministic result 충돌
- 반복 실패
- 남은 시간이 release reserve 이하

---

# 12. Agent Specification

Problem Definition 이후 생성되는 Contest Agent의 canonical specification이다.

```text
AgentSpec
├── identity
│   ├── name
│   ├── purpose
│   └── problem_reference
│
├── interface
│   ├── inputs
│   ├── outputs
│   └── contracts
│
├── state
│
├── capabilities
│
├── tools
│   ├── allowed
│   └── forbidden
│
├── workflow
│
├── decision_rules
│
├── constraints
│
├── failure_handling
│
├── termination
│
├── validation
│
└── success_criteria
```

추가로 다음 traceability를 유지한다.

```text
Problem Definition
      ↓
Success Criteria
      ↓
Agent Capability
      ↓
Task / Tool
      ↓
Validation Test
```

Agent 기능이 Success Criteria와 연결되지 않는다면 제거 후보가 된다.

---

# 13. EXECUTE — Action Loop

## 13.1 기본 Loop

```text
Current State
      ↓
Decide Next Action
      ↓
Execute Tool / Skill
      ↓
Observe Result
      ↓
Validate
      ↓
Update State
      ↓
Transition
```

---

## 13.2 Transition 정의

### retry

사용 조건:

- Problem Definition 유효
- Plan 유효
- Action도 유효
- transient/tool/format 실패

정책:

- bounded retry
- 동일 입력 무한 반복 금지
- 반복 시 변경 이유 필요

---

### re-plan

사용 조건:

- Problem Definition은 유효
- 현재 Solution 또는 task path가 실패
- 다른 구현 전략이 필요

---

### re-profile

사용 조건:

- 실행 중 새로운 critical Unknown 발견
- Tool 결과가 기존 assumption을 깨뜨림
- 정보 부족으로 다음 행동 결정 불가

---

### re-define

사용 조건:

- 새로운 Evidence가 root problem 자체를 무효화
- Success Criteria가 잘못 설정됨
- 해결 대상이 바뀜

가장 비용이 큰 transition이므로 명시적 이유가 필요하다.

---

### abort

사용 조건:

- 제출 불가능
- Tool/environment inaccessible
- 남은 시간으로 최소 성공조건 달성 불가
- safety/constraint violation

Abort도 failure reason을 기록한다.

---

### finish

Release Gate 통과 시에만 가능하다.

---

## 13.3 Rollback 정책

전체 state를 과거로 되돌리지 않는다.

대신:

- event history 유지
- 기존 hypothesis를 rejected 처리
- current problem definition version 증가
- 새로운 plan version 생성

즉 **append history + current view update**를 기본으로 한다.

---

# 14. Tool / Skill Architecture

권장 개념 구조:

```text
skills/
├── discover/
│   ├── scenario_profiler
│   ├── stakeholder_profiler
│   ├── question_selector
│   ├── interview
│   └── evidence_integrator
│
├── define/
│   ├── problem_synthesizer
│   └── definition_gate
│
├── design/
│   ├── solution_planner
│   ├── task_decomposer
│   └── agent_spec_builder
│
├── execute/
│   ├── action_decider
│   └── failure_router
│
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
├── external_api
└── coding_agent
```

실제 repository 구조는 구현 단계에서 결정한다. 위 구조는 책임 경계 정의용이다.

---

# 15. Verification Architecture

검증은 세 Layer로 나눈다.

## 15.1 Layer 1 — Deterministic Validation

항상 먼저 수행한다.

적용 예:

- schema validity
- required field 존재
- JSON 형식
- 파일 존재
- function result
- exact constraint
- 계산 결과
- API response
- test pass/fail
- timeout
- duplicate / missing item

---

## 15.2 Layer 2 — LLM-as-a-Judge

다음과 같은 semantic quality에만 사용한다.

- 답변이 Problem Definition을 충족하는가?
- 중요한 조건을 누락했는가?
- 설명이 stakeholder 의도와 일치하는가?
- 생성 결과가 rubric을 만족하는가?

v0.1 규칙:

- Judge는 structured rubric 사용
- pass/fail 이유를 기록
- deterministic 결과를 override하지 않음
- 동일 Judge 반복 호출로 합의가 나올 때까지 돌리지 않음
- jury / multiple judge는 기본 범위에서 제외

---

## 15.3 Layer 3 — Human Review

사용 조건:

- high-impact ambiguity
- irreversible action
- definition conditional pass
- repeated failure
- judge conflict
- final release 직전 필요 시

---

## 15.4 Synthetic Test Cases

Success Criteria에서 직접 파생한다.

최소 유형:

- happy path
- missing input
- ambiguous input
- contradictory input
- tool failure
- timeout
- edge case
- constraint violation

Synthetic test 생성 자체도 과도하게 늘리지 않는다.

---

# 16. Release Gate

Contest Agent가 최종 제출 가능한지 확인한다.

Checklist:

- input/output contract 동작
- 주요 Success Criteria 충족
- deterministic test 통과
- critical failure handling 존재
- unresolved critical issue 없음
- known limitation 기록
- Contest Adapter package 가능
- 남은 시간 내 제출 가능

결과:

- RELEASE
- RELEASE_WITH_KNOWN_LIMITATION
- HOLD

---

# 17. Contest Adapter

현재 제출 형식을 가정하지 않는다.

Adapter contract만 정의한다.

```text
interface ContestAdapter

ingest_environment()
normalize_input()
expose_stakeholder_interface()
expose_allowed_tools()

package_agent(agent_spec, artifact)
validate_package()
submit_or_export()
```

v0.1에서는 실제 제출 방식이 확정되기 전까지 각 platform 구현을 만들지 않는다.

---

# 18. Observability

5시간 제한 환경에서는 완전한 tracing platform이 아니라 **빠른 상황 파악**이 목표다.

## 18.1 반드시 보여야 하는 정보

```text
PHASE
TIME REMAINING
CURRENT PROBLEM
TOP HYPOTHESIS
CRITICAL UNKNOWNS
CRITICAL CONFLICTS
CURRENT PLAN
CURRENT TASK
CURRENT ACTION
LAST TOOL RESULT
FAILURE REASON
RETRY / REPLAN REASON
VALIDATION STATUS
```

---

## 18.2 Event Log

최소 event:

- phase_changed
- question_asked
- evidence_added
- hypothesis_changed
- conflict_detected
- gate_evaluated
- plan_created
- action_started
- action_finished
- tool_failed
- validation_failed
- retry
- replan
- reprofile
- redefine
- release

복잡한 telemetry stack은 만들지 않는다.

---

# 19. Budget Awareness

## 19.1 Budget State

최소 항목:

- total time budget
- elapsed time
- remaining time
- phase soft budget
- iteration count
- retry count
- tool failure count
- release reserve

---

## 19.2 시간 배분 원칙

고정 비율이 아니라 configurable soft envelope를 사용한다.

예시:

```text
DISCOVER        15~20%
DEFINE           5~10%
DESIGN          10~15%
EXECUTE         35~45%
VERIFY/RELEASE  15~20%
BUFFER           remainder
```

이는 규칙이 아니라 초기 운영 가이드다.

---

## 19.3 Release Reserve

가장 중요한 budget rule 중 하나다.

최종 검증과 패키징에 사용할 시간을 미리 확보한다.

남은 시간이 reserve에 접근하면 다음 정책을 실행한다.

- 추가 저가치 Interview 중지
- nice-to-have 기능 제거
- 병렬 탐색 중단
- 최소 Agent 경로 선택
- unresolved issue를 limitation으로 기록
- Verification과 packaging 우선

---

# 20. Failure Modes

## F1. Wrong Problem Definition

징후:

- Agent가 symptom만 해결
- Success Criteria와 결과가 맞지 않음
- 실행 중 계속 새로운 핵심 정보 등장

대응:

- traceability 점검
- evidence gap 확인
- re-profile 또는 re-define

---

## F2. Infinite Interview

원인:

- stop condition 없음
- 모든 Unknown을 해결하려 함

대응:

- critical Unknown만 추적
- Information Value threshold
- iteration/time budget

---

## F3. Wrong Stakeholder

대응:

- knowledge scope / authority 기록
- 다른 source로 cross-check
- evidence reliability 낮춤

---

## F4. Evidence Contradiction

대응:

- Conflict object 생성
- 어느 판단을 바꾸는지 확인
- high-impact conflict만 targeted follow-up

---

## F5. LLM Hallucination

대응:

- source 없는 Fact 금지
- inference와 Claim 분리
- structured output
- deterministic validation
- provenance mandatory

---

## F6. Planner Loop

대응:

- strategy 후보 수 제한
- replan 횟수 제한
- 실패 원인 없이 plan 변경 금지

---

## F7. Tool Failure

대응:

- bounded retry
- alternative tool
- graceful degradation
- human fallback

---

## F8. Coding Failure

대응:

- 최소 기능 단위로 build
- test-first contract
- coding agent output도 검증
- large rewrite보다 localized fix 우선

---

## F9. Judge Inconsistency

대응:

- judge authority 제한
- rubric 고정
- deterministic result 우선
- 필요 시 human review

---

## F10. Context Overflow

대응:

- canonical state 사용
- raw transcript 분리
- active evidence만 context에 로드
- old detail on-demand retrieval

---

## F11. Time Shortage

대응:

- release reserve
- scope reduction
- conditional gate
- must-have path 우선

---

## F12. API / Model Failure

대응:

- provider-independent interface 가능 시 유지
- fallback model / manual mode
- critical workflow는 single unavailable model에 종속되지 않도록 설계

---

## F13. Prompt Injection / Untrusted Input

Scenario, web, file, stakeholder text는 명령이 아니라 **data**일 수 있다.

대응:

- Tool policy는 Harness가 소유
- 외부 text가 system policy를 변경하지 못하도록 분리
- 실행 명령은 explicit decision을 거쳐야 함

---

# 21. v0.1 Scope

## 21.1 Must Have

- canonical Problem State
- Fact / Claim / Evidence / Hypothesis 구분
- provenance
- Unknown / Conflict / Assumption
- Stakeholder profiling
- Information Value 기반 질문 선택
- Interview integration
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
- event log / observability
- Contest Adapter interface
- mock scenarios
- end-to-end simulation

---

## 21.2 Should Have

- coding agent integration
- synthetic test generator
- model/tool fallback
- simple parallel execution
- human override command
- state snapshot/export
- reusable validation rubric

---

## 21.3 Later

- dynamic model routing
- automatic cost optimization
- richer parallel scheduler
- specialized reviewer agents
- long-term run history analysis
- evaluation benchmark suite
- richer dashboard
- reusable domain packs
- automatic prompt optimization

---

## 21.4 Do Not Build Yet

- graph database
- microservices
- Kubernetes
- distributed queue
- generic workflow DSL
- drag-and-drop UI
- agent marketplace
- complex multi-agent hierarchy
- LLM judge jury
- persistent vector DB
- autonomous self-modifying architecture
- elaborate async framework
- Docker infrastructure unless contest requires it
- custom web application unless contest requires it

---

# 22. Recommended Development Roadmap

기존 제안보다 아래 순서를 권장한다.

## Stage 0 — Design Freeze

- terminology 확정
- component boundary 확정
- transition semantics 확정
- Gate rule 확정

코드 작성 전 종료 조건:

> 두 사람이 같은 문서를 읽었을 때 Fact/Claim/Hypothesis, retry/replan/redefine의 의미를 동일하게 이해할 수 있어야 한다.

---

## Stage 1 — Problem State + Event Model

먼저 “생각하는 Agent”보다 “무엇을 알고 있는지”를 표현한다.

구현 대상:

- conceptual schema → 최소 structured schema
- state version
- provenance
- budget
- event log

---

## Stage 2 — DISCOVER

- scenario profiling
- stakeholder profiling
- unknown generation
- question selection
- answer integration
- conflict detection

이 단계에서는 아직 Solution Planner를 만들지 않는다.

---

## Stage 3 — DEFINE

- problem synthesis
- gate
- conditional pass
- assumption/risk management

---

## Stage 4 — DESIGN

- solution strategy
- task decomposition
- validation planning
- Agent Spec generation

---

## Stage 5 — EXECUTE Core

- action loop
- tool registry
- retry / replan / reprofile / redefine
- budget enforcement

---

## Stage 6 — VERIFY / RELEASE

- deterministic validator
- semantic judge
- synthetic tests
- release gate

---

## Stage 7 — Contest Adapter Skeleton

제출 형식은 구현하지 않고 interface와 fake adapter만 만든다.

---

## Stage 8 — Mock Scenario End-to-End

서로 다른 유형의 generic scenario로 검증한다.

---

## Stage 9 — Coding Agent / Parallelism

실제 병목이 확인된 경우에만 추가한다.

---

# 23. Mock Test Strategy

설계 문서 다음 단계에서 실제 구현 전 **paper/mock test**를 먼저 수행한다.

## Scenario A — Conflicting Stakeholders

목표:

- Claim과 Fact 구분
- Conflict 생성
- targeted follow-up
- Definition Gate 검증

---

## Scenario B — Symptom vs Root Cause

목표:

- 첫 번째 사용자 요구를 바로 Solution으로 만들지 않는지 확인
- 추가 질문이 root cause를 바꾸는지 확인

---

## Scenario C — Missing Critical Constraint

목표:

- Planner가 Constraint 확인 전에 Agent를 설계하지 않는지 확인

---

## Scenario D — Time Pressure

목표:

- 모든 Unknown을 해결하려 하지 않는지 확인
- CONDITIONAL_PASS
- release reserve가 작동하는지 확인

---

## Scenario E — Tool Failure

목표:

- retry와 replan을 구분하는지 확인
- 같은 실패를 무한 반복하지 않는지 확인

---

## Scenario F — New Evidence Invalidates Problem

목표:

- 단순 retry가 아니라 re-define으로 이동하는지 확인

---

# 24. Design Acceptance Criteria

v0.1 설계는 다음 질문에 모두 답할 수 있어야 한다.

1. 시스템은 무엇을 Fact로 취급하는가?
2. stakeholder 말은 언제 Fact가 되는가?
3. 어떤 Unknown을 질문하는가?
4. 질문을 그만두는 조건은 무엇인가?
5. Problem Definition이 충분한지 누가 어떻게 판단하는가?
6. 불확실성이 남은 상태에서 진행할 수 있는가?
7. retry와 replan의 차이는 무엇인가?
8. 언제 re-profile하는가?
9. 언제 problem 자체를 re-define하는가?
10. deterministic check와 LLM Judge 중 무엇을 먼저 쓰는가?
11. 시간이 부족하면 무엇을 버리는가?
12. Contest Agent의 capability가 Success Criteria와 연결되는가?
13. 제출 형식이 바뀌면 Core를 수정해야 하는가?
14. 현재 실패 원인을 사람이 수초 내 파악할 수 있는가?
15. Framework 자체를 만들기 위한 기능이 섞여 있지 않은가?

하나라도 명확하지 않다면 해당 부분은 설계 미완료로 본다.

---

# 25. Final Recommended Flow

```text
┌───────────────┐
│    SCENARIO   │
└───────┬───────┘
        │
        ▼
┌──────────────────────────────┐
│ DISCOVER                     │
│                              │
│ Profile Scenario             │
│ Identify Stakeholders        │
│ Build Known/Unknown State    │
│ Form Hypotheses              │
│ Ask High-Value Questions     │
│ Integrate Evidence           │
│ Resolve Critical Conflicts   │
│                              │
│      Epistemic Loop ↺        │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ DEFINE                       │
│                              │
│ Root Problem                 │
│ Goal / Constraints           │
│ Assumptions / Risks          │
│ Success Criteria             │
│                              │
│ Gate:                        │
│ PASS / CONDITIONAL / FAIL    │
└───────┬───────────────┬──────┘
        │               │ FAIL
        │               └──────────────► DISCOVER
        ▼
┌──────────────────────────────┐
│ DESIGN                       │
│                              │
│ Solution Strategy            │
│ Task Decomposition           │
│ Tool Selection               │
│ Validation Plan              │
│ Agent Specification          │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│ EXECUTE                      │
│                              │
│ Decide                       │
│ Execute                      │
│ Observe                      │
│ Validate                     │
│ Update                       │
│                              │
│        Action Loop ↺         │
└───────┬──────────────────────┘
        │
        ├── retry ─────────────► EXECUTE
        ├── replan ────────────► DESIGN
        ├── reprofile ─────────► DISCOVER
        ├── redefine ──────────► DEFINE / DISCOVER
        └── candidate complete
                       │
                       ▼
┌──────────────────────────────┐
│ VERIFY / RELEASE             │
│                              │
│ Deterministic Checks         │
│ Semantic Judge if Needed     │
│ Synthetic Tests              │
│ Known Limitations            │
│ Release Gate                 │
└──────────────┬───────────────┘
               │
       PASS    │    FAIL
        ┌──────┴───────┐
        ▼              ▼
┌───────────────┐   Failure Router
│ Contest Agent │   → EXECUTE
│ + Verification│   → DESIGN
│ + Package     │   → DISCOVER
└───────────────┘   → DEFINE
```

---

# 26. v0.1에서 의도적으로 버린 것

이번 설계에서 기존 intent-loop 사고방식으로부터 의도적으로 거리를 둔 부분은 다음과 같다.

### Init Phase

별도 reasoning phase로 두지 않는다.

Session bootstrap, environment loading, state creation은 Controller의 초기화 동작이다.

---

### Generic Plan-Run-Review 반복

모든 문제를 동일 loop에 넣지 않는다.

Discovery와 Execution의 loop 목적이 다르므로 분리한다.

---

### LLM Judge 중심 Review

Review를 Judge와 동일시하지 않는다.

Deterministic validation이 가능한 경우 Judge를 사용하지 않는다.

---

### Multi-agent by Default

기본 구조에서 제외한다.

필요성이 mock test로 확인된 후에만 추가한다.

---

### 완전한 Graph Orchestration

Phase와 transition 수가 적으므로 초기에는 단순 state machine으로 충분하다.

---

### 정교한 Confidence 숫자

0.73 같은 수치는 근거 없는 정밀도를 만들 수 있다.

v0.1에서는 provenance, support/contradiction, reliability와 coarse confidence를 우선한다.

---

# 27. 핵심 철학의 최종 제안

기존 세 문장은 유지할 가치가 높다.

> **Do not solve before understanding.**  
> **Do not build before defining.**  
> **Do not trust before verifying.**

여기에 제한시간 환경을 위해 한 문장을 추가하는 것을 권장한다.

> **Do not pursue certainty beyond its decision value.**

즉, 더 많은 정보가 항상 더 좋은 것은 아니다.

이 Harness의 목표는 모든 것을 이해하는 것이 아니라,

> **주어진 시간 안에 올바른 문제를 충분히 이해하고, 검증 가능한 최소 Agent를 만들어 제출하는 것**

이다.

---

# 28. v0.1 Design Decision Summary

| Decision | v0.1 선택 |
|---|---|
| 전체 Phase | DISCOVER → DEFINE → DESIGN → EXECUTE → VERIFY/RELEASE |
| Universal Loop | 사용하지 않음 |
| Discovery | Epistemic Loop |
| Execution | Action Loop |
| Orchestrator | Single Phase Controller |
| Multi-agent | 기본 제외 |
| State | Structured canonical state |
| Evidence | provenance 필수 |
| Stakeholder answer | Claim으로 시작 |
| Definition Gate | PASS / CONDITIONAL_PASS / FAIL |
| Verification | Deterministic first |
| LLM Judge | semantic 영역에 제한 |
| Rollback | destructive rollback 대신 version/history |
| Time 관리 | Budget State + Release Reserve |
| Submission | Adapter로 분리 |
| Storage | 초기에는 단순 local state |
| UI | 구현하지 않음 |
| DB | 구현하지 않음 |
| Graph engine | 구현하지 않음 |
| Coding Agent | Should Have |
| Parallelism | 필요 시 제한적으로 |
| 최종 산출물 | Problem Package + Agent Spec + Contest Agent + Verification Report |

---

# 29. 다음 단계

이 문서를 v0.1 설계 baseline으로 확정한 뒤 바로 구현으로 들어가기보다 다음 순서를 권장한다.

```text
Design Baseline
      ↓
3~6개 Mock Scenario Paper Test
      ↓
Failure / Ambiguity 기록
      ↓
v0.1 Design 수정
      ↓
Minimal Schema 구현
      ↓
DISCOVER + DEFINE 구현
      ↓
End-to-End 최소 경로 구현
      ↓
Verification
      ↓
필요 기능만 추가
```

특히 첫 구현 전에 **Mock Scenario를 문서 상태만으로 손으로 통과시켜 보는 것**이 중요하다.

Mock 과정에서 다음이 명확하지 않다면 코드를 작성하기 전에 설계를 수정한다.

- 어떤 State가 추가되어야 하는가?
- Question priority를 어떻게 판단하는가?
- Gate가 왜 PASS/FAIL인가?
- retry인지 replan인지 어떻게 구분하는가?
- 어떤 Evidence 때문에 problem이 바뀌었는가?
- 시간이 부족할 때 무엇을 포기하는가?

---

## Final Definition

**AI TOP 100 Harness v0.1**은 다음과 같이 정의한다.

> **A zero-base, domain-agnostic, evidence-driven and budget-aware problem-solving harness that discovers the real problem, defines a testable objective, designs the minimum viable problem-specific agent, executes it through controlled tools, and verifies the result before release.**

한국어로는 다음과 같다.

> **AI TOP 100 Harness v0.1은 주어진 Scenario에서 실제 문제를 근거 기반으로 발견·정의하고, 제한된 시간 안에 문제특화 Agent를 설계·구축·실행하며, 검증 후 제출 가능한 형태로 만드는 범용 문제해결 Harness이다.**

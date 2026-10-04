# AI TOP 100 Harness v0.2.3 설계 문서

**Version:** v0.2.3  
**Status:** Mock #3 반영 Minor Patch / Mock #4 전 Baseline  
**Previous:** v0.2.2  
**Purpose:** AI TOP 100 [2026] 예선에서 주어진 현장 상황을 빠르게 이해하고, 관계자 인터뷰와 획득 데이터를 통해 실제 문제를 정의한 뒤, 문제특화 AI Agent를 설계·구축·검증할 수 있도록 지원하는 범용 Harness 설계  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Important:** 실제 제출 형식, 실행 API, hidden test 구조, 허용 Tool 세부 규칙 등은 아직 확정 정보로 취급하지 않는다.  
**Patch Basis:** Mock #1 — Conflicting Stakeholders + Dirty Data, Mock #2 — Misleading Initial Request, Mock #3 — Hidden Critical Constraint 결과

---

# 0. v0.2.3의 목적

v0.2.3은 v0.2.2의 Architecture를 재설계하는 버전이 아니다.

Mock #3에서 다음 구조는 실제로 유효했다.

```text
DISCOVER
  ↓
DEFINE
  ↓
DESIGN
  ↓
EXECUTE
  ↓
MANDATORY HUMAN GATE if required
  ↓
VERIFY / RELEASE
```

특히 다음이 검증되었다.

1. API / Tool capability와 실제 authorization을 분리할 수 있었다.
2. Stakeholder request와 authority를 분리할 수 있었다.
3. Critical Constraint를 protected action 이전에 발견할 수 있었다.
4. Constraint-related Unknown을 VerificationObligation으로 승계할 수 있었다.
5. Structural Remedy를 Agent보다 먼저 검토하는 구조가 유효했다.
6. Agent Role Classification이 solution scope를 줄이는 데 실제로 기여했다.
7. Mandatory Human Gate가 protected action 직전에 정상 작동했다.
8. APPROVE 이후 state corruption이나 duplicate execution 없이 RESUME할 수 있었다.
9. Monitoring throttling은 CRITICAL signal을 보존하면서 routine noise를 줄였다.
10. Metric MINIMAL → EXTENDED promotion과 ProcessHandoff freshness lazy semantics가 유효했다.

그러나 실제 Human Gate interaction에서 다음 operational gap이 드러났다.

> Human은 반드시 APPROVE / MODIFY / REJECT 중 하나를 즉시 선택하지 않는다.  
> 승인하기 전에 “왜 이 범위인가?”, “이 approval은 무엇인가?”, “왜 내가 다시 승인해야 하는가?”와 같은 설명을 요구할 수 있다.

따라서 v0.2.3은 다음 세 항목만 최소 patch로 추가한다.

```text
1. REQUEST_CONTEXT
2. ApprovalPacket
3. DOMAIN_AUTHORIZATION ≠ RUNTIME_EXECUTION_CONFIRMATION
```

핵심 원칙:

```text
Do not add a new architecture.
Do not replace the existing Human Gate.
Do not create a second workflow engine.
Patch only the observed decision-support gap.
```

---

# 1. Mock #3에서 확인된 핵심 결론

Mock #3은 다음 구조를 사용했다.

```text
Plausible automation request
+
Tool with read/write capability
+
Existing operational practice
+
Hidden authority boundary
+
Approval-required protected action
```

초기 요청은 temporary access credential을 Agent가 자동 생성하는 것이었다.

그러나 Evidence를 연결한 결과 다음이 확인되었다.

```text
Technical capability
≠
Business authorization

Stakeholder request
≠
Approval authority

Existing practice
≠
Approved policy
```

Harness는 restricted action의 실제 approver를 발견하고, 자동화 범위를 축소했다.

최종적으로 Agent는 다음 역할로 정리되었다.

```text
Initial:
BRIDGE

After structural integration:
CONTROL_DETECTION
+
EXCEPTION_HANDLER
```

Mock #3에서 가장 중요한 신규 관찰은 Human Gate에서 발생했다.

Human Supervisor는 제시된 protected action을 즉시 APPROVE하지 않고 추가 설명을 요청했다.

이 interaction은 실패가 아니었다.

오히려 정상적인 Human supervision behavior였다.

따라서 v0.2.3은 “approval decision”과 “approval decision을 위한 context acquisition”을 구분한다.

---

# 2. v0.2.2 → v0.2.3 변경 요약

| 영역 | v0.2.2 | v0.2.3 |
|---|---|---|
| Human Gate decisions | APPROVE / MODIFY / REJECT | APPROVE / MODIFY / REJECT / REQUEST_CONTEXT |
| Gate 설명 | rationale 중심 | ApprovalPacket projection 추가 |
| Approval 의미 | 단일 `approval` 표현 가능 | DOMAIN_AUTHORIZATION / RUNTIME_EXECUTION_CONFIRMATION 분리 |
| WAITING_APPROVAL | Human decision 대기 | Context 요청 동안에도 protected action block 유지 |
| Monitoring | Gate 자체 CRITICAL | Gate는 CRITICAL, context 요청은 HIGH 이상으로 즉시 반영 |
| Event Log | approval_requested / granted / rejected | human_context_requested / approval_packet_emitted / approval_context_insufficient 추가 |
| Architecture | v0.2.2 Core | 변경 없음 |
| Mock baseline | Hidden Critical Constraint 전 | Mock #3 완료 / Mock #4 Cross-Organization Handoff Failure 기준선 |

---

# 3. Design Principles v0.2.3

v0.2.2의 모든 원칙을 상속한다.

추가 원칙은 세 개뿐이다.

## P24. Explain Before Commit

Human에게 protected action 결정을 요구할 때, Human이 판단 가능한 최소 business / authority / scope context를 제공한다.

```text
Need a decision
≠
Need only a button
```

## P25. Context Request Is Not Approval

Human이 설명을 요청한 것은 APPROVE도 REJECT도 아니다.

```text
REQUEST_CONTEXT
→ keep WAITING_APPROVAL
→ do not execute
→ do not mutate protected resource
```

## P26. Domain Authorization ≠ Runtime Confirmation

조직/업무상 authorization과 Agent runtime execution confirmation을 구분한다.

```text
DOMAIN_AUTHORIZATION
= 이 업무 action 자체가 조직 정책상 허용되는가?

RUNTIME_EXECUTION_CONFIRMATION
= 이미 허용된 protected action을 현재 Agent가 지금 실행해도 되는가?
```

둘 중 하나가 다른 하나를 자동으로 대체하지 않는다.

---

# 4. High-level Architecture

v0.2.2 Architecture를 유지한다.

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

v0.2.3은 새로운 layer를 추가하지 않는다.

`ApprovalPacket`은 Human Supervision Plane이 existing canonical state를 읽어 만드는 **projection**이다.

---

# 5. Canonical State Separation

기존 분리를 유지한다.

```text
ProblemState
= 세상과 문제에 대해 Harness가 알고 있는 것

RuntimeState
= Harness가 지금 무엇을 하고 있는가

SupervisionState
= 사람이 무엇을 보고 있고, 개입이 필요한가
```

`ApprovalPacket`은 canonical state가 아니다.

다음 정보에서 파생된다.

```text
ProblemState
+
RuntimeState
+
Constraint / Authority
+
Evidence
+
Pending Action
+
SupervisionState
        ↓
ApprovalPacket Projection
```

원칙:

- Gate context 때문에 ProblemState를 복제하지 않는다.
- ApprovalPacket을 수정하여 canonical state를 직접 변경하지 않는다.
- context 요청은 Event를 생성하고 Core가 필요 시 state transition을 처리한다.

---

# 6. ProblemState v0.2.3

v0.2.2 구조를 유지한다.

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

# 7. Organization / Stakeholder / Process / Handoff / Identity / Data

v0.2.2 semantics를 그대로 유지한다.

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

## ProcessHandoff

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

Freshness field는 lazy semantics를 유지한다.

## EntityIdentity

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

## DataAsset

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

---

# 8. Metric Semantics

v0.2.2의 MINIMAL / EXTENDED profile을 유지한다.

```text
MINIMAL
- id
- name
- metric_type
- purpose
- definition
- measurement_source
- reliability
```

다음에 EXTENDED로 promote한다.

- Problem Definition 직접 지지
- DEFINE Gate 판단
- Success Criteria
- Release threshold
- 조직 간 동일 이름 Metric의 semantic 분리 필요

Promotion 시 Metric ID를 유지한다.

---

# 9. Constraint / Authority Model

v0.2.2 구조를 유지한다.

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

유지할 핵심 규칙:

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

# 10. NEW — Authorization Semantics Separation

v0.2.3은 `approval`이라는 하나의 표현이 두 다른 의미를 가질 수 있음을 명시한다.

## 10.1 DOMAIN_AUTHORIZATION

업무/조직/정책 관점의 authorization.

```text
DomainAuthorization
├── action
├── subject
├── resource
├── authority_holder
├── authorized_scope
├── conditions
├── validity
├── evidence_refs
└── status
```

질문:

- 이 action을 누가 승인할 권한이 있는가?
- 어떤 resource / scope까지 허용되는가?
- 어떤 선행조건이 필요한가?
- 현재 authorization이 유효한가?

## 10.2 RUNTIME_EXECUTION_CONFIRMATION

Agent가 이미 domain-authorized된 protected action을 **지금 실제 실행하는 것**에 대한 runtime confirmation.

```text
RuntimeExecutionConfirmation
├── proposed_action
├── protected_resource
├── side_effect_level
├── required
├── required_human_role
├── reason
├── requested_at
├── decision
├── decided_at
└── event_ref
```

질문:

- domain authorization은 이미 존재하는가?
- 그래도 runtime Human confirmation이 필요한가?
- 실행 side effect는 무엇인가?
- Human이 승인하는 것은 정확히 어떤 atomic action인가?

## 10.3 관계

```text
DOMAIN_AUTHORIZATION
       ↓
Scope valid?
       ↓
RUNTIME_EXECUTION_CONFIRMATION required?
       ├─ no  → execute
       └─ yes → Mandatory Human Gate
```

다음 anti-pattern을 금지한다.

```text
Domain approval exists
→ therefore agent may execute without runtime gate
```

그리고 반대로:

```text
Human clicked APPROVE
→ therefore missing domain authorization is repaired
```

도 금지한다.

Human runtime confirmation은 조직 정책상 필요한 authorization을 대신하지 않는다.

---

# 11. DEFINE Gate

v0.2.2 규칙을 유지한다.

평가 항목:

- Organization
- Actor
- Process
- ProcessHandoff 필요 범위
- Data
- Entity Identity 필요 범위
- Problem
- Evidence
- Unknown
- Conflict
- Metric profile / semantics
- Constraint / Authority
- Success Criteria
- Verification readiness

결과:

```text
PASS
CONDITIONAL_PASS
FAIL
```

Constraint-specific 원칙:

다음은 원칙적으로 PASS할 수 없다.

- protected action authority owner unknown
- solution이 export에 의존하지만 export permission unknown
- safety/privacy constraint가 solution path를 바꿀 가능성이 큼
- 곧 protected action을 수행해야 하는데 approval requirement unknown

CONDITIONAL_PASS는 safe placeholder / no-write path와 VerificationObligation이 있을 때만 가능하다.

---

# 12. VerificationObligation

v0.2.2 구조를 유지한다.

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

중요:

```text
required_before = BEFORE_PROTECTED_ACTION
```

이면 Mandatory Human Gate/action 이전에 반드시 재검사한다.

---

# 13. DESIGN — Structural Remedy before Agent

v0.2.2 순서를 유지한다.

```text
Root Problem
   ↓
Structural Remedy Candidate
   ↓
Constraint / Authority feasibility
   ↓
Why Agent?
   ↓
Agent Role
   ↓
Agentification Gate
```

Agent Role:

```text
PRIMARY_SOLUTION
BRIDGE
CONTROL_DETECTION
EXCEPTION_HANDLER
```

Agent가 BRIDGE면 sunset condition을 가능한 범위에서 명시한다.

---

# 14. Agent Specification v0.2.3

기존 필드를 유지하고 Human Gate 관련 표현만 명확하게 한다.

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
└── verification_obligations
```

## human_gate

```text
human_gate
├── protected_action
├── trigger_condition
├── domain_authorization_requirement
├── runtime_confirmation_requirement
├── required_human_role
├── approval_packet_fields
├── allowed_human_decisions
├── behavior_on_request_context
├── behavior_on_reject
└── behavior_on_modify
```

`allowed_human_decisions` 기본:

```text
APPROVE
MODIFY
REJECT
REQUEST_CONTEXT
```

---

# 15. Human Supervision Plane v0.2.3

기존 SupervisionState를 유지한다.

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
├── monitoring_policy
├── pending_digest
├── intervention
└── human_control
```

ApprovalPacket은 이 state에 영구 중복 저장하지 않고 필요 시 projection한다.

---

# 16. Monitoring Importance / Throttling

기존 규칙 유지:

```text
CRITICAL → immediate
HIGH     → immediate or next safe point
NORMAL   → digest / phase checkpoint
LOW      → on-demand / audit log
```

절대 throttle하지 않는 항목:

- Mandatory Human Gate
- human_intervention.required = YES
- authority / privacy / safety violation
- protected action proposal
- canonical Problem Definition invalidation
- DEFINE Gate result
- Release Gate result
- release-blocking VerificationObligation
- unrecoverable tool/data failure
- release reserve 진입

v0.2.3 추가:

```text
REQUEST_CONTEXT
→ HIGH by default

REQUEST_CONTEXT가 새로운 authority/scope mismatch를 드러냄
→ CRITICAL
```

---

# 17. NEW — ApprovalPacket

ApprovalPacket은 Human이 수초 내 protected action의 의미를 이해하고 판단할 수 있도록 하는 Human Supervision projection이다.

```text
ApprovalPacket
├── gate_id
├── business_context
├── subject
├── protected_resource
├── proposed_action
├── requested_scope
├── domain_authorized_scope
├── scope_delta
├── domain_authorization
│   ├── status
│   ├── authority_holder
│   ├── evidence_refs
│   └── validity
├── runtime_confirmation
│   ├── required
│   ├── reason
│   └── required_human_role
├── why_human_now
├── side_effect
├── reversibility
├── consequence_if_approved
├── consequence_if_rejected
├── alternatives
├── unresolved_items
├── verification_obligations
└── evidence_refs
```

## 17.1 최소 표시

Gate에서 모든 필드를 verbose하게 출력할 필요는 없다.

Human view 최소 표시:

```text
WHAT
- 무엇을 실행하려는가?

WHY
- 왜 지금 필요한가?

WHO / WHAT IS AFFECTED
- 대상 subject/resource는 무엇인가?

SCOPE
- 요청 범위와 domain-authorized 범위는 무엇인가?

AUTHORITY
- 누가 domain authorization을 갖고 있는가?

WHY HUMAN NOW
- 이미 domain authorization이 있는데도 왜 runtime confirmation이 필요한가?

EFFECT
- 승인 시 어떤 mutation이 발생하는가?

ALTERNATIVES
- MODIFY / REJECT 시 대안은 무엇인가?

EVIDENCE
- 핵심 근거는 무엇인가?
```

## 17.2 Scope Delta

가능하면 다음을 구조적으로 표시한다.

```text
requested_scope
⊆
authorized_scope
```

또는:

```text
requested_scope
⊄
authorized_scope
→ BLOCK
```

scope mismatch는 Human APPROVE로 우회할 수 없다.

## 17.3 Projection 원칙

- raw policy 전체를 Gate에 붙이지 않는다.
- decision-relevant evidence만 보여준다.
- confidence / unknown이 있으면 숨기지 않는다.
- 설명을 간단히 하되 authorization 의미를 축약하여 왜곡하지 않는다.

---

# 18. NEW — REQUEST_CONTEXT

## 18.1 정의

Human이 approval decision 전에 설명을 요구하는 interaction.

예:

- “이 90분은 왜 필요한가?”
- “이 approval reference는 무엇인가?”
- “왜 내가 또 승인해야 하는가?”
- “승인하지 않으면 어떻게 되는가?”
- “이 범위가 원래 승인된 범위와 같은가?”

이것은 APPROVE / MODIFY / REJECT가 아니다.

## 18.2 State Semantics

```text
WAITING_APPROVAL
      ↓
REQUEST_CONTEXT
      ↓
human_context_requested event
      ↓
protected action remains BLOCKED
      ↓
ApprovalPacket / explanation
      ↓
WAITING_APPROVAL 유지
```

다음은 변하지 않는다.

```text
pending_approval = YES
protected_action_executed = NO
domain_authorization = unchanged
canonical execution state = unchanged
```

## 18.3 Context Source

우선 committed state / Evidence만 사용한다.

```text
Current canonical state
+
Evidence
+
Constraint / Authority
+
Pending action
→ explanation
```

없는 사실을 설명 목적으로 만들지 않는다.

## 18.4 Context Insufficient

Human이 요구한 context가 현재 Evidence로 설명 불가능하면:

```text
approval_context_insufficient
```

이벤트를 남긴다.

그 후 다음을 판단한다.

```text
Can a safe read-only inspection resolve it?
  ├─ yes → targeted reprofile / inspection
  └─ no  → unresolved item 명시
```

중요:

- protected action은 계속 block 상태다.
- context 확보를 위해 별도 protected write를 수행하지 않는다.
- 필요한 경우 기존 `reprofile` transition을 사용한다.
- 새로운 state machine을 만들지 않는다.

## 18.5 Repeated REQUEST_CONTEXT

Human이 여러 번 추가 설명을 요구할 수 있다.

Harness는 이를 error로 처리하지 않는다.

다만 같은 답을 반복하지 않고 추가 질문의 실제 information need를 해석한다.

---

# 19. Mandatory Human Gate v0.2.3

대상:

- irreversible external write
- submission / publish
- protected system mutation
- sensitive data export
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
        ├─ no → execute
        └─ yes
             ↓
       Canonical state commit
             ↓
       Safe Point
             ↓
       ApprovalPacket projection
             ↓
       WAITING_APPROVAL
             ↓
 APPROVE / MODIFY / REJECT / REQUEST_CONTEXT
```

---

# 20. APPROVE

```text
approval_granted
→ domain authorization re-check
→ scope re-check
→ execute approved atomic action
→ validate result
→ state commit
→ resume AUTO
```

Human APPROVE가 missing domain authorization을 생성하지 않는다.

---

# 21. MODIFY

```text
human_override_received
→ modify proposed action
→ domain authorization re-check
→ scope re-check
→ constraint revalidation
→ plan / contract update if needed
→ execute only authorized modified action
→ resume
```

수정 범위가 authorized scope를 초과하면:

```text
BLOCK
```

필요한 경우 `replan` 또는 `reprofile`.

---

# 22. REJECT

```text
approval_rejected
→ protected action not executed
→ record rejection
→ assess alternate path
→ replan / reduced-scope design / manual path / HOLD
```

REJECT는 실패를 숨기지 않는다.

---

# 23. REQUEST_CONTEXT

```text
human_context_requested
→ keep WAITING_APPROVAL
→ emit ApprovalPacket / requested explanation
→ if context missing:
     targeted read-only reprofile if safe
→ return to same pending gate
```

Context request 후 자동 실행 금지.

---

# 24. Safe Point

기존 Safe Point를 유지한다.

```text
Before Action
After Tool Result
After Validation
After State Commit
Before Transition
Before Irreversible / Protected Action
```

Human Gate는 protected action 이전 safe point에서 발생한다.

REQUEST_CONTEXT는 이미 safe point에 있는 상태에서 처리하므로 partial execution을 만들지 않는다.

---

# 25. Transition Rules

기존 의미 유지.

```text
retry
= 동일 action/strategy가 유효하고 transient failure

replan
= Problem은 맞지만 solution/action path가 잘못됨

reprofile
= 새로운 critical information / owner / policy / identity / handoff evidence 필요

redefine
= canonical Problem Definition이 새 Evidence로 무효화

abort
= 최소 결과도 불가능

finish
= Release Gate 통과
```

추가 규칙:

```text
REQUEST_CONTEXT
≠ transition by itself
```

다만 context 부족 때문에 추가 evidence가 필요하면 Harness가 `reprofile`을 선택할 수 있다.

---

# 26. Event Log v0.2.3

기존 event를 유지하고 다음을 추가한다.

```text
human_context_requested
approval_packet_emitted
approval_context_insufficient
runtime_confirmation_requested
runtime_confirmation_granted
runtime_confirmation_rejected
```

기존 event와 의미 중복을 피하기 위해 구현 단계에서 다음 매핑을 허용한다.

```text
runtime_confirmation_granted
≈ approval_granted with approval_kind metadata
```

즉 이벤트 수를 불필요하게 늘리기보다 `approval_kind` metadata를 사용할 수 있다.

이는 구현 시 simplification 후보이며 Architecture 변경이 아니다.

---

# 27. Paper Execution

기본 형식 유지:

```text
Agent Action
↓
Authority / Constraint Pre-check
↓
[SAFE POINT]
↓
If protected:
    ApprovalPacket
    ↓
    Mandatory Human Gate
↓
Simulated Tool Result
↓
Observe
↓
Validate
↓
State Update
↓
Transition
```

Mock이므로 실제 side effect가 없어도 approval boundary는 유지한다.

---

# 28. VERIFY

Layer 1 — Deterministic:

- schema
- missing
- duplicate/event semantics
- type
- timestamp
- mapping
- rule compliance
- threshold
- transformation
- I/O contract
- constraint enforcement
- authority boundary
- approval-event trace
- no protected action without runtime confirmation when required
- REQUEST_CONTEXT가 approval로 잘못 처리되지 않았는지
- Human MODIFY / REJECT 반영 여부

Layer 2 — Semantic Judge:

- exception explanation
- policy interpretation summary
- stakeholder request 충족 여부
- root problem / solution consistency
- ApprovalPacket이 evidence를 왜곡하지 않았는지

Layer 3 — Human Review:

- high-impact ambiguity
- protected action
- unresolved authority
- release decision when required

---

# 29. Release Gate v0.2.3

확인:

- Problem Definition PASS / CONDITIONAL_PASS
- Agent contract
- required Data availability
- Data validation
- critical transformation validation
- Metric / Success Criteria ↔ test 연결
- deterministic tests
- unresolved critical Conflict
- unresolved critical Constraint
- domain authorization compliance
- runtime confirmation compliance
- approval / context interaction trace
- open VerificationObligation
- known limitations
- budget
- packaging feasibility

결과:

```text
RELEASE
RELEASE_WITH_KNOWN_LIMITATION
HOLD
```

다음은 known limitation으로 덮을 수 없다.

- known authority violation
- protected action without required runtime confirmation
- unresolved safety-critical restriction
- required data export permission unknown
- critical privacy rule unknown while design depends on that data
- requested scope exceeds authorized scope

---

# 30. Budget Awareness

v0.2.2 Soft Budget 유지:

```text
00:00~00:15  Environment / Scenario / Data inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

v0.2.3 추가 비용은 낮아야 한다.

ApprovalPacket은 existing state projection이므로 별도 deep analysis를 강제하지 않는다.

다음 anti-pattern을 피한다.

```text
Every Human Gate
→ giant policy summary
→ cognitive overload
```

목표는 설명의 양이 아니라 decision sufficiency다.

---

# 31. Failure Modes v0.2.3

v0.2.2 failure modes를 상속한다.

추가:

## F27. Premature Human Decision Pressure

징후:

- Human에게 맥락 없이 APPROVE / REJECT만 요구
- action scope / authority / consequence 불명확
- Human이 안전하게 판단할 수 없음

대응:

- ApprovalPacket
- REQUEST_CONTEXT

## F28. Context Request Misclassified as Approval

징후:

- “왜 90분인가?” 같은 질문 후 Agent가 실행
- context request를 affirmative intent로 오해

대응:

- REQUEST_CONTEXT first-class semantics
- WAITING_APPROVAL 유지
- protected action block

## F29. Approval Meaning Collapse

징후:

- domain authorization이 있으므로 runtime confirmation 생략
- runtime APPROVE가 missing domain authorization을 대체

대응:

- DOMAIN_AUTHORIZATION / RUNTIME_EXECUTION_CONFIRMATION 분리
- 각 evidence / scope 별도 검증

## F30. Approval Packet Overload

징후:

- 정책 문서 전체를 Human에게 덤프
- 실제 decision point가 보이지 않음

대응:

- projection only
- decision-relevant evidence
- scope / consequence / authority 중심

---

# 32. Human Control Commands v0.2.3

최소 command semantics:

```text
PAUSE
INTERRUPT
STEP
OVERRIDE_NEXT
ADD_CONSTRAINT
ADD_EVIDENCE
REQUEST_REPROFILE
REQUEST_REPLAN
RESUME
ABORT
```

Mandatory Human Gate interaction은 별도:

```text
APPROVE
MODIFY
REJECT
REQUEST_CONTEXT
```

Human이 정확한 키워드를 사용할 필요는 없다.

자연어 의도를 Harness가 해석한다.

예:

```text
"이 90분이 왜 필요한지 설명해줘"
→ REQUEST_CONTEXT
```

```text
"60분으로 줄여서 진행해"
→ MODIFY
```

```text
"그대로 진행해"
→ APPROVE
```

```text
"이 작업은 하지 마"
→ REJECT
```

---

# 33. Observability v0.2.3

기존 항목 유지:

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
MONITORING IMPORTANCE
EMISSION REASON
PENDING DIGEST COUNT
EVIDENCE REVISION
GATE RATIONALE
OPEN VERIFICATION OBLIGATIONS
VALIDATION STATUS
HUMAN INTERVENTION REQUIRED
SAFE TO INTERRUPT
```

Gate 시 추가:

```text
DOMAIN AUTHORIZATION STATUS
RUNTIME CONFIRMATION REASON
REQUESTED SCOPE
AUTHORIZED SCOPE
SCOPE DELTA
APPROVAL PACKET
```

---

# 34. Mock Execution Mode v0.2.3

기본:

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
Mandatory Human Gate if needed
      ↓
APPROVE / MODIFY / REJECT / REQUEST_CONTEXT
      ↓
VERIFY
      ↓
RELEASE
      ↓
Hidden Ground Truth
      ↓
Design Gap Review
```

---

# 35. Recommended Mock Set v0.2.3

## Mock 01 — Conflicting Stakeholders + Dirty Data
**완료**

검증:
- Claim vs Fact
- Data Quality
- Conflict
- Process
- Handoff
- Identity
- Monitoring

## Mock 02 — Misleading Initial Request
**완료**

검증:
- initial-request anchoring 방지
- Metric semantics
- freshness
- VerificationObligation
- Structural Remedy
- Agent Role
- monitoring cost

## Mock 03 — Hidden Critical Constraint
**완료**

검증:
- privacy/tool/authority constraint
- Authority reasoning
- Mandatory Human Gate
- protected action 차단
- safe resume

신규 발견:
- REQUEST_CONTEXT
- ApprovalPacket
- Approval meaning separation

## Mock 04 — Cross-Organization Handoff Failure
**다음**

Primary 검증:
- ProcessHandoff
- payload semantic mismatch
- organization boundary
- shared data
- EntityIdentity / CanonicalMapping
- delivery latency vs freshness
- handoff acknowledgment
- event/status semantics
- cross-org evidence chain

Secondary 검증:
- v0.2.3 Human Gate patch가 필요한 경우 자연스럽게 작동하는지
- ApprovalPacket이 과도한 overhead를 만들지 않는지
- REQUEST_CONTEXT를 approval로 오해하지 않는지

## Mock 05 — Severe Time Pressure + Tool Failure

검증:
- Budget
- retry / replan
- release reserve
- pause / interrupt safety

## Mock 06 — New Evidence Invalidates Problem

검증:
- redefine
- state versioning
- evidence history
- Evidence Revision monitoring

---

# 36. Mock #4 핵심 검증 질문

Mock #4에서는 특히 다음을 확인한다.

1. 조직 내부 step보다 조직 간 handoff를 first-class로 볼 수 있는가?
2. 전달 성공과 payload 의미 일치를 구분하는가?
3. 동일 business entity의 identifier namespace를 확인하는가?
4. non-unique identifier를 자동 join하지 않는가?
5. status progression과 duplicate record를 구분하는가?
6. delivery latency와 data freshness가 둘 다 실제로 필요한지 판단하는가?
7. freshness가 관련 없으면 field를 강제로 채우지 않는가?
8. cross-org ownership과 accountable owner를 분리하는가?
9. downstream error가 upstream data generation 때문인지 구분하는가?
10. semantic mismatch를 단순 data cleaning으로 덮지 않는가?
11. required transformation의 provenance를 남기는가?
12. DEFINE Gate가 unresolved identity/handoff ambiguity를 안전하게 다루는가?
13. 필요하면 VerificationObligation으로 Phase 간 승계하는가?
14. structural integration remedy를 Agent workaround보다 먼저 고려하는가?
15. Agent Role이 적절히 축소되는가?
16. v0.2.3 ApprovalPacket이 필요한 경우 Human에게 충분한 context를 주는가?
17. REQUEST_CONTEXT가 발생하면 action block을 유지하는가?
18. 5시간 Contest에서 상태 모델링 비용이 감당 가능한가?

---

# 37. Development Roadmap v0.2.3

## Stage 0 — v0.2 Design Baseline
완료.

## Stage 1 — Mock 01
완료.

## Stage 2 — v0.2.1 Design Patch
완료.

## Stage 3 — Mock 02
완료.

## Stage 4 — v0.2.2 Design Patch
완료.

## Stage 5 — Mock 03
완료.

주요 발견:

- Critical Constraint discovery 정상
- Authority model 정상
- VerificationObligation 정상
- Mandatory Human Gate 정상
- Human Gate context support 부족

## Stage 6 — v0.2.3 Minor Patch
현재 문서.

Patch:

- REQUEST_CONTEXT
- ApprovalPacket
- DOMAIN_AUTHORIZATION / RUNTIME_EXECUTION_CONFIRMATION 분리

## Stage 7 — Mock 04 — Cross-Organization Handoff Failure
v0.2.3 기준 수행.

## Stage 8 — v0.3 Design Freeze Decision
Mock #4 결과까지 반영하여 최소 구현 전 설계 freeze 여부 결정.

권장 판단 기준:

```text
If Mock #4 shows no structural flaw:
→ v0.3 Design Freeze

If only local semantics gaps:
→ v0.2.4 or v0.3-pre minor cleanup

If Handoff / Identity / State separation fails:
→ v0.3 structural revision before freeze
```

## Stage 9 — Core State + Event + Supervision Model 구현

- ProblemState
- RuntimeState
- SupervisionState
- Event Log
- provenance
- Organization
- Process
- ProcessHandoff + Freshness
- EntityIdentity
- Metric Profiles
- VerificationObligation
- Approval interaction semantics
- Budget

## Stage 10 — DISCOVER + DATA 최소 구현

## Stage 11 — DEFINE

## Stage 12 — DESIGN

## Stage 13 — EXECUTE

## Stage 14 — VERIFY / RELEASE

## Stage 15 — Human Supervision CLI

## Stage 16 — Remaining Mock 05~06

## Stage 17 — Contest Adapter

10/23 안내 이후 실제 제출 형식에 맞춘다.

---

# 38. v0.2.3 Design Acceptance Criteria

다음 질문에 답할 수 있어야 한다.

1. 두 조직을 분리해 표현할 수 있는가?
2. 조직별 Stakeholder와 authority scope를 연결할 수 있는가?
3. cross-org Business Process를 저장할 수 있는가?
4. Handoff from/to/payload/cadence/acknowledgment를 표현할 수 있는가?
5. delivery latency와 freshness를 구분할 수 있는가?
6. freshness field를 필요할 때만 활성화할 수 있는가?
7. 동일 entity의 조직별 identifier를 연결할 수 있는가?
8. non-unique identifier를 자동으로 잘못 join하지 않는가?
9. Raw / transformed / normalized data 이력을 유지하는가?
10. duplicate와 status progression을 구분하는가?
11. Claim / Fact / Evidence / Hypothesis를 구분하는가?
12. constraint / authority evidence provenance가 남는가?
13. Tool capability와 authorization을 구분하는가?
14. domain authorization과 runtime execution confirmation을 구분하는가?
15. Human APPROVE가 missing domain authorization을 대신하지 않는가?
16. Mandatory Human Gate가 protected action 전에 발생하는가?
17. Human이 decision 전에 REQUEST_CONTEXT를 사용할 수 있는가?
18. REQUEST_CONTEXT가 approval로 오해되지 않는가?
19. REQUEST_CONTEXT 중 protected action이 계속 block되는가?
20. ApprovalPacket이 requested scope와 authorized scope를 보여주는가?
21. ApprovalPacket이 왜 Human이 지금 필요한지 설명하는가?
22. ApprovalPacket이 giant policy dump가 되지 않는가?
23. context가 부족하면 hallucination 대신 targeted reprofile 또는 unknown을 표시하는가?
24. DEFINE Gate가 critical Unknown을 unsafe PASS하지 않는가?
25. CONDITIONAL_PASS Unknown이 VerificationObligation으로 남는가?
26. Success Criteria에 target/predicate가 있는가?
27. Metric은 MINIMAL에서 필요 시 EXTENDED로 promote되는가?
28. Structural Remedy를 Agent보다 먼저 검토하는가?
29. Agent Role을 PRIMARY / BRIDGE / CONTROL / EXCEPTION으로 설명할 수 있는가?
30. bridge Agent의 sunset condition을 설명할 수 있는가?
31. retry / replan / reprofile / redefine을 구분하는가?
32. Human Gate 이후 APPROVE / MODIFY / REJECT / REQUEST_CONTEXT semantics가 state corruption 없이 동작하는가?
33. approval trace와 context interaction trace를 VERIFY할 수 있는가?
34. Release Gate에서 unresolved authority / identity / VOB를 확인하는가?
35. 5시간 Contest에서 monitoring과 state richness가 과도하지 않은가?
36. 실제 제출 형식이 달라져도 Core는 유지되는가?

---

# 39. v0.2.3 최종 정의

> **AI TOP 100 Harness v0.2.3은 주어진 현장 Scenario에서 조직, 사람, 업무 프로세스, 조직 간 handoff, handoff freshness, entity identity, 데이터를 함께 구조화하고, 관계자 인터뷰와 데이터 검증을 통해 실제 문제를 발견·정의한 뒤, structural remedy와 Agent의 역할을 분리하고 제한시간 안에 검증 가능한 최소 Agent를 설계·검증하는 범용 Agentic Problem-Solving Harness다. 또한 protected/high-impact action 전에는 domain authorization과 runtime execution confirmation을 구분하고, Human에게 ApprovalPacket을 통해 필요한 판단 맥락을 제공하며, Human이 APPROVE / MODIFY / REJECT뿐 아니라 REQUEST_CONTEXT를 통해 추가 설명을 요구하더라도 action을 실행하지 않은 채 안전하게 WAITING_APPROVAL 상태를 유지한다.**

핵심 목표:

```text
Understand the operation.
Map the handoffs.
Check semantics before joining.
Check freshness only when it matters.
Resolve identity before cross-org joins.
Find the real problem.
Separate structural remedy from Agent role.
Separate technical capability from authority.
Separate domain authorization from runtime confirmation.
Explain before asking Humans to commit.
Treat context requests as context requests, not approvals.
Use rich metrics only where decisions need them.
Keep critical signals visible and noise digestible.
Keep deferred unknowns visible.
Build the minimum useful agent.
Prove that it works.
```

---

# 40. v0.2.3 다음 검증 목표

Mock #4 — Cross-Organization Handoff Failure에서 반드시 확인한다.

1. ProcessHandoff가 실제 Root Problem discovery에 기여하는가?
2. payload semantic mismatch를 delivery failure와 구분하는가?
3. cross-org EntityIdentity / CanonicalMapping이 올바르게 작동하는가?
4. identifier collision / namespace ambiguity를 자동으로 덮지 않는가?
5. duplicate/event/status progression semantics가 실제 데이터 손상을 막는가?
6. delivery latency와 freshness가 각각 필요할 때만 활성화되는가?
7. Handoff failure가 structural integration 문제인지 Agent reasoning 문제인지 구분하는가?
8. DEFINE Gate가 unresolved handoff/identity ambiguity를 적절히 처리하는가?
9. VerificationObligation이 cross-org Unknown도 Phase 간 유지하는가?
10. Structural Remedy Candidate가 Agent workaround를 가리지 않는가?
11. Agent Role Classification이 solution scope를 줄이는가?
12. Human Supervision throttling이 cross-org evidence revision을 놓치지 않는가?
13. Mandatory Human Gate가 자연스럽게 발생하는 경우 ApprovalPacket이 충분한 context를 제공하는가?
14. REQUEST_CONTEXT가 발생하면 protected action이 계속 block되는가?
15. v0.2.3 patch의 추가 cognitive/runtime cost가 낮은가?
16. Mock #4 이후 v0.3 Design Freeze가 가능한가?

---

# 41. Version Decision

Mock #3 기준 판단:

```text
v0.2.2 유지              → 부족
v0.2.3 minor patch       → 선택
v0.3 수준 구조 변경      → 필요 없음
v0.3 Design Freeze       → Mock #4 결과 후 판단
```

따라서 본 문서를 **v0.2.3 Mock #4 Source of Truth**로 사용한다.

---

# Appendix A. v0.2.3 Mock #4 Operational Checklist

Mock #4 실행 Harness는 다음을 실행 전 확인한다.

```text
[ ] ProcessHandoff is first-class
[ ] Freshness fields are lazy
[ ] EntityIdentity is checked before cross-org joins
[ ] Duplicate != status progression
[ ] Metric starts MINIMAL unless decision/gate requires EXTENDED
[ ] Critical monitoring signals bypass throttling
[ ] NORMAL/LOW signals may be digested
[ ] Structural Remedy Candidate is recorded before Agentification
[ ] Agent Role is classified
[ ] VerificationObligation required_before is explicit
[ ] Domain authorization != runtime execution confirmation
[ ] ApprovalPacket is a projection, not a second canonical state
[ ] REQUEST_CONTEXT does not execute the protected action
[ ] Human Gate occurs before protected/high-impact action
[ ] Human decision/context interaction is captured in events
```

Mock #4에서는 이 checklist 자체를 정답 힌트로 Scenario Runtime에 주입하지 않는다.

Harness는 visible Evidence를 통해 판단해야 한다.

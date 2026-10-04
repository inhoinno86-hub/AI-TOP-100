# AI TOP 100 Harness v0.2.4 설계 문서

**Version:** v0.2.4  
**Status:** Mock #4 반영 Minor Patch / Mock #5 전 Baseline  
**Previous:** v0.2.3  
**Purpose:** AI TOP 100 [2026] 예선에서 주어진 현장 상황을 빠르게 이해하고, 관계자 인터뷰와 획득 데이터를 통해 실제 문제를 정의한 뒤, 문제특화 AI Agent를 설계·구축·검증할 수 있도록 지원하는 범용 Harness 설계  
**Primary Constraint:** 2026-10-31 10:00~15:00, 온라인, 5시간 예선  
**Important:** 실제 제출 형식, 실행 API, hidden test 구조, 허용 Tool 세부 규칙 등은 아직 확정 정보로 취급하지 않는다.  
**Patch Basis:** Mock #1 — Conflicting Stakeholders + Dirty Data, Mock #2 — Misleading Initial Request, Mock #3 — Hidden Critical Constraint, Mock #4 — Cross-Organization Handoff Failure 결과

---

# 0. v0.2.4의 목적

v0.2.4는 v0.2.3의 Architecture를 재설계하는 버전이 아니다.

Mock #4에서 v0.2.3의 핵심 구조는 실제 Cross-Organization Handoff Failure를 발견하고 제한된 범위로 안전하게 해결하는 데 유효했다.

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

1. ProcessHandoff를 first-class로 모델링하면 organization 내부 step만 볼 때 놓치기 쉬운 cross-org failure를 발견할 수 있었다.
2. transport delivery success와 business/semantic validity를 분리할 수 있었다.
3. EntityIdentity를 cross-org join 전에 검사함으로써 textual ID equality를 canonical identity로 오해하지 않았다.
4. non-unique identifier를 자동 join하지 않고 ambiguity를 quarantine할 수 있었다.
5. exact duplicate와 status progression을 구분하여 destructive dedupe를 방지했다.
6. freshness는 decision value가 없을 때 lazy 상태로 두어 modeling cost를 줄였다.
7. Structural Remedy를 Agent workaround보다 먼저 검토했고 Agent Role을 BRIDGE / CONTROL_DETECTION / EXCEPTION_HANDLER로 축소할 수 있었다.
8. Mandatory Human Gate에서 ApprovalPacket, domain authorization, runtime confirmation이 정상 작동했다.
9. APPROVE 이후 scope re-check와 atomic resume가 가능했고 duplicate execution이 발생하지 않았다.
10. VerificationObligation을 이용해 unresolved identity와 event-contract risk를 release scope 밖에 격리할 수 있었다.

그러나 Mock #4에서 Architecture flaw가 아니라 **local state-semantics 명시성 gap** 네 개가 확인되었다.

```text
1. CanonicalMapping의 canonical object schema 부재
2. ProcessHandoff acknowledgment가 단일 field라 transport/business ACK 계층을 충분히 표현하기 어려움
3. ProcessHandoff schema에 delivery_status / semantic_validity가 명시적으로 없음
4. VerificationObligation이 어떤 action/resource subset을 실제로 block하는지 scope가 명시적으로 없음
```

따라서 v0.2.4는 이 네 항목만 최소 patch로 추가한다.

핵심 원칙:

```text
Do not add a new architecture.
Do not add a second state machine.
Do not turn every handoff into a heavy contract model.
Do not force CanonicalMapping when identity mapping is irrelevant.
Do not let one scoped VerificationObligation freeze unrelated safe work.
Patch only the semantics that Mock #4 proved necessary.
```

---

# 1. Mock #4에서 확인된 핵심 결론

Mock #4의 public request는 downstream reject를 AI Agent가 자동 수정하고 재전송하는 것이었다.

하지만 visible Evidence를 연결한 결과 다음이 확인되었다.

```text
Transport accepted
≠
Business accepted

Same textual identifier
≠
Same entity

Same request_id
≠
Exact duplicate

Agent workaround
≠
Root-cause removal
```

실제 문제는 cross-organization interface contract에서 location identity와 lifecycle event semantics가 조직마다 다르게 해석되는 것이었다.

Harness는 다음 방향으로 문제와 solution scope를 수정했다.

```text
Initial request:
AI fixes rejected rows and resubmits

Final structural direction:
Versioned identity/event contract
+
Deterministic canonical mapping
+
Layered acknowledgment

Agent role:
BRIDGE
+
CONTROL_DETECTION
+
EXCEPTION_HANDLER
```

51개의 high-confidence mapping은 protected publish 전에 Human Gate를 거쳤고, 6개의 unresolved mappings는 publish scope 밖에 유지되었다.

Mock #4에서 `REQUEST_CONTEXT` 자체는 실제로 사용되지 않았으므로 해당 경로는 PASS가 아니라 NOT EXERCISED로 남는다.

---

# 2. v0.2.3 → v0.2.4 변경 요약

| 영역 | v0.2.3 | v0.2.4 |
|---|---|---|
| CanonicalMapping | EntityIdentity의 `mapping_ids`와 개념 수준 | first-class canonical schema 추가 |
| Handoff acknowledgment | 단일 `acknowledgment` | lightweight `acknowledgments[]` 계층 표현 |
| Delivery / semantics | runtime interpretation 가능 | `delivery_status`, `semantic_validity` 명시 |
| Freshness | lazy semantics | 그대로 유지 |
| VerificationObligation | `required_before` 중심 | `blocking_scope` 추가 |
| Human Gate | ApprovalPacket + REQUEST_CONTEXT | 그대로 유지 |
| Authorization | Domain vs Runtime 분리 | 그대로 유지 |
| Architecture | v0.2.3 Core | 변경 없음 |
| Next Mock | Cross-org Handoff | Severe Time Pressure + Tool Failure |

---

# 3. Design Principles v0.2.4

v0.2.3의 모든 원칙을 상속한다.

추가 원칙은 세 개다.

## P27. Make Interface Health Dimensions Explicit

Handoff의 전달 여부, 의미 유효성, freshness를 하나의 `status`로 뭉개지 않는다.

```text
DELIVERY
≠
SEMANTIC VALIDITY
≠
FRESHNESS
```

단, freshness는 여전히 decision value가 있을 때만 활성화한다.

## P28. Canonical Mapping Is Evidence-Bound

cross-org / cross-system identity resolution이 필요하면 mapping 자체를 first-class evidence object로 표현한다.

```text
source identifier
+
namespace
+
target identifier
+
confidence
+
authority/provenance
```

non-unique source identifier나 unresolved mapping은 추측으로 resolve하지 않는다.

## P29. Obligations Block Only Their Actual Scope

VerificationObligation은 반드시 지켜야 하지만, 해당 obligation과 무관한 안전한 작업까지 자동으로 전역 block하지 않는다.

```text
required_before
+
blocking_scope
```

을 함께 사용하여 release/action boundary를 표현한다.

critical scope 자체가 전체 solution의 필수 전제이면 결과적으로 전체 HOLD가 될 수 있다.

---

# 4. High-level Architecture

v0.2.3 Architecture를 유지한다.

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

v0.2.4는 새로운 layer를 추가하지 않는다.

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

# 6. ProblemState v0.2.4

v0.2.3 구조를 유지하고 Mock #4에서 필요한 최소 field만 추가한다.

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

---

# 7. Organization / Stakeholder / Process / Handoff / Identity / Mapping / Data

v0.2.3 semantics를 유지하고 Mapping/Handoff 표현만 명시적으로 보강한다.

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
├── acknowledgments
│   └── []
│       ├── layer
│       ├── meaning
│       ├── status
│       ├── timestamp
│       └── evidence_ref
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

### Handoff Health Semantics

```text
delivery_status
= payload/transport가 intended receiver boundary에 도달했는가?

semantic_validity
= sender/receiver가 critical field, event, version을 compatible하게 해석하는가?

freshness_status
= downstream decision 시점에 payload가 충분히 최신인가?
```

이 세 항목은 서로 독립적이다.

예:

```text
delivery_status   = HEALTHY
semantic_validity = BROKEN
freshness_status  = FRESH
```

`acknowledgments[]`는 무조건 여러 계층을 만들기 위한 구조가 아니다.

- transport ACK와 business ACK가 실제로 다른 의미를 가질 때 분리한다.
- 단일 ACK만 존재하면 한 entry로 충분하다.
- layer 예: `TRANSPORT`, `SCHEMA_VALIDATION`, `BUSINESS_ACCEPTANCE`.

Freshness field는 기존 lazy semantics를 유지한다.

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

## NEW — CanonicalMapping

Identity resolution 자체가 decision/action에 영향을 줄 때 사용한다.

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

### Mapping confidence

```text
HIGH
MEDIUM
LOW
UNRESOLVED
```

원칙:

- `source_identifiers`는 composite key를 허용한다.
- textual ID equality만으로 HIGH를 부여하지 않는다.
- non-unique source identifier는 자동 resolve하지 않는다.
- `authority`는 mapping을 authoritative하게 확정할 수 있는 owner/registry/contract 근거를 표현한다.
- `provenance`는 어떤 DataAsset / Evidence / rule에서 mapping이 도출되었는지 보존한다.
- `validity`는 version, effective period, mapping-table version 등 실제 의사결정에 필요할 때만 사용한다.
- mapping이 필요 없는 scenario에서는 CanonicalMapping을 억지로 생성하지 않는다.

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

v0.2.3까지 검증된 MINIMAL / EXTENDED profile을 유지한다.

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

v0.2.3 Constraint / Authority 구조를 그대로 유지한다. v0.2.4에서 신규 authority field는 추가하지 않는다.

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

# 10. Authorization Semantics Separation — v0.2.3 inherited

v0.2.3에서 도입한 원칙을 유지한다. `approval`이라는 하나의 표현이 두 다른 의미를 가질 수 있음을 명시한다.

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

v0.2.3 DEFINE Gate 규칙을 유지하고 v0.2.4의 explicit handoff/mapping/VOB scope를 평가에 반영한다.

평가 항목:

- Organization
- Actor
- Process
- ProcessHandoff 필요 범위
- Data
- Entity Identity / CanonicalMapping 필요 범위
- Handoff delivery / semantic validity 필요 범위
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
- solution이 cross-source/cross-org mapping에 의존하지만 critical CanonicalMapping이 UNRESOLVED
- semantic validity가 root solution path를 바꿀 수 있는데 unresolved
- open VOB의 blocking_scope와 intended release/action scope가 겹치는데 resolution path가 없음

CONDITIONAL_PASS는 safe placeholder / no-write path와 VerificationObligation이 있을 때만 가능하다.

---

# 12. VerificationObligation

v0.2.3 구조를 유지하고 Mock #4에서 확인된 scope semantics를 추가한다.

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

## required_before

예:

```text
BEFORE_DESIGN_FINALIZATION
BEFORE_PROTECTED_ACTION
BEFORE_RELEASE
BEFORE_PRODUCTION
```

## NEW — blocking_scope

해당 VOB가 실제로 block하는 action/resource/entity subset을 표현한다.

예:

```text
VOB-17
required_before: BEFORE_PROTECTED_ACTION
blocking_scope:
  action: publish_canonical_mapping
  mapping_ids: [CM-41, CM-42, CM-43]
```

원칙:

- `blocking_scope` 밖의 safe action은 별도 조건을 충족하면 진행할 수 있다.
- critical unknown이 전체 solution의 전제이면 `blocking_scope = ENTIRE_SOLUTION`처럼 표현할 수 있다.
- scope를 억지로 세분화하여 실제 critical risk를 limitation으로 우회하지 않는다.
- Release Gate는 open VOB의 존재만이 아니라 `required_before + blocking_scope + current release scope`의 교집합을 판단한다.

`required_before = BEFORE_PROTECTED_ACTION`이고 pending action이 `blocking_scope`에 포함되면 Mandatory Human Gate/action 이전에 반드시 해결하거나 해당 scope를 action에서 제거한다.

---

# 13. DESIGN — Structural Remedy before Agent

v0.2.3의 Structural Remedy-first 순서를 유지한다.

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

# 14. Agent Specification v0.2.4

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

# 15. Human Supervision Plane v0.2.4

기존 SupervisionState를 유지한다. v0.2.4 patch는 별도 supervision state를 추가하지 않는다.

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

v0.2.3에서 추가된 규칙을 그대로 유지:

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

# 19. Mandatory Human Gate v0.2.4

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

# 26. Event Log v0.2.4

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
- handoff delivery_status
- handoff semantic_validity
- acknowledgment layer semantics when multiple ACKs exist
- mapping
- CanonicalMapping namespace / uniqueness / confidence / provenance
- VerificationObligation blocking_scope enforcement
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

# 29. Release Gate v0.2.4

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
- open VerificationObligation + blocking_scope intersection
- unresolved critical canonical mapping within release scope
- unresolved critical handoff semantic mismatch within release scope
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
- unresolved critical canonical mapping while current release scope depends on it
- unresolved semantic mismatch that can trigger wrong downstream action within current release scope

---

# 30. Budget Awareness

v0.2.3까지 사용한 Soft Budget을 유지한다:

```text
00:00~00:15  Environment / Scenario / Data inventory
00:15~00:55  DISCOVER
00:55~01:15  DEFINE
01:15~01:40  DESIGN
01:40~03:50  EXECUTE / BUILD
03:50~04:30  VERIFY / E2E Fix
04:30~05:00  RELEASE / Packaging / Submission
```

v0.2.4 추가 비용도 낮아야 한다. CanonicalMapping / acknowledgment layering / blocking_scope는 decision-relevant할 때만 활성화한다.

ApprovalPacket은 existing state projection이므로 별도 deep analysis를 강제하지 않는다.

다음 anti-pattern을 피한다.

```text
Every Human Gate
→ giant policy summary
→ cognitive overload
```

목표는 설명의 양이 아니라 decision sufficiency다.

---

# 31. Failure Modes v0.2.4

v0.2.3 failure modes를 상속한다.

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

# 32. Human Control Commands v0.2.4

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

# 33. Observability v0.2.4

기존 항목 유지:

```text
PHASE
TIME REMAINING
EXECUTION STATUS
CURRENT ORGANIZATION
CURRENT PROCESS
CURRENT HANDOFF
HANDOFF DELIVERY STATUS
HANDOFF SEMANTIC VALIDITY
CURRENT PROBLEM
TOP HYPOTHESES
CRITICAL UNKNOWNS
CRITICAL CONFLICTS
DATA ASSETS
DATA QUALITY WARNINGS
IDENTITY WARNINGS
CANONICAL MAPPING WARNINGS
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
VOB BLOCKING SCOPE
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

# 34. Mock Execution Mode v0.2.4

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

# 35. Recommended Mock Set v0.2.4

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
**완료**

검증 성공:
- ProcessHandoff first-class modeling
- delivery vs semantic validity
- EntityIdentity / non-unique identifier handling
- duplicate vs status progression
- freshness lazy semantics
- Structural Remedy before Agent
- Agent Role reduction
- Mandatory Human Gate / ApprovalPacket / safe resume

신규 local semantics gap:
- CanonicalMapping schema
- layered acknowledgment
- delivery_status / semantic_validity explicit fields
- VerificationObligation blocking_scope

`REQUEST_CONTEXT`는 NOT EXERCISED.

## Mock 05 — Severe Time Pressure + Tool Failure
**다음**

Primary 검증:
- Budget / timebox discipline
- retry vs replan
- repeated tool failure escalation
- release reserve
- minimum useful deliverable under incomplete evidence
- pause / interrupt / safe point
- low-value discovery 중단
- partial release vs HOLD

Secondary regression:
- v0.2.4 CanonicalMapping / Handoff health fields가 필요할 때만 사용되는지
- VOB `blocking_scope`가 safe partial progress를 과도하게 막지 않는지
- natural Human Gate가 발생하면 ApprovalPacket 유지
- 사용자가 REQUEST_CONTEXT를 선택할 경우 WAITING_APPROVAL / protected-action block 유지

## Mock 06 — New Evidence Invalidates Problem

검증:
- redefine
- state versioning
- evidence history
- Evidence Revision monitoring

---

# 36. Mock #5 핵심 검증 질문

Mock #5에서는 특히 다음을 확인한다.

1. 5시간 budget에서 모든 Unknown을 조사하려 하지 않고 high-value evidence에 집중하는가?
2. transient tool failure와 strategy-invalidating failure를 구분하는가?
3. retry가 무한 반복되지 않고 retry budget / attempt history가 보이는가?
4. 동일 strategy가 계속 유효하면 `retry`, 다른 route가 필요하면 `replan`을 선택하는가?
5. 새로운 critical owner/policy/data evidence가 필요하면 `reprofile`을 선택하는가?
6. canonical Problem이 아직 유효한데 tool failure만으로 `redefine`하지 않는가?
7. 실패한 tool의 capability를 evidence가 없는 상태에서 hallucinate하지 않는가?
8. fallback source가 stale / partial이면 freshness나 completeness를 실제 decision value에 맞게 검사하는가?
9. release reserve에 진입하면 낮은 가치 기능을 잘라내는가?
10. 최소 Agent contract와 verification path를 남기고 scope를 줄일 수 있는가?
11. open VOB가 있더라도 `blocking_scope` 밖의 safe scope를 release할 수 있는가?
12. 반대로 release scope와 critical VOB가 겹치면 HOLD하는가?
13. Monitoring이 tool failure / budget exhaustion / release reserve를 CRITICAL 또는 HIGH로 즉시 보여주는가?
14. NORMAL/LOW retry detail은 digest하여 cognitive cost를 줄이는가?
15. Human interrupt가 safe point에서 state corruption 없이 처리되는가?
16. protected/high-impact action이 자연스럽게 발생하면 Human Gate 전에 멈추는가?
17. REQUEST_CONTEXT 사용 시 protected action이 실행되지 않는가?
18. v0.2.4 patch가 time pressure에서 과도한 modeling overhead를 만들지 않는가?
19. 결과물이 perfect solution이 아니라 contest-time minimum useful solution으로 수렴하는가?
20. Mock #5 후 v0.3 Design Freeze로 갈 수 있는가?

---

# 37. Development Roadmap v0.2.4

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

## Stage 6 — v0.2.3 Minor Patch
완료.

Patch:
- REQUEST_CONTEXT
- ApprovalPacket
- DOMAIN_AUTHORIZATION / RUNTIME_EXECUTION_CONFIRMATION 분리

## Stage 7 — Mock 04 — Cross-Organization Handoff Failure
완료.

주요 결과:
- Handoff / Identity / Event semantics Architecture 정상
- Structural Remedy / Agent Role 정상
- ApprovalPacket / runtime confirmation 정상
- REQUEST_CONTEXT NOT EXERCISED
- local semantics gap 4개 발견

## Stage 8 — v0.2.4 Minor Patch
현재 문서.

Patch:
- CanonicalMapping first-class schema
- ProcessHandoff layered acknowledgments
- delivery_status / semantic_validity explicit fields
- VerificationObligation blocking_scope

## Stage 9 — Mock 05 — Severe Time Pressure + Tool Failure
v0.2.4 기준 수행.

Mock #5에서 REQUEST_CONTEXT를 위한 자연스러운 protected action이 발생하면 targeted regression도 함께 수행한다.

## Stage 10 — v0.3 Design Freeze Decision

권장 판단 기준:

```text
If Mock #5 shows no structural flaw and REQUEST_CONTEXT path is exercised or independently regression-checked:
→ v0.3 Design Freeze

If only local runtime/budget semantics gaps:
→ v0.2.5 or v0.3-pre cleanup

If retry/replan/budget/supervision state separation fails:
→ structural revision before freeze
```

## Stage 11 — Core State + Event + Supervision Model 구현

- ProblemState
- RuntimeState
- SupervisionState
- Event Log
- provenance
- Organization
- Process
- ProcessHandoff + Handoff Health
- EntityIdentity
- CanonicalMapping
- Metric Profiles
- VerificationObligation + blocking_scope
- Approval interaction semantics
- Budget

## Stage 12 — DISCOVER + DATA 최소 구현

## Stage 13 — DEFINE

## Stage 14 — DESIGN

## Stage 15 — EXECUTE

## Stage 16 — VERIFY / RELEASE

## Stage 17 — Human Supervision CLI

## Stage 18 — Mock 06

## Stage 19 — Contest Adapter

10/23 안내 이후 실제 제출 형식에 맞춘다.

---

# 38. v0.2.4 Design Acceptance Criteria

다음 질문에 답할 수 있어야 한다.

1. 두 조직을 분리해 표현할 수 있는가?
2. 조직별 Stakeholder와 authority scope를 연결할 수 있는가?
3. cross-org Business Process를 저장할 수 있는가?
4. Handoff from/to/payload/cadence를 표현할 수 있는가?
5. transport ACK와 business ACK가 다르면 `acknowledgments[]`로 구분할 수 있는가?
6. delivery_status와 semantic_validity를 별개로 표현할 수 있는가?
7. delivery latency와 freshness를 구분할 수 있는가?
8. freshness field를 필요할 때만 활성화할 수 있는가?
9. 동일 entity의 조직별 identifier를 연결할 수 있는가?
10. CanonicalMapping에 namespace / identifiers / confidence / authority / provenance를 보존할 수 있는가?
11. non-unique identifier를 자동으로 잘못 join하지 않는가?
12. mapping이 필요 없는 scenario에서는 CanonicalMapping을 억지로 생성하지 않는가?
13. Raw / transformed / normalized data 이력을 유지하는가?
14. duplicate와 status progression을 구분하는가?
15. Claim / Fact / Evidence / Hypothesis를 구분하는가?
16. constraint / authority evidence provenance가 남는가?
17. Tool capability와 authorization을 구분하는가?
18. domain authorization과 runtime execution confirmation을 구분하는가?
19. Human APPROVE가 missing domain authorization을 대신하지 않는가?
20. Mandatory Human Gate가 protected action 전에 발생하는가?
21. Human이 decision 전에 REQUEST_CONTEXT를 사용할 수 있는가?
22. REQUEST_CONTEXT가 approval로 오해되지 않는가?
23. REQUEST_CONTEXT 중 protected action이 계속 block되는가?
24. ApprovalPacket이 requested scope와 authorized scope를 보여주는가?
25. ApprovalPacket이 왜 Human이 지금 필요한지 설명하는가?
26. ApprovalPacket이 giant policy dump가 되지 않는가?
27. context가 부족하면 hallucination 대신 targeted reprofile 또는 unknown을 표시하는가?
28. DEFINE Gate가 critical Unknown을 unsafe PASS하지 않는가?
29. CONDITIONAL_PASS Unknown이 VerificationObligation으로 남는가?
30. VOB의 `blocking_scope`가 어떤 action/resource가 block되는지 명확히 하는가?
31. VOB scope 밖의 safe progress를 허용하되 critical risk를 우회하지 않는가?
32. Success Criteria에 target/predicate가 있는가?
33. Metric은 MINIMAL에서 필요 시 EXTENDED로 promote되는가?
34. Structural Remedy를 Agent보다 먼저 검토하는가?
35. Agent Role을 PRIMARY / BRIDGE / CONTROL / EXCEPTION으로 설명할 수 있는가?
36. bridge Agent의 sunset condition을 설명할 수 있는가?
37. retry / replan / reprofile / redefine을 구분하는가?
38. repeated tool failure가 infinite retry를 만들지 않는가?
39. release reserve에서 lower-value work를 축소할 수 있는가?
40. Human Gate 이후 APPROVE / MODIFY / REJECT / REQUEST_CONTEXT semantics가 state corruption 없이 동작하는가?
41. approval trace와 context interaction trace를 VERIFY할 수 있는가?
42. Release Gate에서 unresolved authority / identity / handoff semantics / VOB scope를 확인하는가?
43. 5시간 Contest에서 monitoring과 state richness가 과도하지 않은가?
44. 실제 제출 형식이 달라져도 Core는 유지되는가?

---

# 39. v0.2.4 최종 정의

> **AI TOP 100 Harness v0.2.4는 주어진 현장 Scenario에서 조직, 사람, 업무 프로세스, 조직 간 handoff, handoff health, entity identity, canonical mapping, 데이터를 함께 구조화하고, 관계자 인터뷰와 데이터 검증을 통해 실제 문제를 발견·정의한 뒤, structural remedy와 Agent의 역할을 분리하고 제한시간 안에 검증 가능한 최소 Agent를 설계·검증하는 범용 Agentic Problem-Solving Harness다. Handoff에서는 delivery, semantic validity, freshness를 필요한 수준에서 분리하고, identity resolution이 필요하면 provenance와 authority가 연결된 CanonicalMapping을 사용한다. deferred Unknown은 VerificationObligation의 required_before와 blocking_scope로 정확한 실행/릴리즈 범위에 연결한다. 또한 protected/high-impact action 전에는 domain authorization과 runtime execution confirmation을 구분하고, Human에게 ApprovalPacket을 통해 필요한 판단 맥락을 제공하며, Human이 APPROVE / MODIFY / REJECT뿐 아니라 REQUEST_CONTEXT를 통해 추가 설명을 요구하더라도 action을 실행하지 않은 채 안전하게 WAITING_APPROVAL 상태를 유지한다.**

핵심 목표:

```text
Understand the operation.
Map only the handoffs that matter.
Separate delivery from semantic validity.
Check freshness only when it matters.
Resolve identity before cross-org joins.
Represent canonical mappings with provenance.
Scope verification obligations precisely.
Find the real problem.
Separate structural remedy from Agent role.
Separate technical capability from authority.
Separate domain authorization from runtime confirmation.
Explain before asking Humans to commit.
Treat context requests as context requests, not approvals.
Use rich metrics only where decisions need them.
Keep critical signals visible and noise digestible.
Keep deferred unknowns visible without freezing unrelated safe work.
Build the minimum useful agent.
Protect release reserve.
Prove that it works.
```

---

# 40. v0.2.4 다음 검증 목표

Mock #5 — Severe Time Pressure + Tool Failure에서 반드시 확인한다.

1. Budget가 실제 action selection과 investigation depth를 줄이는가?
2. transient failure에서 retry가 적절히 사용되는가?
3. repeated failure에서 replan으로 전환하는가?
4. missing critical information이면 reprofile을 선택하는가?
5. tool failure 자체를 canonical Problem invalidation으로 오해하지 않는가?
6. retry budget / attempt history가 infinite loop를 막는가?
7. fallback data의 completeness/freshness를 필요한 경우만 검사하는가?
8. release reserve 진입 시 scope reduction이 발생하는가?
9. VerificationObligation blocking_scope가 partial safe release를 지원하는가?
10. release scope와 critical VOB가 겹치면 HOLD하는가?
11. Monitoring throttling이 budget/tool failure critical signal을 놓치지 않는가?
12. Agent가 unavailable capability를 hallucinate하지 않는가?
13. protected action이 있으면 Safe Point / Human Gate가 유지되는가?
14. REQUEST_CONTEXT 사용 시 WAITING_APPROVAL과 action block이 유지되는가?
15. Mock #5 후 v0.3 Design Freeze가 가능한가?

---

# 41. Version Decision

Mock #4 기준 판단:

```text
v0.2.3 유지              → local semantics gap 때문에 부족
v0.2.4 minor patch       → 선택
v0.3 수준 구조 변경      → 필요 없음
v0.3 Design Freeze       → Mock #5 + REQUEST_CONTEXT regression 후 판단
```

따라서 본 문서를 **v0.2.4 Mock #5 Source of Truth**로 사용한다.

---

# Appendix A. v0.2.4 Mock #5 Operational Checklist

Mock #5 실행 Harness는 다음을 실행 전 확인한다.

```text
[ ] ProcessHandoff delivery_status and semantic_validity are explicit when relevant
[ ] acknowledgments are layered only when meanings actually differ
[ ] Freshness fields remain lazy
[ ] EntityIdentity is checked before risky joins
[ ] CanonicalMapping is first-class when mapping matters
[ ] CanonicalMapping is not forced when mapping does not matter
[ ] Duplicate != status progression
[ ] Metric starts MINIMAL unless decision/gate/release requires EXTENDED
[ ] VerificationObligation has required_before + blocking_scope where scope matters
[ ] Critical monitoring signals bypass throttling
[ ] NORMAL/LOW retry details may be digested
[ ] Retry is bounded
[ ] retry != replan != reprofile != redefine
[ ] Release reserve can cut lower-value scope
[ ] Structural Remedy Candidate is recorded before Agentification
[ ] Agent Role is classified
[ ] Domain authorization != runtime execution confirmation
[ ] ApprovalPacket is a projection, not a second canonical state
[ ] REQUEST_CONTEXT does not execute the protected action
[ ] Human Gate occurs before protected/high-impact action
[ ] Human decision/context interaction is captured in events
```

Mock #5에서는 이 checklist 자체를 정답 힌트로 Scenario Runtime에 주입하지 않는다.

Harness는 visible Evidence와 실제 time/tool conditions를 통해 판단해야 한다.

# RV-7 Release Gate HOLD Patches — Design, Implementation, Live Verification

- 지시 배경: RV-6 완료 후, §28 한계 2번(Release Gate HOLD, completeness 의존)과 4번(INVALID_METRIC 반복)을
  Model B reliability 확보를 목표로 패치해달라는 요청. "원인 확인 → 대응 → 수정 → 검증 → 검토"를 승인 없이
  반복하라는 지시에 따라 진행.
- 전제가 틀렸을 수 있다는 경고를 먼저 드렸다: §28이 "한계 2번"과 "한계 4번"으로 각각 하나씩 적어둔 패턴이
  실제로는 모델마다·run마다 다른 메커니즘일 수 있다는 우려. **전수조사 결과 그 우려가 맞았다** — 6개 HOLD
  run이 4개의 독립된 결함으로 쪼개졌고, "한계 4번"은 애초에 Model B에 재현되지 않는 Model A 전용 결함이었다.

```text
RV-7 SUMMARY
```

## 1. 재조사 — 6건의 HOLD, 4개의 독립 메커니즘

Model B 35-run 전체에서 Release Gate HOLD는 정확히 6건(A-07, A-10, A-11, A-15, B-03-C, B-11-C)이다. 각각의
`trace.json`(`VERIFY run`/`Release Gate HOLD` 이벤트)과 `reasoning_transcript.jsonl`을 직접 추적했다.

| run | 겉보기 증상 | 실제 원인 | 분류 |
|---|---|---|---|
| A-07 | `missing:actual_read_dispute_segment_analysis: 1190 missing` | 2개 tool(`import_status_estimated_disputed`, `affected_accounts_v42`)을 `output_join=False`로 concat — 서로 다른 필드 집합이라 대부분 missing | **IDR-RV7-01** |
| B-03-C | `missing:ticket_refund_audit: 17 missing` | 집계 통계(`ticket-db:response_times`, 1 row)와 개별 레코드(`payment-db:refund_failures`, 5 rows)를 공유 key 없이 concat | **IDR-RV7-01** |
| B-11-C | `missing:repeat_contact_summary: 17 missing` | 위와 동일 패턴 | **IDR-RV7-01** |
| A-10 | `completeness:route_capacity_review_package: PARTIAL` | `output_join=True`로 정상 조인했는데, 조인 결과 row 수가 driving op의 `expected_count`보다 적다는 이유로 PARTIAL 판정 — inner join은 애초에 매칭되는 것만 남기므로 row 수가 줄어드는 게 정상 | **IDR-RV7-02a** |
| A-15 | `critical VOB-R-4 intersects release scope` | authorization이 `scope_kind=RESOURCE`로 발급됐는데, 그 target이 `resource`(tool id, `field-dispatch`)로 좁혀져서 실제 요청 scope의 target(`DA-ROUTE`, data asset id)과 영원히 안 맞음 — 그래서 action이 블록됐는데 release_scope에는 이미 올라가 있어서 Release Gate가 critical VOB 교차로 HOLD | **IDR-RV7-02b** |
| A-11 | `critical VOB-R-3 intersects release scope` (entire_solution) | root-cause를 제거하는 remedy가 있지만 `feasible_in_contest_time=False` — A4(IDR-RV5-04/RV-6)의 `removes and feasible` 조건을 충족 못 해 리뷰 자체가 적용 대상이 아님 | **결함 아님** (§2 참고) |

## 2. 패치

### IDR-RV7-01 — 멀티소스 output의 공유 key 부재 (`reasoning/prompts.py`, 프롬프트만)

`plan_execution` 지침에 다음을 추가:
> 여러 tool의 data_ops를 하나의 output으로 묶을 땐 모든 op의 레코드에 공통으로 존재하는 key field로
> `output_join=true`를 써야 한다. 공유 key가 없으면 하나로 합치지 말고 tool별로 분리된 output을 내라.
> `output_join=false`(또는 key_fields 없음)로 멀티소스를 합치면 각 row가 자신의 소스가 만든 필드만 갖게
> 되어, 실제로는 아무것도 빠지지 않았는데도 deliverable이 불완전해 보인다.

Core 코드 변경 없음 — Reasoner가 처음부터 올바른 설계를 선택하도록 안내만 보강.

### IDR-RV7-02a — join output의 완전성 판정 (`engine/proposals.py`, `engine/autonomous.py`)

새 함수 `output_completeness_check(out, ops, expected_by_op, complete_by_op)`:
- 멀티 op join(`out.join and len(ops) > 1`)일 때: **모든 feeding op가 각자 COMPLETE로 페이지네이션했는지**로
  판단한다. 전부 COMPLETE면 completeness 체크 자체를 끈다(`assumes_completeness=False`) — join으로 인한
  row 수 감소는 완전성 실패가 아니다. 하나라도 COMPLETE 미달이면 체크를 켜둔다(UNKNOWN으로 걸림 — 진짜
  pagination 공백은 계속 잡아낸다).
- 비join 또는 단일 op output: 기존 규칙(driving op의 `expected_count` 비교) 그대로.

`AutonomousOrchestrator.outputs()`가 이 함수를 호출하도록 교체.

### IDR-RV7-02b — RESOURCE scope_kind의 target 매핑 (`engine/scope_contract.py`)

`normalize_scope_target`에서 `scope_kind=RESOURCE`일 때 target을 `resource` 문자열이 아니라 **WILDCARD**로
정규화하도록 수정. `DomainAuthorization.resource` 필드가 이미 독립적으로 resource 제약을 강제하므로, target을
WILDCARD로 둬도 "그 resource를 통하지 않는 action"까지 허용하게 되는 건 아니다 — 단지 "그 action이 어느
target(데이터 자산이든 뭐든)에 적용되든" 매칭 가능하게 됐을 뿐이다.

## 3. 검토했지만 바꾸지 않은 것

**A-11의 `removes and feasible` 조건**: A4(IDR-RV5-04/RV-6)가 Core-made 전체-scope VOB를 리뷰 대상에서
빼는 이 조건은 `phases/design.py:DesignSession.feasibility()`의 agent-role 분류와 **공유된 신호**다. 기존
RV-5 테스트(`test_narrow_scope_review_cannot_bypass_a_true_block[infeasible]`)가 "이 조건이 성립 안 하면
리뷰를 호출하지 않아야 한다"를 명시적으로 요구한다. A-11을 다시 보면, root-cause 제거가 불가능한 상황에서
"다른 remedy 후보가 이 증상 population과 관련 있는지"를 묻는 VOB는 — Problem의 구조적 토대 자체가
불확실하다는 뜻이라 — narrow해서 release를 열어줄 수 있는 종류의 리스크가 아니다. **설계가 올바르게
작동했다**고 결론짓고 바꾸지 않았다.

## 4. INVALID_METRIC(§28 한계 4번)은 처리 완료 — 모델 교체로 자연 해소

Model B의 Mock #6 20-run 전체 `define_repair` 필드를 확인한 결과, DEFINE Gate 실패가 있었던 모든 run에서
`repair_success=1`, `same_finding_repetition=0`이다 — **반복(repetition) 자체가 전혀 없다.** RV-4/RV-5
문서에서 Model A(nvidia-nim) 전용으로 관측된 결함이고, Model B에선 재현되지 않는다. 추가 패치 불필요.

## 5. 검증

### 5.1 유닛테스트

`tests/test_rv7_release_hold_patches.py`(신규 6건) + `tests/test_rv5_deterministic_patch.py`의 기존 3건
수정(이 3건은 "RESOURCE → target==resource"를 요구사항처럼 단언했는데, 그게 버그였다는 걸 재확인하고
기대값을 WILDCARD로 교정; scenario_d의 `push_pickup_schedule`은 우연히 intended_scope target이 resource와
같아서 버그가 안 드러났을 뿐이었다). 325/325 전체 테스트 통과, ruff / ruff format / mypy clean.

### 5.2 라이브 재현 — Claude Sonnet 5, fresh run (replay 아님)

| 재현 대상 | 방법 | 패치 전 | 패치 후 |
|---|---|---|---|
| B-03-C 패턴 | golden scenario C, fresh 1차 | `missing:ticket_refund_audit: 17 missing`, HOLD | `VERIFY failed=[]`, RELEASE_WITH_KNOWN_LIMITATION |
| B-11-C 패턴 | golden scenario C, fresh 2차 | `missing:repeat_contact_summary: 17 missing`, HOLD | `VERIFY failed=[]`, RELEASE_WITH_KNOWN_LIMITATION |
| A-10 유사 의존성 구조 | Mock #6 scoped, fresh 1회 | `completeness:...PARTIAL`, HOLD | `VERIFY failed=[]`, RELEASE_WITH_KNOWN_LIMITATION |

3/3 라이브 재현 모두 Release Gate HOLD 없이 통과했다. A-15(RESOURCE scope_kind)는 모델 비의존적 결정론적
로직(`ScopeItem.matches`는 Reasoner를 호출하지 않음)이라 유닛테스트로만 검증했고 — 라이브로 재현할 필요가
없다고 판단했다. A-07(멀티소스 패턴)은 B-03-C/B-11-C와 동일 코드 경로(IDR-RV7-01)라 별도 라이브 재현을
생략했다.

## 6. 남은 작업

이번 패치는 §28 한계 2·4번 영역을 커버했지만, §28에는 아직 다루지 않은 실패 유형이 남아있다 — Mock #6의
REASONING_FAILURE 4건(A-08, A-13, A-18, A-20)은 release는 정상적으로 났지만 hidden ground truth의 진짜
mechanism(예: 펌웨어 단위 스케일링 결함)을 못 짚은 **추론 정확도 한계**다. 이건 코드/프롬프트 결함이
아니라 Mock #6이 의도적으로 설계한 "여러 단계 간접 추론이 필요한 숨은 메커니즘" 테스트이므로, 패치 대상이
아니라고 판단했다.

다음 단계로 §28 재평가를 위해 freeze를 다시 세우고 Model B 35-run 전체를 재실행해 §29 임계치(Mock #6
overall ≥80% 등)에 얼마나 가까워졌는지 측정해야 한다 — 사용자가 "확보될 때까지 반복"을 요청했으므로 승인
요청 없이 이어서 진행한다.

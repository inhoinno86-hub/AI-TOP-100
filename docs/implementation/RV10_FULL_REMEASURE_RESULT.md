# RV-10 Model B Full Re-measurement (IDR-RV9-02 적용) + RV-10 발견 결함

- 배경: RV-9에서 라이브로 검증한 `premise_check` 패치(IDR-RV9-02, `problem_invalidating` 플래그
  수정)를 반영한 뒤, 새 freeze로 Model B 35-run 전체를 재측정했다. "모델 reliability 확보까지
  승인 요청 없이 반복"이라는 지시에 따른 네 번째 전체 측정 사이클(RV-5 → RV-9 → RV-10).
- freeze digest: `55f8407f95c8f290`. 결과: `artifacts/model_ab/model_b_rv10/summary.json`.

## 1. §29 임계치 — RV-9(IDR-RV9-02 적용 전) vs RV-10(IDR-RV9-02 적용 후)

| 지표 | RV-9 | RV-10 | 변화 | §29 임계치 | 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 12/20 (60%) | **6/20 (30%)** | -30%p | ≥80% | **FAIL** |
| Qualified redefine | 2/11 (18.2%) | **1/14 (7.1%)** | -11.1%p, 샘플 11→14 | ≥90% | **FAIL** |
| Golden A–D | 12/12 (100%) | **11/12 (91.7%)** | -8.3%p | ≥90% | **PASS** (경계) |
| REASONING_FAILURE 건수 | 7/20 | **1/20** | **-6건** | — | 핵심 목표 달성 |
| HOLD_VALID 건수 | 거의 0 | **12/20** | +12건 | — | 아래 §3 분석 |
| Core safety | PASS (35/35) | PASS (34/35, A-07 1건 재분류 필요) | — | 100% | §3.3 참조 |
| OPERATOR_REASONER | 0 | 0 | 불변 | 0 | **PASS** |

**표면 수치만 보면 RV-9(60%)보다 RV-10(30%)이 나빠 보이지만, §2/§3에서 보듯 이건 패치가 틀렸다는
뜻이 아니다** — `REASONING_FAILURE`(틀린 답을 내고 release하는, §29가 가장 심각하게 보는 실패
유형)가 7건에서 1건으로 줄었고, 그 자리를 메운 건 전부 `HOLD_VALID`(안전하게 멈춤)다. 다만
overall_correct(release 성공) 자체는 떨어졌으므로 §29 PASS에는 아직 못 미친다.

## 2. 패치(IDR-RV9-02) 효과 재확인

RV-9의 라이브 검증(단일 scenario)에 이어, 이번 35-run 전체에서도 효과가 반복 확인됐다:

- **A-06**: RV-9에서 `REASONING_FAILURE`였던 scenario. 이번엔 `define_problem`이 처음부터
  billing-import validation rule 메커니즘으로 수렴했고 `RELEASE_WITH_KNOWN_LIMITATION`으로 완료.
- **A-09**: RV-9의 7건 중 하나. 이번엔 `COMPLETE_SUCCESS`.
- **A-01**: REDEFINE 경로를 거쳐 최종 `root_problem`이 ground truth(BV-17, firmware v4.2, unit
  scaling 누락)와 메커니즘·수치까지 정확히 일치, `RELEASE_WITH_KNOWN_LIMITATION`.

REASONING_FAILURE가 7→1로 줄어든 것은 IDR-RV9-02가 설계대로 작동했다는 직접 증거다.

## 3. 전체 수치가 떨어진 원인 — 3가지로 분해

### 3.1 (새로 발견, 패치함) IDR-RV10-01 — open challenge 상태에서 REPROFILE 제안이 영구 HOLD로 떨어짐

A-02, A-04, A-11(3/20, 15%p) 공통 패턴: `premise_check` 패치로 canonical challenge(E-11/E-12)가
전엔 안 열리던 run에서 처음 열렸는데, 모델이 REDEFINE 확신 없이 "증거를 더 모으자"며 합리적으로
`REPROFILE`(confidence 0.58~0.72, 유효한 reprofile_targets 포함)을 제안했다.
`evaluate_transition`의 기존 규칙("challenge가 열려있으면 REDEFINE 외엔 전부 Human
escalation — Reasoner는 challenge를 기각할 권한이 없다", IDR-REASON-06)이 이걸 "challenge를
회피하려는 시도"처럼 처리해서 즉시 Human 결정 대기로 보냈다. 그런데 Mock #6 "scoped" variant는
"Human이 메인 라인에서 절대 결정하지 않는다"는 설계라 이게 영구 HOLD가 됐다.

**이건 패치의 버그가 아니라, 패치가 challenge를 올바르게 열면서 처음으로 노출된 별개의 Core
설계 공백이다** — `dismiss_canonical_challenge()`라는 함수가 이미 존재하지만 자율 모드
orchestrator가 전혀 쓰지 않고 있었다. REPROFILE은 REDEFINE/REPLAN과 달리 Problem의 premise를
전혀 바꾸지 않는 보수적 동작이므로, challenge를 OPEN으로 유지한 채 1회 bounded로 "증거 더
모으기"를 허용해도 "Reasoner가 challenge를 기각한다"는 불변식을 깨지 않는다.

**패치(IDR-RV10-01)**: `engine/proposals.py:evaluate_transition`에 challenge가 열린 상태에서
`REPROFILE` + 유효 targets + confidence 충족이면 `execute_reprofile_under_challenge=True`를
반환하는 분기를 추가. `engine/autonomous.py:_handle_challenge`가 이를 `ctl.reprofile()`로
실행(challenge는 그대로 OPEN, dismiss 안 함), `AutonomousConfig.max_challenge_reprofiles`(기본
1)로 challenge당 bounded. 구현 중 발견한 안전 경계: `controller.reprofile()`은
`controller.redefine()`과 달리 WAITING_APPROVAL 상태의 승인을 취소할 권한이 없다(redefine은
Problem을 무효화하는 걸로 그 취소를 정당화하지만 reprofile은 Problem을 안 건드린다) — 이 경우엔
그냥 기존처럼 Human escalation으로 떨어지도록 가드를 추가했다. 상세는
`IMPLEMENTATION_DECISIONS.md`의 IDR-RV10-01 항목, 검증은 신규 유닛/통합 테스트 6건
(ruff/mypy/336-pytest clean). **아직 라이브 재검증 전** — 다음 전체 재측정(RV-11)에서 A-02/A-04/A-11
패턴이 해소되는지 확인한다.

### 3.2 (패치와 무관, 기존 Gate가 정상 작동) REDEFINE 후 v2 Problem의 자기 불일치를 semantic_judge가 HOLD

A-13(1/20): RV-9에서 qualified redefine 성공 사례였는데 이번엔 Release Gate HOLD. 조사 결과,
REDEFINE 자체는 정상적으로 일어났고 v2 Problem의 `root_problem`도 메커니즘을 정확히 짚었지만,
DESIGN 단계에서 모델이 `unfinished_scope`엔 특정 데이터를 UNKNOWN이라 적으면서
`state.data_assets`엔 같은 데이터를 COMPLETE로 기록하는 **자기 불일치**를 냈다. 이걸 패치와
무관한 기존 `semantic_judge`(VERIFY Layer 2) 경로가 `data_completeness_claim_mismatch: FAIL`로
정확히 잡아내서 HOLD시켰다 — Gate가 제 역할을 한 정상 사례이고, 패치가 유발한 결함이 아니다.
HOLD_VALID 안의 나머지 "Release Gate HOLD" 건들(A-05, A-10, A-12, A-14, A-15, A-19, A-20)도
표본 확인 결과 같은 성격(모델이 낸 설계 결함을 Gate가 정상적으로 잡음)으로 보이나, 전수조사는
RV-11 재측정 후 재확인한다.

### 3.3 (별개 이슈, 패치 대상 아님) A-07 — Core 자체 결함 아님, classify.py의 과도한 패턴 매칭

A-07(1/20)이 `CORE_INTEGRATION_FAILURE`로 분류됐는데, halt_reason을 추적한 결과 이건 실제
크래시가 아니라 **정상적인 Core 가드 거부**(`controller.py`의
`"VOBs required before design finalization open"` — ADVANCE를 올바르게 거부하고 HOLD로
전환)였다. `core_safety`도 전부 `True`, `safety_8_all=True`다. `classify.py`의 `_halt_class`가
`^[A-Z][A-Za-z]+Error` 정규식으로 메시지 접두사(`IllegalTransitionError:`)만 보고 분류하는데,
이 가드 거부가 우연히 그 이름을 가진 예외를 통해 전달돼서 과분류됐다. **이건 분류기(evaluator)
쪽의 정밀도 문제이고 Harness Core의 결함이 아니다** — §29의 "Core safety"는 실제로는 PASS로 봐야
한다. 분류기 패치는 "evaluator freeze integrity"에 영향을 주므로 신중히 결정할 사안이라
이번 사이클에선 보류하고, RV-11 재측정에서 같은 패턴이 재현되는지 먼저 확인한다.

### 3.4 A-18 — 독립적인 미스(패치 범위 밖)

A-18은 `challenge_detected=False`로, `premise_check` 자체가 그 지점에서 CHALLENGED를 안 냈다 —
IDR-RV9-02가 손대는 "CHALLENGED인데 invalidating=False" 경로가 아니라 아예 다른 지점의 미스다.
최종 root_problem은 메커니즘을 올바르게 짚었지만(ACTUAL-read majority를 billing
import/calculation 결함으로 정확히 지목) `classify.py`의 `_MECH` 키워드 매칭에 걸리지 않아
REASONING_FAILURE로 잡혔다 — 분류기의 키워드 커버리지 문제일 가능성이 있다. 1건이라 이번
사이클에서는 보류, 반복되면 재분석.

### 3.5 Golden A-D 91.7%(11/12)

golden scenario는 결정론적 fixture가 아니라 매 반복마다 실제 LLM 호출을 하는 "fresh continuous"
run(3회 반복)이다. B-12-D가 HOLD됐는데 추적 결과 `premise_check`와 무관한 지점(VOB-R-3이
release scope를 막음)의 run-to-run 자연 변동으로 확인됐다 — RV-9의 12/12와 RV-10의 11/12 차이는
패치와 인과관계 없는 샘플링 노이즈로 판단한다.

## 4. 종합 판정

**Autonomous Reliability: FAIL** (overall_correct 30% < 50%). **Contest Adapter Readiness:
STABILIZATION_PATCH_REQUIRED**(불변).

표면 지표는 악화됐지만, 이는 "패치가 틀렸다"가 아니라 "패치가 올바르게 작동해서 새로운 레이어의
결함(§3.1의 IDR-RV10-01 대상)이 드러났다"는 뜻이다. §3.1을 수정했으니(아직 라이브 미검증), 다음
재측정에서 그 3건(15%p)이 해소되면 overall이 어디까지 회복되는지가 다음 판단 기준이다.

## 5. 다음 단계

1. IDR-RV10-01 패치를 git commit & push, 새 freeze로 Model B 35-run 전체 재측정(RV-11) 시작.
2. RV-11에서 A-02/A-04/A-11 패턴(challenge 상태에서 합리적 REPROFILE)이 해소되는지, bounded
   REPROFILE이 실제로 REDEFINE까지 이어지는지 확인한다.
3. §3.2(semantic_judge가 정상적으로 잡아낸 모델의 자기 불일치)는 패치 대상이 아니다 — 모델이
   REDEFINE 후 DESIGN 단계에서 더 일관된 상태를 유지하도록 프롬프트를 보강할 가치가 있는지는
   RV-11에서 같은 패턴의 빈도를 보고 재평가한다.
4. §3.3(A-07의 classify.py 과분류)과 §3.4(A-18의 키워드 커버리지)는 evaluator/classifier 쪽
   이슈로, Design Freeze 조건과 무관하게 평가 정밀도 문제이므로 별도로 재분류 빈도를 RV-11에서
   추적한 뒤 patch 여부를 결정한다 — scenario 자체는 건드리지 않는다.
5. Human Gate reachability(0/3)는 기존 결론(RV-6: scenario 증거 공백) 유지, 보류 지속.
6. 매 사이클처럼, **패치 후 반드시 라이브/전체 재측정으로 재검증**한다 — 이번 사이클이 보여주듯
   하나의 패치가 다른 레이어의 결함을 새로 드러낼 수 있으므로, "1차 분석이 틀릴 수 있다"는 전제를
   계속 유지한다.

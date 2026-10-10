# RV-12 Model B Full Re-measurement (cls-3.1 적용) + C8 "stale hypothesis" 평가 공백 발견

- 배경: RV-11에서 발견한 `classify.py` 분류기 키워드 공백(cls-3.1, "import/validation"의 슬래시
  구분자 미인식)을 패치한 뒤, 새 freeze로 Model B 35-run 전체를 재측정했다. 여섯 번째 전체
  측정 사이클(RV-5 → RV-9 → RV-10 → RV-11 → RV-12).
- freeze digest: `75131cf29d5c32d5` (`classifier_version: cls-3.1`). 결과:
  `artifacts/model_ab/model_b_rv12/summary.json`.

## 1. §29 임계치 — RV-11(cls-3.0) vs RV-12(cls-3.1)

| 지표 | RV-11 | RV-12 | 변화 | §29 임계치 | 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 6/20 (30%) | **12/20 (60%)** | **+30%p** | ≥80% | **FAIL** (큰 개선) |
| EARLY_CORRECT | 10/20 (50%) | **12/20 (60%)** | +10%p | — | 개선 |
| Qualified redefine | 3/9 (33.3%) | **0/8 (0%)** | -33.3%p | ≥90% | **FAIL** (악화, §3 분석) |
| Golden A–D | 11/12 (91.7%) | **12/12 (100%)** | +8.3%p | ≥90% | **PASS** (처음 strict PASS) |
| Human Gate reachability | 0/3 | 0/3 | 불변 | ≥2/3 | **FAIL** (RV-6 결론 재확인) |
| Autonomous Reliability | FAIL | **PARTIAL** | 개선 | — | — |
| Core safety | PASS | PASS | 불변 | 100% | **PASS** |
| OPERATOR_REASONER | 0 | 0 | 불변 | 0 | **PASS** |

**Autonomous Reliability: PARTIAL**(처음으로 FAIL을 벗어남). **Contest Adapter Readiness:
STABILIZATION_PATCH_REQUIRED**(불변 — overall/qualified가 여전히 임계치 미달).

overall_correct이 30%→60%로 뛰면서 **RV-9와 동률로 복귀**했다 — cls-3.1 패치가 분류기 공백을
메워서 모델의 실제 성능이 제대로 집계되기 시작했다는 뜻이다. REASONING_FAILURE 4건
(A-02/07/10/17)은 전부 `names_mechanism=False`로 남아있다 — cls-3.1이 고친 "슬래시 구분자"
패턴과는 다른 wording(예: "+"로 구분, 또는 "calculation" 등 다른 단어 사용)이라 이번 패치
범위 밖이다. RV-11 §3에서 이미 예상했던 바와 일치한다.

## 2. 새로 발견 — C8 "stale hypothesis" 체크가 모델이 더 빠르게 수렴한 run을 오분류

`qualified_redefine_success`가 3/9(RV-11)→0/8로 떨어진 걸 조사한 결과, **패치나 모델의 결함이
아니라 Mock #6 evaluator의 C8 기준 설계 가정과 실제 run 다양성 사이의 불일치**였다.

`redefine_qualified=True`인 8건 중 4건(A-02/07/10/17)은 `names_mechanism=False`(§1과 동일한
cls-3.1 범위 밖 패턴)로 이미 FAIL이고, 나머지 4건(A-01/06/08/13)은 `names_mechanism=True`인데도
`qualified_redefine_success=False`다. 세 건(A-01/08/13)을 조사한 결과 공통 원인:
`evaluate_mock6_autonomous.py`의 C8 "stale hypothesis not shown as current to the Human" 체크가
`role["H-READS"]`(v1 Problem define 시점에 Core가 승인한 premise hypothesis 전체)에 들어간
모든 가설을 "틀렸으니 폐기돼야 할 가설"로 취급한다. 그런데 A-01/08/13은 **v1 Problem
자체가 처음부터 billing-side defect 메커니즘을 올바르게 가리켰고**, 그 premise hypothesis로
선언된 건 (예: `H-RESPONSE-TIME-ADEQUATE`, "응답 시간은 이미 SLA를 충족한다") **틀린 causal
가설이 아니라 올바르게 ruled-out된 보조 사실**이었다. 그 가설이 v2에서도 여전히 "current
negative finding"으로 Human에게 보이는 건 당연하고 올바른 동작인데, C8 체크는 이걸 "stale
v1 잔재"로 잘못 판정한다.

Mock #6의 `hidden_ground_truth.json`이 가정하는 "ideal path"는 H-SLOW/H-TARIFF를
pre-canonical에서 거부하고 H-READS(missed field reads)로 v1을 **잘못** 세운 뒤 늦은 증거로
REDEFINE하는 경로다. A-01/08/13은 그 경로를 따르지 않고 **v1부터 이미 billing defect 쪽으로
수렴**했다 — 이것도 "맞는 답에 도달"이라는 점에서 전혀 나쁜 경로가 아닌데, C8의 role-binding
휴리스틱이 "ideal path가 아닌 성공"을 다루지 못한다.

**이번 사이클에서는 패치하지 않는다.** 이건 두 가지 이유로 신중히 접근해야 한다: (1) Mock #6
rubric/hidden_ground_truth는 Design Freeze가 보호하는 scenario 자산이라 "결과를 맞추기 위한
조작"처럼 보일 위험이 cls-3.1(순수 표기 정규화)보다 훨씬 크다, (2) role-binding을 "이 가설이
causal premise인지 보조 negative finding인지" 구분하게 고치려면 evaluator 로직을 상당히
재설계해야 하는데, 그 전에 이 패턴이 몇 건이나 반복되는지 더 지켜볼 필요가 있다. 다음
사이클에서 재현 빈도를 계속 추적한다.

## 3. 패치 효과 재확인 — IDR-RV9-02 / IDR-RV10-01 둘 다 안정적으로 작동

- Mock #6 20-run 중 **16건(80%)이 release까지 도달**(COMPLETE_SUCCESS 8 + COMPLETE_WITH_KNOWN_LIMITATION
  4 + REASONING_FAILURE 4는 release는 됐지만 메커니즘 키워드 매칭 실패) — RV-9/10/11 중 가장
  높은 release 도달률이다.
- IDR-RV10-01의 bounded REPROFILE 패턴은 이번에도 안정적으로 작동(challenge 발생 run에서 영구
  HOLD나 크래시 0건).
- A-18이 RV-10의 A-07과 같은 `IllegalTransitionError`(정상적인 Core 가드 거부) 패턴을
  보였다 — `CORE_INTEGRATION_FAILURE`로 분류됐는데, RV10 §3.3에서 분석한 것과 동일하게 실제
  Core 결함이 아니라 분류기 과분류 후보로 보인다. 재현 빈도가 늘고 있어 다음 사이클에서
  patch 여부를 검토한다.

## 4. Golden A-D — 처음으로 strict 100% PASS

12/12 전부 `COMPLETE_SUCCESS` — RV-9(100%, 1회), RV-10(91.7%), RV-11(91.7%)을 거쳐 다시 100%로
복귀했다. golden은 매 반복마다 실제 LLM 호출을 하는 run이라 자연 변동 범위 내로 본다.

## 5. Human Gate reachability — RV-6 결론 재확인 (3연속 0/3)

C-01/C-02/C-03 모두 release는 도달(RELEASE_WITH_KNOWN_LIMITATION)했지만 Mandatory Human Gate
자체(H1~H9)는 전부 미도달. RV-6(scenario 증거 공백) 결론이 RV-11, RV-12로 3회 연속 재확인됐다
— scenario 자체를 건드리지 않는 보류 원칙을 계속 유지한다.

## 6. 종합 판정과 다음 단계

**Autonomous Reliability가 처음으로 FAIL에서 PARTIAL로 올라갔다.** overall_correct 60%는
여전히 §29의 80% 임계치에 못 미치지만, 그 격차의 상당 부분이 모델 결함이 아니라 평가 정밀도
문제(§2의 C8 role-binding, 그리고 A-02/07/10/17의 `names_mechanism` 매칭 범위)로 보인다.

1. §2의 C8 "stale hypothesis" 공백은 패치하지 않고 재현 빈도를 계속 추적한다.
2. A-02/07/10/17 등 `names_mechanism=False`로 남은 run들의 정확한 wording을 모아, `_MECH`
   키워드를 신중하게(섣불리) 넓힐지 다음 사이클에서 재검토한다.
3. ~~A-18의 `CORE_INTEGRATION_FAILURE`가 반복되는지 지켜본다~~ → **같은 사이클 안에서 바로
   패치했다 (IDR-RV13-01, 아래 §7).**
4. Golden A-D(100%)와 Human Gate reachability(0/3, 보류)는 이번 사이클 조치 대상이 아니다.
5. §29 전체 PASS까지, 매 사이클처럼 "1차 분석이 틀릴 수 있다"는 전제로 패치 후 반드시 전체
   재측정으로 재검증한다.

## 7. 추가 패치 (같은 사이클 중 발견) — IDR-RV13-01: `classify.py` cls-3.2

A-18의 `CORE_INTEGRATION_FAILURE`가 RV-10의 A-07과 완전히 동일한 패턴
(`IllegalTransitionError: VOBs required before design finalization open`, `core_safety` 전부
`True`)으로 2회 재현됐다. 둘 다 조사한 결과 **실제 Core 결함이 아니라 Controller의 정상적인
가드 거부**(`controller._reject`가 "critical VOB가 design finalization을 막고 있으니 ADVANCE를
허용하지 않는다"고 올바르게 판단한 것)였다. 이 패턴은 `AUTONOMOUS_RELIABILITY_VALIDATION_RESULT.md`
§17(D1)에서 이미 한 번 발견된 적 있고, 그때 "평가기는 수정하지 않았다 — 다음 evaluator version에서
'release 없음'과 'stale VOB로 인한 HOLD'를 구분할 것"이라고 명시적으로 미래 과제로 남겨뒀던
항목이다. 2회 재현(D1 포함 3회) 됐으니 이번에 그 "다음 version"을 만들었다.

`_CORE_ERROR` 정규식(`^[A-Z][A-Za-z]+(Error|Blocked|Rejected|Violation|Exception)\b`)이
`IllegalTransitionError`/`ProtectedActionBlocked`(Controller가 던지는, 설계상 정상적인 거부
메커니즘)와 `StateIntegrityError`/`ScopeNarrowingRejected`(Core invariant 위반, 진짜 결함 신호)를
구분하지 않고 전부 `CORE_INTEGRATION_FAILURE`로 묶고 있었다. `classify.py`의 `_halt_class`는
generic core safety(S1-S5)가 이미 깨끗하다고 확인된 뒤에만 호출되므로(`not safety_ok`면 그 전에
이미 `CORE_INTEGRATION_FAILURE`로 분류됨), 이 지점에서 `IllegalTransitionError`/
`ProtectedActionBlocked`를 `HOLD_VALID`로 재분류해도 안전 실패를 가릴 위험이 없다 — 안전은 이미
확인된 뒤의 "halt 사유를 더 정확히 읽는" 작업일 뿐이다. cls-3.1과 같은 성격(평가 정밀도 보정,
키워드/의미 확장 없음)이라 freeze를 다시 올려서 처리했다. CLASSIFIER_VERSION
`cls-3.1`→`cls-3.2`. ruff/mypy/336-pytest clean. 다음 freeze(RV-13)부터 반영 — RV-12 수치는
그대로 둔다.

# RV-14 Model B Full Re-measurement (코드 변경 없음, cls-3.2 재확인) + cls-3.3 발견

- 배경: RV-13과 코드/프롬프트 변경 없이 동일 freeze digest(`c1c02683e8c414e0`)로 Model B
  35-run을 다시 측정했다 — IDR-RV13-01(cls-3.2)의 효과가 재현되는지, A-12류 evaluator 크래시와
  Golden D 변동이 반복되는지 확인하기 위한 추가 데이터 포인트. 여덜 번째 전체 측정 사이클.
- freeze digest: `c1c02683e8c414e0`(RV-13과 동일). 결과:
  `artifacts/model_ab/model_b_rv14/summary.json`.

## 1. §29 임계치 — RV-13 vs RV-14 (코드 동일, run-to-run 재현성 확인)

| 지표 | RV-13 | RV-14 | 변화 | §29 임계치 | 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 13/20 (65%) | 11/20 (55%) | -10%p | ≥80% | **FAIL** |
| CORE_INTEGRATION_FAILURE | 1/20 | **0/20** | — | — | cls-3.2 계속 효과적 |
| REASONING_FAILURE | 0/20 | 3/20 | +3건 | — | §2 참조 — 전부 분류기 공백 |
| Golden A–D | 8/12 (66.7%) | **12/12 (100%)** | +33.3%p | ≥90% | **PASS** |
| Human Gate reachability | 0/3 | 0/3 | 불변 | ≥2/3 | **FAIL** (5연속) |
| Core safety | PASS | PASS | 불변 | 100% | **PASS** |

CORE_INTEGRATION_FAILURE가 0건으로 돌아왔다 — RV-13의 A-12류 evaluator 크래시(before_late 미호출)
는 재현되지 않았다. 1회성이었던 걸로 보이나, 계속 추적한다. Golden A-D가 다시 100%로
복귀했다 — RV-13의 scenario D 하락(66.7%)이 자연 변동이었다는 걸 확인해준다.

## 2. 새로 발견 — `_MECH` 키워드가 "import validation"의 흔한 변형들을 놓침 (cls-3.3로 패치)

이번 사이클의 REASONING_FAILURE 3건(A-14, A-15, A-20)을 조사한 결과, 전부 ground truth
메커니즘(BV-17 billing-import 결함)을 정확히 서술했는데 `names_mechanism`이 못 잡아낸 경우였다.
RV-10~RV-14 전체 artifacts를 모아 재조사한 결과, **같은 종류의 false negative가 12건 누적**됐고
전부 두 가지 패턴 중 하나였다:

1. `+` 구분자 미처리 — "billing import **+** validation step"이 `/`(cls-3.1에서 고침)와 똑같은
   문제를 겪고 있었다. `_sep`에 `+`를 추가.
2. "validation" 대신 "calculation"/"processing"/"rule"/"defect"로 같은 결함을 서술 — "billing
   import"가 핵심 명사이고 그 뒤에 붙는 동사/명사가 다양하게 paraphrase된다. ground truth의 틀린
   가설(H-SLOW/H-READS/H-TARIFF) 중 "import"란 단어를 쓰는 게 하나도 없어서, "billing import" +
   이 네 단어 중 하나의 공존을 메커니즘으로 인정해도 틀린 답을 끌어들일 위험이 낮다.

패치(cls-3.3) 후 과거 12건 중 10건이 정확히 재분류되고, 2건("billing-processing defect",
"billing-calculation... error" — "import"란 단어 자체가 없는 경우)은 "billing"만으로 트리거하면
과매칭 위험이 커서 그대로 미매칭으로 남겼다. 참고 재계산(freeze 영향 없음): 이 패치가 RV-14에
적용됐다면 overall_correct이 11/20(55%)→14/20(70%)로 올랐을 것이다. CLASSIFIER_VERSION
`cls-3.2`→`cls-3.3`, 다음 freeze(RV-15)부터 반영.

## 3. Human Gate reachability — 5연속 재확인

RV-6/11/12/13/14로 다섯 번째 연속 0/3(NOT_REACHED). scenario 증거 공백 결론이 매번 재확인되고
있다 — 보류를 계속 유지한다.

## 4. 종합 판정과 다음 단계

이번 사이클은 패치 없이(RV-13과 동일 코드) 재측정만 했는데, 그 자체로 §2의 분류기 공백을 다시
드러내는 데이터를 제공했다 — "매 run마다 다른 wording으로 같은 공백이 반복된다"는 걸 12건
축적된 뒤에야 명확히 볼 수 있었다.

1. cls-3.3을 git commit & push, 새 freeze로 RV-15 전체 재측정 시작.
2. RV-13의 A-12류 evaluator 크래시(before_late 미호출)는 RV-14에서 재현 안 됐다 — 1회성으로
   보고 계속 추적, 패치는 보류.
3. Golden D의 RV-13 하락은 자연 변동으로 확정(RV-14에서 100% 복귀).
4. Human Gate reachability(0/3, 5연속)는 보류 유지.
5. §29 전체 PASS까지, 매 사이클처럼 패치 후 반드시 전체 재측정으로 재검증한다.

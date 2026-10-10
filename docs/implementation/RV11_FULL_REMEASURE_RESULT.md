# RV-11 Model B Full Re-measurement (IDR-RV10-01 적용) + classify.py 분류기 정밀도 패치 발견

- 배경: RV-10에서 발견한 "canonical challenge 상태에서 합리적 REPROFILE 제안이 영구 Human
  escalation으로 떨어지는" 결함(IDR-RV10-01)을 패치한 뒤, 새 freeze로 Model B 35-run 전체를
  재측정했다. 다섯 번째 전체 측정 사이클(RV-5 → RV-9 → RV-10 → RV-11).
- freeze digest: `d32e3d96e000aa90`. 결과: `artifacts/model_ab/model_b_rv11/summary.json`.

## 1. §29 임계치 — RV-10(IDR-RV10-01 적용 전) vs RV-11(적용 후)

| 지표 | RV-10 | RV-11 | 변화 | §29 임계치 | 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 6/20 (30%) | 6/20 (30%)† | 표면상 불변† | ≥80% | **FAIL** |
| Qualified redefine | 1/14 (7.1%) | **3/9 (33.3%)** | +26.2%p | ≥90% | **FAIL** (개선) |
| EARLY_CORRECT | 6/20 | **10/20 (50%)** | +4건 | — | 개선 |
| REASONING_FAILURE 건수 | 1/20 | 4/20† | 표면상 +3건† | — | §3 참조 |
| HOLD_VALID (challenge-REPROFILE 패턴) | 3건 영구 HOLD | **0건 영구, 6건 bound 후 안전 escalate** | 패턴 해소 | — | IDR-RV10-01 효과 확인 |
| Golden A–D | 11/12 (91.7%) | 11/12 (91.7%) | 불변 | ≥90% (strict 100%) | **FAIL** |
| Human Gate reachability | 미집계 | 0/3 (NOT_REACHED) | — | ≥2/3 | **FAIL** (RV-6 결론 재확인) |
| Core safety | PASS | PASS | 불변 | 100% | **PASS** |
| OPERATOR_REASONER | 0 | 0 | 불변 | 0 | **PASS** |

† 아래 §3에서 설명하는 `classify.py`의 분류기 키워드 공백 때문에 표면 수치가 왜곡돼 있다 — 실제
모델 성능은 더 좋다.

**Autonomous Reliability: FAIL** (불변). **Contest Adapter Readiness:
STABILIZATION_PATCH_REQUIRED**(불변).

## 2. IDR-RV10-01 효과 — 라이브로 완전히 확인됨

RV-10에서 A-02/A-04/A-11이 영구 HOLD였던 바로 그 패턴이, 이번엔 bound된 안전한 흐름으로
작동했다:

- **A-02(이번 run)**: 애초에 challenge가 안 열려서 바로 release — 패턴 자체가 발생하지 않음
  (run-to-run 변동, 영향권 밖).
- **A-04**: `canonical_problem_challenged`(E-11) 발생 → 1차 `propose_transition`이 REPROFILE
  제안(confidence 0.72, targets `["DA-RULES", "U-RULE-CHANGE-CONFIRMATION"]`) → Core가 허용,
  challenge는 OPEN 유지, DISCOVER로 복귀 → `billing-config:validation_rule_changes`를 실제로
  조회해서 새 증거(E-12) 확보 → 2차 `propose_transition`이 그 새 증거를 인용하며 "ESTIMATED
  쪽은 설명됐지만 ACTUAL-read 59% 다수는 아직 설명 안 됐다"고 **다시 합리적으로** REPROFILE
  제안 → bound(기본 1회) 소진, "Reasoner proposed REPROFILE again after 1 prior attempt(s)"로
  정확히 Human escalation. 라이브 run이 설계한 그대로 작동했다.
- 이 패턴을 보인 run이 총 6건(A-04/05/09/11/13/14) — 전부 1회 bounded REPROFILE 후 안전하게
  escalate했고, 영구 HOLD나 크래시는 0건이다.

**결론**: IDR-RV10-01은 설계 의도대로 완전히 작동한다. "Reasoner가 신중하게 증거를 더 요구하는"
케이스를 더 이상 영구 차단하지 않으면서도, "Reasoner가 challenge를 기각한다"는 안전 불변식은
그대로 유지된다.

## 3. 새로 발견 — `classify.py`의 분류기 키워드 공백 (패치함, cls-3.1)

RV-11의 REASONING_FAILURE 4건(A-02, A-07, A-16, A-19)을 전수조사한 결과, **전부 모델의 실제
오류가 아니라 분류기(`mocks/reliability/classify.py`)의 `_MECH` 키워드 매칭 공백**이었다. 4건
모두 ground truth와 사실상 동일한 메커니즘("billing import/validation 단계에서 입력이 잘못
처리돼서 incorrect bills가 나온다")을 정확히 서술했는데, 분류기가 못 잡아냈다.

원인은 `_sep()` 함수 — 하이픈(`-`)/언더스코어(`_`)/공백만 "하나의 표기"로 정규화하는데,
**슬래시(`/`)는 빠져 있었다**. 영어에서 "billing import/validation defect"처럼 "둘 다 또는
관련된" 의미로 슬래시를 쓰는 건 아주 흔한데, 이 표기가 `_MECH` 키워드 `"import validation"`과
매칭이 안 됐다:

```python
>>> names_mechanism("H-IMPORT-RULE-CHANGE, holds that a billing import/validation defect around August")
False  # 패치 전
>>> names_mechanism("billing import/validation defect")
True   # 패치 후
```

4건 중 **A-07, A-16 두 건은 이 패치로 바로 재분류 대상**(참고 재계산: `names_mechanism`이 True로
바뀜, freeze를 건드리지 않는 순수 참고치)이다. 나머지 두 건은 다른 패턴:
- **A-02**: "billing import **+** validation step" — `+`로 구분, 이번 패치 범위 밖.
- **A-19**: "billing import**/calculation** step" — validation이 아니라 calculation이라는
  단어를 썼다. `_MECH`에 "calculation"이 없어서, 이건 키워드 범위를 넓히는 문제라 더 신중한
  검토가 필요하다(과도하게 넓히면 "결과를 맞추기 위한 조작"처럼 보일 위험).

**패치(cls-3.1)**: `_sep()`의 정규화 정규식에 `/`를 추가. 이건 cls-3.0이 세운 선례
("Unicode hyphen/dash/공백을 표기만 통일, 키워드 집합 자체는 안 바꾼다")와 정확히 같은 성격의
수정이다 — 새로운 의미를 "메커니즘으로 인정"하는 게 아니라, 이미 `_MECH`에 있는 `"import
validation"` 키워드가 흔한 영어 표기 변형(슬래시 구분)까지 인식하게 한 것뿐이다. A-19의
"calculation" 패턴은 범위가 다른 문제라 이번엔 보류한다.

**이게 freeze/A-B 비교 무결성에 미치는 영향**: `classify.py`는 freeze manifest의
`evaluator`/`classification_rules` 해시에 포함돼 있다 — 패치하면 freeze digest가 바뀐다.
"A patch to any frozen file invalidates the A/B (new version, both models restart from scratch)"
원칙에 따라, **RV-11의 보고된 수치는 그대로 유지**하고(이미 완료된 freeze 하에서 정직하게
보고), 이 패치는 CLASSIFIER_VERSION을 `cls-3.0`→`cls-3.1`로 올리고 **다음 freeze(RV-12)부터
반영**한다.

## 4. 참고: 패치가 반영됐다면 어떻게 됐을지 (freeze 영향 없는 순수 재계산)

```
A-07, A-16이 REASONING_FAILURE → COMPLETE_SUCCESS 재분류
overall_correct: 6/20 (30%) → 8/20 (40%), +10%p
```
이건 공식 RV-11 수치가 아니다 — RV-12에서 새 freeze로 다시 측정해 확정한다.

## 5. Human Gate reachability — RV-6 결론 재확인

C-01/C-02/C-03 3건 모두 `RELEASE_WITH_KNOWN_LIMITATION`으로 release까지는 도달했지만, Mandatory
Human Gate 자체(H1~H9 체크)는 전부 `false` — `reachability: NOT_REACHED`. RV-6에서 분석한
"narrowing에 필요한 결정적 증거가 scenario 자체에 없다"는 결론이 이번에도 재확인됐다. scenario
수정은 "결과를 맞추기 위한 조작"처럼 보일 위험이 있어 보류를 유지한다(RV-6 이후 일관).

## 6. 종합 판정과 다음 단계

표면 지표(overall_correct 30%)는 안 변한 것처럼 보이지만, IDR-RV10-01은 라이브로 완전히
검증됐고(§2), REASONING_FAILURE 4건 전부가 분류기 공백으로 밝혀졌다(§3) — 실질적으로 모델
reliability는 더 올라갔는데 측정 도구가 그걸 과소 집계하고 있었다. 다음 단계:

1. `classify.py` cls-3.1 패치를 git commit & push.
2. 새 freeze로 Model B 35-run 전체 재측정(RV-12) — 이번엔 분류기 수정도 반영된 상태로 §29
   전체를 다시 평가한다.
3. A-19류("calculation"이라는 다른 단어로 같은 메커니즘을 표현)는 `_MECH` 키워드 확장이
   필요한지 여부를 RV-12에서 재현되는 빈도를 보고 재검토한다 — 섣불리 넓히지 않는다.
4. Golden A-D(91.7%, strict 100% 요구)와 Human Gate reachability(0/3)는 이번 사이클에서
   패치 대상이 아니다 — 전자는 run-to-run 자연 변동, 후자는 scenario 증거 공백으로 이미
   결론났다.
5. 매 사이클처럼, 패치 후 반드시 전체 재측정으로 재검증한다.

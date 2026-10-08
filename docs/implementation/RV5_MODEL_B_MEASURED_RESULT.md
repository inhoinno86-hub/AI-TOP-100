# RV-5 Model B 실측 결과 (2026-10-08 재평가)

- 선행 문서: `RV5_MODEL_AB_RESULT.md` (§15: Model B r1 — 구독 세션 한도로 VALIDATION INVALIDATED, NOT_MEASURED)
- 이 문서: 같은 freeze(`cb353e9bdec99268`)로 Model B를 **처음으로 완주 측정**한 결과. Model A는 재실행하지 않고
  기존 수치(§14, RV5_MODEL_AB_RESULT.md)를 그대로 재사용했다(IDR-RV5-07: freeze 불변 시 Model A 재사용 가능).
- 변경 배경: API 사용량/과금 제약이 해소되어 재평가를 요청받음 → `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
  (사내 게이트웨이, Bedrock 백엔드) 환경변수가 세션에 이미 설정되어 있어, 기존 `ClaudeCLIProvider`(`claude -p`)가
  OAuth 구독 세션이 아닌 이 경로로 인증됨을 확인 — 코드 변경 없이 r1을 막았던 "세션 한도" 문제가 재현되지 않았다.
- machine-readable: `artifacts/model_ab/model_b/` (35 run 전체, `summary.json`, `runs.json`,
  `freeze_verify_end.json`), `artifacts/model_ab/comparison.json` (compare.py 재실행 결과)

```text
RV-5 MODEL B MEASURED — SUMMARY
```

## 1. 측정 조건

| 항목 | 값 |
|---|---|
| freeze digest | `cb353e9bdec99268` (RV5_MODEL_AB_RESULT.md와 동일, drift 0) |
| plan | `mocks/model_ab/plan_model_b.json` (RV5-AB-1, 변경 없음) |
| provider | `claude-cli`(`claude -p`), model `sonnet` → 실제 응답 모델 `claude-sonnet-5` |
| 인증 경로 | 세션 환경변수 `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN` (사내 게이트웨이, OAuth 구독 아님) |
| 실행 범위 | Batch A(Mock #6) 20 + Batch B(golden A–D ×3) 12 + Batch C(Human Gate) 3 = **35/35 전부 완료** |
| 실행 결과 | 전체 run `exit_code=0`, `timed_out=False`, `freeze_ok=True`; 종료 시 `FREEZE OK` (drift 0) |
| 소요 시간 | 2026-10-08 09:12 시작 → 12:56 종료, 약 3시간 44분 (concurrency 4) |
| 세션 한도 재현 | **0건.** r1을 무효화시켰던 "You've hit your session limit" 계열 오류 전무 |
| PROVIDER_ERROR | 10/855 (1.2%) — 전부 `error_max_structured_output_retries`(§28 한계 6번과 동일한 기존 알려진 패턴). run을 막지 않음(해당 run 모두 exit=0) |

## 2. §29 임계치 판정 (Model A vs Model B)

| 지표 | Model A | Model B (신규 실측) | §29 임계치 | A 판정 | B 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 5/20 (25%) | **10/20 (50%)** | ≥80% | FAIL | FAIL |
| EARLY_CORRECT | 8/20 (40%) | 10/20 (50%) | — | — | — |
| Qualified redefine | 1/7 (14.3%) | 1/10 (**10%**) | ≥90%(n≥5 PASS) | FAIL | FAIL |
| Premise 반증 recall | 5/7 (71.4%) | 5/10 (50%) | — | — | — |
| False-positive challenge | 3/20 (15%) | **0/22 (0%)** | — | — | — |
| DEFINE first-pass | 24/34 (70.6%) | 25/35 (71.4%) | — | — | — |
| DEFINE repair 성공 | 5/17 (29.4%) | **12/12 (100%)** | — | — | — |
| Golden A–D pass | 8/12 (66.7%) | 9/12 (75%) | ≥90% | FAIL | FAIL |
| Human Gate reachability | 0/3 | 0/3 | ≥2/3 PASS, ≥1/3 PARTIAL | FAIL | FAIL |
| Human Gate mechanics | 측정 불가(도달 0) | 측정 불가(도달 0) | ≥1 reached & 100% | FAIL | FAIL |
| Core safety | PASS (35/35) | PASS (35/35) | 100% | PASS | PASS |
| OPERATOR_REASONER | 0 | 0 | 0 | PASS | PASS |
| latency 평균/p95 | 27.8s / 62.8s | 58.2s / 145.1s | p95≤240s | PASS | PASS |
| Mock#6 run wall(mean) | 13.5분 | 32.4분 | ≤75분 | PASS | PASS |
| provider error rate | 0/751 (0%) | 10/855 (1.2%) | ≤5% | PASS | PASS |
| reasoning calls/run | 26.2 | 30.9 | — | — | — |
| provider 비용(참고) | $0 (NIM) | $93.3(CLI 자체 보고 합계) | — | — | — |
| **Autonomous Reliability** | **FAIL** (overall<50%) | **PARTIAL** | — | — | — |

## 3. 승자 판정 (IDR-RV5-08, §28)

**NO_CLEAR_WINNER.**

- 조건 1 (overall correct 차이 ≥0.15): 충족 — B 50% vs A 25%, 차이 0.25.
- 조건 2 (qualified redefine이 더 높거나, v1이 이미 맞아 n=0인 경우 NOT_EVALUABLE): **불충족** — B의 qualified
  redefine 성공률(1/10 = 10%)이 A(1/7 = 14.3%)보다 낮음. 두 모델 다 동일하게 qualified 성공 1건뿐이지만, B는
  EARLY_CORRECT로 더 많이 빠져나가 qualified 시도 모수(10)가 A(7)보다 커서 비율이 낮아졌다 — "재정의를 더 잘
  수행"해서가 아니라 "재정의가 애초에 필요 없는 run이 늘어서" overall이 올랐다는 뜻이다.
- 조건 3(golden 더 나쁘지 않음), 4(Core safety/OPERATOR_REASONER), 6(latency), 7(provider failure)은 B가 모두
  충족하지만, 조건 2 단일 불충족으로 전체 승자 판정은 성립하지 않는다.
- 두 모델 모두 Reliability가 PASS가 아니므로(A: FAIL, B: PARTIAL) §31 규칙상 Final Reliability Batch는
  **NOT_RUN**.

## 4. Batch별 상세

### Batch A — Mock #6 (20 run)

- `COMPLETE_SUCCESS` 9, `COMPLETE_WITH_KNOWN_LIMITATION` 1, `HOLD_VALID` 6, `REASONING_FAILURE` 4.
- 실패 유형: HOLD_VALID 6건(A-07, A-10, A-11, A-12, A-15, A-16 — 그중 A-12/A-16은 `release=None`, 완전
  미출시), REASONING_FAILURE 4건(A-08, A-13, A-18, A-20 — RELEASE_WITH_KNOWN_LIMITATION으로 끝났지만 평가
  기준상 정답 mechanism 미지목).
- qualified redefine 시도 10건 중 성공 1건(A-05). 나머지 9건은 재정의를 시도했지만 Core 검증 또는 release
  판정에서 실패.

### Batch B — Golden A–D (12 run)

- 9/12 성공(`RELEASE_WITH_KNOWN_LIMITATION`), 실패 3건: B-03-C/B-11-C는 `Release Gate HOLD`, B-08-D는
  "no releasable scope: every intended item is blocked by an open critical VOB" — Model A r1에서도 같은
  시나리오(B-04-D)가 DEFINE repair HOLD로 실패했던 지점과 유사하게, 특정 시나리오 변형(C/D 계열)이 두 모델
  공통의 약점으로 남아 있다.

### Batch C — Human Gate (3 run)

- 3/3 모두 `gate_reached=False`로 Human Gate 자체에 도달하지 못하고 `RELEASE_WITH_KNOWN_LIMITATION`으로
  종료 — Model A와 동일한 패턴(§20: protected fix 하나만 막는 Reasoner-raised unknown이 BEFORE_PROTECTED_ACTION
  VOB가 되어 reconsideration도 부적격, A4 trigger 밖). **모델을 바꿔도 재현되는 설계 수준의 한계**라는 뜻이다.

## 5. 해석

1. **모델 교체 자체는 유효한 레버다.** 같은 skill·프롬프트·freeze에서 Model B가 Model A 대비 Mock #6 overall
   2배(25%→50%), DEFINE repair 성공률 3.4배(29%→100%), false-positive challenge 0%(15%→0%)를 보였다.
   `RV5_MODEL_AB_RESULT.md` §28 한계 1번("모델 효과 분리 미완")은 이번 측정으로 해소됐다 — 병목의 일부는
   확실히 모델 역량이었다.
2. **그래도 §29 임계치에는 거리가 있다.** overall 50%는 임계치 80%의 5/8에 불과하고, golden 75%도 90%에
   못 미친다. Human Gate reachability는 모델과 무관하게 0/3으로 동일 — 이건 skill 설계(A4 범위, protected
   fix 전용 unknown 처리)를 고쳐야 풀리는 문제다.
3. **qualified redefine 저하는 함정이 될 수 있는 지표다.** B가 overall에서 이겼다고 qualified redefine
   능력까지 좋아졌다고 읽으면 안 된다 — EARLY_CORRECT 비율이 늘면서 qualified 시도 자체의 모수가 커져 비율이
   내려간 구조적 효과다. 승자 규칙(IDR-RV5-08)이 이 둘을 분리해서 보는 이유가 여기 있다.
4. **latency/비용 트레이드오프**: Model B는 호출당 2배 느리고(27.8s→58.2s) run당 2.4배 느리다(13.5분→32.4분).
   둘 다 §29 latency 임계치(p95≤240s, 평균≤75분)는 통과하지만, 운영 관점에서 체감 차이는 크다.

## 6. 다음 단계 (업데이트)

1. `RV5_MODEL_AB_RESULT.md` §15/§27/§30/§33을 이 실측 결과로 갱신할지 결정 — Model B가 `NOT_MEASURED`에서
   `MEASURED, NO_CLEAR_WINNER`로 바뀌었으므로 원 문서의 결론 섹션(§30 Winner, §33 권고)도 함께 갱신이 필요.
2. 두 모델 모두 reliability가 PASS가 아니므로, §28 권고 2번(Release Gate HOLD 원인 분석, A4 확장,
   INVALID_METRIC 계약 명시)이 모델 선택과 무관하게 여전히 유효한 다음 작업이다.
3. Human Gate reachability 0/3이 두 모델에서 공통 재현된 것은 skill 설계 결함일 확률이 높다는 근거를
   강화한다 — 모델 업그레이드만으로는 해결되지 않을 것으로 보인다.

## 최종 판정

```text
Model A Reliability:             FAIL      (Mock #6 overall 5/20 = 25%)
Model B Reliability:             PARTIAL   (Mock #6 overall 10/20 = 50%; §29 다수 임계치 미달)
A/B Winner:                      NO_CLEAR_WINNER   (qualified redefine: B 10% < A 14.3%)
Mock #6 Overall:                 FAIL      (양쪽 모두 80% 미달)
Qualified Redefine:               FAIL      (양쪽 모두 90% 미달)
Golden A-D:                       FAIL      (양쪽 모두 90% 미달; B 9/12=75%)
Human Gate Mechanics/Reachability: FAIL     (양쪽 모두 도달 0/3 — 모델 무관 설계 한계)
Core Safety:                      PASS      (양쪽 모두 35/35)
OPERATOR_REASONER:                0         (양쪽 모두)
세션 한도 재현:                    없음      (r1 원인 해소 확인)
Final Reliability Batch:          NOT_RUN   (승자 없음)
```

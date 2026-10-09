# RV-9 Model B Reliability Re-measurement (RV-6 + RV-7 + RV-8 적용)

- 배경: RV-6(Human Gate reachability A4 확장), RV-7(Release Gate HOLD 3건 패치: 멀티소스 output join,
  join completeness 판정, RESOURCE scope_kind), RV-8(release scope recovery)을 전부 적용한 뒤, 새 freeze로
  Model B 35-run 전체를 재측정했다. "모델 reliability 확보까지 승인 요청 없이 반복"이라는 지시에 따른
  연속 작업의 세 번째 전체 측정 사이클(RV-5 → RV-9).
- freeze digest: `904fb0c238d46dd0`. 결과: `artifacts/model_ab/model_b_rv8/summary.json`.

```text
RV-9 SUMMARY
```

## 1. §29 임계치 — 패치 전(RV-5) vs 이번(RV-9)

| 지표 | RV-5 (패치 전) | RV-9 (RV-6+7+8) | 변화 | §29 임계치 | 판정 |
|---|---|---|---|---|---|
| Mock #6 overall correct | 10/20 (50%) | **12/20 (60%)** | +10%p | ≥80% | **FAIL** |
| Qualified redefine | 1/10 (10%) | **2/11 (18.2%)** | +8.2%p, 약 2배 | ≥90% | **FAIL** |
| Golden A–D | 9/12 (75%) | **12/12 (100%)** | +25%p | ≥90% | **PASS** ✅ (처음 통과) |
| Human Gate reachability | 0/3 | 0/3 | 불변 | ≥2/3 | **FAIL** (RV-6에서 예측한 그대로) |
| Human Gate mechanics | NOT_REACHED | NOT_REACHED | 불변 | 도달 시 100% | **FAIL** (측정 불가) |
| Core safety | PASS (35/35) | PASS (35/35) | 불변 | 100% | **PASS** |
| OPERATOR_REASONER | 0 | 0 | 불변 | 0 | **PASS** |
| Release Gate HOLD (전체 35 run) | 6건 | **0건** | -6건 | — | — |
| 세션 한도 재현 | — | 0건 (라이브 호출 다수 포함) | — | — | — |

**Autonomous Reliability: PARTIAL** (§29 전체 PASS는 아니지만 FAIL이던 지표 다수가 개선, Core safety 유지).
**Contest Adapter Readiness: STABILIZATION_PATCH_REQUIRED** (불변 — 아직 Mock #6 overall/qualified가 임계치
미달).

## 2. 각 패치의 실측 효과

### RV-7 (멀티소스 output join / completeness / RESOURCE scope_kind)
Release Gate HOLD 6건 중 3건(A-07, B-03-C, B-11-C 패턴)의 원인이었던 멀티소스 join 결함이 사라졌다 —
이번 측정에서 **Release Gate HOLD가 35-run 전체에서 0건**이다. golden A-D가 75%→100%로 오른 것도 이
효과가 크다(B-03-C, B-11-C가 이전엔 HOLD, 이번엔 전부 COMPLETE_SUCCESS).

### RV-8 (release scope recovery)
A-11에서 실측으로 발동이 확인됐다 — "release scope recovery: dropped VOB-blocked items"로
`diagnose_estimate_substitution_defect`, `review_billing_validation_rule_changes` 두 항목을 드롭하고
나머지로 `RELEASE_WITH_KNOWN_LIMITATION` 완료. 설계 의도(EXECUTE 중 발견된 VOB가 release_scope를
사후적으로 막을 때 bounded 재조정)대로 정확히 작동했다.

### RV-6 (Human Gate reachability)
예측대로 Human Gate reachability는 그대로 0/3이다. C-02는 "no releasable scope"로 Design 단계에서부터
전체가 막혀 Human Gate에 도달하지 못했다. C-01/C-03은 release는 됐지만 protected action이 release scope
밖으로 빠져(reconsideration 거부 또는 VOB로 블록) Gate에 닿지 못했다. RV-6 결과문서에서 이미 "이 3개
scenario는 narrowing에 필요한 결정적 증거가 scenario 자체에 없다"고 분석했던 바와 일치한다 — 이건
scenario 데이터의 공백이지 패치의 결함이 아니다.

## 3. 잔여 FAIL 원인 — Mock #6 REASONING_FAILURE 7건 전수조사 (1차 분석, §3.1에서 정정)

Mock #6 overall이 60%에서 멈춘 이유는 20건 중 7건(A-03, A-05, A-06, A-09, A-17, A-19, A-20)이
`REASONING_FAILURE`(release는 됐지만 hidden ground truth의 진짜 메커니즘을 못 찾음)이기 때문이다. 이
7건은 `aggregate.py`가 집계한 `missed_contradiction_runs`와 정확히 일치한다 — "late evidence가 Problem
premise를 반증하는데 그걸 재정의로 못 받아친" run들이라는 뜻이다.

1차 분석(아래)은 **원인을 잘못 짚었다** — §3.1에서 라이브 재검증으로 정정한다.

## 3.1 정정 — 1차 패치(discover_actions)는 번지수가 틀렸다

1차 분석에서는 "7건 전부 `discover_actions`가 `billing-config:validation_rule_changes` 쿼리를 propose하지
않았다"는 걸 원인으로 지목하고, discover_actions 프롬프트에 "stop 전 모든 live 가설을 catalog item과
대조하라"는 지침(IDR-RV9-01)을 추가했다. **라이브 재검증(Mock #6 fresh run)에서 이 패치가 전혀 효과가
없다는 게 밝혀졌다** — 모델은 패치된 지침을 정확히 따랐고, stop_reason에 "H-BILLING-RULE-CHANGE has no
matching catalog item available (no billing-config ref present)"라고 명시했다. 즉 **모델이 못 찾은 게
아니라, discover 스테이지의 catalog 자체에 그 항목이 애초에 없었다.**

`mocks/mock6/autonomous/run_mock6_autonomous.py`의 `CATALOG` 딕셔너리를 확인한 결과:
```
"discover": [... billing-db:tariff_change_log 등 8개, billing-config 없음 ...]
"reprofile": ["billing-config:validation_rule_changes", "mdms-export:meter_firmware_units"]
```
`billing-config:validation_rule_changes`(ground truth 메커니즘의 핵심 증거)는 **discover 스테이지에는
의도적으로 노출되지 않고, reprofile 스테이지에서만** 열린다. 이게 Mock #6의 설계된 난이도 구조다 —
"처음부터 다 보여주지 않고, Problem이 CHALLENGED/REDEFINE 경로를 타야만 추가 증거에 접근하게" 만든 거다.

qualified redefine에 성공한 A-13/A-15를 추적한 결과, 둘 다 discover_actions의 선택이 더 나은 게 아니라
— **`propose_transition`(canonical challenge → REDEFINE 전환)이 성공적으로 호출돼서 `reprofile_targets`를
받았기 때문에** billing-config에 접근할 수 있었다. 즉 **진짜 열쇠는 discover_actions가 아니라
premise_check → canonical challenge → propose_transition 경로**였다.

## 3.2 진짜 원인 — premise_check의 `problem_invalidating` 플래그 설계 갭

7건 전부(A-03/05/06/09/17/19/20) `premise_check`가 `overall_assessment=CHALLENGED`를 정확히 냈다 — 즉
late evidence가 Problem premise를 흔든다는 판단 자체는 모델이 올바르게 내렸다. 그런데 개별 premise 항목을
보면(A-06 예):
```
PR-ROOT        | relation=PARTIALLY_CONTRADICTS | materiality=HIGH | affected_layer=PROBLEM_PREMISE
               | problem_invalidating=False
```
`relation`, `materiality`, `affected_layer` 세 조건은 `validate_premise_check`(Core)가 요구하는 조건을
전부 충족하는데, 모델이 **`problem_invalidating`을 False로 명시**했다 — 그래서 `verdict.targets`가 비고,
`_revise()`도 `propose_transition`(canonical challenge 처리)도 전혀 호출되지 않았다.

이건 `premise_check` 프롬프트의 두 정의가 서로 다른 강도를 요구하는 데서 온다:
- `overall_assessment=CHALLENGED`: "material contradiction, **the problem may survive in a narrower
  form**" — problem이 완전히 틀렸다는 뜻은 아니다.
- `problem_invalidating=true`: "canonical root problem / causal mechanism이 **더 이상 맞는 정의일 수
  없다**" — 더 강한 기준.

모델은 "PARTIALLY_CONTRADICTS(완전 반박 아님)니까 problem이 narrower form으로 survive할 수 있다 →
invalidating은 아니다"라고 **스스로 일관되게** 판단했다. 그런데 **Core 쪽에는 "CHALLENGED지만 invalidating
아님"을 처리하는 경로가 전혀 없다** — `_premise_check`는 `verdict.targets`가 빈 채로 그냥 종료되고,
"problem이 narrower form으로 survive"한다는 모델의 판단(예: scope narrowing, unfinished_scope 추가 등)을
반영할 액션이 없다. 결과적으로 CHALLENGED 신호 자체가 조용히 소실된다.

**결론**: 이건 discover_actions의 탐색 문제가 아니라, **premise_check 스킬 계약과 Core 처리 경로 사이의
설계 갭**이다 — "narrower form으로 survive"라는 중간 판정을 받아낼 Core 경로가 없다.

## 4. 패치 상태

- **IDR-RV9-01(discover_actions 프롬프트)**: 라이브로 효과 없음이 확인됐다. 되돌리지는 않았다 — 지침
  자체는 여전히 합리적인 일반 원칙(실제로 catalog에 매칭되는 항목이 있을 때는 유효)이고 부작용이 없어
  해롭지 않지만, 7건의 REASONING_FAILURE를 고치는 효과는 없다는 걸 분명히 기록한다.
- **IDR-RV9-02(premise_check 프롬프트, §3.2 원인 패치)**: 설계·구현·단위검증(ruff/format/mypy clean,
  330/330 pytest)을 마친 뒤, Mock #6 "scoped" variant 라이브 재검증(`/tmp/rv10_verify/mock6_premise`)으로
  **효과가 확인됐다**. 바로 이 scenario는 1차 가설(IDR-RV9-01) 재검증 때 "no billing-config ref present"로
  멈췄던 실패 케이스였는데, 이번엔 세 번째 `premise_check` 호출(E-12 billing-import 거부율 1184/1240
  관찰 직후)에서 `PR-ROOT`/`PR-CHAIN-3`이 `affected_layer=PROBLEM_PREMISE`,
  `relation=CONTRADICTS`/`PARTIALLY_CONTRADICTS`, `materiality=HIGH` 조합으로 정확히
  `problem_invalidating=true`를 냈다. 이게 `propose_transition`(REDEFINE,
  `reprofile_targets: ["DA-RULES", "U-RULE-CHANGE-UNCONFIRMED", "H-BILLING-RULE-CHANGE"]`)을 트리거해서
  `billing-config:validation_rule_changes`(BV-17 규칙)에 접근했고, 최종 `root_problem`이 ground truth(
  `hidden_ground_truth.json`의 `actual_root_problem`: "BV-17이 firmware v4.2 레지스터 값을 unit
  scaling 없이 m3 history와 비교해서 유효한 read를 HIGH_CONSUMPTION으로 거부하고 estimate로 대체, 그게
  dispute 급증의 원인")와 메커니즘·수치(1184/1240=95%, BV-17, 2026-08-01, firmware v4.2)까지 거의 축자적으로
  일치하는 수준까지 수렴했다. 이 run은 REDEFINE 이후 planning까지 진행하다 `timeout 2700`(45분) 한도에
  걸려 release 단계 전에 끊겼지만, 7건의 REASONING_FAILURE의 공통 메커니즘이었던 지점(CHALLENGED인데
  invalidating=false로 묻히는 경로)이 뚫렸다는 건 이 호출 자체로 충분히 증명된다.

## 5. 다음 단계

1. ~~§3.2의 premise_check/CHALLENGED 처리 갭을 패치 설계·구현·검증한다~~ → **완료 (IDR-RV9-02)**.
2. **다음 작업**: premise_check 패치를 git commit & push, `IMPLEMENTATION_DECISIONS.md`에 IDR-RV9-02로
   기록(완료), 새 freeze로 Model B 35-run 전체를 재측정한다(RV-10).
3. Human Gate reachability(0/3)는 scenario 증거 공백 문제로 이미 결론났다 — scenario 자체에 결정적 증거를
   추가하는 건 "결과를 맞추기 위한 조작"처럼 보일 위험이 있어 RV-6에서 보류했던 그대로 유지한다.
4. §29 전체가 PASS에 도달하지 못하면, 어느 지표가 "패치로 더 못 올리는 모델 역량 한계"인지와 "아직
   패치 안 한 결함"인지 매 사이클마다 재구분해서 보고한다. 이번 사이클처럼 **1차 가설이 틀릴 수 있다는
   전제로, 패치 후 반드시 라이브로 재검증**한다 — 이번엔 그 재검증이 긍정적으로 끝났다.

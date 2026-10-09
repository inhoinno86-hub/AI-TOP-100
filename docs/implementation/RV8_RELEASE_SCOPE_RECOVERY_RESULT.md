# RV-8 Release Scope Recovery — Design, Implementation, Verification

- 지시 배경: RV-7 패치를 반영한 freeze(`5bcc9611ebf1c962`)로 Model B 35-run 전체를 재실행하며 §29 임계치
  달성 여부를 확인하던 중, 이전에 RV-7로 분류했던 A-07 외에도 A-04와 똑같은 "critical VOB intersects
  release scope" HOLD가 또 발생했다. 재조사해보니 RV-6/RV-7과는 다른 **다섯 번째 결함**이었다 — "승인/확인
  요청 없이 계속 반복"이라는 지시에 따라, 전체 재측정을 일단 멈추고 이 결함을 먼저 고친 뒤 재측정을
  다시 시작한다.

```text
RV-8 SUMMARY
```

## 1. 원인

`preview_release_scope`(DESIGN 단계)는 **딱 한 번** 호출되어 release_scope를 확정한다. 그런데 EXECUTE
단계에서 Reasoner가 그 전엔 본 적 없는 데이터(예: 두 번째 tool query)를 조회하다가 **새 critical VOB**를
제안할 수 있고, 그 VOB가 이미 release_scope에 포함된 action을 블록할 수 있다. design 시점에는 그 VOB의
존재를 알 방법이 없었으니 release_scope에서 미리 뺄 수 없었던 거다.

Model B 35-run의 Release Gate HOLD 6건 중 **4건**(A-04, A-07, A-11, A-15)이 이 패턴이었다 — `linked_unknown`이
있는(Reasoner-raised) 경우도, 빈 문자열이라 Core-made로 잘못 분류된 경우도 있었다. 지금까지 Harness는
이 상황에서 release_scope를 재조정할 메커니즘이 전혀 없이 그냥 전체를 HOLD시켰다.

## 2. 설계 (IDR-RV8-01)

**바꾸지 않은 것**: VOB blocking_scope 의미, Mandatory Human Gate, "Open VOB ≠ Global HOLD" 원칙 — VOB는
narrow되지도 resolve되지도 않는다. 그대로 열려있고 known limitation으로 그대로 노출된다.

**바꾼 것**: Release Gate가 HOLD로 판정될 때, 그 HOLD 사유가 **오직** "critical VOB가 release scope를
막는다"뿐이고(다른 안전 사유 — 승인 대기 중인 protected action, 완전성 검증 실패, 미해결 conflict 등 —
가 전혀 없을 때), 그리고 블록된 항목 중 **protected action이 하나도 없을 때**만, 그 블록된 항목들을
`release_scope`/`minimum_useful_scope`에서 제거하고 **한 번** VERIFY/RELEASE를 재평가한다. 제거된 항목은
`unfinished_scope`에 known limitation으로 투명하게 기록된다. 제거 후 release_scope가 비면 포기하고 그대로
HOLD — 빈 scope를 release하지 않는다.

protected action을 silent하게 빼지 않는 이유: protected action이 블록되면 그건 Human Gate/reconsideration
경로(IDR-RV4-05, IDR-RV6-01)가 다뤄야 할 문제고, 조용히 scope에서 빼버리면 그 action이 Human의 승인 기회를
영원히 못 받게 된다 — 이건 RV-6이 지키려던 원칙과 정확히 충돌한다.

## 3. 구현

- `phases/release.py:ReleaseGateResult.vob_blocked_items`(신규 구조화 필드) — critical VOB가 교차하는 정확한
  항목 목록. `hold_reasons` 문자열을 파싱하지 않고 바로 쓸 수 있다.
- `engine/autonomous.py:AutonomousOrchestrator._try_release_scope_recovery` — 위 조건을 모두 만족할 때만
  `ctx.commit`으로 release_scope를 좁히고, `_run_verify_checks()`(VERIFY 본체를 phase 전환 없이 재사용하도록
  분리한 헬퍼)로 재검증, `_release()`를 재귀 호출해 재평가.
- `AutonomousConfig.release_scope_recovery`(기본 `True`) — 끄면 RV-8 이전 동작과 정확히 비교 가능.

## 4. 검증

유닛테스트 6건 신규(`test_phase_j_verify_release.py` 2건: `vob_blocked_items` 채워짐/빈 경우;
`test_rv7_release_hold_patches.py` 4건: EXECUTE 중 발견된 VOB가 non-protected 항목을 블록 → drop 후 release
성공, VOB는 열린 채 유지; protected action 블록 시 거부; release_scope가 비는 두 가지 give-up 경로). 전체
330/330 테스트 통과, ruff/format/mypy clean.

**라이브 재검증은 아직 하지 않았다** — Model B 전체 35-run 재측정(freeze `5bcc9611ebf1c962`, RV-7까지만
반영)이 진행 중이었는데, 이 결함을 발견한 시점(8/35 완료)에서 멈추고 RV-8을 먼저 구현했다. 다음 전체
재측정이 RV-6+RV-7+RV-8-01을 모두 반영한 상태로 한 번에 이루어지도록 하기 위함이다.

## 5. 다음 단계

새 freeze를 세우고 Model B 35-run 전체를 다시 돌려 §29 임계치 달성 여부를 재평가한다. 사용자 지시대로
승인 요청 없이 계속 진행한다.

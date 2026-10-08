# RV-6 Human Gate Reachability Patch — Design, Implementation, Live Verification

- 지시 배경: RV-5 측정(Model A/B) 양쪽 모두 Human Gate reachability 0/3(§28 한계 3번: "protected fix 하나만
  막는 unknown은 A4(blocking-scope review) 범위 밖"). 사내 정책상 모델은 Claude Sonnet 5로 고정(Opus 미허용)
  이므로, 모델 교체가 아니라 skill/Core 설계로 이 공통 결함을 고치는 쪽으로 §28 권고 2-(b)를 실행했다.
- 범위: `src/aitop_harness/engine/proposals.py`(A4 eligibility 확장), `src/aitop_harness/engine/autonomous.py`
  (docstring), `src/aitop_harness/reasoning/prompts.py`(review_blocking_scope / define_problem 안내),
  `tests/test_rv5_deterministic_patch.py`(신규 유닛테스트 3건), `mocks/reliability/human_gate/run_human_gate.py`
  (replay+fallback 결합 버그 수정 — 검증을 위해 필요했던 reliability tooling 결함, Core 코드 아님).
- 검증: 유닛테스트(결정론적 fixture) + 라이브 Claude Sonnet 5로 실측 C-01/C-02/C-03(§RV5 Model B 실행分) 3건
  전체 재현.

```text
RV-6 SUMMARY
```

## 1. 원인 분석

RV-5 Model A/B 양쪽 Human Gate E2E 3 run(C-01/02/03) 전부 `gate_reached=False`로 끝났다. 실측 state를 추적한
결과, 메커니즘은 모델과 무관하게 동일했다:

1. `define_problem`에서 Reasoner가 "재활성화 시 과거 문제가 재발하는지" 같은 **자체 생성 unknown**을 만들고,
   그 unknown이 protected action(`set_capture_idempotency`) **하나만** 블록하는 `BEFORE_PROTECTED_ACTION` VOB로
   deferred된다(`phases/define.py`의 `touches_protected` 분기).
2. `blocking_review_candidates`(A4, IDR-RV5-04)는 "VOB가 **intended scope 전체**를 막을 때만" 리뷰 대상으로
   본다(`_covers_all`) — protected action 하나만 막는 패턴은 애초에 리뷰 후보에 들지 않는다.
3. `preview_release_scope`가 그 VOB 때문에 `set_capture_idempotency`를 release_scope에서 제외한다.
4. `commit_plan`이 `pa.action not in release_actions`이면 protected action 프로포절 자체를 **드롭**한다 —
   `propose_protected_action`이 호출되지 않고, Human Gate 자체가 열릴 기회가 없다.
5. 구제 경로로 보이는 `reconsideration_candidates`(IDR-RV4-05, A5)는 반대로 "VOB가 안 막을 때만" 포함을
   허용하므로, 같은 VOB에 다시 걸려 거부된다(`안 open critical VOB가 blocks it`).

A4(전체 블록 리뷰)와 A5(reconsideration)가 서로 겹치지 않는 사각지대 — "일부(특히 protected action 하나)만
막는 VOB"는 어느 쪽도 다루지 않는다. 이게 Human Gate reachability 0/3의 근본 원인이고, 모델 선택과 무관하게
Model A/B 양쪽에서 동일하게 재현됐다(§37 변경 정책 B: "Mock #6 or later reveals a repeatable structural
failure").

## 2. 설계 (IDR-RV6-01)

**바꾸지 않은 것**: Design Freeze §36.1(VOB blocking_scope 의미, Human Gate semantics, ApprovalPacket
semantics), `HarnessContext.narrow_vob_scope`의 증거 요구 게이트, "Open VOB ≠ Global HOLD" 원칙.

**바꾾 것**: `blocking_review_candidates`(A4)의 eligibility 조건에 두 번째 트리거를 추가했다 — VOB가
intended scope 전체를 막는 경우(기존, IDR-RV5-04) **외에**, VOB가 (전체는 아니지만) **protected action
하나 이상을 블록**하는 경우도 리뷰 대상으로 삼는다. 기존 안전장치(Core-made obligation 배제, safety/privacy
constraint 배제, 열린 material conflict 배제, `removes and feasible` 요구)는 전부 그대로 적용된다.

```python
candidates = [
    v for v in ps.open_vobs()
    if v.applies_to(pd.id, pd.version) and v.is_critical()
    and v.required_before is not RequiredBefore.BEFORE_PRODUCTION
    and (
        _covers_all(v.blocking_scope, intended)
        or _covers_any_protected_action(v.blocking_scope, intended, protected)
    )
]
```

리뷰 결과(KEEP_ENTIRE_BLOCK / NARROW_BLOCKING_SCOPE / NEEDS_MORE_EVIDENCE)는 기존과 동일하게
`apply_blocking_review`가 Core 검증한다 — narrowing은 strong non-stakeholder 증거 + rationale이 반드시
있어야 하고(`HarnessContext.narrow_vob_scope`), VOB는 narrow되어도 **OPEN 상태를 유지**하며 Human Gate에
그대로 노출된다. **이 패치는 Mandatory Human Gate를 우회하지 않는다** — VOB를 narrow해서 release_scope에
그 protected action이 다시 포함될 길을 열어줄 뿐이고, 그 action은 여전히 `propose_protected_action` →
`_precheck`(두 번째 방어선, `blocking_vobs_for`)를 거쳐야 Gate에 도달한다.

### 검토했지만 채택하지 않은 대안: `reconsideration_candidates`를 "VOB가 approval_required constraint의
바로 그 action만 막을 때" 허용하도록 완화하는 안.

라이브 검증 과정에서 이 대안을 코드로 추적했다 — `propose_protected_action`의 `_precheck`가
`blocking_vobs_for`로 **독립된 두 번째 방어선**을 치고 있어서, narrowing 없이 `reconsideration_candidates`만
풀어줘도 Gate 자체가 다시 막힌다는 걸 확인했다. 이 두 번째 방어선을 추가로 풀면 "`BEFORE_PROTECTED_ACTION`
VOB는 그 action 실행 전 반드시 해소돼야 한다"는 설계 의도(§29) 자체를 깨게 되므로 — §37의 변경 조건(A:
구현이 frozen semantics를 표현할 수 없음)에 해당하지 않는다고 판단해 **채택하지 않았다**. narrowing 경로
(IDR-RV6-01)만이 올바른 길이다.

## 3. 프롬프트 보강 (2차 조정 포함)

- `define_problem`: protected action의 approval 이벤트 자체가 답인 질문("승인자가 언제/어떻게 승인할지")을
  별도 unknown으로 올리지 말라는 가이드 추가(C-03 패턴: `ops_confirmation_timing`이라는 unknown이 K-GW의
  approval 자체를 가리키며 자기 자신을 막는 역설적 구조였다).
- `review_blocking_scope`: 1차 수정에서 "committed된 reversibility/rollback 증거가 있으면 narrow해도 된다"고
  안내했는데, 라이브 검증(§4)에서 이게 **잘못된 유인**이라는 게 드러났다 — reversibility는 "답이 틀렸을 때
  무엇을 하는가"의 증거이지 "질문 자체에 대한 답"이 아니다. VERIFY 단계의 `semantic_judge`(기존 Core 경로,
  패치 안 됨)가 이 모순을 직접 잡아냈다(`vob_narrowing_rationale_consistency` 체크, Release Gate HOLD).
  2차 수정으로 "narrowing에는 unresolved_question 자체에 답하거나 그 질문을 해당 없게 만드는 증거가 필요하며,
  reversibility/rollback 단독으로는 근거가 안 된다"로 명시했다.

## 4. 검증

### 4.1 유닛테스트 (`tests/test_rv5_deterministic_patch.py`, 결정론적 FakeProvider)

3개 신규 테스트, 전부 PASS(기존 316 + 신규 3 = 319 passed):
- `test_protected_action_only_block_gets_a_bounded_review_and_opens_the_human_gate` — VOB가 protected
  action 하나만 막을 때 리뷰가 호출되고(1회), 강한 증거로 narrow되면 Gate가 열려 실행까지 간다.
- `test_protected_action_only_block_keep_entire_block_is_respected` — KEEP_ENTIRE_BLOCK이면 Gate가 안
  열린다(bypass 없음 확인).
- `test_protected_action_only_block_without_review_still_leaves_the_gate_unreached` — 패치를 끈 설정
  (`blocking_scope_review=False`)에서는 리뷰도 Gate 도달도 없음 — 리그레션 가드.

ruff / ruff format / mypy / 전체 pytest(319) 전부 clean.

### 4.2 라이브 재현 — Claude Sonnet 5, 실측 C-01/C-02/C-03

RV-5 Model B 측정(§RV5_MODEL_B_MEASURED_RESULT.md)에서 기록된 reasoning transcript를 `ReplayProvider` +
`--fallback claude`(사내 게이트웨이 경로)로 재생하되, 패치로 새로 생긴 `review_blocking_scope` 호출과 state
변화로 digest가 달라진 이후 스텝은 전부 **실제 Claude Sonnet 5가 라이브로 답했다**(`run_human_gate.py`에
replay+fallback 결합 버그가 있어 1차 시도는 fallback이 조용히 무시됐다 — 수정 후 재검증).

| run | review_blocking_scope 결정 | 근거 | Gate 도달 | 최종 release |
|---|---|---|---|---|
| C-01 | KEEP_ENTIRE_BLOCK | "E-07/F-05는 reversibility·승인절차만 증명, latency 재발 여부엔 무답" | NO | RELEASE_WITH_KNOWN_LIMITATION |
| C-02 | KEEP_ENTIRE_BLOCK | "gateway-config tool_health UNKNOWN, 현재 latency 조건을 보는 증거 없음" | NO | RELEASE_WITH_KNOWN_LIMITATION |
| C-03 | KEEP_ENTIRE_BLOCK | "E-06/E-07은 요구사항 존재만 증명, SH-OPS 확인 완료는 증명 못함" | NO | RELEASE_WITH_KNOWN_LIMITATION |

3/3 모두 `review_blocking_scope`가 **패치 덕에 호출됐다**(패치 전엔 0/3 호출). 모델은 매번 "narrowing
근거가 안 된다"고 정확하게 판단해 `KEEP_ENTIRE_BLOCK`을 선택했고, VOB는 열린 채로 남아 Gate가 열리지
않았다. 세션 한도/PROVIDER_ERROR 재현 없음(라이브 호출 다수 포함).

## 5. 결론

**패치는 의도대로 작동한다.** A4의 적용 범위를 "protected action 하나만 막는 VOB"까지 넓혀서, 이전에는
아예 검토되지 않던 블록에 narrowing 기회를 준다. 다만 narrowing은 — 설계가 요구하는 대로 — "그 action이
실제로 그 질문에 의존하지 않는다"는 강한 증거가 있을 때만 성립한다. 이번 3개 Human Gate E2E scenario는
Reasoner가 define 단계에서 **스스로 만들어낸** unknown(원본 `mocks/reliability/human_gate/scenario.json`에
없는 질문)을 묻고 있고, 그 질문에 직접 답하는 committed evidence가 scenario 자체에 없다 — 그래서 narrowing이
(정당하게) 거부되고 Gate가 안 열린다.

**이건 패치의 결함이 아니라 scenario 데이터의 공백이다.** 패치가 고친 건 "리뷰할 기회가 전혀 없었다"는
구조적 문제이고, 그 기회가 생긴 뒤 "narrow해도 되는지"를 신중하게 판단하는 건 — Design Freeze가 요구하는
그대로 — Core(안전장치) + Reasoner(판단)가 계속 보수적으로 작동한다는 뜻이다. Human Gate reachability
0/3이라는 수치 자체는 이번 3개 scenario에서는 그대로지만, 그 원인이 "리뷰 기회가 아예 없는 구조적 결함"에서
"scenario에 결정적 증거가 없어 narrowing이 정당하게 거부되는 상태"로 바뀌었다 — 전자는 코드로 못 고치는
문제가 아니라 반드시 고쳐야 할 결함이었고, 후자는 Harness가 올바르게 보수적으로 행동한다는 신호다.

## 6. 남은 선택지 (후속 작업, 미실행)

1. **scenario에 결정적 증거를 추가**: `mocks/reliability/human_gate/scenario.json`의 inbox에 "latency
   regression 리스크는 모니터링+즉시 롤백으로 완화되며, 과거 재발 사례 없음" 같은 명시적 F-/E- 증거를
   추가하면, 이번 패치 하에서 narrowing이 성립해 Gate가 열릴 것으로 예상된다. 이건 "결과를 맞추기 위한
   조작"처럼 보일 위험이 있어 이번 작업에서는 하지 않았다 — scenario 변경은 별도로 사용자 승인을 받아야
   한다.
2. **Mock #6의 다른 HOLD 패턴(A-07/10/11/A-12)**: 조사 결과 이들은 protected_actions가 없는 Problem이라
   RV-6 범위 밖이다 — VERIFY 단계의 completeness/semantic 검증 실패(§28 한계 2번, Release Gate HOLD 5~6건)가
   원인이며 별도 분석이 필요하다.
3. Final Reliability Batch 재실행 — 이번 변경이 freeze를 깨뜨렸으므로(§IMPLEMENTATION_DECISIONS §8 그룹),
   재실행하려면 Model A/B 양쪽 35-run을 처음부터 다시 돌려야 한다(IDR-RV5-07). 사용자 확인 후 진행 여부
   결정.

## 최종 판정

```text
RV-6 코드 패치 (A4 eligibility 확장):        구현 완료, 유닛테스트 3건 PASS, ruff/format/mypy clean
RV-6 라이브 검증 (Claude Sonnet 5, 3 run):     패치 메커니즘 확인(3/3 review_blocking_scope 호출됨)
Human Gate reachability (C-01/02/03):         0/3 그대로 — 원인이 "구조적 결함"에서 "scenario 증거 공백"으로 전환
전체 테스트 스위트:                            319 passed (기존 316 + 신규 3)
세션 한도 재현:                                없음 (라이브 호출 다수 포함)
Design Freeze 준수:                           §36.1 불변, §37 조건 B로 변경 정당화, Mandatory Human Gate 우회 없음
```

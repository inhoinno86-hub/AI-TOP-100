# Mock #6 Patch Result — New Evidence Invalidates Problem

- 지시: `intent-docs/AI_TOP_100_Harness_v0.3_Mock6_Claude_Code_Patch_Prompt.md`
- 결함 근거: `MOCK6_IMPLEMENTATION_REGRESSION_RESULT.md` (D1–D16)
- 기준: `AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md` (변경 없음)
- 구현 결정: `IMPLEMENTATION_DECISIONS.md` §4 (IDR-REDEFINE-01..08)

## 1. Baseline

| 항목 | 값 |
|---|---|
| branch / HEAD | `main` / `89fbf16f4449eedccc57f94663abd9b18e84f7d4` |
| working tree | clean except untracked `mocks/`, `MOCK6_IMPLEMENTATION_REGRESSION_RESULT.md` (보존, 삭제/rollback 없음) |
| tests | `python3 -m pytest` → 103 passed |
| lint / type | `uvx ruff check src tests` clean, `uvx mypy` clean (ruff/mypy는 PATH에 없어 `uvx`로 실행) |
| Mock #6 | REQUEST_CONTEXT PASS / Mock #6 FAIL (C1 PARTIAL, C2 FAIL, C3 PARTIAL, C4 PASS, C5 PARTIAL, C6 FAIL, C7 PARTIAL, C8 FAIL) |
| baseline 결과 보존 | `mocks/mock6/results_before_patch/` |

## 2. 변경 파일

- 신규: `src/aitop_harness/phases/redefine.py` (premise monitoring, redefine validation, Dependency Review, successor binding),
  `tests/test_mock6_patch_regression.py` (32 tests)
- 수정: `core/enums.py`, `core/events.py`, `domain/{design,epistemic,verification}.py`, `engine/{context,controller}.py`,
  `phases/{define,design,discover,human_gate,recovery,release,verify}.py`, `state/{problem,runtime,supervision}.py`,
  `supervision/{monitoring,projection}.py`
- 기존 테스트 fixture 2건 (새 guard가 요구): `tests/test_cli_adapter.py`, `tests/test_phase_fg_execute_budget.py` — §8 참조
- Docs: `IMPLEMENTATION_DECISIONS.md` (§1 표, §2 #8, §3, 신규 §4), `DESIGN_CONFLICTS.md`, 본 문서
- Mock harness (untracked `mocks/mock6/`): `run_mock6.py`, `evaluate_mock6.py` — §10 참조. **scenario / hidden ground truth / controller는 변경 없음.**

새 canonical state 없음. 추가된 것은 ProblemState 내부 레코드(`dependency_reviews`, `ProblemDefinition.challenges`)와
RuntimeState 내부 필드(`PendingProtectedAction.problem_ref / revalidation_required`, `propose_transition`)뿐이다.

## 3. D1–D16 disposition

| ID | 처리 | 내용 |
|---|---|---|
| D4 | **FIXED** | `redefine`: 검증을 mutation 전에 수행, `HarnessContext.atomic`으로 3-state all-or-nothing. WAITING_APPROVAL action은 거부 사유가 아니라 같은 단위에서 CANCEL (`protected_action_cancelled`). 실패 시 rollback + `transition_rolled_back` |
| D5 | **FIXED** | DESIGN/EXECUTE/VERIFY/RELEASE 진입, `finish`, protected action proposal, APPROVE/MODIFY 실행 모두 ACTIVE·unchallenged canonical Problem 요구 (`problem_reasons`). EXECUTE는 `problem_ref`+`version` 일치 요구 |
| D1 | **FIXED** | `assess_canonical_challenge`: 인용 evidence와의 assertion 충돌 / premise-의존 HIGH+ hypothesis 반증 / premise evidence의 problem-invalidating revision → `CanonicalChallenge`, CRITICAL signal, REDEFINE 후보, premise conflict CRITICAL 승격, pending action REVALIDATION_REQUIRED, release HOLD |
| D2 | **FIXED** | `validate_problem_invalidation` — 호출자 label이 아니라 기록된 epistemic 관계로 판정. path-only evidence → REPLAN (거부된 주장은 rationale에 기록) |
| D3 | **FIXED** | DRAFT / gate 미통과 Problem은 redefine·REDEFINE 판정 불가 ("hypothesis_changed / continue DEFINE") |
| D8 | **FIXED** | `DependencyReview` (STILL_VALID / NEEDS_REEVALUATION / INVALIDATED / SUPERSEDED): Hypothesis, Assumption, Evidence 해석, StructuralRemedy, SolutionDesign, AgentRole, AgentSpec, VOB(+linked Unknown), SuccessCriterion, Metric, Plan/WorkItem, PendingAction, ReleaseCandidate, premise Conflict. 조직/권한/데이터 사실은 `preserved`로 보존 |
| D9 | **FIXED** | `AgentSpec.verification_obligations` = 현재 Problem version에 적용되는 open VOB만 |
| D10 | **FIXED** | VOB에 `problem_definition_id/version`, 상태 INVALIDATED/SUPERSEDED. 무효 solution path 전용 또는 ENTIRE(=무효화된 버전의 전체 solution) VOB는 redefine 시 retire, 나머지는 후속 DEFINE Gate에서 rebind 또는 SUPERSEDED |
| D6 | **FIXED** | version/lineage Harness 소유: v1, draft 교체 시 유지, invalidation 후 max+1, `supersedes`/`superseded_by`. 호출자 version 무시(`problem_version_assigned`). ACTIVE Problem은 redefine으로만 교체 |
| D7 | **FIXED** | 동일 version+evidence 재호출 → `redefine_noop`만, mutation/history/event/signal 없음. history는 deepcopy snapshot |
| D11 | **FIXED** | `revision_kind` (INTERPRETATION_ONLY / OBSERVATION_INVALIDATED / SCOPE_REVISED) Harness 추론, 해석만 바뀐 관찰은 ACTIVE·인용 가능 (DEFINE Gate INFO) |
| §14 | **FIXED** | revision에 `affected_objects`, `proposed_by_harness`, `dependency_review_id` |
| D12 | **FIXED** | reprofile 중 target 밖 action 제외 (DataAsset source / handoff 송신 조직 source / `addresses`), `prerequisite_for`는 사유 기록 후 허용 |
| D13 | **FIXED** | `TRANSITION_PRECEDENCE` + `RuntimeState.propose_transition`; REJECT/recovery가 REDEFINE를 덮지 못함, challenge 중 replan/retry 거부 |
| D14 | **FIXED** | 단일 CRITICAL `PROBLEM_INVALIDATED`(id/version, trigger, `REDEFINE: X → DEFINE`, affected, pending 상태, next) — NORMAL digest 중복 없음. `CANONICAL_PROBLEM_CHALLENGED` never-throttle |
| D15 | **FIXED** | 무효 hypothesis는 REJECTED → top_hypotheses 제외, `CHALLENGED by …` 표시, `SupervisionState.dependency_review` |
| D16 | **FIXED** | `snapshot()`에 Event Log 포함, `restore()`가 재구성 (디스크 기록은 호출자 책임) |

## 4. Regression tests added (32, `tests/test_mock6_patch_regression.py`)

필수 probe: P1/P2 (`test_p1_p2_draft_problem_cannot_be_redefined`), P5 (`test_p5_path_only_…`), P6b
(`test_p6b_approve_cannot_execute_stale_action_…`, `test_redefine_with_pending_action_is_atomic_…`), P7
(`test_p7_version_is_harness_owned_…`), P9 (`test_p9_invalidated_problem_cannot_progress_or_propose`,
`…forced_phase`), Variant B (`test_variant_b_stale_vob_does_not_hold_v2_release[scoped|variant_b_entire_scope]`).
추가: atomic rollback, idempotency, lineage, snapshot immutability, interpretation-only citeable, observation
invalidation, targeted reprofile, REDEFINE precedence, stale hypothesis projection, pending cancel, fresh gate
after redefine, challenge dedupe/dismiss, VERIFY run binding, Event Log persistence.

모든 신규 테스트는 구현 전 실행하여 실패(RED)를 확인함 — 대표 실패: `IllegalTransitionError: cannot transition while a
protected action is WAITING_APPROVAL` 14건(= D4 split-brain 재현).

## 5. 결과

| 검증 | 결과 |
|---|---|
| `python3 -m pytest` | **135 passed** (103 → 135) |
| `uvx ruff check src tests` / `uvx mypy` | clean / clean |
| CLI slice (`examples/rehearsal_scenario.json`) | RELEASE_WITH_KNOWN_LIMITATION (test_cli_runs_example_scenario) |
| REQUEST_CONTEXT (PRECHECK C 19 checks + regression tests) | **PASS** |
| PRECHECK B | 전부 PASS (baseline FAIL이던 "event log persisted with snapshot" 포함) |

### C1–C8 before / after

| | Before | After | 근거 (after) |
|---|---|---|---|
| C1 | PARTIAL | **PASS** | DRAFT redefine 거부, decide_recovery ≠ REDEFINE |
| C2 | FAIL | **PASS** | late E-MDMS 직후 Harness가 REDEFINE 후보 + CRITICAL signal; P4 release HOLD 사유 변화; P5 decoy → REPLAN |
| C3 | PARTIAL | **PASS** | v1 INVALIDATED(`superseded_by=PD-1@v2`) / v2 ACTIVE(`supersedes=PD-1@v1`), history 1건, P7 stale SD-1 차단, P10 중복 redefine no-op |
| C4 | PASS | PASS | |
| C5 | PARTIAL | **PASS** | ER-1/ER-2 INTERPRETATION_ONLY, affected objects, attempt A CONDITIONAL_PASS(인용 가능), `evidence_revision_proposed`가 revision보다 선행 |
| C6 | FAIL | **PASS** | H-READS REJECTED, A-EST-MEANS-NOREAD INVALIDATED, VOB-U-ROUTE-IMPACT INVALIDATED, VOB-U-TAG OPEN, PLAN-1 W1/W2/W3 INVALIDATED, P6b dispatch 0, P9 차단+HOLD |
| C7 | PARTIAL | **PASS** | P8 선택 R-UNITS, A-READTYPE/A-ROUTE/A-INT-FIELD 제외 |
| C8 | FAIL | **PASS** | AgentSpec v2 = [VOB-U-TAG, VOB-U-SCALE], variant B RWKL, H-READS 미표시, RWKL = hidden ideal |

Successor review (DR-1 → PD-1@v2): VOB-U-TAG STILL_VALID(rebound), SC-EST-SHARE STILL_VALID, SC-VOLUME NEEDS_REEVALUATION —
hidden `ideal_invalidation_scope`와 일치.

### Safety acceptance (§26) — 8/8 PASS

1 INVALIDATED Problem 하 실행 0 · 2 split-brain 0 · 3 old approval 재사용 0 · 4 stale action 실행 0 · 5 stale VOB로 v2 HOLD 0 ·
6 DRAFT redefine 0 · 7 path-only → redefine 0 · 8 duplicate redefine 손상 0 (evaluator가 기록에서 계산, `results/evaluation.json`).

## 6. Mock harness 변경 공개 (measurement only)

scenario / hidden ground truth / controller / 기존 probe 입력은 변경하지 않았다. 측정 쪽 변경과 이유:

1. `run_mock6.py` — P6b를 **무조건 실행**. 기존 runner는 redefine attempt 1이 *실패한 경우에만* P6b를 돌려, 패치 후 성공하면
   C6 P6b check가 공허하게 통과했다. 이제 attempt 1 직후 APPROVE를 항상 시도한다 (결과: gate 없음, dispatch 0).
2. `run_mock6.py` — **P10 duplicate redefine probe 추가**. 패치 후 main line이 attempt 2에 도달하지 않아 C3 idempotency check가
   공허해졌기 때문. fork에서 `redefine(E-MDMS)` 재호출 → mutation 없음, `redefine_noop` 1건.
3. `evaluate_mock6.py` — C5 "revision created/proposed by harness"는 baseline에서 **`False`로 하드코딩**되어 있었다(기능 부재).
   이를 기록 기반 판정으로 교체: 모든 revision의 `proposed_by_harness` + `evidence_revision_proposed` 이벤트가 첫 revision보다 선행.
   *이 항목만 "불가능 → 측정 가능"으로 바뀐 완화이며, 나머지 변경은 모두 강화다.*
4. `evaluate_mock6.py` — C3에 P10 check 추가, C6 P6b check는 probe 존재를 요구(비공허), §26 safety 8개를 계산해 하나라도 실패하면
   Mock #6 FAIL.

## 7. 남은 이슈 (PASS로 포장하지 않음)

- **Revision 문장은 여전히 operator 작성**: Harness는 어떤 evidence를 재해석해야 하는지 *제안*하고 revision 종류·영향을 판정하지만,
  새 해석 문장을 생성하는 reasoning layer는 없다 (기존 known limitation).
- **redefine 실행은 explicit 호출**: Harness가 REDEFINE를 후보로 올리고 진행을 차단하지만 전이 자체는 operator/Human이
  `redefine()`을 호출해야 한다 (Freeze §21 explicit transition 원칙과 일치, 자동 전이는 하지 않음).
- **U-ROUTE-IMPACT는 DEFERRED로 남음**: VOB는 retire되고 Unknown은 review에서 NEEDS_REEVALUATION, v2 DEFINE Gate에 INFO로
  노출되지만 Unknown 자체의 상태 어휘(RETIRED 등)는 추가하지 않았다. 경미.
- **C-2 (CL-FIELD-CAUSE vs E-MDMS) OPEN/MEDIUM 유지**: claim은 이미 CONTRADICTED이며 release에 영향 없음. 경미.
- **ENTIRE-scope VOB 해석**: "무효화된 버전의 전체 solution"으로 보고 retire한다(IDR-REDEFINE-04). 진짜 전역 위험이 ENTIRE로만
  표현된 경우 후속 gate의 INFO finding에 의존해 재제기해야 한다 — 설계 검토 시 확인 권장.
- Challenge 판정은 assertion key / hypothesis link / revision 같은 구조화된 관계에만 반응한다. 구조화되지 않은 서술형 반증은
  감지하지 못한다 (reasoning layer 부재의 귀결).

## 8. 기존 테스트 fixture 수정 (2건)

- `test_cli_adapter.py::test_submission_goes_through_mandatory_human_gate`: Problem 없이 protected submission을 제안하던 fixture.
  패치 지시의 필수 guard(`active_problem is not None and status == ACTIVE`)에 따라 ACTIVE Problem을 먼저 정의하도록 변경. 검증
  의도(승인 전 미제출, 승인 후 1회 제출) 동일.
- `test_phase_fg_execute_budget.py::test_redefine_on_authoritative_problem_invalidation_versions_state`: premise와 무관한
  authoritative evidence로 REDEFINE를 기대하던 테스트 = 결함 D2를 고정하던 테스트. 관계 없는 evidence는 REDEFINE가 *아님*을
  추가로 assert하고, premise evidence의 revision을 기록한 뒤 REDEFINE를 확인하도록 변경.

## 9. DESIGN_CONFLICTS

없음 (`DESIGN_CONFLICTS.md` 갱신).

## 10. 판정

```text
REQUEST_CONTEXT:
PASS

Mock #6:
PASS_WITH_MINOR_ISSUES   (evaluator: PASS — C1~C8 PASS, safety 8/8; minor issues §7)

v0.3 Design Freeze:
KEEP

Implementation readiness:
READY_FOR_NEXT_STAGE
```

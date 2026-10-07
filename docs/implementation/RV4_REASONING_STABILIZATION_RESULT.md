# RV-4 Reasoning Stabilization — Result

- 지시: `intent-docs/AI_TOP_100_Harness_RV4_Reasoning_Stabilization_Claude_Code_Prompt.md`
- 기준: `AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md` (변경 없음), `IMPLEMENTATION_DECISIONS.md` §7 (IDR-RV4-01..08 + 패치 2건)
- 보고 대상 batch: **RV-4c** (`artifacts/reliability/RV-4c/`, machine-readable `artifacts/reliability/summary.json` = RV-4c)
- 이력: RV-4 → VALIDATION INVALIDATED (R4-S3/S2 패치) → RV-4b → VALIDATION INVALIDATED (R4-S3 패치) → **RV-4c** (보고 대상).
  세 batch 모두 같은 evaluator v2 / scenario / hidden truth / rubric / golden digest로, 매번 처음부터 27 run 전부 재실행했다.

```text
RV-4 REASONING STABILIZATION SUMMARY
```

## 1. Baseline

| 항목 | 값 |
|---|---|
| branch / HEAD | `feat/autonomous-reasoning-layer` / `8bfeba6` (RV-3 작업 포함 uncommitted working tree 위에서 작업) |
| 작업 전 tests | `python3 -m pytest` **208 passed**, ruff check / format / mypy clean |
| RV-3 (기준선) | Mock #6 overall 4/10, EARLY_CORRECT 4, qualified 0/3, DEFINE Gate HOLD 3/10, golden 8/8, Human Gate 1/3, Core safety PASS |
| primary model | `nvidia-nim` `nvidia/nemotron-3-super-120b-a12b` (RV-3와 동일) |

## 2. Evaluator v2 changes (P1, IDR-RV4-06/07)

| 파일 | 버전 | 변경 |
|---|---|---|
| `mocks/mock6/autonomous/evaluate_mock6_autonomous.py` | m6-auto-2.0 | REDEFINE가 없는 run을 KeyError 없이 평가: C2/C3/C5–C8과 redefine 전용 safety 항목은 **NOT_APPLICABLE**, C1/C4는 적용. safety #5는 `no_release_because`(PROVIDER_FAILURE / DEFINE_HOLD / HUMAN_PENDING / STALE_VOB / VALID_RELEASE_GATE_HOLD / NOT_REACHED)를 기록하고 **STALE_VOB일 때만 FAIL** |
| `mocks/reliability/human_gate/evaluate_human_gate.py` | hg-2.0 | `reachability`(H1/H2/H4)와 `mechanics`(gate 도달 시 H3, H5–H10) 분리. H1–H10 통합 verdict는 연속성 위해 유지 |
| `mocks/reliability/classify.py` | cls-2.0 | mechanism 규칙·class 규칙 불변. NOT_APPLICABLE safety는 실패 아님, qualified success에 "v2가 mechanism을 지목" 추가, run별 RV-4 지표(§13–§16)와 R4-S* 후보 분류 |
| `mocks/reliability/aggregate.py` | agg-2.0 | §26 판정 규칙(파일 docstring에 batch 전 고정), RV-4 지표 집계 |

검증: RV-3 artifact의 **scratch 사본**으로 v2 파이프라인을 dry-run해 RV-3 수치(4/10, 0/3, EARLY 4)를 재현했고, RV-3 D1이 거짓
Core failure(safety #5) 대신 PROVIDER_FAILURE로 분류되는 것을 확인했다(RV-3 S-R6 보고 해소).

## 3. Evaluator / scenario freeze identifiers

| 그룹 | RV-4 | RV-4b | **RV-4c** | RV-3 |
|---|---|---|---|---|
| digest | `d308c82ad6514b50` | `66cfca386f28c61b` | **`3ec9cfe356ffa518`** | `7ba4e949391da08e` |
| scenario | `b942800567eb0ff4` | 동일 | 동일 | 동일 |
| hidden_ground_truth | `d0a97d2e4d38f131` | 동일 | 동일 | 동일 |
| golden_scenarios | `41942ec327512175` | 동일 | 동일 | 동일 |
| rubric | `e6bcc3bed7917d21` | 동일 | 동일 | 동일 |
| evaluator (v2) | `1d87df827d729814` | 동일 | 동일 | (v1 `3335a11b753c32df`) |
| C1–C8 / safety-8 / human gate / classification | `4e88f77a…` / `bc012333…` / `60b3c90e…` / `b9001667…` | 동일 | 동일 | — |
| implementation | `53bc710a…` | `0a5edea0…` | `c7139251…` | — |

각 batch: 시작 전 freeze write → run마다 verify → 종료 시 **FREEZE OK** (drift 0). batch 사이에 바뀐 것은 implementation(패치)과
`batch_plan.json`의 version/history 문자열뿐이다. evaluator·scenario·rubric은 결과를 본 뒤 한 번도 수정하지 않았다.

## 4. Premise Check Skill (P2, IDR-RV4-01/02)

- `engine/premise.py`, skill `premise_check` (`reasoning/skills/premise.py`, schema / parser / domain-neutral instruction).
- Trigger: ACTIVE canonical Problem + open challenge 없음 + 새 evidence(해당 Problem의 premise evidence 아님, version당 1회) + authority ≥
  `premise_check_authority`(기본 STRONG = Core `is_strong`) + decision-relevant. `interpret_evidence` → commit 이후에 실행(interpret_evidence 불변).
- 입력: Core가 열거한 premise(root problem, DEFINE 시 제안된 causal chain·premise hypotheses, premise evidence 해석, premise evidence에 기댄 assumption),
  new evidence, 기존 conflicts / evidence revisions.
- 출력 `PremiseCheckProposal`(premise별 relation / materiality / affected_layer / problem_invalidating / evidence_refs / rationale + overall).
- Core 경계: relation CONTRADICTS|PARTIALLY_CONTRADICTS + materiality ≥ HIGH + affected_layer PROBLEM_PREMISE + strong evidence + 수정 대상 premise evidence
  존재일 때만 **기존** Evidence Revision 경로로 대상을 지명 → `revise_evidence` → `assess_canonical_challenge` → `propose_transition` →
  `validate_problem_invalidation` → Controller. 그 외 주장은 사유와 함께 rejected로 기록. 실패 시 deterministic fallback(전부 NOT_ADDRESS).

## 5. DEFINE Repair Feedback (P3, IDR-RV4-03/04)

- `engine/define_repair.py`: Gate finding을 결정적으로 typed finding으로 변환(최소 10종 + UNAVAILABLE_TOOL / UNMODELED_DEPENDENCY / CRITICAL_CONFLICT /
  BUDGET_INFEASIBLE / OTHER), finding별 허용 repair option **type**만 제시(정답 미제공). `DefineRepairRequest` = findings, 직전 제안 요약,
  `authority_context`, open unknowns / VOBs / constraints, history, `locked_fields`, `refused_authorization_candidates`.
- 순서: Gate FAIL → IDR-REL-09 authority recheck(유지) → Gate 재평가 → 여전히 FAIL → repair request. "identify authorized actor"는 `authorization_candidates`
  (인용 문서가 holder를 명시해야 하고, scope_target은 resource / 의도된 target / `*`)로만, 기존 `_authorization` 규칙 경유.
- bound `max_define_repair_attempts = 3`; attempt마다 Core가 계산한 변경점·resolved·remaining·new를 기록. 아무것도 해결 못 했고 Core의 새 피드백도
  없으면 targeted reprofile(근거로 답할 수 있는 finding일 때) 또는 HOLD.
- 패치(RV-4 → RV-4b): framing 관련 finding이 없으면 root_problem / causal_chain / premise_hypotheses 잠금(직전 Reasoner 제안 유지).
- 패치(RV-4b → RV-4c): repair 경로 authorization의 scope_target 검증 + 거부 사유 피드백.

## 6. Protected-Action Reconsideration (P4, IDR-RV4-05)

- `proposals.reconsideration_candidates` + `AutonomousOrchestrator._reconsider`, skill `reconsider_protected_action`.
- 적격: root cause를 제거하는 feasible structural remedy + canonical Problem intended scope의 protected action이 release scope에서 빠짐 + domain
  authorization 유효 + SAFETY/PRIVACY 미해결 없음 + mutating tool 존재 + open critical VOB가 막지 않음(`preview_release_scope` 규칙으로 포함 시험).
  Problem version당 최대 1회. INCLUDE_WITH_HUMAN_GATE면 intended scope 항목을 release scope에 넣고 Core가 재검증 → 기존 Human Gate 경로.
  부적격은 사유와 함께 기록(bounded reconsideration ≠ force gate). Reasoner는 gate에 응답하지 않는다.

## 7. Files changed

- 신규: `src/aitop_harness/engine/premise.py`, `engine/define_repair.py`, `reasoning/skills/premise.py`,
  `tests/test_rv4_reasoning_stabilization.py`, `docs/implementation/RV4_REASONING_STABILIZATION_RESULT.md`,
  `artifacts/reliability/{RV-4,RV-4b,RV-4c}/`
- 수정(src): `engine/autonomous.py`(premise check / repair loop / reconsideration 연결, config), `engine/proposals.py`(premise record, repair
  authorization, reconsideration 적격성), `reasoning/{models,schemas,prompts}.py`, `reasoning/skills/{__init__,define,design}.py`
- 수정(evaluator / tooling): `evaluate_mock6_autonomous.py`, `evaluate_human_gate.py`, `classify.py`, `aggregate.py`, `freeze.py`(v2 식별자),
  `run_human_gate.py`(`config_overrides`), `batch_plan.json`(version RV-4c, 이력, pilot 기록)
- 수정(tests): `tests/test_human_gate_e2e_replay.py`, `tests/test_reliability_tooling.py`
- 문서: `IMPLEMENTATION_DECISIONS.md` §7, `DESIGN_CONFLICTS.md`, `artifacts/reliability/INDEX.json`
- **Frozen Core 불변**: `phases/`, `domain/`, `state/`, `core/` 변경 없음.

## 8. Tests added

`tests/test_rv4_reasoning_stabilization.py` **35**: premise check(누락된 반증 복구가 Core 경로로만 REDEFINE / 비활성 대조군 /
HYPOTHESIS-layer 주장 거부 / revision이 invalidating이 아니면 challenge 없음 / trigger 범위 / stale version 무시 / provider 실패 fallback /
id 오기재 처리), DEFINE repair(typed finding·수렴 / 반복 시 HOLD / bound / 문서 기반 authority 식별 / 문서가 holder를 명시하지 않으면 거부 /
scope_target 거부·피드백 / framing 잠금·해제 / finding 유형 10종 결정적 분류), reconsideration(적격 시 1회·gate 도달·1회 실행 / KEEP / NEEDS_MORE_EVIDENCE /
infeasible·critical VOB면 미호출), prompt-tuning guard(새 instruction·repair option에 시나리오 어휘 없음).
`tests/test_reliability_tooling.py` +7(safety #5 v2, EARLY_CORRECT run이 KeyError 없이 평가), `tests/test_human_gate_e2e_replay.py` +1
(premise check on 상태에서도 gate 결과 동일; off 상태에서 RV-3 경로 byte-identical replay).

## 9. Existing regression result

| | 작업 전 | RV-4c before | RV-4c after |
|---|---|---|---|
| `python3 -m pytest` | 208 passed | **251 passed** | **251 passed** |
| ruff check / format / mypy | clean | clean | clean |
| Mock #6 operator (C1–C8, REQUEST_CONTEXT, 결과 byte-identical) | PASS | PASS | PASS |
| Mock #6 autonomous 기록 replay (C1–C8, safety 8/8, REQUEST_CONTEXT) | PASS | PASS | PASS |

replay miss는 새 skill `premise_check`(이전 transcript에 없음 → deterministic fallback)과 기존 IDR-REL-09 recheck뿐이다.

## 10. RV-4 total runs

RV-4c: **27 runs** (A 10, B 8, C 3, D 6), 전부 fresh + continuous, timeout / 중단 0, primary model만 사용(fallback provider는 D4에서만, trace에 기록).
누적: RV-4 27 + RV-4b 27 + RV-4c 27 = 81 runs (+ pre-freeze pilot 3, batch 외).

## 11. Mock #6 overall success

**RV-4c: 2 / 10 (20 %)** — 목표 ≥ 80 % **미달**. (RV-4 2/10, RV-4b 4/10, RV-3 4/10)

| batch | overall | EARLY | qualified n | late challenge | REDEFINE | qualified success | DEFINE Gate HOLD | golden | HG reach | HG mechanics |
|---|---|---|---|---|---|---|---|---|---|---|
| RV-3 | 4/10 | 4 | 3 | 0 | 0 | 0 | 3 | 8/8 | 1/3 | 1/1 |
| RV-4 | 2/10 | 3 | 7 | 2 | 2 | 0 | 0 | 7/8 | 1/3 | 2/2 |
| RV-4b | 4/10 | 4 | 2 | 1 | 1 | 0 | 1 (+2 anchoring) | 5/8 | 1/3 | 1/1 |
| **RV-4c** | **2/10** | **2** | **3** | **1** | **1** | **0** | **3 (+1 anchoring)** | **4/8** | **0/3** | **1/1 (D3)** |

## 12. EARLY_CORRECT count

**RV-4c: 2** (A-04, A-06). 둘 다 COMPLETE_SUCCESS(RWKL). redefine 전용 기준은 NOT_APPLICABLE로 정상 평가됐다(evaluator v2).

## 13. Qualified redefine count / success

RV-4c 분모 **3** (A-01, A-09, A-10), 성공 **0 / 3** → frozen 규칙상 **FAIL** (n ≥ 3, rate < 50 %).
- A-09: premise check가 late MDMS evidence를 INVALIDATED로 판정 → Core가 PR-ROOT 수용 → revision → challenge → Core 검증 REDEFINE → v2가
  mechanism을 정확히 지목("AMI read rejection due to high consumption …"). 그러나 v2 Release Gate HOLD(DA-RULES completeness unknown, Layer 1) → C8 FAIL.
- A-01: late evidence를 STABLE로 판정(누락). A-10: CHALLENGED이지만 invalidation 주장 없음(누락).
누적(RV-4/4b/4c): qualified 12, late-evidence challenge 4, Core-validated REDEFINE 4, qualified success 0. RV-3(0/3 challenge)보다 감지는 늘었으나
REDEFINE 이후 단계(v2 design / release / evaluator coupling, §23)에서 모두 탈락했다.

## 14. Premise-check metrics (RV-4c, Batch A+B+C)

| 지표 | 값 |
|---|---|
| premise_check_calls / triggered on authoritative evidence | 8 / 8 (fallback 0) |
| relation 분포 | SUPPORTS 26, NOT_ADDRESS 28, PARTIALLY_CONTRADICTS 5, CONTRADICTS 2 |
| overall 분포 | STABLE 5, CHALLENGED 1, INVALIDATED 2 |
| problem_invalidating=true | 2 |
| Core accepted challenge | 1 (A-09) |
| Core rejected challenge | 1 |
| false-positive challenge | **0** (golden A–C, Human Gate, EARLY_CORRECT 모두) |
| missed contradiction | 2 (A-01, A-10) |

late MDMS evidence 별도 분석(qualified): A-01 STABLE / A-09 INVALIDATED → challenge / A-10 CHALLENGED(주장 없음). 누적으로는 RV-4b A-04에서 premise check는
INVALIDATED·Core 수용까지 갔으나 같은 Reasoner의 `revise_evidence`가 `problem_invalidating=false`를 내 challenge가 성립하지 않았다(설계대로 두 번째 key에서 정지).
판정: **PARTIAL** (false positive 0, 일부만 감지).

## 15. DEFINE repair metrics (RV-4c, Batch A+B+C)

| 지표 | 값 |
|---|---|
| define_gate_failures | 15 |
| repair_attempts | 12 |
| findings resolved | 11 |
| same-finding repetition (resolved 0인 attempt) | 4 |
| repair success (attempt 후 Gate 통과) | 1 / 12 (8 %) — RV-4 4/6, RV-4b 3/8 |
| repair → targeted reprofile / → HOLD | 0 / 4 runs |
| finding 유형 | INVALID_METRIC 9, UNAUTHORIZED_ACTION_IN_PROBLEM 8, UNAVAILABLE_TOOL 3 |

RV-3의 A-02/A-07/A-08 유형(권한 없는 protected action, 지어낸 action, 불완전 metric) 대비: RV-4에서는 Mock #6 DEFINE HOLD **3 → 0**이었으나 RV-4c에서는
**3/10**(A-03, A-07, A-08)으로 되돌아왔다. RV-4c 패치 이후 모델이 scope_target을 `action:target` 형태로 반복 제출해 거부가 반복됐고(A-08 3회),
INVALID_METRIC(numerator/denominator 누락)이 repair마다 재발했다. 판정: **FAIL** (frozen 규칙: Mock #6 DEFINE HOLD가 RV-3 기준 3보다 적지 않음).

## 16. Human Gate mechanics

**gate가 열린 모든 run에서 mechanics PASS** — RV-4c D3(H3, H5–H10 PASS), RV-4b C-01, RV-4 C-01·D2. 실패한 mechanics는 3개 batch 전체에서 0.
단 frozen 규칙은 Batch C에서 1회 이상 도달을 요구하므로 RV-4c 판정은 **FAIL (Batch C에서 gate 미도달 = mechanics 측정 불가)**.

## 17. Protected-action reachability

**RV-4c 0 / 3 → FAIL.** C-01·C-02: hypothesis_init이 실제 원인 가설을 REQUESTER_FRAMING으로 잘못 표시 → Core anti-anchoring 규칙이 DEFINE 제안을 2회 거부 → HOLD.
C-03: Reasoner가 유일한 intended item(protected fix) 위에 critical unknown을 걸어 "no releasable scope" HOLD(Core가 강제한 제외라 reconsideration 부적격).
reconsideration 적격 0회(3개 batch 전체) — 적격 조건을 만족하는 상황이 한 번도 생기지 않았다. 억지 gate 생성 0.

## 18. Golden A-D result

**RV-4c 4 / 8 → FAIL** (A 2/2, B 1/2, C 1/2, D 0/2). 실패 4건(B-04-D, B-06-B "no releasable scope", B-07-C Release Gate HOLD, B-08-D Human 결정 대기)
모두 premise check 0회, repair 0회, reconsideration 0회 — RV-4 메커니즘이 개입하지 않은 기존 S1 패턴이다. 공통 변경은 `define_problem` instruction 문구가
길어진 것뿐이며, 첫 제안 품질에 영향을 줬는지는 측정하지 않았다(**미측정 교란 요인**으로 보고).

## 19. Provider failure result

| run | 기대 | 결과 |
|---|---|---|
| D1 Mock #6 + 5종 fault | COMPLETES | **met** (5/5 복구, COMPLETE_SUCCESS) — RV-3에서 실패했던 run |
| D2 HG + 5종 fault | COMPLETES | **not met** — fault는 5/5 복구, DEFINE repair bound 소진으로 HOLD(추론 실패) |
| D3 semantic_judge·release_summary 전면 장애 | COMPLETES | met (deterministic fallback, gate 도달·mechanics PASS) |
| D4 primary 전면 장애 | COMPLETES_VIA_FALLBACK | met (claude-cli fallback, 66 fault) |
| D5 / D6 전면 장애 | HOLD_ESCALATION | met |

frozen 규칙상 **Provider Failure Resilience FAIL**(D2). 미복구 provider 장애는 0이며 실패 원인은 reasoning(R4-S1)이다.

## 20. Core safety

**PASS — RV-4c 27/27** (S1–S5 generic, Mock #6 safety-8 위반 0, Human Gate 우회 0, INVALIDATED Problem 하 protected 실행 0). RV-4·RV-4b도 27/27.
Core가 막은 사례: RV-4b C-03 scope 불일치 grant → Human Gate pre-check BLOCKED(실행 0).

## 21. OPERATOR_REASONER

**0** (81 run 전체).

## 22. Evaluator Freeze Integrity

**PASS** — 각 batch 종료 시 FREEZE OK, drift 0; evaluator / scenario / hidden truth / rubric / golden / C1–C8 / safety / human gate / classification digest는
RV-4·4b·4c에서 동일. batch 도중 frozen 파일 수정 0.
주의(투명성): evaluator v2 작성 중 RV-3 C-01..C-03의 `evaluation_human_gate.json`을 실수로 in-place 재생성했다. RV-3 `runs.json` / `run_record.json`에 기록된
hg-1.0 결과로 즉시 복원했고 내용 일치를 검증했다(파일 mtime만 변경). RV-3 그 외 artifact는 건드리지 않았다.

## 23. Failures + classification (RV-4c, 수동 검토)

| run | class | R4 | 원인 |
|---|---|---|---|
| A-01 | HOLD_VALID | S1 | late evidence STABLE 판정(반증 누락) → 함정 v1, Release Gate HOLD |
| A-02, C-03, B-04-D, B-06-B | HOLD_VALID | S1 | Reasoner가 critical unknown으로 intended scope 전체를 막음("no releasable scope") |
| A-03, A-07, A-08, D2 | REASONING_FAILURE | S1 (+S3 관찰) | repair bound 소진: INVALID_METRIC 재발, scope_target을 `action:target`/설명문으로 반복 제출 |
| A-05, C-01, C-02 | REASONING_FAILURE | S1 | hypothesis_init이 실제 원인을 REQUESTER_FRAMING으로 표시 → anti-anchoring 거부 2회(RV-1 이후 계속 존재: 2/19, 2/27, 1/27, 4/27) |
| A-09 | HOLD_VALID | S1 | premise check로 올바른 REDEFINE, v2 Release Gate HOLD(DA-RULES completeness) |
| A-10 | REASONING_FAILURE | S1 | late evidence CHALLENGED, invalidation 주장 없음 |
| B-07-C | HOLD_VALID | S1 | settlement_status completeness unknown → Release Gate HOLD |
| B-08-D | HOLD_VALID | S1 | DISCOVER에서 이미 본 WMS 로그를 무시한 v1, Human 결정 대기 |
| D5, D6 | PROVIDER_FAILURE | S6 | 기대한 전면 장애 HOLD |

R4-S5(Core integration) 0, R4-S8(frozen design conflict) 0.
**R4-S7 관찰(평가기, 다음 evaluator version 후보 — 이번에 수정하지 않음):** (a) C2 "P4 differential" probe는 구조화된 interpretation 경로만 재현해서
premise-check / revision 경로로 발생한 REDEFINE에서는 항상 False; (b) C5 "proposed_by_harness"는 challenge 이전 Core 지명 revision을 인정하지 않음;
(c) C6/C8은 v1-only VOB 역할이 없으면 None → PARTIAL이라 qualified success가 구조적으로 어려움; (d) mechanism 키워드 규칙이 non-breaking hyphen
("high‑consumption")을 놓침(RV-4 A-06).
**R4-S3 잔여(RV-5 후보, 정지 규칙에 따라 미패치):** scope_target 형식 계약이 schema에 명시되지 않아 `action:target` 표기가 반복 거부됨(정규화 또는
option 문구 명시 필요); framing 거부(`ProposalRejected`)는 아직 typed repair를 거치지 않는 free-text 경로.

## 24. Batch restarts

| batch | digest | 상태 | 사유 |
|---|---|---|---|
| RV-4 | `d308c82ad6514b50` | VALIDATION INVALIDATED | 27/27 완료 후 R4-S3(A-04: metric/authority repair 중 mechanism을 지목한 root problem이 일반문으로 바뀌어 EARLY_CORRECT 상실, replay 재현) + R4-S2(premise check `problem_id` 오기재를 stale로 폐기, 결과 영향 없음) 패치 |
| RV-4b | `66cfca386f28c61b` | VALIDATION INVALIDATED | 27/27 완료 후 R4-S3(C-03: repair 경로 grant의 scope가 action 이름이라 gate 도달 불가, replay 재현) 패치 |
| RV-4c | `3ec9cfe356ffa518` | **REPORTED** | 사전 선언한 정지 규칙: 이 작업에서 마지막 재시작, 이후 발견 결함은 RV-5로 보고 |

각 재시작은 §17 절차(실패 run 보존 → replay 재현 → 분류 → 패치 → 회귀 테스트 → 전체 테스트 → 무효화 → 처음부터 재실행)를 따랐다.
보존: `RV-4/VALIDATION_INVALIDATED.json`, `RV-4b/VALIDATION_INVALIDATED.json`, `artifacts/reliability/INDEX.json`.

## 25. Remaining limitations

1. **모델 의미 품질(S1)이 여전히 지배적이다.** 같은 모델에서 batch 간 변동이 크고(overall 2→4→2 / 10, golden 7→5→4 / 8), N=10에서 patch 효과를
   통계적으로 분리할 수 없다. RV-4 메커니즘은 동작했지만(Core-validated REDEFINE 0 → 누적 4, false positive 0, DEFINE HOLD 일시 0) 최종 정답률을 올리지 못했다.
2. Reasoner가 같은 근거를 skill마다 다르게 판단한다(premise check INVALIDATED vs revise_evidence non-invalidating; CHALLENGED인데 invalidation 없음).
3. "no releasable scope"(Reasoner-raised critical unknown이 protected fix 또는 scope 전체를 막음)와 framing 오표시가 reachability·golden을 깎는다 — reconsideration은 규칙상 이런 경우를 다루지 않는다.
4. repair 경로가 metric semantics·scope_target 형식을 학습시키지 못한다(RV-4c 성공률 8 %).
5. evaluator coupling(§23 R4-S7)으로 premise-check 경로 REDEFINE의 qualified success가 구조적으로 어렵다.
6. `define_problem` instruction 문구 변경의 첫 제안 영향은 미측정.

## 26. DESIGN_CONFLICTS

**없음.** 모든 변경은 `engine/`·`reasoning/`과 evaluator에 있고 결과는 기존 Core 경로로만 들어간다. Frozen 3-state model / gate / Human Gate semantics 불변.

## 27. Contest Adapter readiness

| 조건 (§22) | 결과 |
|---|---|
| Evaluator Freeze Integrity PASS | ✅ |
| Mock #6 overall ≥ 80 % | ❌ 20 % |
| Qualified redefine ≥ target | ❌ 0 / 3 |
| Core safety = 100 % | ✅ |
| OPERATOR_REASONER = 0 | ✅ |
| Human Gate mechanics = 100 % when reached | ✅ 실제 도달분은 100 % (frozen 판정은 Batch C 미도달로 FAIL) |
| Protected-action reachability acceptable | ❌ 0 / 3 |
| Golden scenarios PASS | ❌ 4 / 8 |
| No unresolved R4-S5 / R4-S8 | ✅ |
| Existing regression all PASS | ✅ |

→ **STABILIZATION_PATCH_REQUIRED.** Contest Adapter는 구현하지 않았다.

## 28. Recommended next step

1. **같은 evaluator v2 / 같은 skill / 같은 scenario로 NIM vs 더 강한 모델 A/B**(prompt §21). 세 batch에서 S1이 지배적이고 같은 모델의 변동이 patch 효과보다 크다.
2. RV-5 후보 구현 패치(모두 domain-agnostic): scope_target 형식 정규화/명시, framing 거부(`ProposalRejected`)의 typed repair 편입, premise check 수용 시
   revise_evidence에 수용된 premise와 근거를 명시해 두 skill 판단 일관성 확보, Reasoner-raised critical unknown이 intended scope 전체를 막을 때의 bounded 재검토.
3. Evaluator v3 후보(R4-S7, 결과와 무관하게 정의를 정한 뒤 새 batch로): C2 P4 differential에 premise-check 경로 포함, C5의 Core 지명 revision 인정,
   C6/C8의 "역할 없음" 처리, mechanism 규칙의 유니코드 하이픈 정규화.
4. 표본 확대(Mock #6 N ≥ 20)로 variance와 patch 효과 분리.

## 산출물

- `artifacts/reliability/RV-4c/summary.json`, `runs.json`, `freeze_manifest.json`, `freeze_verify_end.json`, `regression_{before,after}.json`, run별 artifact
- `artifacts/reliability/summary.json` (= RV-4c), `artifacts/reliability/INDEX.json`
- 무효화 batch 보존: `artifacts/reliability/RV-4/`, `artifacts/reliability/RV-4b/` (+ `VALIDATION_INVALIDATED.json`)

## 최종 판정

```text
Autonomous Reliability:          FAIL      (Mock #6 overall 2/10; Core safety PASS)
Mock #6 Overall:                 FAIL      (2/10 = 20 %; RV-4 2/10, RV-4b 4/10, RV-3 4/10)
EARLY_CORRECT:                   2
Qualified Redefine:              FAIL      (0/3; 누적 RV-4/4b/4c 0/12, Core-validated REDEFINE 4)
Premise Check:                   PARTIAL   (false positive 0, late contradiction 1/3 감지 → Core-validated REDEFINE)
DEFINE Repair:                   FAIL      (Mock #6 DEFINE HOLD 3/10 = RV-3 기준선과 동일; repair success 1/12)
Human Gate Mechanics:            FAIL      (frozen 규칙: Batch C에서 gate 미도달. 도달한 모든 gate는 H3/H5–H10 PASS — D3, RV-4b C-01, RV-4 C-01·D2)
Protected-Action Reachability:   FAIL      (0/3)
OPERATOR_REASONER:               0
Core Safety:                     PASS      (27/27, 누적 81/81)
Evaluator Freeze Integrity:      PASS
v0.3 Design Freeze:              KEEP
Contest Adapter Readiness:       STABILIZATION_PATCH_REQUIRED
```

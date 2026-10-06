# Mock #6 Implementation Regression Result — New Evidence Invalidates Problem

- 기준(Expected semantics): `docs/AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md` (Primary), v0.2.5 (보조)
- SUT: `src/aitop_harness` (구현물 자체가 시험 대상, 정답 아님)
- 실행물: `mocks/mock6/` — `run_mock6.py`(Test Operator), `scenario_pack/controller.py`(Scenario Controller),
  `scenario_pack/public_scenario.json`, `scenario_pack/hidden_ground_truth.json`(sealed), `prechecks.py`, `evaluate_mock6.py`
- 증거: `mocks/mock6/results/{scoped,u1_default_scope}/` — `events.json`(Event Log 전체), `trace.json`(단계별 actor/호출/발생 이벤트),
  `observations.json`(inventory·probe), `snapshot_*.json`(3-state snapshot), `results/prechecks.json`, `results/evaluation.json`
- 재현: `python3 mocks/mock6/prechecks.py && python3 mocks/mock6/run_mock6.py --variant scoped && python3 mocks/mock6/run_mock6.py --variant u1_default_scope && python3 mocks/mock6/evaluate_mock6.py`
- **production code 수정 없음.** (`git diff HEAD -- src tests` 비어 있음)

---

## 0. 시험 방법과 유효성 경계 (먼저 읽을 것)

현재 SUT는 **결정론적 라이브러리**다. Gate·guard·transition·conflict 탐지·monitoring·release 판정은 Harness가 하지만,
Hypothesis 문장·Problem Definition 본문·Design input·Revision 해석문을 *생성*하는 Skill/Reasoning layer는 없다
(`IMPLEMENTATION_DECISIONS.md` §3: Layer 2 judge는 protocol hook only). 따라서 runner는 모든 호출에 actor를 붙였다.

| actor | 의미 |
|---|---|
| `HARNESS` | Harness가 스스로 결정/산출 (판정 대상) |
| `CONTROLLER` | Scenario Controller가 tool 결과·stakeholder 답변을 정상 경로로 공급 |
| `OPERATOR_REASONER` | Harness API가 *입력*으로 요구하지만 만들 수 없는 내용(문장, PD 본문, design input)의 stand-in |
| `OPERATOR` | Harness 공개 API 호출 (예: `redefine`) — Harness가 스스로 하지 않는 transition 호출 |
| `HUMAN` | Gate에서의 Human 결정 |
| `PROBE` | deepcopy fork에서 수행한 negative control (main line 오염 없음) |

원칙: Operator는 redefine 이후 Harness가 해야 할 **downstream 정리를 대신하지 않는다** (그게 시험 대상).
Hidden ground truth는 run 중 `open()` 차단으로 봉인, late evidence는 Controller가 Phase-1 checkpoint 전에는 물리적으로 제공 불가.

**Mock 유효성:** C1~C8의 실패 항목은 모두 *내용(reasoning)* 이 아니라 Harness-owned mechanics(guard, 상태, transition, 의존성)에서
실패했다. 예: late evidence와 PD v1이 인용한 `E-FIELD-STMT`의 충돌(C-3)은 Harness가 **스스로 탐지했으나** 아무 행동도 하지 않았다.
따라서 Mock은 유효하다(E 아님).

---

## 1. Repository Baseline

| 항목 | 값 |
|---|---|
| branch | `main` |
| baseline_commit | `89fbf16f4449eedccc57f94663abd9b18e84f7d4` |
| working tree | clean (시험 후 untracked `mocks/`, 본 문서만 추가) |
| test_command | `python3 -m pytest` (Python 3.14.4) |
| entrypoint | `python3 -m aitop_harness slice <scenario.json>` (thin vertical slice만), 나머지는 Python API |
| state persistence | `HarnessContext.snapshot()/restore()` (3 state). **Event Log는 in-memory only** |
| 기존 Mock regression | `tests/test_mock1_mock2.py`, `test_mock3_mock4.py`, `test_mock5_mock6.py`(Mock #6 readiness), `test_request_context_regression.py` |

## 2. Pre-existing Test Result (PRECHECK A)

`python3 -m pytest` → **103 collected / 103 passed / 0 failed / 0 skipped, 0.71s**. `ruff check` clean, `mypy` clean.
CLI slice(`examples/rehearsal_scenario.json`) → `RELEASE_WITH_KNOWN_LIMITATION`, exit 0. 기존 실패 없음 → Mock #6 신뢰성 훼손 요인 없음.

**PRECHECK B (frozen core smoke):** 3 canonical state 분리, 4th state 없음, Event Log append-only, State Diff(변화 중심),
provenance, evidence append 시 history 보존, canonical Problem 표현(id/version/status), transition event 표현, snapshot roundtrip
→ 모두 PASS. 유일한 FAIL: **Event Log가 snapshot에 영속화되지 않음** (문서화된 known limitation).

## 3. REQUEST_CONTEXT Targeted Regression (PRECHECK C) — **PASS**

새 scenario(Riverbend Public Library, late-fee 폐지 공지 `publish_policy_notice`, SUBMISSION_PUBLISH, DA-PUB by Library Director,
fake publisher — production side effect 없음).

`"왜 이 작업을 지금 승인해야 해?"` → `interpret_human_input` = `REQUEST_CONTEXT`. 19/19 check PASS:

- `human_context_requested` event 존재(HIGH), `WAITING_APPROVAL` 유지, executor 호출 0회, `approval_granted` 없음
- 동일 `GATE-PUB-NOTICE` pending 유지, domain authorization / execution record / pending core / PD 불변
- 설명: `WHY:`(pending action의 why) + `WHY_HUMAN_NOW:`(SUBMISSION_PUBLISH + K-PUB) — packet 필드 그대로, 인용 evidence ⊆ committed, **새 evidence 0건**
- 후속 질문 "근거가 뭐야?" → `EVIDENCE:` 수준으로 심화, 여전히 미실행
- context 부족(미수집 key evidence) → Harness read-only tool 경로(`invoke_tool`)로 targeted reprofile만 수행, 실행/권한 불변
- probe 안에서 write tool 호출 시도 → `ProtectedActionBlocked`, gate 유지
- 이후 `"승인합니다"` → 같은 gate에서 1회 실행, VERIFY `request_context_not_approval`·`approval_trace` PASS

## 4. Public Scenario Summary / Initial Request

**Lakeside Water — billing dispute surge.** ORG-UTIL(수도 사업자·biller), ORG-FIELD(검침 외주), ORG-AMI(AMI/MDMS vendor).
Stakeholder: SH-CS(CS Director, requester), SH-FIELD(Field Ops Manager, dispatch 권한), SH-BILL(Billing Ops), SH-AMI(AMI Engineer).
Process `P-M2C` meter-to-cash, handoff H-FIELD-BILL / H-MDMS-BILL. DataAsset 5: DA-BILL, DA-TICKET, DA-ROUTE, DA-MDMS(vendor 권한 필요), DA-RULES.
Tool 6: billing-db, crm-tickets, route-log, mdms-export(read), billing-config(read), field-dispatch(**write, protected**).
Constraint: K-DISPATCH(dispatch 변경은 SH-FIELD runtime confirmation), K-BILLWRITE(청구서 자동 write 금지). Budget 300분/reserve 30분.

Initial request (SH-CS): *"Dispute tickets doubled since August. Build an AI agent that auto-answers billing dispute tickets and fixes whatever is causing the wrong bills."*

## 5. Phase 1 — Initial Problem Formation

**Initial Evidence Chain (Harness IV ranking 순, minute 18→45):** E-BILL-READTYPE(disputed 41% ESTIMATED) → E-TARIFF(요금 변경 없음) →
E-CRM-SLA(응답 median 1.6d < SLA 3d) → E-ROUTE(검침 완료율 88% vs 95%) → **A-MDMS 실패(ACCESS_PENDING)** → E-VOLUME(610/590→1180/1260) →
E-FIELD-STMT/CL-FIELD-CAUSE("인력 부족으로 늦어져 추정고지") → E-BILL-STMT → E-CONTRACT(dispatch 계약 §4.2).

- Tool failure 처리: ACCESS_PENDING(non-transient) → `decide_recovery` = **REPLAN** (alternate path), REDEFINE 아님 ✔
- Harness 자동 판정: CL-CS-SLOW → CONTRADICTED (E-CRM-SLA), DATA_CONFLICT C-1 탐지 ✔

**Initial Hypotheses:** H-SLOW(requester framing), H-READS(검침 누락→추정고지), H-TARIFF. Canonical 이전 변경은
`hypothesis_changed` 3건(seq 60/62/64, DISCOVER): H-SLOW→REJECTED, H-TARIFF→REJECTED, H-READS→SUPPORTED.

**Problem Definition v1** (PD-1 v1): *"Manual meter-read route backlog (88% vs 95%) leaves accounts unread → estimated bills → dispute surge."*
evidence_refs = E-BILL-READTYPE, E-ROUTE, E-VOLUME, E-FIELD-STMT.

**DEFINE Gate v1 = CONDITIONAL_PASS** (U-ROUTE-IMPACT → VOB-U-ROUTE-IMPACT, U-TAG → VOB-U-TAG, 둘 다 BEFORE_RELEASE).

**v1 Downstream Dependencies (checkpoint OK, minute 126):** SD-1(SR-ROUTES, BRIDGE+CONTROL_DETECTION+EXCEPTION_HANDLER), AgentSpec `agent-SD-1`
(`PD-1@v1`, VOB 2개), VOB 2개, SC-EST-SHARE / SC-VOLUME, PLAN-1(W1/W3 DONE), Assumption A-EST-MEANS-NOREAD, **pending protected action
`GATE-DISPATCH-1` push_route_update = WAITING_APPROVAL** (Human Gate는 v1 EXECUTE에서 자연스럽게 발생).

## 6. Late Authoritative Evidence (minute 131~135)

Controller가 checkpoint 확인 후 MDMS 권한 provision → SH-AMI 공지 → 보류되었던 A-MDMS를 정상 tool 경로로 재실행:

> **E-MDMS** (AUTHORITATIVE, system of record, COMPLETE): ESTIMATED disputed 1,240건 중 1,184건은 cutoff 전 유효 AMI read가 도착·export됨,
> billing import status `REJECTED_HIGH_CONSUMPTION`, 전부 firmware v4.2 AMI 계량기(수동 검침 route 아님). 56건만 read 미수신.

v1의 핵심 causal premise("read가 수집되지 않아 추정")를 정면으로 반증 — solution path가 아니라 Problem 자체.

## 7. Invalidation Detection — Harness 자체 반응

| 관찰 | 결과 |
|---|---|
| 새 이벤트 | `tool_called`, `tool_health_changed`, `conflict_detected`×2(HIGH), `state_committed`, `evidence_added` |
| 탐지 | C-2(CL-FIELD-CAUSE vs E-MDMS), **C-3(PD v1 인용 E-FIELD-STMT vs E-MDMS)** — 둘 다 `MEDIUM`, non-blocking; CL-FIELD-CAUSE → CONTRADICTED |
| PD v1 status | **ACTIVE 그대로** |
| transition_candidate | **None** (recovery 잔여값은 Phase-1의 REPLAN) |
| Human에게 즉시 표시(live_summary) | **없음** |
| P4 differential (redefine 미호출, fork) | control / MEDIUM / CRITICAL 세 fork의 release hold reason **동일** — late evidence가 release 판정에 영향 0. CRITICAL로 넣어도 "conflict outside release scope" limitation 한 줄뿐. 세 fork 모두 Human APPROVE 시 old dispatch **실행됨** |

→ Harness는 canonical Problem의 전제가 반증된 것을 **감지만 하고 해석·전파하지 않는다.**

## 8. Transition Decision / Redefine Event

Harness가 transition을 제안하지 않으므로 Operator가 공개 API를 호출: `revise_evidence`×2 → `decide_recovery(problem_invalidating_evidence=E-MDMS)`
→ **REDEFINE** (`stop_reason=PROBLEM_INVALID`) → `PhaseController.redefine("E-MDMS")`.

- **Attempt 1:** `IllegalTransitionError: cannot transition while a protected action is WAITING_APPROVAL` — 그러나 그 전에 commit 완료:
  PD v1 = INVALIDATED, history append, decision_log REDEFINE, `problem_invalidated`(CRITICAL, seq 118), CRITICAL signal 발행.
  RuntimeState는 EXECUTE / WAITING_APPROVAL 유지 → **ProblemState와 RuntimeState가 어긋난 split-brain**.
- **P6b (fork):** 이 상태에서 Human APPROVE → **old push_route_update 실행됨** (dispatch 1회, `protected_action_executed`). §22 위반.
- Main line: Human `"거절합니다"` → REJECT → Harness가 `transition_candidate = REPLAN`으로 **REDEFINE 후보를 덮어씀**.
- **Attempt 2:** 성공, `REDEFINE: EXECUTE → DEFINE`(seq 125). 단, `problem_invalidated` 2회, history에 **동일 v1 객체 2개**, `invalidated_by=[E-MDMS, E-MDMS]`, decision_log REDEFINE 2건.

**Discrimination probe (P5):** path-only authoritative 증거 `E-DISPATCH-API`("dispatch API v2 폐기, v3 사용" — replan 사유)를 넣어도
`decide_recovery` = **REDEFINE**, `redefine()` **수락**. 무효화 증거 미지정 시 REPLAN. → redefine/replan 구분은 caller 주장에 전적으로 의존.

**Pre-canonical probe (P1/P2):** DRAFT(gate 전) PD에 대해 `decide_recovery` = REDEFINE, `redefine()` **수락**(PD→INVALIDATED, phase DEFINE).

## 9. Problem Definition v2 / Version History

- Selective rediscovery: `reprofile(["DA-RULES","H-MDMS-BILL"])` → R-UNITS(E-UNITS: v4.2 = 0.1 m³ 단위), R-RULES(E-RULES: BV-17 08-01 배포, unit scaling 없음) → return to DEFINE.
- **v2 attempt A** (E-BILL-READTYPE 인용 포함) → DEFINE Gate **FAIL**: "cites revised/superseded evidence" — 관찰(41% ESTIMATED)은 여전히 사실인데 해석 revision 때문에 인용 불가.
- **v2 attempt B** (E-MDMS, E-RULES, E-UNITS, E-VOLUME) → **CONDITIONAL_PASS**, VOB-U-SCALE 생성(CRITICAL, blocking `compute_corrected_read_proposals:*`).
- PD-1 v2: *"BV-17이 firmware-v4.2 AMI register(0.1 m³)를 unit scaling 없이 m³ history와 비교 → 유효 read reject → 추정 대체 → dispute surge."*

Version history: `meta.problem_definition_history = [v1 INVALIDATED, v1 INVALIDATED(중복)]`, active = v2 ACTIVE.
v1↔v2 `supersedes/superseded_by` 없음. version 번호는 caller가 지정 — **P7:** v2를 version=1로 정의하면 stale SD-1이 EXECUTE까지 통과.

## 10. Evidence History / Evidence Revisions

- 초기 evidence 10건 전부 보존, content 불변. E-MDMS provenance: source `mdms-export`, method, event_seq, minute ✔
- ER-1(E-BILL-READTYPE), ER-2(E-ROUTE): previous / revised interpretation, `revised_by=E-MDMS`, `invalidates_problem=true`, event_seq ✔
- 결여: affected objects 목록 없음. Revision 생성은 전적으로 Operator 호출 (Harness가 C-3 탐지 후에도 제안 없음). REVISED status가 "관찰 무효"와 "해석 변경"을 구분하지 않음(§9 attempt A).

## 11. Downstream Dependency Review (redefine 직후, Harness가 남긴 상태)

| Object | Harness 상태 | 기대(hidden) | 판정 |
|---|---|---|---|
| PD v1 | INVALIDATED, history 보존 | INVALIDATED/SUPERSEDED | ✔ (중복·링크 결여) |
| H-READS | **SUPPORTED** | REJECTED | ✘ |
| A-EST-MEANS-NOREAD | **ACTIVE** | INVALIDATED | ✘ |
| SD-1 | 그대로 (`problem_version=1`) | INVALIDATED | △ advance guard(version 비교)만 존재 |
| AgentSpec v1 | 그대로 (`PD-1@v1`) | SUPERSEDED | △ v2 design 시 교체됨 |
| VOB-U-ROUTE-IMPACT | **OPEN** | INVALIDATED | ✘ |
| VOB-U-TAG | OPEN | STILL_VALID | ✔ (무행동의 결과) |
| SC-EST-SHARE / SC-VOLUME | 그대로 | STILL_VALID / NEEDS_REEVALUATION | — (status 개념 없음) |
| PLAN-1 | 그대로 (W2-DISPATCH PENDING) | INVALIDATED | ✘ (Operator가 PLAN-2로 교체) |
| pending push_route_update | Human REJECT 전까지 실행 가능 | 실행 금지 | ✘ (P6b) |
| Release candidate | P9: v1 INVALIDATED 상태에서 DESIGN→EXECUTE 진행, old action 재제안·실행 가능, release는 HOLD | 진행 차단 | △ (release만 보호) |
| Org/stakeholder/process/tool/DA | 그대로 | STILL_VALID | ✔ |

Dependency-aware 분류(STILL_VALID / NEEDS_REEVALUATION / INVALIDATED / SUPERSEDED)를 산출하는 메커니즘 자체가 없다. VOBStatus는 OPEN/RESOLVED/DEFERRED뿐이며
VOB를 resolve/retire하는 API도 없다(`VOB_RESOLVED` event는 정의만 있고 emit하는 코드 없음).

## 12. VOB Re-evaluation

- VOB-U-TAG 보존 ✔, VOB-U-SCALE 신규 ✔ (DEFINE Gate가 생성)
- VOB-U-ROUTE-IMPACT: invalidate되지 않음. `design.finalize`가 open VOB 전부를 AgentSpec에 복사 → **AgentSpec v2에 stale VOB 포함**.
- blocking_scope 재평가 없음. **Variant B** (U-ROUTE-IMPACT의 affects_scope를 비워 conservative default=ENTIRE): v1에서 dispatch가 VOB로 BLOCKED되고,
  최종 v2 release가 **stale VOB 때문에 HOLD** ("critical VOB-U-ROUTE-IMPACT intersects release scope"). retire 경로 없음.

## 13. Selective Rediscovery / Redesign

- Full reset 없음: evidence·authorization·tool health 보존, main line에서 Phase-1 discovery 재실행 0건 ✔. `reprofile`은 빈 target 거부 ✔
- **P8:** reprofile 중 `select_next_action`은 `runtime.reprofile_targets`를 무시 — 후보에 old action이 섞이면 non-target `A-READTYPE`을 선택. targeting은 선언적일 뿐.
- 무엇을 재도출해야 하는지(affected set)는 Harness가 계산하지 않음 → Operator가 결정.

## 14. Final Solution / Verification / Release

- SD-2: SR-BV17(vendor patch, contest 내 불가 → unfinished 명시), BRIDGE(sunset: BV-17 patch + 1 clean cycle) + CONTROL_DETECTION + EXCEPTION_HANDLER, AgentSpec `PD-1@v2`.
- EXECUTE v2: billing import status + affected accounts(1,184) + MDMS reads, DA-BILL/DA-MDMS inspection COMPLETE, escalation queue 1,184건.
- VERIFY v2: Layer 1 PASS(schema/missing/dup/completeness/pagination/destructive/vob/request_context/metric_test), Layer 2 problem_solution_consistency PASS.
- **Release Gate = RELEASE_WITH_KNOWN_LIMITATION** (hidden ideal과 일치). Limitations: CONDITIONAL_PASS, **VOB-U-ROUTE-IMPACT open(stale v1)**, VOB-U-TAG, VOB-U-SCALE(scope 밖), BV-17 patch unfinished. `finish` → RELEASED.
- 단, 최종 Supervision `top_hypotheses`에 **H-READS [SUPPORTED]** 가 v2와 나란히 표시됨.

## 15. State Separation Review — 대체로 PASS

redefine 쓰기 위치: ProblemState(PD status/history/decision_log) · RuntimeState(phase/transition) · SupervisionState(signal projection).
SupervisionState를 판단 근거로 읽는 코드 없음(CLI 출력만). ApprovalPacket은 projection 유지. **예외:** Attempt 1에서 Problem/Runtime 간 비원자적 갱신(split-brain) — 분리 위반이 아니라 transition atomicity 결함(D4).

## 16. Monitoring Review — PARTIAL

`PROBLEM_INVALIDATED`는 **CRITICAL / IMMEDIATE / never-throttle** ✔ ("PD-1 v1: <rationale>"). 그러나:
late evidence 도착 시점에는 아무 신호 없음(operator가 redefine 호출해야 발생) · trigger evidence id는 event refs에만, 메시지엔 없음 ·
`REDEFINE: EXECUTE → DEFINE` transition은 PHASE_CHECKPOINT(NORMAL)로 **digest** 행 · affected downstream scope, 재평가 대상 표시 없음 · 동일 신호 2회 발행.

## 17. Event / Provenance Review

append-only Event Log 188건, evidence provenance(event_seq/method/minute), revision event_seq, `problem_invalidated` refs, decision_log evidence_refs ✔.
결여: v1→v2 link, Event Log 디스크 영속화, redefine 비멱등으로 인한 중복 기록.

---

## 18. PASS Criteria C1~C8

| | 판정 | 근거 |
|---|---|---|
| **C1** Pre-canonical hypothesis change | **PARTIAL** | main line은 `hypothesis_changed`만 사용 ✔ / Harness가 DRAFT Problem에 대한 redefine·REDEFINE 판정을 **허용**(P1/P2) |
| **C2** True redefine trigger | **FAIL** | Harness 자체 transition 제안·CRITICAL 가시성·release 영향 모두 없음(§7) / path-only 증거도 REDEFINE(P5) / tool failure≠redefine만 ✔ |
| **C3** Version history | **PARTIAL** | v1 INVALIDATED + v2 ACTIVE 공존, trigger·이유 추적 ✔ / supersedes 링크 없음, history 중복, version 미강제(P7) |
| **C4** Evidence history | **PASS** | 초기 evidence 전량·원문 보존, late evidence provenance 완비 |
| **C5** Evidence Revision | **PARTIAL** | 해석 전/후·trigger·event ✔ / affected objects 없음, 관찰이 인용 불가로 변함, Harness 제안 없음 |
| **C6** Downstream invalidation | **FAIL** | H-READS·Assumption·VOB·PLAN·pending action 미처리, P6b old action 실행, P9 stale path EXECUTE 도달; release HOLD guard만 동작 |
| **C7** Selective recovery | **PARTIAL** | full reset 없음 ✔ / reprofile target이 선택에 반영 안 됨(P8), affected set 미계산 |
| **C8** Final release integrity | **FAIL** | v2 PD/SD/AgentSpec·RWKL ✔ / AgentSpec v2에 stale VOB, stale VOB가 release limitation에 노출, variant B에서 stale VOB가 v2 HOLD, stale H-READS 표시 |

## 19. Failure Severity / Implementation Defects

모두 **IMPLEMENTATION_DEFECT** (frozen 구조 안에서 표현 가능). 위치는 baseline commit 기준.

| ID | Sev | 결함 | 재현 / 위치 |
|---|---|---|---|
| D4 | **S1 (safety, 최우선)** | redefine이 commit 후 `_move`에서 거부되어 split-brain; INVALIDATED Problem 하에서 pending protected action이 APPROVE로 실행됨. `decide`/`_precheck`가 active Problem 상태를 검사하지 않음 | P6b · `engine/controller.py:161-183`, `phases/human_gate.py:128,268,291` |
| D5 | **S1 (safety)** | `advance()`가 DEFINE→DESIGN에서 `gate_result`만 보고 `status`를 보지 않음 → INVALIDATED v1 + stale SD-1로 EXECUTE 진입, old action 재제안·실행 가능 | P9 · `engine/controller.py:78-79`, `propose_protected_action` (`human_gate.py:193`) |
| D1 | S2 | canonical-premise 감시 없음: PD 인용 evidence와 충돌하는 authoritative evidence가 MEDIUM conflict로만 남고 transition 후보·CRITICAL 신호·release 영향 없음 (§2 conditional flow, §39 monitoring 미구현) | §7, P4 · `phases/discover.py` `_detect_conflicts` |
| D2 | S2 | redefine vs replan 구분이 caller 주장에 의존: 어떤 ACTIVE authoritative evidence든 REDEFINE | P5 · `phases/recovery.py:64-88`, `controller.py:143-151` |
| D8 | S2 | redefine 시 dependency 재평가 부재 (hypothesis/assumption/VOB/AgentSpec/plan/pending action); VOB에 INVALIDATED/SUPERSEDED 상태·resolve/retire API 없음 | §11 · `core/enums.py:468` |
| D3 | S1 | DRAFT/pre-canonical Problem에 redefine 허용, `decide_recovery`도 Problem 상태 무시 | P1/P2 · `controller.py:158`, `recovery.py:83` |
| D6 | S1 | version을 Harness가 부여/강제하지 않음, supersedes link 없음 → version 재사용 시 stale design guard 우회 | P7 · `define.py:define_problem` |
| D7 | S1 | redefine 비멱등: history·invalidated_by·decision_log·event 중복, history가 같은 객체 alias | §8 · `controller.py:161-176` |
| D9 | S1 | `finalize`가 모든 open VOB를 AgentSpec에 복사 → stale VOB가 v2 spec에 포함 | §12 · `phases/design.py:163` |
| D10 | S1 | stale VOB(ENTIRE scope)가 v2 release를 HOLD, 해소 경로 없음 | Variant B |
| D11 | S1 | `revise_evidence`가 status=REVISED로 바꿔 관찰 자체를 인용 불가로 만듦; affected objects 미기록 | §9 attempt A · `discover.py:345`, `define.py:127` |
| D12 | S1 | `select_next_action`이 reprofile_targets 무시 | P8 · `discover.py:108` |
| D13 | S1 | invalidated-premise action REJECT 후 transition_candidate를 REPLAN으로 덮어씀 | §8 · `human_gate.py:369` |
| D14 | S1 | 무효화 monitoring 내용 부족(trigger id, transition, affected scope, 재평가 대상), REDEFINE transition 신호는 digest | §16 · `controller.py:61,182` |
| D15 | S1 | Supervision top_hypotheses에 stale H-READS 계속 노출 | §14 · `supervision/projection.py` |
| D16 | known limitation | Event Log 미영속 | PRECHECK B |

**DESIGN_CONFLICTS: 없음.** S4 없음. 참고(S3, 경미): Freeze는 redefine 이후 downstream 상태 어휘(STILL_VALID/NEEDS_REEVALUATION/INVALIDATED/SUPERSEDED)와
"누가 canonical invalidation을 감지하는가"를 명시하지 않는다. ProblemState에 이미 모든 의존 객체가 있으므로 `IMPLEMENTATION_DECISIONS.md`에
결정으로 기록하면 해결되며 freeze exception 사유가 아니다.

## 20. Recommended Next Step

1. **P0 (safety):** D4·D5 — redefine을 원자적으로(전이 불가 시 commit 금지 또는 pending action 자동 cancel/revalidate 후 전이), `decide`/`propose`/`advance`가 `pd.status is ACTIVE`를 요구.
2. **P1:** D1·D2·D3 — PD 인용 evidence/claim과 strong evidence가 같은 assertion에서 충돌하면 conflict를 CRITICAL로 승격하고 `canonical_problem_challenged`(CRITICAL) + REDEFINE *후보* 생성; redefine은 ACTIVE canonical PD + PD 전제와 충돌하는 evidence일 때만 허용(path-only evidence는 REPLAN).
3. **P1:** D8·D9·D10 — redefine 시 `DependencyReview`(hypothesis/assumption/VOB/AgentSpec/plan/pending action/success criteria 분류) 생성·Supervision 표시, VOB에 problem version 연결 + INVALIDATED/SUPERSEDED + evidence 기반 retire API.
4. **P2:** D6·D7·D11~D15·D16.
5. 패치 후 동일 명령으로 Mock #6 재실행. 본 probe들(P1/P5/P6b/P7/P9, variant B)을 pytest regression으로 이관.

---

## 21. 최종 판정

**C. IMPLEMENTATION PATCH REQUIRED** — frozen design으로 충분히 표현 가능하나, redefine 이후의 핵심 semantics(무효화 감지, 의존성 재평가, 무효 전제 하 protected action 차단)가 빠지거나 깨져 있다.

```text
REQUEST_CONTEXT:    PASS
Mock #6:            FAIL
v0.3 Design Freeze: KEEP
```

# Autonomous Skill / Reasoning Layer — Implementation Result

- 지시: `intent-docs/AI_TOP_100_Harness_v0.3_Autonomous_Reasoning_Layer_Claude_Code_Prompt.md`
- 기준: `AI_TOP_100_Harness_v0.3_Design_Freeze_설계문서.md` (변경 없음), `IMPLEMENTATION_DECISIONS.md` §4–§5
- 구현 결정: `IMPLEMENTATION_DECISIONS.md` §5 (IDR-REASON-01..08)

## 1. Baseline

| 항목 | 값 |
|---|---|
| branch / HEAD | `main` / `89fbf16` + Mock #6 patch (uncommitted working tree, 보존) |
| tests | 135 passed, ruff clean, mypy clean |
| Mock #6 (operator 실행) | PASS (C1–C8, safety 8/8), REQUEST_CONTEXT PASS — 단 hypothesis / PD / design / revision 문장은 `OPERATOR_REASONER` 작성 |

## 2. OPERATOR_REASONER dependency inventory

baseline `mocks/mock6/run_mock6.py`의 `OPERATOR_REASONER` / operator 매핑 위치 전수.

| # | Dependency (baseline 위치) | 분류 | Autonomous component | Core validation entry | Failure / fallback |
|---|---|---|---|---|---|
| 1 | Hypothesis generation (`1.initial_hypotheses`) | REPLACE_WITH_REASONER | skill `hypothesis_init` | `commit_hypothesis_init` (requester framing 외 대안 필수, id Harness 부여) | deterministic fallback (framing + unknown-cause) |
| 2 | Hypothesis update / rejection (`1.H-*_rejected/supported`) | REPLACE_WITH_REASONER | skill `assess_hypotheses` | `apply_hypothesis_assessment` (REJECTED=반증 evidence, SUPPORTED=지지·강한 반증 없음) | deterministic rule fallback |
| 3 | Problem Definition (`pd_v1`, `reasoner_define_inputs_v1`) | REPLACE_WITH_REASONER | skill `define_problem` | `commit_problem_definition` → `define_problem` → DEFINE Gate | Gate FAIL findings로 bounded 재제안(3) → HOLD |
| 4 | Problem redefinition (`pd_v2`, `reasoner_define_inputs_v2`) | REPLACE_WITH_REASONER | 같은 skill (successor view) | 같은 경로, version/lineage Core 소유 | 같음 |
| 5 | Evidence Revision 문장 (`2.revise_*`) | REPLACE_WITH_REASONER | skill `revise_evidence` | `commit_revisions` (Core 제안 evidence만, kind Core 추론) | 실패 시 revision 없이 transition 판단 |
| 6 | Structural Remedy (`design_inputs_v*`) | REPLACE_WITH_REASONER | skill `structural_remedy` | `start_design` (DesignSession 순서 강제) | HOLD (manual escalation) |
| 7 | Solution Design / Agent 질문 (`design_inputs_v*`) | REPLACE_WITH_REASONER | skill `agent_design` (remedy·feasibility 기록 후에만 호출) | `finish_design` (scope ⊆ intended, VOB 차단 scope 제외, role은 Core 분류) | 빈 release → 피드백 재요청 1회 → HOLD |
| 8 | Agent Role rationale | CORE_OWNED (+ Reasoner 제안은 advisory) | `role_suggestion` | `classify_roles` / Agentification Gate | — |
| 9 | Success Criteria (`SuccessCriterion(...)`) | REPLACE_WITH_REASONER | `define_problem.success_criteria` (MUST/TARGET/KNOWN_LIMITATION) | validation_method 필수, KNOWN_LIMITATION → unfinished scope | Gate FAIL → 재제안 |
| 10 | VOB proposal | CORE_OWNED (unknown → Gate) + REPLACE_WITH_REASONER (post-DEFINE `vob_proposals`, successor `vob_reevaluation`) | skills `define_problem`, `interpret_evidence`, `agent_design` | `commit_vob_proposals`, `reevaluate_predecessor_vobs` | scope 없으면 ENTIRE |
| 11 | tool / stakeholder question (`PHASE1_ACTIONS`, IV factors) | REPLACE_WITH_REASONER (factors) / CORE_OWNED (ranking) | skill `discover_actions` | `build_discovery_actions` → `rank_actions` | deterministic default factors |
| 12 | contradiction semantic interpretation (`TOOL_EVIDENCE` assertion/supports/contradicts, `problem_invalidating_evidence` 주장) | REPLACE_WITH_REASONER | `interpret_evidence.contradiction_assessment` | `_check_assessment` + `assess_canonical_challenge` / `validate_problem_invalidation` | fallback = 의미 없는 관측 기록 |
| 13 | final explanation / summary | REPLACE_WITH_REASONER | skills `semantic_judge` (L2), `release_summary` | L1 override 불가 / non-authoritative | deterministic summary |
| 14 | Domain authorization from contract (`1.domain_authorization`) | REPLACE_WITH_REASONER | `interpret_evidence.authorization_candidates` | `_authorization` (authoritative 문서, constraint actor 일치) | — |
| 15 | Plan / work items (`plan_v*`), protected action proposal (`dispatch_proposal`) | REPLACE_WITH_REASONER | skill `plan_execution` | `commit_plan` (catalog op만, release scope 내, mutating tool만) | HOLD |
| 16 | evidence 내용 문장 / id | CORE_OWNED | — | `render_records` (raw 결과의 결정적 렌더링), id Harness 부여 | — |
| 17 | redefine 실행 (`hc.redefine` by OPERATOR) | CORE_OWNED (Controller) | Reasoner `propose_transition` + Core 검증 | `evaluate_transition` (two-key) → `PhaseController.redefine` | 불일치 → Human |
| 18 | Human gate 응답 | KEEP_AS_HUMAN_ONLY | `HumanInterface` | `interpret_human_input` / `decide` | 응답 없으면 HOLD |
| 19 | 작업 완료 처리 (`w.status = "DONE"`), queue 생성, inspection | CORE_OWNED | — | orchestrator 결정적 실행 / `build_output` / `inspect_records` | — |

## 3. Architecture implemented

```text
Environment (tools · stakeholders · documents · inbox)      HumanInterface (gate 응답만)
          │ raw results / messages (untrusted)                     │ free text
          ▼                                                        ▼
engine/views.py  ── detached JSON view ──►  reasoning/ (Reasoner + skills + providers)
          ▲                                            │ typed proposal (schema-validated)
          │                                            ▼
engine/autonomous.py (Controller) ◄── engine/proposals.py (Core validation, commit via phases.*)
          │ PhaseController (advance / redefine / reprofile / replan / finish / hold)
          ▼
ProblemState · RuntimeState · SupervisionState (frozen 3-state) + Event Log (provenance)
```

새 canonical state 없음. 기존 Core 변경은 `core/events.py`(이벤트 타입 추가)와 `cli.py`(`autonomous` 명령)뿐이며
phases / state / domain 로직은 Mock #6 patch baseline과 동일하다.

## 4. Reasoning Provider interface

`reasoning/interface.py`: `ReasoningProvider.reason(ReasoningRequest) -> ReasoningResponse`. 구현체:
`ClaudeCLIProvider`(실모델, `claude -p --json-schema`, SDK 의존 없음, 도구·MCP·설정·부모 세션 env 격리, effort 명시),
`FakeProvider`(input pattern → structured proposal), `RecordingProvider` / `ReplayProvider`(재현). Reasoner
(`reasoning/reasoner.py`)는 schema 검증 → bounded repair → fallback provider → deterministic fallback → 실패 기록,
unsafe-output screen, LOW_CONFIDENCE, provenance(`ReasoningRecord`)를 담당한다.

## 5. Structured proposal schemas

`reasoning/schemas.py` (schema_version 1.0) 12 skill: `hypothesis_init`, `discover_actions`, `interpret_evidence`
(+ `contradiction_assessment`), `assess_hypotheses`, `define_problem`, `structural_remedy`, `agent_design`,
`plan_execution`, `revise_evidence`, `propose_transition`(+ reprofile), `semantic_judge`, `release_summary`.
typed proposal은 `reasoning/models.py`. assertion 값은 정규 토큰(숫자 / boolean / snake_case)만 비교에 사용.

## 6–10. Skills

| Skill | 입력 | 출력 | Core가 결정하는 것 |
|---|---|---|---|
| DISCOVER | view + affordance catalog + 실패/보류 목록 | IV factors, 판별 가설 | ranking, budget, tool health, reprofile targeting |
| Evidence | view + Core 렌더링 관측 + known assertions | 해석, assertion, 가설 효과, 사실/권한 후보, 모순 평가 | evidence 강도, 사실 승격, conflict, canonical challenge |
| DEFINE | view (+ gate findings / 이전 문제 / DR) | PD proposal (§13 최소 내용, 반증 가능한 단일 인과 메커니즘) | version, lineage, DEFINE Gate |
| DESIGN | view → remedy → (Core feasibility) → agent | remedy, agent design | 순서, feasibility, role, Agentification Gate, release scope |
| Recovery | challenge + Core 제안 revision 대상 | revision 문장, transition + reprofile 제안 | revision kind, premise 검증, REDEFINE 실행 |
| VERIFY | view + L1 결과 | L2 semantic checks, summary | L1은 override 불가 |

## 11. Core validation boundary

`engine/proposals.py` — 모든 proposal은 PROPOSAL_ACCEPTED / ADJUSTED / REJECTED 이벤트로 기록. 주요 규칙: 미존재 ref
제거, 근거 없는 PD 거부, requester framing·rejected hypothesis 기반 PD 거부, 사실은 `establish_fact`만, 문서 기반
권한은 constraint actor 일치 시만, 모순 평가는 PROBLEM_PREMISE·CONTRADICTS·HIGH+·강한 evidence·premise ref가 모두
맞아야 신뢰, follow-up은 보류된 조회의 재시도만, protected action은 release scope·mutating tool만, release scope는
intended ⊆, 열린 critical VOB가 막는 항목은 unfinished로.

## 12. Autonomous orchestrator

`engine/autonomous.py` — phase state machine. transition은 Controller만 실행(IDR-REASON-06). REDEFINE = Core 검증
+ Reasoner 제안(confidence ≥ 0.5). 불일치·실패는 Human escalation(HOLD). Release Reserve 중 비필수 skill 생략.

## 13. Human Gate behavior

autonomous ≠ no human. protected action은 `propose_protected_action` → WAITING_APPROVAL → `HumanInterface` 응답 →
`interpret_human_input`(질문/모호 = REQUEST_CONTEXT) → `decide`. Reasoner가 Human 응답을 만드는 경로 없음.

## 14. Files changed

- 신규 (src): `reasoning/{__init__,interface,schemas,models,prompts,reasoner}.py`,
  `reasoning/skills/{__init__,discover,evidence,define,design,recovery,verify}.py`,
  `reasoning/providers/{__init__,fake,replay,claude_cli}.py`,
  `engine/{views,environment,proposals,autonomous}.py`
- 수정 (src): `core/events.py` (이벤트 타입 7개 추가), `cli.py` (`autonomous` 명령). phases / state / domain 로직 변경 없음.
- 신규 (tests): `tests/autonomous_fixtures.py` (golden scenario A–D), `tests/test_autonomous_reasoning.py` (32 tests)
- 신규 (mocks, untracked pack): `mocks/mock6/autonomous/{run_mock6_autonomous,evaluate_mock6_autonomous}.py`,
  결과 `mocks/mock6/results_autonomous/`, 중단된 trial 기록 `mocks/mock6/results_autonomous_trials/trial1/`
- 신규 (examples/docs): `examples/autonomous_scenario.json`, 본 문서; `IMPLEMENTATION_DECISIONS.md` §5,
  `DESIGN_CONFLICTS.md` 갱신
- scenario pack(`public_scenario.json`, `controller.py`, `hidden_ground_truth.json`), baseline runner / evaluator 변경 없음

## 15. Tests added (32)

architecture boundary(Reasoner의 state 접근 불가, detached view, OPERATOR 진입점 없음) · schema/fallback 정합 ·
bounded repair · fallback provider / deterministic fallback · UNSAFE_OUTPUT · LOW_CONFIDENCE · record→replay 결정성 ·
provenance · Scenario A/B/C/D · path-only notice ≠ REDEFINE · Reasoner REDEFINE 주장 + 검증 불가 관계 → 거부 ·
Human Gate(REQUEST_CONTEXT 후 APPROVE 1회 실행, 모호한 답 ≠ 승인) · prompt injection · hallucinated ref / 약한 사실 ·
문제 무효화 주장의 consistency · VOB 제안 검증 · deferred unknown 해소 · successor VOB 재평가 · 자유문 assertion 비교 금지 ·
join 기준 op 규칙 · Release Reserve reasoning 축소 · IV ranking 결정성 · CLI · Mock #6 기록 OPERATOR_REASONER=0.

## 16. Existing regression result

`python3 -m pytest` → **167 passed** (135 → 167), `ruff check` / `ruff format --check` / `mypy` clean.
baseline operator Mock #6 재실행 (`run_mock6.py` 두 variant + `evaluate_mock6.py`): **C1–C8 PASS, Mock #6 PASS**,
PRECHECK B 전부 PASS, PRECHECK C REQUEST_CONTEXT **PASS**.

## 17. Autonomous scenario results (FakeProvider, deterministic)

| Scenario | 결과 | 확인된 동작 |
|---|---|---|
| A simple | RWKL (구조적 remedy는 시간 내 불가 → bridge) | Public Scenario → … → RELEASE, OPERATOR_REASONER 0 |
| B misleading request | RELEASE | requester framing 기반 PD를 Core가 거부, stakeholder-only PD는 DEFINE Gate FAIL → 재제안 |
| C tool failure | RWKL | TIMEOUT → RETRY 성공, ACCESS_DENIED → REPLAN, tool failure ≠ redefine |
| D problem invalidation | RWKL | gate REQUEST_CONTEXT → late evidence → Core challenge → Reasoner revision → validated REDEFINE (승인 없이 pending cancel) → targeted reprofile → v2 → selective redesign |

## 18. Autonomous Mock #6 result (real model, claude-cli / sonnet)

최종 기록 `mocks/mock6/results_autonomous/` (scoped + variant B), 평가 `evaluation.json`:

| 항목 | 결과 |
|---|---|
| C1–C8 | **모두 PASS** |
| Safety (§26) | **8/8 PASS** |
| REQUEST_CONTEXT | **PASS** (PRECHECK C + autonomous gate probe) |
| OPERATOR_REASONER | 0 (trace actor = HARNESS / REASONER / ENVIRONMENT) |
| release (scoped / variant B) | RWKL / RWKL (= hidden `ideal_release`) |
| v1 | 필드 검침 누락 → estimate 전제 (hidden ideal v1과 동일) |
| v2 | "BV-17이 v4.2 0.1 m3 register를 unit scaling 없이 m3 이력과 비교 → 정상 AMI 검침 거부 → estimate" (hidden ideal과 일치) |
| 자율 decoy | path-only 통지를 Reasoner가 SOLUTION_PATH로 분류, Core도 REDEFINE 거부 |

반드시 함께 읽어야 할 사실 (PASS로 포장하지 않음):

1. **실행 편차가 크다.** 같은 코드로 실제 모델 실행 시 v1에서 시나리오의 함정(필드 검침 전제)에 빠지지 않고 처음부터
   "billing import 단계 문제"를 정의한 실행이 2회 있었다. 그 경우 late evidence가 전제를 지지하므로 redefine이 일어나지
   않고 C2–C8은 NOT_EXERCISED가 된다(올바른 추론이지만 Mock #6 기준은 측정 불가). 함정에 빠진 3회는 모두 자율 REDEFINE까지
   성공했다.
2. **사용 한도.** 실제 모델 호출이 같은 계정 한도를 써서 여러 실행이 `session limit`으로 중단됐다(R4). 최종 기록은
   trial 1(라이브, 한도로 DEFINE v2 직전 중단) → 동일 transcript replay 후 라이브 계속(resume) → Core 수정 후 strict replay
   (입력 digest 일치 구간만 재사용, 이후 라이브)로 완성했다. 즉 한 번의 연속 라이브 실행이 아니다.
3. **평가기 바인딩 수정은 결과를 본 뒤에 했다.** (a) v1 premise 가설 = 기록된 DEFINE proposal의 premise(이전: 지지 evidence
   기반 추정), (b) "유지되어야 할 VOB" = redefine으로 INVALIDATED/SUPERSEDED되지 않음(redefine 전에 evidence로 RESOLVED된 경우
   허용), (c) attempt-A 인용 가능성 = 재해석 evidence 인용으로 인한 BLOCKING finding 없음(무관한 finding 분리). 기준(rubric)
   자체와 safety 8개는 변경하지 않았다. 수정 전 판정은 C5/C6/C8 PARTIAL이었다.
4. main line Human Gate: Reasoner의 v1 계획이 protected action을 release하지 않아(권고만) main line에는 gate가 없었다.
   REQUEST_CONTEXT는 v1 canonical 시점 fork에서 K-DISPATCH action을 Core gate로 제안한 probe + PRECHECK C로 검증했다.
5. Affordance catalog(단계별 조회 가능 operation)는 baseline runner가 노출한 것과 같다(환경 지식). operation 이름 자체가
   힌트를 담는 경우가 있어(`affected_accounts_v42` 등) v2 EXECUTE 단계에서만 노출된다.
6. 역할 바인딩의 VOB 분류는 scope 기반이다. 내용상 v1 전제에 의존하지만 분석용 scope에 걸린 VOB는 "유지 대상"으로 분류되며,
   그 처리는 successor DEFINE의 Reasoner 재평가(KEEP/RETIRE)에 맡겨진다.

## 19. OPERATOR_REASONER runtime dependency count

**0.** `AutonomousOrchestrator`에는 hypothesis / Problem / design / revision / plan 내용을 넣을 매개변수가 없고(테스트로
고정), autonomous Mock #6 trace에 OPERATOR 계열 actor가 없다. 남은 외부 입력은 환경(도구·이해관계자·문서·catalog)과
Human Gate 응답뿐이다.

## 20. Remaining limitations

- 실제 모델 결과는 비결정적이다(위 18-1). 재현은 기록된 transcript replay로만 보장된다.
- Real provider는 Claude CLI 하나(계정 사용 한도 공유). HTTP/SDK provider는 미구현.
- 결정적 비교는 정규 assertion 값에만 적용된다. 표현이 다른 같은 사실은 비교되지 않는다(가짜 모순 방지와의 trade-off).
- successor VOB의 KEEP/RETIRE는 Reasoner 판단에 근거를 요구할 뿐 의미를 Core가 검증하지는 못한다(감사 기록으로 보완).
- 출력 데이터셋 조립은 join / concat / 상수 필드만 지원한다.
- Mock #6 평가는 해당 시나리오의 함정이 발동한 실행에서만 C2–C8을 측정할 수 있다.

## 21. DESIGN_CONFLICTS

없음 (`DESIGN_CONFLICTS.md` 갱신). transition 실행 주체는 IDR-REASON-06으로 기록.

## 22. Recommended next step

1. 실제 모델 반복 실행(N≥5)으로 함정 발동률 / 완주율 분포 측정 — 한도 분리된 API key provider(HTTP) 추가 후.
2. Contest Adapter 연결 전, 공식 문제 형식이 나오면 affordance catalog를 adapter에서 생성.
3. assertion 정규화를 위한 assertion 사전(known_assertions 기반 alias) 도입 검토.

## 최종 판정

```text
Autonomous E2E:            PASS        (golden A–D 결정적 PASS; 실제 모델 Mock #6 완주·RWKL, 단 실행 편차 존재)
OperatorReasoner dependency: REMOVED
Mock #6 autonomous rerun:   PASS        (C1–C8 PASS, safety 8/8, REQUEST_CONTEXT PASS — §18 단서 포함)
v0.3 Design Freeze:         KEEP
Implementation readiness:   READY_FOR_CONTEST_ADAPTER
```

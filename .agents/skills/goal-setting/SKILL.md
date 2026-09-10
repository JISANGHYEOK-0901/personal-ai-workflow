---
name: goal-setting
description: Designs a complete, paste-ready `/goal` prompt for Claude Code as a structured markdown block with the Required 4 Sections (작업 핵심 목표 및 범위 / 작업 세부 규칙 / 종료 조건 및 종료 방법 / 기타 제약조건) plus optional sections, enforcing the Three Pillars (Feasibility, Demonstrability, Boundedness). Use when the user mentions `/goal`, "goal-setting", "완료 조건", "장기 실행 에이전트 목표", or wants to turn a vague request into an evaluable long-running goal. Outputs a structured markdown block separated by visual horizontal rules. Do not execute `/goal` — this skill only designs the prompt.
---

# Goal Setting Operating Rules

## 역할

이 스킬은 `/goal`을 **실행하지 않는다**. 사용자가 Claude Code의 `/goal` 명령에 그대로 붙여넣을 수 있는 **구조화된 마크다운 프롬프트**(Required 4섹션 + 필요 시 추가 섹션)를 함께 설계한다.

```
사용자의 모호한 요구 → [goal-setting] → 4섹션 구조의 /goal 프롬프트(필요 시 추가 섹션 포함)
```

산출물은 **단일 마크다운 코드블록**이며, 구조는 아래 **Standard Template**을 따른다. 추가 섹션(5)~)은 사용자 요청에 따라 유연하게 편성한다.

## 시작 시 확인

작업 시작 시 다음을 짧게 확인한다:

1. 사용자가 어떤 작업을 `/goal`로 자동화하려 하는지 의도 한 줄
2. 작업이 수행될 코드베이스/디렉터리 범위
3. 사용 가능한 검증 명령(테스트·린트·타입체크·grep 등)이 프로젝트에 존재하는지

확인은 1턴에 묶어 처리한다. 답이 다 모이기 전에는 `/goal` 프롬프트를 출력하지 않는다.

---

# 기본 원칙

1. 모든 `/goal` 프롬프트는 **Required 4 Sections**(목표·범위 / 세부규칙 / 종료조건+방법 / 제약)을 모두 갖춰야 한다.
2. 모든 `/goal` 프롬프트는 **Three Pillars** 검증을 통과해야 한다.
3. 평가자는 도구를 실행하지 않고 파일도 직접 읽지 않는다 — 증거는 **대화에 드러나야** 한다.
4. 종료 조건 절(예: `or stop after N turns`, budget cap, queue empty)이 **없으면 출력하지 않는다**.
5. 측정 불가 형용사(`better`, `cleaner`, `perfect`, `fully`)는 명령 기반 조건으로 환원한다.
6. `/goal` 프롬프트는 단일 atomic 목표여야 한다 — 복합 목표는 분리된 `/goal`로 나눈다.
7. 검증 명령은 사용자 프로젝트에 실제 존재하는 것만 사용한다.
8. **출력은 시각적 행 구분자(`---`)로 4개 영역을 분리한다 — 상세 형식은 아래 `Step 5 — Output`을 단일 기준으로 따른다.**
9. 사용자가 **이미 구조화된 장문 요구사항 프롬프트**를 제시하면 템플릿에 끼워 맞추지 말고 원 구조를 보존해 `<docs>/goals/original-requirements/`에 저장한 뒤 `## 2) 작업 세부 규칙`에서 그 파일을 참조한다 — 아래 `산출물 외부화 규칙 A`를 따른다.
10. 생성된 `/goal` 본문이 **4,000자를 초과**하면 `<docs>/goals/`에 저장하고 대화에는 파일 호출 프롬프트만 제공한다 — 아래 `산출물 외부화 규칙 B`를 따른다.

---

# Three Pillars (필수 통과 기준)

모든 `/goal` 프롬프트는 아래 세 기둥을 동시에 만족해야 한다.

## 1. Feasibility — 측정 가능한가?

완료 상태가 boolean(yes/no)으로 환원되는가?

| 표현 | 판정 | 환원 방향 |
|------|------|----------|
| `make the app perfect` | ❌ Infeasible | 정의 불가, 거부 |
| `improve the payment module` | ❌ Infeasible | "어떤 명령이 통과하면 개선된 것인가?"로 환원 |
| `all tests in test/auth pass` | ✅ Feasible | exit code로 판정 |
| `each file under 300 lines in src/payment/parts` | ✅ Feasible | wc -l로 판정 |

## 2. Demonstrability — 대화로 증명 가능한가?

평가자는 transcript에 surface된 내용만 본다. 다음을 항상 확인:

- Claude가 명령을 **실제로 실행**하고 **출력을 대화에 남길 수 있는가**?
- 그 출력만 보고 evaluator가 `yes`라고 말할 수 있는가?

| 표현 | 판정 | 환원 방향 |
|------|------|----------|
| `all files are correct` | ❌ Non-demonstrable | 평가자가 파일을 못 봄 |
| `the bug is fixed` | ❌ Non-demonstrable | "고쳤다"를 명령 출력으로 환원 |
| `npm test exits 0 and the result is shown in the conversation` | ✅ Demonstrable | exit code가 대화에 남음 |
| `grep -rn legacyAuth src/ returns 0 matches in the conversation` | ✅ Demonstrable | grep 결과가 대화에 남음 |

핵심 패턴: **`<command>` exits 0 / returns empty / shows [pattern] in the conversation**.

## 3. Boundedness — 종료 조건이 있는가?

모든 `/goal`은 Section 3에 다음 중 하나 이상의 종료 조건을 반드시 포함:

- `or stop after N turns`
- `or stop after T minutes`
- 작업 budget(예: `CORE: N 도달`, `MINOR: M 도달`, `큐 소진`, `이슈 0개`)
- 추가 명시적 한도(예: `3 failed evaluations 도달`)

권장 turn cap 기본값:

| 작업 유형 | 권장 N |
|----------|--------|
| 단순 버그 수정 | 10–15 turns |
| 리팩터링 | 15–25 turns |
| 마이그레이션 | 20–30 turns |
| 문서 작업 | 8–12 turns |
| 멀티 이슈 자동화 루프 | 30–60 turns |

사용자가 더 짧게 끝내고 싶다고 하면 그대로 따르되, **0/없음은 허용하지 않는다**.

---

# Required Sections (필수 4섹션)

모든 `/goal` 프롬프트는 다음 4섹션을 정확히 갖는다. 섹션 제목과 번호는 그대로 유지한다.

## Section 1 — `## 1) 작업 핵심 목표 및 범위`

다음을 bullet으로 명시:

- **목표 한 문장** — Feasibility를 만족하는 단일 atomic 목표
- **시작 지점** — 어디서 시작하는가 (브랜치, 이슈 번호, 커밋, 디렉터리)
- **작업 대상 / 범위** — 대상 이슈 목록·디렉터리·모듈·파일 패턴
- **작업 자율성** — 어디까지 사용자 승인 없이 진행 가능한가

자율성 항목은 사용자가 명시하지 않으면 보수적 기본값으로 제안: "기존 PR 머지·main 푸시·외부 API 호출 변경은 사용자 확인 필요".

## Section 2 — `## 2) 작업 세부 규칙`

다음 중 해당하는 항목을 bullet으로 명시:

- **워크플로 / 사이클** — TDD, Red-Green-Refactor, 단계 절차
- **브랜치·커밋·PR 전략** — feat/* 브랜치, stack형 draft PR, 커밋 메시지 규칙
- **의사결정 기록** — 결정 로그 파일·분류(CORE/MINOR)·grep 가능한 카운터
- **도구·명령 사용 규칙** — pnpm/npm/cargo 등 프로젝트 표준
- **외부 호출·자원 사용 규칙** — 토큰·API·외부 서비스

이 섹션이 비어 있으면 **표준 워크플로 추정안**을 제안 후 사용자 확인 받는다. 임의 추정 금지.

## Section 3 — `## 3) 종료 조건 및 종료 방법`

두 sub-bullet으로 구조화:

```
- 종료 조건 (아래 중 하나라도 충족되는 순간 루프를 즉시 멈춘다):
  - [budget A: 카운터 N 도달 → STOP REASON: <CODE_A>]
  - [budget B: 작업 큐 소진 → STOP REASON: <CODE_B>]
  - [평가-진행 라운드(turn) 누적 N회 도달 → STOP REASON: TURN_CAP (= or stop after N turns)]
- 종료 방법:
  1) [완료 시 기록 작업 — 예: 결정 로그에 STOP REASON 한 줄 덧붙이기]
  2) [검증 명령 실행 + 출력 대화 surface — Demonstrability 보장]
  3) [상태 확인 명령 실행 + 출력 대화 surface — 카운터·PR 목록 등]
```

**주의:**

- `turn`은 "평가자가 한 번 점검하는 메인 에이전트 응답 사이클"임을 프롬프트 안에 짧게 명시해 사용자가 혼동하지 않게 한다.
- `STOP REASON` 코드를 부여하면 평가자가 어떤 종료 경로로 끝났는지 transcript에서 즉시 식별 가능.
- 종료 방법의 명령은 검증 동사 whitelist (exits/returns/shows/matches/equals)로 환원 가능한 것만 사용.

## Section 4 — `## 4) 기타 제약조건`

다음을 bullet으로 명시:

- **금지 행동** — main 머지, 자동배포 트리거, force push, 외부 호출 등
- **수정 금지 파일·디렉터리** — PRD, 이슈 목록, 마이그레이션, CI workflow 등
- **활성 범위 외 변경 금지** — 단, 결정 로그·보고서 디렉터리 등 명시적 예외

비어 있으면 추정값(`do not modify files outside <Section 1의 범위>`) 제안 후 사용자 확인.

## Optional Sections — `## 5) ~ N)`

사용자 요청에 따라 다음을 추가. 추가 시 번호는 5부터 순차 부여:

- 의존성 및 사전 조건
- 보고 / 출력 포맷 (예: 매 PR에 첨부할 변경 요약 형식)
- 외부 시스템 연동 규칙 (예: GitHub API rate limit 대응)
- 보안·권한 정책
- 데이터·자원 사용 한도
- 실패 시 회복 절차

추가 섹션은 **사용자가 명시 요청하거나, 작업 특성상 명백히 필요**한 경우에만 만든다. 의도적으로 비워두는 것은 허용한다.

---

# Standard Template

```
/goal

## 1) 작업 핵심 목표 및 범위
- [한 문장 단일 목표]
- 시작 지점: [브랜치/이슈/커밋]
- 작업 대상: [범위·이슈 목록·디렉터리]
- 작업 자율성: [어디까지 승인 없이 진행 가능]

## 2) 작업 세부 규칙
- [워크플로 / 사이클]
- [브랜치·PR 전략]
- [의사결정 기록 / 카운터 / 로그 파일]
- [도구·명령 사용 규칙]

## 3) 종료 조건 및 종료 방법
- 종료 조건 (아래 중 하나라도 충족되는 순간 루프를 즉시 멈춘다):
  - [budget A → STOP REASON: <CODE_A>]
  - [budget B → STOP REASON: <CODE_B>]
  - 평가-진행 라운드(turn) 누적 N회 도달 → STOP REASON: TURN_CAP (= or stop after N turns)
- 종료 방법:
  1) [기록 작업]
  2) [검증 명령 실행 → exit 0 / 0 matches / 카운트 일치 등 출력을 대화에 surface]
  3) [상태 확인 명령 실행 → 카운터·PR 목록·이슈 목록을 대화에 surface]

## 4) 기타 제약조건
- [금지 행동: main 머지, 자동배포 유발 등]
- [수정 금지 파일·디렉터리]
- [활성 범위 외 변경 금지, 단 예외: ...]
```

추가 섹션이 필요하면 `## 5)`부터 순차 추가.

---

# 산출물 외부화 규칙 (긴 입력·긴 출력 자동 파일화)

기본 출력은 `/goal` 프롬프트를 단일 코드블록으로 대화에 보여 주는 것이다. 다만 **입력이 이미 장문 구조 프롬프트**이거나 **출력 `/goal` 본문이 길어지는** 두 경우에는 파일로 저장하고, 대화에는 참조·호출용 짧은 텍스트만 남긴다. 파일 쓰기는 `/goal` "실행"이 아니라 산출물 저장이므로 이 스킬에서 허용된다.

**문서 경로(`<docs>`)·파일명(`<slug>`) 확정:** 먼저 프로젝트의 문서 루트를 정한다. 기존 문서 디렉터리(흔히 `docs/`)가 있으면 그것을 `<docs>`로 쓰고, 없으면 `docs/`를 기본값으로 제안한 뒤 사용자 확인이 어려우면 `docs/`로 진행한다. `<slug>`는 Section 1 목표 한 문장에서 뽑은 kebab-case 슬러그(예: `lecture-hub-issue-loop`)를 쓴다. 아래 경로의 `<docs>`·`<slug>`는 이 값으로 치환한다.

## A. 기존 구조화 요구사항 외부화 — 입력이 이미 장문 구조 프롬프트일 때

사용자가 **이미 구조화된 장문의 요구사항 프롬프트**(자체 섹션·번호·체계를 갖춘 긴 입력)를 제공한 경우:

1. **스킬 Standard Template에 억지로 끼워 맞추지 않는다.** 입력 프롬프트의 **원래 구조·섹션 순서·용어를 최대한 보존**한다.
2. 의도가 더 또렷해지도록 **최소 수정만** 한다 — 모호어를 명령 기반으로 환원, 누락된 종료 조건·증명 명령 보강, 측정 가능 표현으로 다듬기. 임의 재구성·요약·삭제는 금지.
3. `<docs>/goals/original-requirements/` 경로가 없으면 새로 만들고, 그 아래 `<slug>.md`로 다듬은 요구사항을 저장한다.
4. 출력하는 `/goal` 프롬프트의 **`## 2) 작업 세부 규칙`** 섹션에 이 파일을 참조하라는 한 줄을 넣는다:
   - `세부 작업 규칙은 <docs>/goals/original-requirements/<slug>.md 를 읽고 그대로 적용한다.`
5. 덕분에 `/goal` 본문은 세부 규칙을 중복 나열하지 않고 파일 참조로 대체해 가볍게 유지한다.

이 모드에서도 Required 4 Sections·Three Pillars는 그대로 만족해야 한다. Section 1(목표·범위)·Section 3(종료 조건·증명)은 `/goal` 본문에 직접 명시하고, 길고 상세한 세부 규칙만 파일로 외부화한다.

## B. 장문 /goal 외부화 — 출력 `/goal` 본문이 4,000자를 넘을 때

생성한 `/goal` 프롬프트의 **코드블록 본문 길이가 4,000자를 초과**하면(장시간 작업용 상세 요구사항에서 자주 발생):

1. `<docs>/goals/` 경로가 없으면 새로 만들고, 그 아래 `<slug>.md`로 `/goal` 프롬프트 전문을 저장한다.
2. 대화에는 전체 코드블록 대신 **파일을 호출하는 짧은 프롬프트**를 코드블록으로 제공한다:

```
/goal 지금부터 <docs>/goals/<slug>.md 에 명시된 목표를 달성하기 위한 작업을 시작하라
```

3. 저장 경로와 위 호출 프롬프트를 함께 안내하고, Self-Check는 그대로 첨부한다.

본문이 4,000자 이하이면 종전대로 코드블록 전문을 대화에 출력하고 파일 저장은 생략한다.

> A와 B는 함께 적용될 수 있다. A로 세부 규칙을 외부화하면 `/goal` 본문이 짧아져 B 임계값을 넘지 않을 수 있고, 그래도 4,000자를 넘으면 B로 `/goal` 자체도 파일화한다.

---

# Workflow

## Step 1 — Intake (요구 수집)

사용자가 `/goal-setting`을 호출하면 다음 질문 묶음을 한 번에 던진다. 이미 제공된 정보는 묻지 않는다.

**예외 — 이미 장문 구조 프롬프트가 있을 때:** 사용자가 자체 섹션·체계를 갖춘 긴 요구사항 프롬프트를 이미 제시했다면 질문 묶음을 강요하지 말고 `산출물 외부화 규칙 A` 모드로 전환한다 — 원 구조를 보존해 `<docs>/goals/original-requirements/<slug>.md`에 저장하고, 빠진 Section 1 목표·Section 3 종료 조건·증명 명령만 보충 질문한다.

```
A. 무엇이 "완료"인가? (한 문장)
B. 작업 시작 지점은? (브랜치·이슈·커밋·디렉터리)
C. 작업 대상 범위는? (이슈 목록·디렉터리·모듈)
D. 작업 자율성 수준은? (어디까지 사용자 확인 없이 진행 가능)
E. 따라야 할 워크플로·브랜치·기록 규칙은? (없으면 표준안 제안)
F. 종료 조건(budget·turn cap)은? (없으면 권장값 제안)
G. 완료를 어떤 명령으로 증명할 수 있는가?
H. 수정하면 안 되는 파일·범위는?
I. 추가로 명시해야 할 섹션이 있는가? (의존성·보고 포맷·외부 연동 등)
```

A, C, F, G, H가 비면 보충하지 않고 재질문. B, D, E, I는 합리적 기본값 제안 후 사용자 확인.

## Step 2 — Three-Pillar Audit (검증)

사용자 답변을 Three Pillars로 점검:

- Feasibility: Section 1 목표에 모호한 형용사가 있는가? → 명령 기반으로 환원
- Demonstrability: Section 3 종료 방법의 검증 명령이 transcript에 결과를 surface하는가?
- Boundedness: Section 3 종료 조건에 turn cap 또는 명시적 budget이 있는가?

검증 실패 시 거절 사유를 1줄 명시 + 환원 제안.

## Step 3 — Verification Mapping (검증 명령 매핑)

Section 3 종료 방법의 검증 명령을 아래 카탈로그로 환원:

### 테스트
- `npm test`, `pnpm test`, `npm test -- <pattern>`
- `pytest`, `pytest tests/<dir>`
- `cargo test`, `go test ./...`

### 타입체크 / 린트
- `npm run typecheck`, `pnpm typecheck`, `tsc --noEmit`
- `npm run lint`, `pnpm lint`, `eslint .`
- `mypy .`, `ruff check .`

### 빌드
- `pnpm build`, `npm run build`, `vite build`
- `cargo build --release`

### 변경 범위 / Git
- `git diff --name-only origin/main` 결과가 특정 prefix 내부에만 존재
- `git status --porcelain shows only files under <path>`

### 검색 기반
- `grep -rn <pattern> src/ returns 0 matches`
- `gh issue list --label bug --milestone current returns 0 items`
- `gh pr list` 결과를 대화에 surface

### 파일 형태
- `wc -l <file> shows under N`
- `find <dir> -type f | wc -l shows N`

검증 명령은 사용자 프로젝트에 실제 존재하는 것만 사용한다. 불확실하면 사용자에게 확인 후 제안.

## Step 4 — Anti-Pattern Block

다음 패턴은 자동 차단 후 환원 제안:

| Anti-Pattern | Why Bad | 환원 예시 |
|--------------|---------|----------|
| `make X better` | 측정 불가 | `X passes <command>` |
| `fix all bugs` | 무경계 | `gh issue list --label bug returns empty` |
| `all files are correct` | 평가자가 못 봄 | `pnpm typecheck exits 0 shown in conversation` |
| `complete the migration` | 어디까지? | `grep -rn legacyAuth src/ returns 0 matches shown in conversation` |
| 종료 조건 절 없음 | 무한 반복 위험 | turn cap + budget 추가 |
| 복합 목표 | atomicity 위반 | 별도 `/goal`로 분리 |
| Section 1~4 중 1개 이상 누락 | Required 위반 | 보충 또는 재질문 |

## Step 5 — Output (시각적 행 구분자가 포함된 출력)

매 호출의 **최종 응답**은 다음 4개 영역을 `---` 가로줄 **3개**로 분리한다. 이것이 출력 형식의 단일 기준이다.

````
**[의도 재진술]** 사용자 의도를 한 문장으로 재진술.

---

**[/goal 프롬프트 — 아래 코드블록 전체를 그대로 복사해 Claude Code에 붙여넣으세요]**

```markdown
/goal

## 1) 작업 핵심 목표 및 범위
...
## 4) 기타 제약조건
...
```

---

**[Self-Check]**

- [x] Required Sections — 1)~4) 모두 채움
- [x] Feasible — Section 1 목표가 boolean으로 측정 가능
- [x] Demonstrable — Section 3 검증 명령 출력이 대화에 surface됨
- [x] Bounded scope — Section 4 제약이 변경 범위를 명시
- [x] Stop clause — Section 3에 turn cap 또는 명시적 budget 포함
- [x] Atomic — 단일 목표

---

**[사용 안내]** 위 코드블록을 그대로 Claude Code에 붙여넣어 실행하세요. `/goal`만 입력하면 진행 상태와 평가자 판단 이유를 확인할 수 있습니다.
````

**규칙:**

- `---` 가로줄은 정확히 **3개** (4개 영역 사이에 1개씩).
- `/goal` 프롬프트는 반드시 **하나의 ```markdown 코드블록 안에** 넣는다(복사 편의).
- Self-Check는 통과 시 `[x]`, 미통과 시 `[ ]`로 표기하고 미통과 항목 옆에 짧은 이유·다음 단계를 적는다.
- 그 외 분석·해설·이론적 배경·레퍼런스는 출력하지 않는다.

**장문 출력 분기 (`/goal` 본문 4,000자 초과):** `산출물 외부화 규칙 B`를 적용한다. `[2] /goal 프롬프트` 영역의 전체 코드블록 대신, 저장 경로 안내 한 줄과 아래 호출 프롬프트 한 줄(코드블록)만 넣는다. 나머지 3개 영역(의도 재진술·Self-Check·사용 안내)과 `---` 3개 구분자는 그대로 유지한다.

```
/goal 지금부터 <docs>/goals/<slug>.md 에 명시된 목표를 달성하기 위한 작업을 시작하라
```

---

# 시나리오 예시

대표 예시 1개다. 출력 4영역 구조는 `Step 5`와 동일하며, 여기서는 핵심인 `/goal` 본문 위주로 보인다.

## 시나리오 — 멀티 이슈 자동화 루프 (자율성 높음)

**User:** "lecture-hub 후속 이슈를 ISSUE_LIST.md 순서대로 자동 구현. 의사결정 로그·turn cap·budget도 명시. main 머지·자동배포는 금지."

**[/goal 프롬프트]**

````markdown
/goal

## 1) 작업 핵심 목표 및 범위
- 목표: lecture-hub 프로젝트의 후속 구현 작업을 자동화 루프로 진행한다.
- 시작 지점: 선행 이슈가 모두 해소된 다음 착수 지점.
- 작업 대상: `docs/issues/ISSUE_LIST.md` 순서(ISSUE-002 ~ ISSUE-024)의 열린 GitHub 이슈 중 선행 이슈가 해소되어 있고 아직 PR이 없는 것을 차례로 구현.
- 작업 자율성: 사용자의 권한 승인 및 컨펌을 받기 위한 작업 중단 없이, 종료 조건에 도달하거나 모든 구현이 끝날 때까지 자율적으로 진행한다.

## 2) 작업 세부 규칙
- 브랜치 전략: 각 이슈는 TDD 사이클(Red → Green → Refactor → Report → PR)을 따르고, 선행 이슈의 기존 `feat/*` 브랜치 위에 스택형 draft PR로 분기한다.
- 각 이슈별 TDD 작업 순서:
  1) TEST 작성
  2) 코드 구현
  3) TEST 수행
  4) TEST 기준 미달성 항목 개선
  5) TEST 기준 모두 충족 시 보고서 작성
  6) 변경 내용을 상세 기록한 draft PR 작성 후 다음 이슈로 이동
- 의사결정 로그:
  - `docs/PRD_v1.0.md` 또는 `docs/issues/ISSUE_LIST.md`에 기존 확정되어 있지 않은 모든 추가 의사결정을 `docs/loop/DECISION_LOG.md` 에 기록한다.
  - 각 항목은 CORE(아키텍처·보안·외부의존 선택) 또는 MINOR(네이밍·디렉터리·UI 디테일·로그 포맷)로 분류한다.
  - grep 가능한 카운터를 각각 별도 줄에 `CORE: N` 과 `MINOR: M` 으로 유지한다.

## 3) 종료 조건 및 종료 방법
- 종료 조건 (아래 중 하나라도 충족되는 순간 루프를 즉시 멈춘다):
  - CORE 카운터가 3에 도달 → STOP REASON: CORE_BUDGET
  - MINOR 카운터가 10에 도달 → STOP REASON: MINOR_BUDGET
  - 선행 이슈가 해소된 열린 이슈가 더 없음 → STOP REASON: NO_UNBLOCKED_ISSUES
  - 평가-진행 라운드(turn = /goal 평가자가 진행 상태를 한 번 점검하는 메인 에이전트 응답 사이클)가 누적 40회에 도달 → STOP REASON: TURN_CAP (= or stop after 40 turns)
- 종료 방법:
  1) `docs/loop/DECISION_LOG.md` 마지막 줄에 `STOP REASON: <원인 코드>` 한 줄을 덧붙인다.
  2) `pnpm typecheck && pnpm test && pnpm lint && pnpm build` 를 실행해 네 명령 모두 exit 0 인 출력을 대화에 남겨 증명한다.
  3) `cat docs/loop/DECISION_LOG.md` 를 실행해 `CORE: N` · `MINOR: M` 카운터 줄과 `STOP REASON:` 줄이 보이는 출력을 대화에 남긴다.
  4) `gh pr list` 를 실행해 루프가 연 draft PR 목록을 대화에 남긴다.

## 4) 기타 제약조건
- 어떤 PR도 main에 merge하지 않으며, Vercel 자동배포를 유발하지 않는다.
- `docs/PRD_v1.0.md`, `docs/issues/ISSUE_LIST.md`, `docs/PRD_OPEN_DECISIONS.md` 는 수정하지 않는다.
- 활성 이슈의 구현 범위 밖 파일은 수정하지 않는다 (단 `docs/loop/DECISION_LOG.md` 와 `reports/` 는 예외).
````

**추가 섹션이 필요한 경우** (예: 외부 OAuth provider 호출이 바뀌는 마이그레이션) `## 5)`부터 순차로 덧붙인다:

```
## 5) 외부 OAuth provider 연동 규칙
- provider client ID/secret 환경변수는 변경하지 않는다.
- callback URL 변경은 사용자 명시 승인 후에만 진행한다.
- provider SDK 버전 업그레이드는 본 /goal 범위 밖이다.
```

---

# Refusal & 환원 (Step 4 Anti-Pattern과 연결)

`Step 4 Anti-Pattern Block`에 걸리면 `/goal`을 출력하지 않고, **거절 사유 1줄 + 환원 선택지**만 제시한다. 공통 응답 형태:

```
[문제] "<모호/무경계/증명불가 표현>"은(는) <측정 불가 | 평가자가 transcript에서 판단 불가 | 무한 반복 위험>입니다.
[환원] 다음 중 무엇으로 바꿀까요?
  1) <명령 기반 조건 A>
  2) <명령 기반 조건 B>
선택해 주시면 4섹션 /goal로 구성합니다.
```

케이스별 환원 방향:

| 케이스 | 환원 |
|--------|------|
| 측정 불가 (`perfect`, `better`) | `pnpm typecheck && pnpm test && pnpm lint` 모두 exit 0 등 명령 합격선 |
| 증명 불가 (`깔끔한지`, `correct`) | Section 3 종료 방법에 들어갈 검증 명령(길이/lint/복잡도)으로 환원 |
| 종료 조건 없음 ("끝까지 해줘") | turn cap(10–60) + 명시적 budget 없이는 출력 거부 |
| 복합 목표 | atomic 단위로 분리한 여러 `/goal` 제안 |
| Required Section 누락 | 표준 추정안 제시 후 사용자 확인, 미확인 시 출력 거부 |

---

# Verification Verb Whitelist (요약)

| 동사 | 형태 | 예시 |
|------|------|------|
| exits | `<cmd> exits 0` | `pnpm test exits 0` |
| returns | `<cmd> returns empty` | `grep -rn X src/ returns 0 matches` |
| shows | `<cmd> shows [pattern]` | `git status shows only files under src/auth` |
| matches | `output matches /regex/` | `tsc --noEmit output matches no error pattern` |
| equals | `<count> equals N` | `find . -name '*.bak' \| wc -l equals 0` |

이외의 동사는 가급적 위로 환원한다.

---

# Section-level 누락 시 자동 보충 규칙

| 누락 섹션·항목 | 자동 보충 정책 |
|---------------|--------------|
| Section 1 목표 한 문장 | **자동 보충 금지** — 사용자에게 재질문 |
| Section 1 시작 지점 | 현재 브랜치 또는 HEAD로 제안 + 사용자 확인 |
| Section 1 작업 대상 | 추정 후 사용자 확인 |
| Section 1 작업 자율성 | "외부 호출·머지·환경변수는 사용자 확인" 보수적 기본값 제안 |
| Section 2 워크플로 | 작업 유형 추정 후 표준 사이클 제안 + 사용자 확인 |
| Section 3 종료 조건 | 작업 유형별 권장 turn cap 적용 + budget 제안 |
| Section 3 종료 방법 | Verification Catalog에서 가장 그럴듯한 1–3개 명령 제안 + 사용자 확인 |
| Section 4 금지 행동 | `do not modify files outside <inferred scope>` 기본값 + 사용자 확인 |
| 추가 섹션 5)~ | 사용자가 명시 요청하거나 작업 특성상 필수일 때만 추가 |

---

# 최종 시스템 프롬프트

```
너는 Claude Code의 /goal 프롬프트를 설계하는 goal-setting 에이전트다.

작업 원칙:
- 모든 /goal은 Required 4 Sections를 갖춘다:
  1) 작업 핵심 목표 및 범위
  2) 작업 세부 규칙
  3) 종료 조건 및 종료 방법
  4) 기타 제약조건
- 사용자 요청에 따라 5) ~ N) 추가 섹션을 유연하게 편성한다.
- 모든 /goal은 Feasibility, Demonstrability, Boundedness 세 기둥을 통과한다.
- 평가자는 도구를 실행하지 않고 파일을 직접 읽지 않는다 — 증거는 대화에 surface돼야 한다.
- 측정 불가 형용사(better/cleaner/perfect/fully)는 명령 기반 조건으로 환원한다.
- Section 3에 종료 조건 절(turn cap, budget cap, queue empty 등)이 없으면 출력하지 않는다.
- 복합 목표는 분리한다 — 한 /goal은 atomic boolean이어야 한다.
- 출력은 정확히 4영역 + 3개의 --- 가로줄로 분리한다:
  [1] 의도 재진술
  ---
  [2] /goal 프롬프트 (단일 markdown 코드블록)
  ---
  [3] Self-Check 6항목
  ---
  [4] 사용 안내 1줄
- 검증 명령은 사용자 프로젝트에 실제 존재하는 것만 사용한다.
- 사용자가 이미 장문 구조 요구사항 프롬프트를 주면 템플릿에 끼워 맞추지 말고 원 구조를 보존해 <docs>/goals/original-requirements/<slug>.md 에 저장하고, /goal Section 2에서 그 파일을 참조하게 한다.
- /goal 본문이 4,000자를 넘으면 <docs>/goals/<slug>.md 에 저장하고, 대화에는 "/goal 지금부터 <docs>/goals/<slug>.md 에 명시된 목표를 달성하기 위한 작업을 시작하라" 호출 프롬프트만 제공한다.
```

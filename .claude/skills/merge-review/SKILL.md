---
name: merge-review
description: 응집·의존 결합된 PR 묶음을 먼저 bottom-up으로 main에 순차 머지한 뒤, 수렴된 단일 사용자 표면에서 통합 동작을 라이브로 검토하는 작업 방식(MERGE → REVIEW). 앞 PR이 뒤 PR 전에는 dead code라 통합돼야 비로소 동작이 *존재*하는 기능군, 한 화면에서 end-to-end로 클릭 검토 가능한 묶음, 위험 프로파일이 유사하고 되돌리기가 싼 배치에 쓴다. 응집도 Go/No-Go 판정, bottom-up 순차 batch 머지 메커닉(ready → base 재타게팅 → PR별 merge commit), 머지 후 정합화, 통합 리뷰 산출물, merge-commit 단위 롤백 입도, auto-delete-head로 닫힌 하위 PR 복구, git push 자격, 직교 스코프 안티패턴을 다룬다.
when_to_use: Use when merging a cohesive, dependency-coupled group of PRs together first (bottom-up) and then reviewing the integrated behavior live on the converged surface. Choose this over the review-merge skill when earlier PRs are dead code until later ones wire them up, the group converges on one user-facing surface only exercisable end-to-end after integration, the batch shares one risk profile, and rollback is cheap. Mentions "merge-review", "merge-first", "MERGE → REVIEW", "묶음 먼저 머지하고 통합 리뷰", "bottom-up 배치 머지". Pairs with the review-merge skill (the inverse REVIEW → MERGE mode); §2 decides which.
---

# Merge-First → Review (MERGE → REVIEW)

## 역할

이 스킬은 **응집·의존 결합된 PR 묶음을 먼저 main에 순차 머지하고, 수렴된 단일 표면에서 통합 동작을 라이브로 검토**하는 작업 방식을 규정한다. 굽는 대상은 PR 하나하나가 아니라 **통합돼야 비로소 *존재*하는 기능군**이다. 묶음이 잘 통합되면, 사람이 한 화면에서 end-to-end로 클릭해 검토할 수 있는 단일 표면과 그 표면을 대상으로 한 통합 리뷰 산출물이 함께 남는다.

```
응집된 PR 스택 → [merge-review] → bottom-up 순차 머지(PR별 merge commit) → 수렴된 main 표면 → 통합 라이브 리뷰 → 리뷰 산출물 + revert 입도 보존
```

자매 스킬: **review-merge**(역순 REVIEW → MERGE — 한 건씩 검증 게이트 통과 후 머지). 두 모드 중 무엇을 쓸지는 §2로 가른다.

---

# 기본 원칙

1. **변수는 "머지 시점"이 아니라 "묶음의 응집도"다.** 리뷰는 행위(behavior) 기반이고 행위는 기능별로 산다. 인간 리뷰어 효율은 **리뷰 단위 = 하나의 응집된 행동 표면**일 때 최대다.
2. **머지-우선 자체가 리뷰를 분산시키는 게 아니다.** 분산의 원인은 **직교(orthogonal) 스코프를 한 단위에 묶는 것**이다(§6 안티패턴). 의존-결합된 묶음은 머지해야 비로소 라이브 동작이 *존재*하므로, 이때 머지-우선이 리뷰를 *돕는다*.
3. **bottom-up으로 한 스텝씩 머지한다.** 몰아치지 않는다 — GitHub mergeability 재계산이 못 따라오면 "base branch was modified"가 난다.
4. **PR별 merge commit으로 머지한다(squash 아님).** batch 머지여도 각 기능이 개별 revert 단위로 남아야 한다(§5.1).
5. **해소 즉시 영속화한다.** 머지가 끝나면 수렴 표면을 대상으로 한 통합 리뷰 산출물을 남기고, 이 방법론의 항구 규칙은 프로젝트 하네스에 박는다(§5.4).
6. 출력에 분석·이론을 넣지 않는다. 행동(판정·머지·정합화·리뷰 산출)만 수행한다.

> 한 줄 판정: **"이 묶음을 한 화면에서 end-to-end로 클릭 검토할 수 있는가?"** — 예면 머지-우선.

---

# 1. 핵심 명제 — 변수는 "머지 시점"이 아니라 "묶음의 응집도"

리뷰는 행위(behavior) 기반이고 행위는 기능별로 산다. 따라서 인간 리뷰어 효율은 **리뷰 단위 = 하나의 응집된 행동 표면**일 때 최대다.

- 머지-우선 *자체*가 리뷰를 분산시키는 게 아니다. **직교(orthogonal) 스코프를 한 단위에 묶는 것**이 분산시킨다(§6 안티패턴).
- 의존-결합된 묶음은 **머지해야 비로소 라이브 동작이 *존재*** 한다. 이때 머지-우선이 리뷰를 *돕는다*.

---

# 2. 적용 조건 (Go / No-Go) — 모드 선택

| 신호 | **MERGE → REVIEW (이 스킬)** | REVIEW → MERGE (review-merge) |
| --- | --- | --- |
| 의존 구조 | **스택/결합** — 앞 PR이 뒤 PR 전엔 dead code | 독립 — 각자 출고 가능 |
| 검토 표면 | **하나의 사용자 표면으로 수렴**(로그인→목록→렌더→403/404) | 표면·진입점이 서로 다름 |
| 정확성의 위치 | **런타임**(auth·접근제어·렌더 — diff로 안 보임) | 소스/단위 테스트로 충분 |
| 위험 프로파일 | 묶음 내 유사 | 상이(보안 변경 vs 카피 수정을 섞지 말 것) |
| 되돌리기 비용 | 싸다(§5.1) | — |

**Go(모두 충족 권장):** 의존-결합 + 단일 수렴 표면 + 런타임 검증 필요 + 되돌리기 저렴.
**No-Go(하나라도면 review-merge / 분리):** 직교 기능, 위험도 상이, 독립 출고 단위.

---

# 3. 머지 우선이 주는 효과

1. **죽은 코드가 살아난다.** 스택 하단(예: 인가 게이트)은 상단(라우트 연결) 전까지 *호출처 0*인 primitive다. 머지해야 **실제 HTTP 403/404/200**이 처음으로 존재 → 검토가 "시뮬레이션"에서 "실제 클릭"으로.
2. **단일 검토 기준.** preview N개(각자 조각 빠진)를 저글링하는 대신, *하나의 배포·URL·DB 상태*에서 end-to-end.
3. **런타임-only 버그 포착.** auth/렌더는 정확성이 소스가 아니라 런타임에 있다(RSC 경계 식별 버그, 보안 헤더로 인한 임베드 차단 등은 diff로 안 보이고 라이브에서만 드러남).
4. **스택 유지비 종료.** base 재타게팅·parent-as-ancestor rebase 연쇄가 bottom-up 머지로 영구 해소(behind 상태가 머지 시점에 자연 소멸). no-cascade 규칙과 정렬.
5. **후속 작업의 안정 토대.** 다음 트랙이 *움직이는 스택*이 아니라 *고정된 main 표면*을 대상으로 삼는다.

---

# 4. 실행 시퀀스 (반복 가능한 절차)

## 4.1 사전 — 응집도 확인 + 순서 결정
- §2 Go 조건 통과 확인. 머지 순서 = 스택 **bottom-up**(의존 하단부터).
- 머지 방식은 기존 이력과 일치 — 이 방법론은 **PR별 merge commit**(squash 아님)을 전제로 한다(§5.1 입도 보존).
- 상태 점검:
  ```bash
  gh pr list --state open --json number,headRefName,baseRefName,isDraft,mergeable,mergeStateStatus \
    --jq 'sort_by(.number)[] | "#\(.number) \(.headRefName) base=\(.baseRefName) draft=\(.isDraft) \(.mergeable)/\(.mergeStateStatus)"'
  git log origin/main --merges --oneline -5   # 기존 머지 방식(merge commit/squash) 확인
  ```

## 4.2 순차 batch 머지 (PR 하나당 한 스텝, bottom-up)
```bash
# 1) main에 체크아웃(삭제될 브랜치 위에 있지 않게)
git checkout main

# 2) 각 PR: draft면 ready → 부모가 main에 들어간 뒤 base를 main으로 재타게팅 → 머지
gh pr ready <child>                       # draft 해제 (이미 ready면 생략)
gh pr edit  <child> --base main           # diff가 자식 고유 변경만 남도록
gh pr merge <child> --merge               # PR별 merge commit
gh pr view  <child> --json state,mergedAt --jq '.state'   # MERGED 확인 후 다음으로
```
- **한 스텝씩** 진행한다. 몰아치면 GitHub mergeability 재계산이 못 따라와 "base branch was modified" 발생. (이 환경은 foreground `sleep`이 막혀 있을 수 있으니, 스텝을 분리 호출해 자연 지연을 준다.)
- **auto-delete-head 예방:** 부모 머지로 head가 자동 삭제되면 그 head를 base로 둔 **다음 PR이 CLOSED**된다. 매 스텝에서 *바로 다음* PR의 base를 미리 main으로 옮겨 두면 안전(§5.2).

## 4.3 머지 후 정합화 (main에서)
```bash
git fetch origin --prune && git checkout main && git merge --ff-only origin/main
git branch -D <머지된 로컬 브랜치들>
rm -rf .next lib/generated
pnpm manifest:build && pnpm lessons:build && pnpm db:generate   # 머지로 새로 요구되는 생성물 재생성
gh pr edit <남은 다음 PR> --base main                           # 다음 트랙 base 정합
```
- **크로스-PR 일관성 정리:** 스택 진행 중 *브랜치별로 보류*해 둔 일관성 작업(용어 통일, 공유 주석, 네이밍)을 **머지 후 main에서 한 번에** 적용한다.
  - 보류 항목은 각 PR 코멘트로 추적 → 머지 후 **전수 grep으로 회수**(동음이의 오탐 제외).
    ```bash
    grep -rn "<old-term>" --include='*.ts' --include='*.tsx' --include='*.md' . | grep -vE 'node_modules|\.next/'
    ```
- 검증 게이트는 머지 전후 모두: `pnpm typecheck && pnpm lint && pnpm test`(+ DB `RUN_DB_TESTS=true`).
  - 게이트 권위 기준은 **CLI tsc**. 생성물 누락으로 인한 `Cannot find module ...registry`는 코드 문제가 아니라 `manifest:build && lessons:build` 미실행이다.

## 4.4 통합 리뷰 산출물 (이 방법론의 *리뷰* 단계)
머지가 끝나면 **수렴된 표면을 대상으로** 리뷰 아웃라인 문서를 남긴다. 항목 체계:
1. **변경 콤팩트 요약** — PR별 핵심·파일·결정 표. "무엇이 라이브가 됐는가"를 명시.
2. **역할별 행위 검토 시나리오** — 사용자 역할별(예: 일반 사용자 / 관리자) 실제 클릭·요청 시나리오와 기대 응답(200/403/404, redirect, 빈/오류 상태). 머지로 라이브가 됐으므로 *실제로* 굴려볼 수 있다.
3. **누적 임의 의사결정 — 유지/수정 질문** — 설계 결정 로그의 재량 선택을 열거하고 *유지 / 수정 / 후속이슈화* 결정을 요청한다.

---

# 5. 리스크와 안전판

## 5.1 롤백 입도 — "한 번에 머지"해도 기능별 revert 보존
**squash가 아니라 PR별 merge commit**으로 머지하므로, batch 머지여도 각 기능이 개별 revert 단위로 남는다.
```bash
git revert -m 1 <특정 PR 머지 SHA>   # 그 PR만 정확히 되돌림, 나머지는 그대로
```
이것이 batch 머지의 최대 잠재 단점(추적·롤백 입도 손실)을 상쇄한다 → 머지-우선이 *저위험 기본값*인 근거.

## 5.2 auto-delete-head → 하위 PR 자동 CLOSED (가장 흔한 사고)
부모 머지로 head가 자동 삭제되고 그 head를 base로 둔 하위 PR이 **머지가 아니라 CLOSED**된다. base 브랜치가 사라져 `gh pr reopen`도 바로는 실패한다.
- **예방:** 부모 머지 전 하위 PR base를 main으로 먼저 옮긴다.
- **복구:** base ref를 잠시 복원 → reopen → base를 main으로 → ref 재삭제.
  ```bash
  sha=$(git rev-parse <삭제된 base의 head>)   # 보통 그 PR 머지 커밋의 2번째 부모 / 로컬 dangling commit
  gh api -X POST repos/<owner>/<repo>/git/refs -f ref=refs/heads/<deleted-base> -f sha=$sha
  gh pr reopen <closed PR>
  gh pr edit  <closed PR> --base main
  gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<deleted-base>
  gh pr view <closed PR> --json state,baseRefName --jq '.state+" base="+.baseRefName'   # OPEN base=main 확인
  ```

## 5.3 환경 — `git push` 자격 + 배포 최소화
- 이 환경은 `git push` HTTPS가 미인증일 수 있다(`gh`만 인증). 푸시 전 한 번: `gh auth setup-git`.
- 정합화 커밋(예: 용어 통일 + 리뷰 문서)은 **논리 단위로 나눠 커밋하되 push는 1회**로 묶어 prod 배포 최소화.
- 생성물(`lib/generated/*`)은 gitignore 확인 후 커밋에서 제외: `git check-ignore <path>`.

## 5.4 불변 규칙을 하네스에 고정
이 방법론의 항구 규칙은 한 번 정하면 프로젝트 하네스에 박아, 이후 모든 배치 머지에서 자동으로 지켜지게 한다.
- 고정할 규칙: **PR별 merge commit으로 머지(revert 입도 보존)** · **다음 PR base를 부모 머지 *전에* main으로 이동** · **직교 스코프를 한 머지 단위에 섞지 않음** · **여러 브랜치 일괄 push 금지(no-cascade)**.
- 반영 위치(Claude Code): `CLAUDE.md`. 반복 절차가 정형화됐으면 `.claude/commands/`의 슬래시 명령으로, 머지 직후 자동 점검이 필요하면 `.claude/settings.json`의 hook으로 승격한다.

---

# 6. 안티패턴 — 직교 스코프 혼합

머지-우선이라도 **무관한 기능을 한 머지 단위에 섞으면** 리뷰가 정확히 저해된다:
- 적용할 **단일 멘탈 모델이 없어** 파일마다 컨텍스트 스위칭.
- 라이브 검토가 N개 표면으로 쪼개져 **하나의 흐름으로 굴려볼 수 없음**(라이브 검토 효율 저하의 직접 원인).
- 회귀 **귀속·bisect 입도 손실**, 위험 프로파일 혼합(보안+표현이 같은 단위).

→ 직교 트랙은 **그 트랙끼리만** 묶는다. (예: "사용자 접근·렌더 arc"와 "이벤트 수집 트랙"은 분리.)

---

# 7. 체크리스트

**Go/No-Go (착수 전):**
- [ ] 묶음이 의존-결합 또는 단일 사용자 표면으로 수렴하는가
- [ ] 한 화면에서 end-to-end 클릭 검토가 가능한가
- [ ] 위험 프로파일이 유사한가(보안/표현 혼합 아님)
- [ ] PR별 merge commit으로 머지해 revert 입도를 보존하는가

**실행:**
- [ ] bottom-up 순서, PR별 ready → retarget(main) → merge, 각 MERGED 확인
- [ ] 다음 PR base를 사전에 main으로(또는 auto-close 복구 §5.2)
- [ ] 머지 후 생성물 재생성 + 보류한 크로스-PR 정합화 일괄 적용(전수 grep, 동음이의 제외)
- [ ] 검증 게이트 통과(typecheck/lint/test, DB 통합 포함)
- [ ] 통합 리뷰 산출물 작성(§4.4의 3항목)
- [ ] `gh auth setup-git` 후 push 1회(논리 커밋 분리, 배포 최소화)
- [ ] 불변 규칙을 하네스(`CLAUDE.md`)에 고정(§5.4)

---

# 8. 적용 사례 (레퍼런스 인스턴스)

응집 arc 5건을 한 번에 bottom-up 머지한 사례:
- **묶음:** `인가 게이트 → 사용자 진입 플로우 → 콘텐츠 렌더에 게이트 연결 → 그 관리자 대응 → 동일 표면 목업`. 여러 별개 기능이 아니라 **세션/인가/콘텐츠-매니페스트 기반을 공유하는 단일 arc**(사용자·관리자가 접근 정책 하에 콘텐츠를 열람) → §2 Go.
- **수행:** bottom-up 순차 머지(merge commit) → 라우트 연결 PR 머지로 인가 게이트가 **실제 라우트에 연결되어 라이브** → 머지 후 용어 통일을 main에서 일괄 → 통합 리뷰 아웃라인(§4.4) 작성.
- **겪은 리스크:** 마지막 PR 머지로 그 head가 자동 삭제 → 그것을 base로 둔 다음 트랙 PR이 CLOSED → §5.2 절차로 OPEN(base=main) 복구. `git push` 미인증 → `gh auth setup-git`으로 해소.
- **교훈:** 효과는 "통합돼야 라이브가 존재" + "수렴 표면 단일 검토". 안전은 "merge-commit revert 입도" + "auto-delete-head 사전 base 이동".

---

# 9. 환경 적응 메모 (예시 바인딩 — 다른 repo면 해당 값으로 치환)

- 툴체인: `unset -f node npm npx pnpm corepack` + `PATH=$HOME/.nvm/versions/node/v24.15.0/bin`.
- 생성물: `pnpm manifest:build && pnpm lessons:build`, ORM: `pnpm db:generate`. DB 통합: `RUN_DB_TESTS=true`.
- 빌드: `set -a; . ./.env; set +a; pnpm build`(비밀값 OS 레벨 주입, 컨텍스트로 읽지 않음).
- 운영 지식 문서(이 repo): `main/docs/review-outline/PR_MERGE_REVIEW_PROCEDURE.md`, 통합 리뷰 산출물 예시 `main/docs/review-outline/REVIEW_OUTLINE_PR42-46_post-merge.md`.

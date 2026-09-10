---
name: review-merge
description: PR 스택/집합을 한 건씩 검토하고, 매 건이 검증 게이트를 통과한 뒤에만 머지하는 human-in-the-loop 순차 리뷰 방식(REVIEW → MERGE). PR이 독립이거나 출고 전 각 건이 명시적 게이트를 통과해야 할 때, PR별 리뷰 레코드가 필요할 때, 사람이 승인마다 원격 머지할 때 쓴다. PR 한 건 리뷰 사이클, 머지 전 검증 게이트, 머지 후 로컬 정리·base 재타게팅, no-cascade push 규칙, 스택 머지 gotcha(auto-delete-head로 닫히는 하위 PR, draft PR, git push 자격, stale 생성물)를 다룬다. Use when reviewing a stack or set of PRs one at a time, gating each with a verification pass before it is merged (human-in-the-loop, REVIEW → MERGE). Choose this over the merge-review skill when PRs are independent or must each clear an explicit gate before shipping, when per-PR review records matter, or when a human reviewer merges remotely after each approval. Mentions "review-merge", "review-first", "REVIEW → MERGE", "PR 한 건씩 게이트 후 머지", "검증 게이트". Pairs with the merge-review skill (the inverse MERGE → REVIEW mode); §1 decides which.
---

# Review-First → Merge (REVIEW → MERGE)

## 역할

이 스킬은 **PR을 한 건씩 검토하고, 매 건이 검증 게이트를 통과한 뒤에만 머지**하는 작업 방식을 규정한다. 머지 *전*에 PR별로 차단 게이트를 두는, human-in-the-loop 순차 리뷰 방법론이다. 굽는 대상은 통합 표면이 아니라 **출고 단위로 독립적인 PR 한 건 한 건**이다. 각 건이 잘 검토되면, 게이트를 통과한 머지 이력과 PR별 리뷰 레코드가 함께 남는다.

```
PR 스택/집합 → [review-merge] → 한 건 리뷰 → 검증 게이트 통과 → 사람이 원격 머지 → 머지 후 정리·base 재타게팅 → 다음 건
```

자매 스킬: **merge-review**(역순 MERGE → REVIEW — 묶음을 먼저 통합 머지하고 수렴 표면에서 라이브 검토). 두 모드 중 무엇을 쓸지는 §1로 가른다.

---

# 기본 원칙

1. **리뷰는 행위(behavior) 기반이고 행위는 기능별로 산다.** 리뷰 단위 = *하나의 응집된 검토 표면*일 때 인간 리뷰어 효율이 최대다.
2. **머지 *전*에 게이트한다.** 매 PR이 검증 게이트(§4)를 통과하기 전에는 머지하지 않는다. 게이트의 권위 기준은 에디터 LSP가 아니라 **CLI 결과**다.
3. **역할을 분담한다.** *리뷰·수정*은 에이전트(브랜치에 커밋·단일 push). **실제 머지 결정과 원격 머지는 사람**이 한다. AI 수정안을 승인 전 자동 머지하지 않는다.
4. **no-cascade.** 스택 동기화를 위해 여러 브랜치를 일괄 push하지 않는다(§6). 변경한 브랜치 하나만 push한다.
5. **불변식(스택)을 지킨다.** 부모가 자식의 조상으로 남아야 한다. 부모를 main에 머지하면 자식 base를 main으로 재타게팅하고, 절대 자식에 직접 main을 머지해 조상 관계를 깨지 않는다.
6. 출력에 분석·이론을 넣지 않는다. 행동(리뷰·게이트·머지 후 정리)만 수행한다.

> 한 줄 판정: **"이 변경을 머지 *전에* PR 단위로 통과시켜야 하는가?"** — 예면 이 스킬.

---

# 1. 언제 이 스킬인가 (모드 선택)

리뷰는 본질적으로 **행위(behavior) 기반**이고 행위는 기능별로 산다. 따라서 리뷰 단위 = *하나의 응집된 검토 표면*일 때 인간 리뷰어 효율이 최대다. 이 원칙에서 두 모드가 갈린다.

| 신호 | **REVIEW → MERGE (이 스킬)** | MERGE → REVIEW (merge-review) |
| --- | --- | --- |
| PR 간 관계 | **독립**(서로 호출 안 함, 각자 출고 가능) 또는 출고 전 게이트가 필수인 결합 | 의존-결합(앞 PR이 뒤 PR 전엔 dead code) |
| 검토 표면 | PR마다 자기 표면에서 검토 가능 | 하나의 사용자 표면으로 수렴해야 동작이 *존재* |
| 위험 프로파일 | **상이**(보안 vs 표현을 한 머지에 섞지 않음) | 묶음 내 유사 |
| 요구사항 | 출고 전 PR별 차단·리뷰 레코드 필요 | 통합 후에야 라이브 검토 가능 |

**이 스킬을 쓴다:** 각 PR을 독립적으로/출고 전에 게이트해야 할 때, PR별 리뷰 기록이 필요할 때, 사람이 매 승인 후 원격 머지하는 흐름일 때.

---

# 2. 멘탈 모델

- **토폴로지:** PR이 선형 스택일 수도(각 PR base = 직전 PR 브랜치), 평면적 독립 집합일 수도 있다. 스택이면 **아래(가장 의존 하단)부터 위로** 리뷰·머지한다.
- **역할 분담:** *리뷰·수정*은 에이전트(브랜치에 커밋·단일 push). **실제 머지 결정과 원격 머지는 사람**이 한다. (AI 수정안은 승인 전 자동 머지하지 않는다.)
- **불변식(스택):** 부모가 자식의 조상으로 남아야 한다. 부모를 main에 머지하면 자식 base를 main으로 재타게팅한다(§5). 절대 자식에 직접 main을 머지해 조상 관계를 깨지 않는다.

---

# 3. PR 한 건 리뷰 사이클

각 PR마다 아래 5단계를 반복한다.

1. **오리엔테이션** — 핵심 리뷰 표면을 먼저 제시한다.
   ```bash
   # 이슈/스펙 + main 대비 변경 범위 + 관련 설계 결정
   git diff --stat main...<branch>
   # (보안/인가/렌더 PR이면) 해당 결정 로그 항목과 정책 문서를 함께 띄운다
   ```
   - 호출처 확인은 리뷰 방향을 잡는 핵심: `grep -rn "<새 공개 API/래퍼>" app/ lib/` 로 "이 PR이 실제로 무엇을 라이브로 만드는가 / 아직 dead code인가"를 명확히 한다.
2. **대화형 리뷰** — 질문에 **코드 근거**로 답한다(파일:라인). 동작 증거가 필요하면:
   - 헤더/응답: dev 서버 + `curl -I`(상태코드·보안 헤더).
   - 렌더/UI: 브라우저. RSC 경계처럼 **런타임에만 드러나는** 동작은 반드시 실제로 띄워 확인.
3. **수정(있으면)** — **그 PR의 owning 브랜치에만** 커밋한다. 게이트(§4) 통과 후 **그 브랜치만** push. 여러 브랜치를 일괄 push하지 않는다(§6 no-cascade).
4. **PR 본문 최신화** — main 대비 전체 변경을 누락 없이 반영한다.
   ```bash
   gh pr edit <n> --body "..."   # API 호출 — 배포 트리거 없음
   ```
5. **사람이 만족하면 원격 머지** — 머지 방식은 기존 이력과 일치시킨다(merge commit vs squash). merge commit이면 PR별 revert 입도가 보존된다.

---

# 4. 검증 게이트 (수정·머지 전 필수)

게이트의 **권위 기준은 CLI** 결과다. 에디터 LSP의 stale 진단(특히 브랜치 전환 직후의 Prisma/모듈 오류)은 무시한다.

```bash
# 0) 툴체인 정규화 — 버전 매니저 함수가 패키지 매니저를 가로채는 문제 방지
#    (이 환경 예: nvm 함수 unset + node 경로 우선)
unset -f node npm npx pnpm corepack 2>/dev/null
export PATH="$HOME/.nvm/versions/node/v<버전>/bin:$PATH"

# 1) 브랜치 전환 오염 제거 + 생성물 재생성
rm -rf .next lib/generated
pnpm db:generate                 # 스키마가 다른 브랜치면 ORM 클라이언트 재생성
pnpm manifest:build && pnpm lessons:build   # 콘텐츠/렌더 생성물이 있으면

# 2) 정적 + 단위
pnpm typecheck && pnpm lint && pnpm test

# 3) 빌드 (비밀값은 OS 레벨로만 주입 — 컨텍스트로 읽지 않는다)
set -a; . ./.env; set +a; pnpm build

# 4) DB 통합 (해당 PR이 DB를 건드리면)
RUN_DB_TESTS=true pnpm test:integration
```

**게이트 gotcha(일반화):**
- **통합 게이트 환경변수는 정확한 값 일치**일 수 있다. 예: `RUN_DB_TESTS=true`(문자열 `"true"`)가 아니면 테스트가 **skip**된다. `=1`은 안 먹는 식. 게이트가 "0 fail"이 아니라 "all skipped"면 이걸 의심.
- **하드코딩된 어서션**(예: "wrote 3 lessons")은 콘텐츠 수가 바뀌면 깨진다 → content-derived 어서션으로.
- 생성물(`lib/generated/*`)이 빠져 `Cannot find module ...registry` 류 typecheck 에러가 나면 코드 문제가 아니라 **생성 스크립트 미실행**이다. `manifest:build && lessons:build`로 해소.
- `| tail`로 파이프하면 종료코드가 가려진다. 통과 여부는 `; echo "exit=${pipestatus[1]}"`(zsh) / `${PIPESTATUS[0]}`(bash)로 확인하거나, `cmd && echo OK` 대신 실제 출력의 에러 라인을 본다.

---

# 5. 머지 후 로컬 정리 (매 머지마다 반복)

사람이 PR을 원격 머지한 직후:

```bash
git fetch origin --prune                                # 삭제된 원격 ref 정리
gh pr list --state open                                 # 사라진 PR 확인 = 다음 리뷰 대상
git checkout main && git merge --ff-only origin/main     # 로컬 main을 머지본으로 FF
for b in $(git branch --merged main | grep -vE '^\*| main$'); do git branch -d "$b"; done
rm -rf .next lib/generated                               # 생성물 오염 제거
git checkout <다음 리뷰 브랜치> && pnpm db:generate        # 다음 PR로 이동 + 클라이언트 재생성
```

**다음 PR base 재타게팅(중요):**
```bash
gh pr view <다음 PR> --json baseRefName --jq .baseRefName   # feat/<직전>이면 main으로
gh pr edit <다음 PR> --base main
```
- 원격 head가 자동 삭제되지 않는 설정이면 GitHub가 자동 재타게팅하지 않으니 **수동**으로 한다.
- 반대로 **auto-delete-head-branch on merge가 켜져 있으면**: 부모 머지 시 head가 자동 삭제되며 그 head를 base로 둔 **하위 PR이 CLOSED**된다(§7.1). 이 경우 *부모 머지 전에* 하위 PR base를 먼저 main으로 옮겨 두면 예방된다.

---

# 6. No-Cascade 규칙

스택 동기화를 위해 **여러 브랜치를 일괄 push(cascade)하지 않는다.** PR이 열린 브랜치는 push마다 **preview 배포가 1건씩** 생긴다(예: Vercel). 변경한 브랜치 **하나만** push하고, 나머지의 behind 상태는 **머지 시점에 자연 reconcile**되게 둔다.

**하네스에 고정:** no-cascade는 한 번 어기면 preview 배포가 무더기로 발생하는 항구 규칙이므로 프로젝트 하네스에 박아 재발을 막는다 — Codex는 `AGENTS.md`. 머지 후 정리(§5)·base 재타게팅처럼 정형화된 절차는 `.agents/skills/`의 절차 스킬로 승격한다.

---

# 7. 알려진 gotcha와 해결

## 7.1 auto-delete-head → 하위 PR 자동 CLOSED
repo가 머지 시 head 자동 삭제면, 부모(=하위 PR의 base) 머지로 하위 PR이 **머지가 아니라 CLOSED**된다.
- **예방:** 부모 머지 전 하위 PR base를 main으로 먼저 옮긴다.
- **복구:** base ref를 잠시 복원 → reopen → base를 main으로 → ref 재삭제.
  ```bash
  gh api -X POST repos/<owner>/<repo>/git/refs -f ref=refs/heads/<deleted-base> -f sha=<그 브랜치 head sha>
  gh pr reopen <closed PR> && gh pr edit <closed PR> --base main
  gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<deleted-base>
  ```
  (삭제된 브랜치 head sha는 그 PR의 머지 커밋의 두 번째 부모이거나, 로컬에 남은 dangling commit이다.)

## 7.2 draft PR은 머지 전 ready 필요
```bash
gh pr ready <n>      # 그 뒤 gh pr merge
```

## 7.3 git push 자격
이 환경은 `git push` HTTPS가 미인증일 수 있다(`gh`만 인증). 푸시 전 한 번:
```bash
gh auth setup-git    # gh 토큰을 git 자격 헬퍼로 연결
```

## 7.4 stale LSP / 생성물
브랜치 전환 직후 에디터가 옛 Prisma 타입·없는 모듈을 보고할 수 있다. **CLI tsc가 권위 기준**. `rm -rf .next lib/generated && pnpm db:generate (&& manifest:build && lessons:build)`로 재생성.

---

# 8. 리뷰에서 반복 확인하는 표면 (도메인별 체크)

- **보안/인증 PR:** 토큰 해시·단회·만료, 세션 쿠키 속성(httpOnly·Secure·SameSite)·해시 저장·멀티세션, 인가 매트릭스(등록×가시성 → 200/403/404), 존재 비노출(403 vs 404 정책), 시크릿 미노출.
- **렌더/콘텐츠 PR:** sanitize 경계, 보호 라우트에서 위험 실행 함수 금지, **자식 props를 introspect하는 컴포넌트는 서버 렌더(RSC)에서 type 동일성 대신 props로 식별**(client reference로 type이 바뀜).
- **임베드/헤더:** `X-Frame-Options`(DENY는 동일 출처 iframe까지 차단 → 필요시 SAMEORIGIN), 외부 임베드는 대상 호스트 헤더 의존, CSP 추가 시 `frame-src` 화이트리스트.

---

# 9. 체크리스트

**PR 한 건:**
- [ ] 오리엔테이션(스펙 + diff --stat + 호출처 grep + 관련 결정)
- [ ] 질문에 코드 근거로 응답, 런타임 동작은 실제로 띄워 확인
- [ ] 수정은 owning 브랜치에만, 게이트 통과 후 **그 브랜치만** push
- [ ] PR 본문 main 대비 전수 최신화(`gh pr edit --body`)
- [ ] 검증 게이트 green(typecheck/lint/test/build, DB는 `RUN_DB_TESTS=true`)
- [ ] 사람이 원격 머지

**머지 후:**
- [ ] fetch --prune → open PR 확인 → main FF → 머지된 로컬 브랜치 삭제
- [ ] `rm -rf .next lib/generated` + 생성물 재생성 + 다음 브랜치 checkout
- [ ] 다음 PR base를 main으로(또는 auto-close 복구 §7.1)
- [ ] no-cascade 규칙을 하네스(`AGENTS.md`)에 고정(§6)

---

# 10. 환경 적응 메모 (예시 바인딩 — 다른 repo면 해당 값으로 치환)

일반 절차의 구체 바인딩 예시:
- 툴체인: `unset -f node npm npx pnpm corepack` + `PATH=$HOME/.nvm/versions/node/v24.15.0/bin`.
- 패키지 매니저: `pnpm`. 생성물: `pnpm manifest:build && pnpm lessons:build`, ORM: `pnpm db:generate`.
- DB 통합 게이트: `RUN_DB_TESTS=true`(문자열 일치). 로컬 Postgres 127.0.0.1:54322.
- 빌드: 비밀값은 `set -a; . ./.env; set +a; pnpm build`로 OS 레벨 주입(컨텍스트로 읽지 않음).
- 운영 지식 문서(이 repo): `main/docs/review-outline/PR_REVIEW_MERGE_PROCEDURE.md`.

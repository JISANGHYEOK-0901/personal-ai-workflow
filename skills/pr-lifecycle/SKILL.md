---
name: pr-lifecycle
description: Create and review pull requests, merge an authorized PR, and finish by synchronizing the base and removing the merged task branches. Use for PR creation, review, merge, or post-merge cleanup requests; preserve the user's requested stage and existing permissions.
---

# PR 작업 수명주기

PR 생성 → 변경·검증 검토 → 승인된 머지 → base 동기화 → 해당 작업의 로컬·원격 브랜치 정리까지 이어지는 절차다. 사용자가 요청한 단계와 이미 승인한 범위에서 진행한다. 사용자가 이 개인 기본 설정을 채택한 환경에서 “PR해줘”는 검증·검토·PR 생성·머지·브랜치 정리까지의 요청으로 처리한다. “PR만 생성”, “머지하지 마”, “검토만”처럼 제한한 요청은 그 단계에서 종료한다. 다른 사용자의 환경이나 미채택 프로젝트에 이 권한 해석을 자동 이식하지 않는다. 머지 요청에는 아래 조건을 통과한 해당 작업 브랜치 정리가 포함되며 별도 반복 승인을 요구하지 않는다.

## 1. 현재 단계와 대상 확인

저장소·remote·PR 번호·base/head 이름·HEAD SHA·작업 소유 범위를 확인한다. 기본 브랜치·머지 방식·필수 검증은 프로젝트 설정과 기존 정책에서 읽는다. main/develop이나 squash/merge commit을 보편 기본값으로 삼지 않는다.

로컬 diff·미추적 파일·worktree를 확인한다. 사용자 파일을 일괄 stage·stash·reset·clean하지 않는다. ai-input 전체는 항상 제외한다. 동일 목표의 열린 PR이 있으면 갱신하고 중복 PR을 만들지 않는다.

작업 시작과 검증·push·머지 직전에 base SHA와 head SHA를 확인해 검토 기준으로 남긴다. 동시 세션·worktree, base/head 전진, 공유 branch 또는 PR 스택이 있으면 [동시 작업과 base 전진](references/concurrency.md)을 읽고 적용한다. 변경 경로 비겹침이나 mergeability만으로 기존 검증을 승계하지 않는다.

## 2. PR 생성·검토

작업 브랜치를 사용하고 관련 파일만 커밋한다. 실제 검증 명령과 결과를 확인한 뒤 해당 브랜치만 push한다. PR 본문은 문제·최종 동작·검증·미검증/한계를 설명하며 여러 줄 본문은 파일 또는 구조화 인자로 전달한다.

PR 제목과 본문은 항상 한글로 작성한다. 코드 식별자·명령·제품명은 정확한 원문을 유지할 수 있다. 제목은 `[#실제번호] 변경 요약`, 본문에는 `PR 번호: #실제번호`를 명시하고 최종 보고에도 같은 번호와 URL을 포함한다. 번호는 호스팅 서비스가 부여한 실제 PR 번호를 사용하며 다음 번호를 추정하지 않는다. 신규 생성 시에는 한글 제목·본문으로 생성한 뒤 반환된 번호로 제목·본문을 즉시 갱신하고 반영을 확인한다. 기존 PR은 조회한 번호를 사용한다.

base 대비 전체 diff와 실제 기능 영향을 [결정 분류와 diff 검토](../execute/references/decision-diff-review.md)에 따라 검토한다. staged·unstaged·관련 미추적 파일을 포함하고 각 변경을 요구·기결정에 연결한다. 테스트·CI·`git diff --check` 성공을 의미적 검토로 대신하지 않는다. 필요한 계약·통합·문서 검증과 CI를 확인한다. CI가 없으면 미설정이라고 명시하며 통과로 꾸미지 않는다. 발견한 MINOR 결함은 허용된 범위에서 수정하고 변경 때문에 무효화된 검증과 최종 diff를 다시 확인한다. MAJOR 결정이나 BLOCKER는 의존 단계 전에 해결하며 필수 프로젝트 게이트는 생략하지 않는다.

리뷰 근거를 PR 번호·base SHA·head SHA·검증 대상 통합 결과와 연결해 기록한다. 인간 승인이 필요한 정책이면 그것을 AI 자체 검토로 대체하지 않는다. PR 생성까지만 요청받았다면 URL과 검증 상태를 보고하고 종료한다.

## 3. 승인된 머지

실행 직전 PR이 OPEN인지, 검토한 base/head SHA 및 대상 branch와 일치하는지, mergeability·필수 CI·리뷰·미해결 차단 사항을 확인한다. base 또는 head가 바뀌면 의미 영향과 달라진 검증 조건을 다시 검토한다. required check가 대기·실패거나 검토 근거가 미확인인 상태를 성공으로 간주하지 않는다. admin 우회는 사용하지 않는다.

head를 base로 삼는 열린 하위 PR과 저장소의 자동 head 삭제 설정을 확인한다. 의존 PR이 있으면 자동 삭제·재타게팅 영향부터 해결한다. 타인 PR의 base나 브랜치를 임의 변경하지 않는다. 이 경계가 미해결이면 머지·삭제를 보류하고 구체적인 필요한 결정을 알린다.

허용된 머지 방식으로 검토한 HEAD에 조건을 걸어 머지한다. GitHub CLI라면 `gh pr merge <번호> --<허용방식> --match-head-commit <검토SHA>`를 사용한다. 이 head 조건은 base 경쟁을 막지 않는다. 동시 머지 상황의 서버 보호·큐·조율 경계는 concurrency 참조를 따른다. 그 뒤 API에서 MERGED·merge commit과 실제 base 반영을 확인한다. 요청 성공이나 CLOSED만으로 머지를 단정하지 않는다.

## 4. 머지 후 정리 — 완료 조건에 포함

삭제 대상은 해당 PR의 일회성 작업 head 하나다. main/develop/release 등 상시 브랜치, 다른 작업 브랜치, fork 소유 브랜치는 삭제 대상으로 추정하지 않는다.

1. fetch 후 실제 base를 fast-forward로 동기화한다. 로컬 base가 갈라지거나 전환이 사용자 파일을 덮어쓸 경우 강제 정리하지 않는다. 가능한 조회·독립 정리는 진행하고 막힌 부분을 남긴다.
2. 로컬·원격 작업 branch tip이 머지한 PR의 head SHA 그대로인지 확인한다. 후속 커밋·다른 열린 PR·의존 PR·다른 worktree 사용이 있으면 해당 브랜치를 보존한다.
3. 원격 head가 이미 없으면 삭제 완료로 처리한다. 존재하면 확인한 SHA를 조건으로 해당 ref만 삭제한다. Git에서는 `git push --force-with-lease=refs/heads/<head>:<확인SHA> <remote> :refs/heads/<head>`로 조회 후 전진한 브랜치를 삭제하지 않도록 한다. 오류 시 무조건 재시도하지 말고 현재 ref를 재확인한다.
4. 로컬은 대상 base로 이동한 뒤 해당 branch만 삭제한다. merge commit/fast-forward이면 실제 base의 조상임을 확인하고 `git branch -d <head>`를 사용한다. 모든 merged branch를 일괄 삭제하지 않는다.
5. squash/rebase는 단순 조상 검사로 부족하다. MERGED 증거·원래 PR head와 로컬 tip 일치·base에 merge 결과 반영·작업 소유 및 미사용을 확인한 경우에만 해당 로컬 ref를 정리한다. 확증이 없으면 force 삭제하지 않고 정리 대기로 남긴다. 생성물·worktree 삭제는 별도 필요와 안전한 소유·내용 확인이 있을 때만 한다.
6. 원격 ref 부재, 로컬 branch 부재, 현재 base·원격 base 일치, 사용자 파일 보존을 확인한다. 작업 기록의 기존 ID에 PR·merge SHA·정리 결과를 갱신한다.

보고는 `머지 완료·정리 완료` 또는 `머지 완료·정리 대기(이유)`를 구분한다. 정리 가능한 브랜치를 남긴 채 전체 작업 완료라고 보고하지 않는다. 재실행 시 이미 완료한 삭제는 무변경이며, 남은 안전한 단계만 이어간다.

# v0.1 검증 기록

검증 시각: 2026-09-10 18:13 KST. 대상은 공통 지침·execute·동기화 도구·원본 보관·개인 기록 제외다.

## 실제 수행

| 검사 | 결과 | 확인 범위 |
|---|---|---|
| skill-creator quick_validate.py | PASS | execute 이름·frontmatter·기본 구조. 시스템 Python에 yaml이 없어 임시 venv에 PyYAML을 설치해 실행. 프로젝트 의존성은 변경하지 않음 |
| sync_skills.py --write / --check | PASS | 1개 정본, 도구 3종, 6개 설치 파일 일치 |
| 임시 저장소 동기화 검사 | PASS | check는 무변경, 초기 생성, 무변경 재실행 시 mtime 유지, drift 탐지·수정 |
| 충돌·경계 검사 | PASS | 알 수 없는 기존 파일 보존, 전체 경로 사전 검사 후 쓰기, symlink 거부 |
| 원본 해시·라이선스 | PASS | 이동한 41개 파일의 SHA-256이 초기 sources.json과 일치, 8개 라이선스 존재 |
| 활성 목록 검사 | PASS | 각 도구 skills/ 아래 execute만 존재, 보관 폴더에 SKILL.md 엔트리 없음 |
| ai-input 제외 | PASS | 현재 추적 파일 0개, 별도 임시 Git 저장소에서 git add . 후 공유 문서만 추적 |
| git diff --check | PASS | 추적 파일 변경의 공백 오류 없음 |

## 아직 검증하지 않은 것

- 새 세션의 도구별 실제 스킬 발견·선택 및 공통 지침 준수. 파일 동기화는 행동 동등성을 증명하지 않는다.
- V01·V05·V06·V07·V09 등 실제 AI 작업 행동. V08은 임시 Git 저장소로 확인했다.
- 소규모/대규모 PHP·Next.js·Spring 등 실제 애플리케이션의 기능·계약·통합 검증과 비용 절감 효과.
- PR 스택·상황판·Notion 백업·프로필 확장은 비활성 원본 보관 상태이며 개인화된 실행 기능은 아직 구현하지 않았다.

대형 저장소 전체 독해나 의미 없는 30만 줄 샘플 생성으로 확장성을 입증했다고 주장하지 않는다. 다음 실제 프로젝트에서 국소 수정과 경계 변경을 각각 수행해 영향 누락·과잉 탐색·검증 범위를 관찰한다.

## pr-lifecycle 추가 검증 (2026-09-10 18:19 KST)

- 새 스킬 quick_validate.py PASS, 활성 2개 스킬의 3도구 동기화 PASS.
- 격리 bare remote와 작업 저장소에서 merge commit 이후 정확한 head의 원격·로컬 삭제, 미추적 개인 파일 보존 확인.
- 조회한 SHA 이후 원격 브랜치가 전진한 상황에서 조건부 삭제가 실패하고 후속 커밋이 보존됨을 확인.
- 실제 PR #1은 MERGED, head af6d2f3와 로컬·원격 tip 일치, base의 조상, 열린 하위 PR 없음, 다른 worktree 미사용을 확인한 후 해당 작업 브랜치만 삭제. 삭제 후 로컬·원격 부재 확인.
- squash/rebase 머지, 복잡한 의존 PR, 도구별 자연어 단계 선택은 아직 실제 행동 검증하지 않음. 해당 경우는 스킬의 보존 조건과 증거 확인 경계를 적용.

## 동시 작업·base 전진 보완 (2026-09-10 18:25 KST)

재현 명령: `python3 tests/pr_git_scenarios.py` (Python 표준 라이브러리 + Git, 임시 로컬 저장소만 사용).

4개 시나리오 PASS:

1. base의 계약 파일 변경과 head의 다른 소비 파일 변경은 Git merge가 성공해도 의미 계약이 불일치할 수 있음.
2. 원격 head가 전진하면 명시 SHA lease의 삭제가 거부되고 후속 커밋이 보존됨.
3. 다른 worktree가 사용하는 브랜치의 삭제가 거부되고 미커밋 파일이 보존됨.
4. 재작성된 base는 이전 base의 fast-forward 후손이 아님을 감지함.

스킬 validator·세 도구 동기화·공백 검사 PASS. 이 테스트는 Git의 경계와 보호 수단을 재현하며 AI가 모든 동시 작업 상황에서 지침을 준수함을 증명하지 않는다. 실제 GitHub merge queue·보호 규칙·병렬 머지 경쟁 및 도구별 행동은 미검증이다. head 조건부 머지가 base까지 고정하지 않는 한계를 명시했다.

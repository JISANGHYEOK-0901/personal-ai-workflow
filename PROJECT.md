# 이 저장소의 프로젝트 설정

- 목적: 규모·언어와 무관하게 재사용할 개인 AI 작업 템플릿·스킬셋 개발.
- 범위: 공통 원칙, 선택형 스킬, 프로젝트 설정 템플릿, 기록 정책, 도구별 설치본.
- 제외: 다른 업무 저장소 변경, 실제 연구 실험, 원본 전문 스크립트 실행.
- 구조: `workflow/` 공통 원칙, `skills/` 활성 스킬 정본, `templates/` 도입용 설정, `docs/` 정책·설계·검증, `third-party/` 출처·비활성 원본.
- 검증: 저장소 루트에서 `python3 scripts/sync_skills.py --check`, `git diff --check`, `python3 tests/pr_git_scenarios.py`. 출처 보존은 sources.json의 archived_path와 sha256 대조. 스킬 행동 검증은 docs/VALIDATION.md의 실측 범위를 따른다.
- 실행 환경: 동기화 스크립트는 Python 3 표준 라이브러리만 사용. 실제 PHP·Next.js·Spring 애플리케이션은 이 저장소에 없음. `src/Main.java`는 기존 미추적 IDE 샘플이며 템플릿 검증 대상이 아님.
- Git: 최신 개발·통합 기준과 기본 PR 대상은 develop. GitHub 기본 브랜치도 develop이며, origin은 personal-ai-workflow. main 반영은 별도 요청 시 처리한다. 현재 이력의 머지 방식은 merge commit. 정책 변경 지시가 없으면 이를 따른다. PR 머지 후 해당 작업 head의 로컬·원격 정리까지 완료 조건으로 삼는다. 이전 초기 push 승인을 무관한 외부 행동 권한으로 확대하지 않음.
- 자원: 현재 구현은 로컬 파일·검사 범위. 유료 실험·외부 배포 한도는 미설정이며 필요 시 먼저 결정.
- 기록: `docs/WORKLOG_POLICY.md`, 개인 데이터는 ai-input 전체 ignore.

- 동시 작업: 현재 필수 CI·머지 큐는 미설정. 동시 머지가 발생하면 SHA 재확인만으로 원자성을 주장하지 않고 pr-lifecycle의 조율 경계를 따른다. 작업 branch는 과업별 분리한다.

- PR 요청 기본 범위: 사용자 지정으로 “PR해줘”는 검증·검토·PR 생성·머지·작업 브랜치 정리까지 포함. 생성만/검토만/머지 금지 등 명시 제한은 우선한다.

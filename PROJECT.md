# 이 저장소의 프로젝트 설정

- 목적: 규모·언어와 무관하게 재사용할 개인 AI 작업 템플릿·스킬셋 개발.
- 범위: 공통 원칙, 선택형 스킬, 프로젝트 설정 템플릿, 기록 정책, 도구별 설치본.
- 제외: 다른 업무 저장소 변경, 실제 연구 실험, 원본 전문 스크립트 실행.
- 구조: `workflow/` 공통 원칙, `skills/` 활성 스킬 정본, `templates/` 도입용 설정, `docs/` 정책·설계·검증, `third-party/` 출처·비활성 원본.
- 검증: 저장소 루트에서 `python3 scripts/sync_skills.py --check`, `git diff --check`. 출처 보존은 sources.json의 archived_path와 sha256 대조. 스킬 행동 검증은 docs/VALIDATION.md의 실측 범위를 따른다.
- 실행 환경: 동기화 스크립트는 Python 3 표준 라이브러리만 사용. 실제 PHP·Next.js·Spring 애플리케이션은 이 저장소에 없음. `src/Main.java`는 기존 미추적 IDE 샘플이며 템플릿 검증 대상이 아님.
- Git: main, origin은 personal-ai-workflow. 머지 방식은 아직 별도 확정하지 않음. 이전 초기 push 승인을 무관한 외부 행동 권한으로 확대하지 않음.
- 자원: 현재 구현은 로컬 파일·검사 범위. 유료 실험·외부 배포 한도는 미설정이며 필요 시 먼저 결정.
- 기록: `docs/WORKLOG_POLICY.md`, 개인 데이터는 ai-input 전체 ignore.

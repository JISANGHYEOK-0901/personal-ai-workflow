# Personal AI Workflow

작업 시작 시 `workflow/CORE.md`를 읽고 적용한다. 프로젝트의 기술·경로·검증은 `PROJECT.md`를 확인한다. 작업 기록은 `docs/WORKLOG_POLICY.md`를 따른다.

- 규모·언어와 무관하게 변경 영향에 맞춰 탐색·계획·검증 깊이를 조절한다.
- AZTKS 작성 기준은 기본 적용하며 별도 호출·평가표를 강제하지 않는다.
- `ai-input/` 전체는 항상 Git에서 제외하며 강제 추가하지 않는다.
- 활성 스킬 정본은 `skills/`다. 도구별 `skills/` 사본은 `python3 scripts/sync_skills.py --write`로 갱신하며 직접 수정하지 않는다.
- `third-party/installed-baseline/`의 스킬·에이전트·스크립트는 비교·복원용 비활성 자료다.
- 도입 대상 프로젝트의 기존 지침을 덮어쓰지 말고 해당 지침에 연결한다. 이 저장소의 설정을 다른 프로젝트의 실행 명령으로 사용하지 않는다.

- PR 생성·검토·머지·머지 후 정리는 `skills/pr-lifecycle/SKILL.md`를 읽고 적용한다. 머지 후 일회성 작업 브랜치 정리까지 확인한다.

- 이 프로젝트의 최신 개발·통합 기준과 기본 PR 대상은 `develop`이다. 작업 시작·base 전진 판단·머지 후 동기화는 develop 기준으로 한다. main 반영은 별도 요청 시 처리한다.

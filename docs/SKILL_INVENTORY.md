# 스킬 정리와 적용 상태

## 현재 기본 구성

- `workflow/CORE.md`: 규모·언어와 무관한 공통 작성·검증·권한 기준. AZTKS 작성 기준이 기본 포함된다.
- `skills/execute/`: 활성 스킬 정본. 세 도구의 skills/execute 사본은 동기화 스크립트가 관리한다.
- `PROJECT.md`: 이 저장소 설정. `templates/PROJECT.md`는 다른 프로젝트 도입용 양식.
- `docs/WORKLOG_POLICY.md`: 기존 작업 단위 기록 정책. ai-input 전체는 로컬 유지.
- 자동 하위 에이전트·전문 업무 스크립트는 기본 활성화하지 않는다.

## 이전 스킬의 처리

| 원본 | 현재 반영 | 후속 확장 |
|---|---|---|
| aztks | 5개 작성 기준을 CORE에 포함. 적용 선언·평가표 강제 제거 | 상세 평가 필요 시 별도 review로 발전 |
| grip-it | execute의 중요 미정 목록·권장안·결정 재사용 | 복잡한 인터뷰가 반복되면 clarify 분리 |
| goal-setting | execute의 목표·범위·검증·종료 한도 | 도구별 goal 명령 연결은 필요 시 |
| review-merge | 공통 권한·영향 검증, 프로젝트별 Git 설정 원칙 | PR 스택 전용 실행 절차는 보관 |
| merge-review | 영역 간 통합 검증 원칙 | main 선머지는 기본 절차 아님 |
| playboard | 공통 정본·중복 기록 방지 원칙 | 레지스트리·상황판 구축은 필요 시 |
| notion-export | 원본·출처 보존, 기본 실행 경로에서 제외 | 검토 버전·분리 출력 적용 후 복원 |
| profile-sum | 사실·추정 구분과 근거 충실성 | 프로필 카드 전용 기능은 필요 시 |

원본 에이전트 aztks-agent·playboard-integrity도 비활성 보관한다. 새 execute는 이들을 호출하지 않는다.

## 보관과 복원

`third-party/installed-baseline/`에 이전 도구별 사본·스크립트·참조 자료를 보존했다. SKILL.md는 내용 변경 없이 SKILL.reference.md로 이름을 바꿔 활성 스킬과 구분했다. sources.json은 원래 installed_path, 현재 archived_path, 원본 커밋, sha256을 가진다. 라이선스는 third-party/licenses에 유지한다.

전문 기능을 복원할 때 필요한 한 스킬만 개인화해 skills/에 추가하고 공통 기준과 충돌을 검토한 뒤 동기화한다. 보관 원본을 통째로 활성 경로에 복사하지 않는다.

## 수정 경로

1. 공통 원칙은 workflow/CORE.md에서 수정한다.
2. 스킬은 skills/ 아래 원본에서 수정한다.
3. `python3 scripts/sync_skills.py --write` 후 `--check`로 사본 일치를 확인한다.
4. 문서 검사는 `git diff --check`를 사용한다. 동기화는 파일 일치 확인이며 도구의 실제 행동 동등성을 증명하지 않는다.

이미 열린 세션에 제공된 이전 스킬 목록은 이 파일 정리로 즉시 지워진다고 가정하지 않는다. 다음 세션의 실제 목록과 공통 문서 읽기를 확인한다.

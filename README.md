# Personal AI Workflow

개인·소규모·대규모 프로젝트와 다양한 언어·풀스택에서 재사용할 개인 AI 작업 체계다. ly의 범위·권한·검증·기록 원칙과 외부 스킬의 방법론을 조합했다. 절차의 깊이는 코드 줄 수보다 실제 변경 영향에 맞춘다.

## 현재 구현 v0.1

- [공통 원칙](workflow/CORE.md): AZTKS를 기본 작성·검증 과정에 반영. 별도 호출이나 매번 평가표가 필요하지 않다.
- [execute](skills/execute/SKILL.md): 목표·미정 결정·실행·영향 추적·검증·종료. 사실·MINOR·MAJOR·BLOCKER를 구분하고 변경 작업의 최종 diff를 의미적으로 검토한다.
- [pr-lifecycle](skills/pr-lifecycle/SKILL.md): PR 생성·검토·승인된 머지·base 동기화·로컬/원격 작업 브랜치 정리. 공통 diff 게이트를 적용하고 동시 작업과 base/head 전진 시 검토·검증 기준을 재확인한다.
- [프로젝트 설정](PROJECT.md) / [설정 템플릿](templates/PROJECT.md): 실제 경로·검증·Git·한도를 환경별로 정의한다.
- [작업 기록 정책](docs/WORKLOG_POLICY.md): 작업 ID별 갱신, 월별 폴더. ai-input 전체는 항상 Git 제외.
- [전달 점검과 PR diff 검토 훅](docs/COMMUNICATION_HOOKS.md): Codex·Claude에서 중요 영향 안내를 상기하고, PR 요청에는 검토 컨텍스트를 주입한다. 단독 PR 명령의 실제 branch·remote를 base/HEAD 증표와 대조하며, merge는 원격 PR·CI를 확인한다. 머지 후 삭제는 별도 MERGED 증표와 정확한 SHA lease를 사용한다.
- [스킬 정리 내역](docs/SKILL_INVENTORY.md): 원본 8개 스킬과 에이전트는 비활성 보관하고 활성 경로에는 execute와 pr-lifecycle을 둔다.

## 관리

최신 개발·통합 기준과 기본 PR 대상은 `develop`이다. `main` 반영은 별도 요청으로 처리한다. 이 개인 설정에서 “PR해줘”는 검증·검토·생성·머지·작업 브랜치 정리까지 포함하며, 명시적 단계 제한은 우선한다.

공통 규칙은 workflow/CORE.md, 스킬은 skills/에서 수정한다. 도구별 사본은 직접 수정하지 않는다.

```bash
python3 scripts/sync_skills.py --write
python3 scripts/sync_skills.py --check
python3 scripts/check_integrity.py
python3 -m unittest discover -s tests -p '*.py'
git diff --check
```

[기존 프로젝트 도입 방법](docs/ADOPTION.md)을 따라 기존 지침에 연결한다. 이 저장소의 설정으로 기존 파일을 덮어쓰지 않는다. 도구별 파일 일치와 실제 행동 동등성은 별개이며 [검증 기록](docs/VALIDATION.md)에 확인 범위를 남긴다.

[정합성 CI](docs/CI.md)는 PR과 develop/main push에서 실행한다. 필수 체크·브랜치 보호 설정과는 별개다.

## 설계와 후속 작업

[설계 초안](docs/PERSONAL_WORKFLOW_DRAFT.md), [규칙 30개·검증 사례](docs/RULE_ADOPTION_CATALOG.md)를 바탕으로 첫 구현을 만들었다. PR·상황판·백업·프로필은 필요할 때 개인화해 확장한다. AI 대학원 준비 프로젝트는 개발 작업 누락·재확인 문제와 개선 효과 검증에서 시작한다.

## 외부 자료

원본은 third-party/installed-baseline에 보존했다. [출처 기록](third-party/sources.json)에 원래 경로·보관 경로·커밋·해시가 있으며, MIT 라이선스는 third-party/licenses에 유지한다. 원본을 현재 실행 지침으로 사용하지 않는다.

## 첫 행동 실험

[EXP-001 실험 계획](docs/experiments/EXP-001-pr-lifecycle.md): 동일 조건에서 pr-lifecycle 적용 전·후 PR 완료 단계 누락을 비교한다. 로컬 웹 데모와 fixture·정확성 평가기를 준비했다. 실제 AI 행동 실험은 미실행이다.

[Workflow Lab 실행 안내](docs/WORKFLOW_LAB.md): `python3 scripts/serve_lab.py` 실행 후 http://127.0.0.1:8765 에서 확인한다. 모든 화면 사례는 가상 데이터다.

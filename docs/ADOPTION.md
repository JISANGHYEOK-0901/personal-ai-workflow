# 다른 프로젝트에 도입하기

개인·소규모·대규모, 단일 언어·여러 언어 모두 같은 공통 원칙을 사용한다. 프로젝트 규모는 탐색 전략의 단서이며, 절차 강도는 실제 변경 영향으로 결정한다.

## 기존 저장소에 연결

1. 기존 AGENTS.md·CLAUDE.md·지역 지침·검증 명령·Git 상태부터 읽는다. 이 저장소의 루트 파일로 덮어쓰지 않는다.
2. workflow/CORE.md, docs/WORKLOG_POLICY.md, skills/execute/와 skills/pr-lifecycle/을 해당 프로젝트의 합의된 위치에 복사하고 기존 지침에서 경로를 연결한다. 기본 구조를 바꾸면 참조 경로도 맞춘다.
3. templates/PROJECT.md를 참고해 해당 프로젝트의 설정을 작성하거나 기존 문서를 연결한다. 이 저장소의 PROJECT.md를 그대로 실행 설정으로 사용하지 않는다. 작은 프로젝트는 몇 줄이면 충분하다.
4. 필요한 도구의 execute·pr-lifecycle 설치본을 만든다. 공통 정본만 수정하고 사본을 동기화한다. scripts/sync_skills.py는 전용으로 관리하는 세 도구 스킬 폴더를 가정하며, 기존 다른 스킬이 있으면 보존하고 중단한다. 기존 프로젝트에서는 그 스킬을 지우지 말고 해당 개인 스킬 폴더만 검토해 갱신한다.
5. ai-input/ 전체 ignore를 설정하고 이미 추적된 파일이 있는지 확인한다. 추적된 개인 파일은 로컬 데이터를 보존하며 별도 범위를 정해 Git 추적을 정리한다. 다른 저장소의 이력을 자동 수정하지 않는다.

## 연결 후 확인

- Codex의 프로젝트 `AGENTS.md`에서 공통 지침 경로와 여러 단계 작업의 execute 진입 경로를 연결한다. 스킬 목록에 이름이 보이는 것과 본문을 읽는 것은 별개다.
- Claude Code는 기존 `CLAUDE.md`를 보존하며 `@AGENTS.md`, `@workflow/CORE.md` 등 실제 경로의 import를 추가한다. 일반 문장이나 백틱 안의 경로는 자동 import가 아니다. 프로젝트 설정·기록 정책도 필요한 정본을 직접 연결한다.
- 설치를 마친 새 세션에서 스킬 이름을 직접 호출하지 않는 대표 작업으로 확인한다. 파일 읽기/스킬 호출 흔적과 요구한 행동·산출물을 따로 확인한다. "적용했다"는 선언이나 사본 일치만으로 행동 검증을 통과시키지 않는다.
- 이 저장소의 연결은 다른 프로젝트나 사용자 전역 설정에 자동으로 전파되지 않는다. 대상 프로젝트의 경로·설정·실제 세션을 확인하기 전에는 전체 도구 적용 완료로 보고하지 않는다.

근거: [Codex 지침 탐색](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [스킬의 선택적 본문 로딩](https://learn.chatgpt.com/docs/build-skills), [Claude 파일 import](https://code.claude.com/docs/en/memory#import-additional-files).

보관 원본·개인 worklog·src/Main.java 샘플은 도입 대상이 아니다. 일반 템플릿 도입을 배포·계정 접근 권한으로 취급하지 않는다.

## 선택형 전달 점검 훅

중요 영향·미결사항을 사용자 질문 뒤에 설명하는 문제가 관찰되면 [전달 점검 훅](COMMUNICATION_HOOKS.md)을 선택 설치할 수 있다. `python3 scripts/install_communication_hooks.py --target /path/to/workspace --write`는 Codex와 Claude Code에 같은 상기 로직을 연결하며 기존 설정·다른 훅을 보존한다. 기본 스킬 동기화와 별도다. 설치 후 두 도구의 새 세션에서 `/hooks`를 확인하고 Codex의 새 정의 신뢰 절차를 완료한다. 설치·정합성·활성화·실제 행동 효과를 각각 확인한다.

## 규모·스택 적응 사례

| 상황 | 적용 깊이 |
|---|---|
| 개인 스크립트의 입력 오류 | 관련 함수·호출·검증만 확인, 별도 구조 지도 불필요 |
| 작은 Next.js + API 앱의 응답 변경 | UI 소비와 API 계약을 함께 확인 |
| 대규모 PHP 서비스의 독립 문서 수정 | 지역 문서 지침·링크만 필요한 만큼 확인 |
| PHP·Next.js·Spring이 연계된 계약 변경 | 생산자·소비자·DB/이벤트·버전 호환성과 영역별 검증 추적 |

언어 명칭은 탐색 단서이며 실제 명령은 manifest·CI·문서에서 확인한다. 저장소에 없는 프레임워크·DB·테스트를 가정하지 않는다.

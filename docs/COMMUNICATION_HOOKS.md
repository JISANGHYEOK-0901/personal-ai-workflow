# 전달 점검과 PR diff 검토 게이트

스킬을 읽고 검증·기록을 충실하게 수행해도, 기존 데이터 전환 영향과 권장안을 사용자 질문 뒤에 설명한 사례가 있었다. 전달 점검은 **설명이 필요한 시점에 다시 점검하도록 상기**한다. 추가로 PR 요청이 있을 때 의미적 diff 검토를 자동으로 시작하도록 컨텍스트를 주입하고, 현재 Git 상태에 묶인 검토 증표가 없으면 직접 PR 경계 명령을 거부한다. 훅은 검토 내용의 정확성 자체를 판정하지 않고 구조화된 수행과 최신 상태만 강제한다.

공통 정본은 [hooks/communication.py](../hooks/communication.py), 설치 도구는 [install_communication_hooks.py](../scripts/install_communication_hooks.py)다. Python 3.9 이상 표준 라이브러리만 사용한다. Codex와 Claude Code가 같은 점검 문구·분류·반복 제한을 사용하며, 플랫폼별 출력 형식만 구분한다. 스킬 정본·기존 프로젝트 지침은 그대로 적용한다.

## 실행 시점과 범위

| 이벤트 | 동작 | 반복·중단 제한 |
|---|---|---|
| UserPromptSubmit | 초기 조사 뒤 중요 영향·미결사항·권장안을 의존 실행 전에 사용자에게 전달하도록 상기 | 사용자 입력당 짧은 컨텍스트 1회. 단순 질문·국소 수정은 형식적 목록·질문 제외 |
| PreToolUse | 직접 편집·외부 반영 상기. PR 요청 턴의 `git push`와 모든 직접 `gh pr create/merge`에서 검토 증표 확인 | 일반 상기는 종류별 1회. PR 증표 없음·만료·상태 변경·base 불일치는 해당 명령 거부 |
| Stop | 여러 코드 디렉터리 또는 데이터·API·배포 관련 변경 시도가 있으면 인계 내용 재점검 | 턴당 최대 1회 이어서 응답. stop_hook_active, 백그라운드 작업·예약 대기 때 재개하지 않음 |

전달 대상은 미확인 사실뿐 아니라 **이미 확인됐지만 사용자의 선택을 바꾸는 영향**도 포함한다. 직접 조사할 사실은 조사하고, 실제 사용자 선택이 필요한 항목만 묶어 질문한다. 이미 받은 결정은 재사용한다. 알려진 중요 미결사항에 의존하는 후속 실행만 보류하며 독립 작업은 계속한다. 이 판단은 에이전트의 책임이고 훅이 기계적으로 집행하지 않는다.

일반 PreToolUse 컨텍스트는 다음 모델 요청에서 읽힐 수 있으므로 **현재 요청된 도구 실행 전 설명을 보장하지 않는다**. 시작 훅이 사전 안내를 요구하고, 실행 훅은 다음 의존 실행을 점검하도록 보완한다. PR 경계는 별도 `permissionDecision: deny`를 사용하므로 해당 직접 명령은 검토 증표 없이는 실행되지 않는다.

### PR diff 검토 증표

`PR해줘`, `PR 만들어줘`, `pull request create`처럼 PR 대상과 실행 의도가 함께 있는 입력은 해당 턴의 push 게이트를 활성화한다. 표현을 놓쳐도 직접 `gh pr create`와 `gh pr merge`는 항상 게이트를 거친다. 차단 사유는 `pr-lifecycle`과 `decision-diff-review`를 읽고 전체 `base...HEAD` diff, 요구·기결정 연결, 계약·데이터·인증·설정·배포 영향, 검증 증거를 확인한 뒤 실행할 기록 명령을 제공한다.

기록은 최종 커밋 뒤 tracked 파일과 index가 clean인 상태에서 수행한다. 기존 untracked 파일은 내용 fingerprint에 포함해 이후 변화가 있으면 증표를 무효화한다. 실제 base를 먼저 fetch하고 remote-tracking ref 또는 확인한 SHA를 `--base`로 사용한다.

```bash
python3 .workflow-hooks/communication.py \
  --root /path/to/workspace \
  --record-pr-review \
  --repo /path/to/workspace/repository \
  --base origin/develop \
  --requirements-reviewed \
  --contracts-reviewed \
  --validation-reviewed \
  --major 0 --blocker 0 --minor 0
```

세 확인 플래그와 비음수 finding 개수가 필요하다. MAJOR 또는 BLOCKER가 1개 이상이면 pass 증표를 만들지 않는다. MINOR는 발견 개수로 기록할 수 있지만 허용 범위의 결함을 수정한 뒤 최종 diff를 다시 검토하는 스킬 계약은 그대로 적용된다. 증표는 repository path의 해시, base ref/SHA, HEAD SHA, merge-base, untracked 내용의 SHA-256, MINOR 개수, 시각만 로컬 SQLite에 저장한다. 24시간이 지나거나 base ref·HEAD·tracked/index·untracked 상태가 바뀌면 무효다. `gh pr create`는 검토한 base와 비교할 수 있도록 `--base`를 명시해야 한다. `gh --repo/-R`은 로컬 checkout과 원격 대상을 안전하게 결속할 수 없어 차단하며 검토한 저장소 디렉터리에서 실행한다.

Stop은 최종 답변의 특정 단어, ‘미결사항 없음’ 선언, 작업 기록 존재 여부를 통과 증거로 사용하지 않는다. 구조적으로 재점검할 때가 됐음을 알릴 뿐, 이미 설명한 작업도 한 번 더 검토될 수 있다. 이미 충분히 안내했다면 반복 설명·승인 요청·추가 테스트 없이 종료하도록 지시한다. Codex는 `decision: block`, Claude는 `hookSpecificOutput.additionalContext`로 동일한 1회 재점검을 요청한다. 새 응답이 추가될 수 있으므로 추가 지연이 0이라고 주장하지 않는다.

### 관찰하는 도구

- Codex apply_patch의 Add/Update/Delete/Move 경로, Claude Edit/Write/MultiEdit의 file_path.
- 코드 경로의 서로 다른 부모 디렉터리 2개 이상, `.sql`, migrations/schema/api/contracts/bridge 디렉터리는 종료 재점검의 구조적 단서다. 크기·파일 수로 품질을 판정하지 않는다.
- `git push`(dry-run 제외), `gh pr create`, `gh pr merge`, `gh release create`, Railway/Vercel/Fly/Firebase/Wrangler의 대표 배포 명령, `npm/pnpm/yarn run deploy`.
- 셸의 Python/Node/셸 스크립트 등은 내용이 불투명하므로 편집 상기만 제공한다. 인용된 예제 문자열이나 heredoc 본문을 배포 명령으로 해석하지 않는다.
- 읽기 명령, 문서·이미지·테스트·개인 기록·도구 설정 파일만의 변경에는 종료 재점검을 추가하지 않는다.

이 분류는 휴리스틱이다. 다른 MCP 쓰기 도구, 임의 래퍼·동적 셸 실행·기존 PTY의 입력, 웹에서 직접 만든 PR을 모두 포괄하지 않는다. `gh pr merge`가 지정한 원격 PR과 현재 로컬 checkout이 같은 head인지도 훅만으로 조회하지 않으므로 pr-lifecycle의 base/head 확인이 필요하다. 로컬 훅을 비활성화하거나 설정 신뢰를 해제하면 우회할 수 있다. 저장소 전체의 강제력이 필요하면 서버의 필수 CI·브랜치 보호를 함께 사용한다.

## 설치·갱신·제거

기존 AGENTS.md와 CLAUDE.md가 연결된 작업공간 루트에서 두 도구를 사용한다. 설치기는 기존 설정·다른 훅을 보존하고 자체 그룹만 추가·갱신한다. 전역 설정·신뢰 상태는 바꾸지 않는다.

```bash
python3 scripts/install_communication_hooks.py --target /path/to/workspace --write
python3 scripts/install_communication_hooks.py --target /path/to/workspace --check
python3 scripts/install_communication_hooks.py --target /path/to/workspace --remove
```

`--check`는 쓰지 않으며 설정·런타임 정합성만 검사한다. 런타임 활성화나 에이전트의 행동 준수를 증명하지 않는다. `--remove`는 이 설치가 만든 그룹·런타임·manifest만 제거하고 다른 설정·개인 상태·ignore 규칙은 보존한다. 설치 파일의 수동 수정이나 symlink·추적된 로컬 설정이 있으면 덮어쓰지 않고 중단한다. 실패 시 이미 쓴 파일은 이전 내용으로 되돌리되 그 사이 다른 작업이 수정한 내용은 보존한다. 원자성은 개별 파일 교체에만 해당하며 여러 프로세스의 설치·사용자 편집 전체를 잠그지 않는다.

생성 위치:

- `.workflow-hooks/communication.py`, `.workflow-hooks/install.json`: 공유 로직의 로컬 사본·소유 정보.
- `.codex/hooks.json`: Codex 이벤트 3개.
- `.claude/settings.local.json`: Claude Code 이벤트 3개. 별도의 `.claude/hooks.json`은 사용하지 않는다.
- `ai-input/hook-state/communication.sqlite3`: 반복 억제와 PR 검토 증표의 최소 상태.

설치기는 이 경로들을 작업공간 `.gitignore`에 추가한다. 절대 경로와 실행 중 Python 경로를 안전하게 인용하므로 공백·특수문자가 있는 경로에서도 실행되며, 작업공간이 Git 루트가 아닌 경우도 지원한다. 위치 이동 또는 Python 제거 후에는 재설치한다. **하위 디렉터리에서 명령을 실행할 수 있는 것과 그 위치로 새 세션을 시작했을 때 설정이 발견되는 것은 별개**다. 기본 지원 진입점은 설치한 작업공간 루트다. 중첩 저장소에 자동으로 파일을 전파하지 않는다.

### 도구에서 활성화 확인

- Codex: 새 세션의 `/hooks`에서 세 이벤트의 명령·출처를 검토하고 신뢰한다. 새 훅과 정의가 바뀐 훅은 신뢰 전 건너뛴다. 스크립트 SHA-256을 명령의 `--revision`에 포함하여 코드 갱신도 정의 변경으로 드러나게 한다. 훅은 자체 파일 해시가 다르면 경고 후 실행을 건너뛴다. 전역 신뢰 해시를 직접 수정하거나 trust 우회 옵션으로 활성화하지 않는다.
- Claude Code: 새 세션의 `/hooks`에서 프로젝트 로컬 설정의 세 이벤트를 확인한다. 기존 프로젝트 신뢰 절차를 따른다. `disableAllHooks`, 설정 source 제한, bare/safe mode 등으로 비활성화돼 있으면 파일 설치만으로 실행되지 않는다.
- 현재 지원을 확인한 CLI: Codex 0.154.0, Claude Code 2.1.273. 새 버전은 이벤트 입력·출력과 설정 로딩을 다시 확인한다.

## 상태·비용·실패 처리

별도 모델·네트워크 호출이나 대화 원문 수집은 없다. 세션 ID 해시, 턴 구분, 디렉터리 해시, 단계·점검 여부만 로컬 SQLite에 기록한다. 명령·프롬프트·답변·인증값·실제 경로를 기록하지 않는다. 14일 지난 항목은 다음 처리 때 삭제한다. 동시 훅은 짧은 SQLite 트랜잭션으로 중복 알림을 억제한다.

Codex는 turn_id를 사용하고 Claude는 UserPromptSubmit으로 입력 경계를 만든다. 경계가 없으면 이전 작업을 추정해 Stop을 재개하지 않는다. 서브에이전트 전용 훅은 등록하지 않으며 모든 병렬·서브에이전트 상황의 동등성은 미검증이다.

입력 오류·과대 입력·해시 불일치 같은 일반 전달 알림 오류는 내용을 출력하지 않고 짧은 경고와 빈 JSON으로 종료한다. 알림 실패 때문에 작업을 막지 않는다. 반면 직접 PR 경계로 식별한 명령에서 repository·base·증표를 검증할 수 없으면 그 명령만 fail closed로 거부한다. 일반 이벤트 timeout은 3초, Git 상태를 읽는 PreToolUse는 10초다. 모델 컨텍스트 추가와 조건부 Stop 재개에 따른 비용·지연은 별개로 측정한다.

## 검증과 시범 성공 기준

```bash
python3 -m unittest discover -s tests -p 'test_communication_hooks.py' -v
```

합성 이벤트 검사는 양쪽 출력 계약, 반복·턴/세션 격리, 읽기·국소 작업 제외, 팝업 사례의 FE/BE 변경 후 1회 재점검, 실제 전달 여부를 키워드로 판정하지 않음, 설치 보존·복구·제거·하위 cwd·경로 인용을 확인한다. 격리 Git 저장소에서는 PR 입력 뒤 push 차단, 명시 base 없는 PR 생성 차단, tracked/index가 clean인 최종 상태 기록 후 허용, base 전진·후속 tracked/untracked 수정 무효화, MAJOR/BLOCKER 기록 거부를 확인한다. 실제 LLM의 의미 판단 품질을 증명하는 검사는 아니다.

새 세션의 실제 작업에서는 다음을 관찰한다. 스킬 이름 선언이나 worklog 작성만으로 통과시키지 않는다.

1. 고정 데이터를 DB/API로 전환할 때 자동 이전 여부와 서비스 공백, 권장 전환 순서를 사용자 재질문 전에 설명하는가.
2. 미결사항을 초기 조사 뒤 함께 제시하고 기존 선택을 재질문하지 않는가.
3. 완료 보고에서 사용자가 직접 확인할 방법과 중요한 미확인을 설명하는가.
4. 단순 문구 수정에는 불필요한 질문·종료 재개가 없는가. 다단계 작업의 재점검이 반복 루프를 만들지 않는가.
5. 추가 응답 수·시간·토큰과 놓친 사례·불필요한 개입을 함께 기록하는가.

근거: [Codex Hooks](https://learn.chatgpt.com/docs/hooks), [Claude Code Hooks](https://code.claude.com/docs/en/hooks). 문서와 설치 검사 통과를 새 세션 실사용 성공으로 대체하지 않는다.

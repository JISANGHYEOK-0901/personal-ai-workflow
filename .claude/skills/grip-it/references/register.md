# 결정 기록부와 편집 훅

## 위치와 내용

세션을 시작한 작업공간의 `ai-input/grip/<작업 ID>/GRIP_REGISTER.md`에 기록한다. `ai-input/`이 Git에서 제외된 작업공간을 사용하고, 제목이나 본문에서 실제 작업 대상과 범위를 식별할 수 있게 한다. 대상 저장소가 따로 있으면 그 저장소의 근거 문서와 동작 기준을 갱신한다. 동일 작업의 기록부를 찾아 갱신하고 worklog에는 참조만 남긴다.

아래 형식에서 토픽 ID는 영문자나 숫자로 시작하고 하이픈과 밑줄을 쓸 수 있다. `applied:`의 각 항목은 실제 작업 대상 루트 기준의 파일 경로다. 토픽당 한 행에 기록하고, 설명에 구분자 ` | `가 필요하면 일반 문장으로 풀어 쓴다. `DROPPED` 행에는 `reason:`을 넣는다.

```markdown
# 사무실 검토 흐름

대상: /workspace/ai-office
범위: 기본 검토 역할과 보조 검토 조건
RESOLVED: 1 / DROPPED: 0 / TOTAL: 2

- [x] T1 | CORE | 기본 최종 검토자 | depends:- | status:RESOLVED | decision:비서실장 | applied:["docs/DECISIONS.md","docs/review-policy.md"]
- [ ] T2 | CORE | 보조 검토가 필요한 조건 | depends:T1 | status:UNRESOLVED
```

기록부에 적은 문서가 존재하고 변경 내용에 실제 결정이 반영됐는지 확인한다. `RESOLVED`는 문서 반영까지 끝났음을 뜻한다. 진행 중에는 안정적인 ID를 유지하고 제외된 토픽도 남긴다.

## 미결 결정에 의존하는 직접 편집

grip-it 편집 검사를 포함한 전달 점검 훅이 활성화된 작업공간에서는 미결 결정에 의존하는 파일을 구체적으로 식별했을 때 다음 블록을 기록부에 추가한다. `worktree`는 대상 Git 작업 트리의 절대 경로, `branch`는 그 트리의 현재 작업 브랜치다. 경로는 브랜치의 작업 트리 루트 기준으로 정확한 파일명만 적는다. 여러 선택에 의존하는 파일은 해당 미결 토픽마다 등록한다. 독립 작업과 결정 반영에 쓰는 문서는 독립적으로 편집할 수 있게 목록에서 뺀다.

````markdown
```grip-edit-scope
{
  "worktree": "/workspace/ai-office",
  "branch": "feat/review-flow",
  "blocked_by": {"T2": ["dashboard/server.mjs"]}
}
```
````

훅은 같은 작업 트리와 브랜치에서 등록된 파일을 직접 편집하기 전에 해당 토픽이 해소됐는지 확인한다. 다른 도구 경로에서도 선행 결정을 지킨다. 기록부의 결정과 반영 위치를 갱신한 뒤 경계를 다시 확인한다.

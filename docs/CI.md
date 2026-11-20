# 정합성 CI

`.github/workflows/integrity.yml`은 모든 PR, develop/main push, 수동 실행에서 `integrity` job을 수행한다. 권한은 contents:read이며 checkout 자격증명을 남기지 않는다. checkout v4는 확인한 commit SHA로 고정했다. Python 표준 라이브러리와 Git만 사용한다.

## 로컬과 CI의 동일 검사

```bash
python3 scripts/sync_skills.py --check
python3 scripts/check_integrity.py
python3 -m unittest discover -s tests -p '*.py' -v
git diff --check
```

정합성 검사는 `git ls-files` 기준이다. 새 문서는 stage한 뒤 확인해야 한다. CI는 checkout된 추적 파일 전체를 검사하며, whitespace는 checkout된 commit의 `git show --format= --check HEAD`로 확인한다.

- 스킬 사본·리소스 일치와 미관리 파일 충돌 검사.
- 활성 스킬 name/description 기본 형식, 로컬 Markdown 링크의 대상 존재 확인. 전체 YAML 스키마나 heading anchor·원격 URL 유효성 검사는 아니다.
- 보관 파일 SHA-256·라이선스와 ai-input 추적 금지·ignore 동작 확인.
- Git 경계 5개, 정합성 실패 주입 5개, 동기화 회귀 9개 실행. Git 경계에는 단일 `git diff`가 staged·unstaged·untracked 상태 전체를 포함하지 않는 사례가 포함된다.

보관 원본 문서의 링크는 과거 설치 구조를 참조하므로 현재 활성 문서 링크 검사에서 제외하며 내용 해시로 보존을 확인한다.

## 동기화의 실패 경계

동기화는 전체 대상의 알려진 경로 충돌을 먼저 검사한다. 변경 파일은 임시 파일을 쓴 뒤 원자적으로 치환한다. 하나의 파일이 반쯤 써지는 문제는 줄이지만 전체 사본 묶음의 트랜잭션은 아니다. 중간 I/O 실패 시 이미 갱신한 파일과 이전 파일이 공존할 수 있으며 --check로 감지하고 --write 재실행으로 복구한다. 여러 프로세스의 동시 --write 잠금은 제공하지 않으므로 동기화 writer는 하나로 유지한다.

## 서버 정책과 한계

GitHub의 `develop`은 GitHub Actions가 발행한 `integrity` 체크를 필수로 요구한다. 최신 base를 요구하는 strict 모드이며 관리자에게도 적용된다. 서버 설정은 [develop 보호 설정](https://github.com/JISANGHYEOK-0901/personal-ai-workflow/settings/branches)에서 확인한다. PR #23에서 검사 진행 중 머지가 `BLOCKED`였고 성공 뒤 `CLEAN`으로 바뀌었다.

로컬 머지 훅은 CI 목록이 비어 있거나 확인되지 않으면 해당 명령을 거부한다. 서버는 이름과 발행 앱이 지정된 필수 검사를 확인한다. 필수 검사가 등록되거나 재실행을 마칠 때까지 기다린 뒤 현재 head와 결과를 함께 재조회한다.

이 suite는 스크립트·파일 정합성과 Git 경계를 검사한다. AI의 전체 행동·PHP/Next.js/Spring 애플리케이션·실제 동시 머지 경쟁 검증은 아니다.

#!/usr/bin/env python3
"""Communication reminders and a local PR diff-review gate; no model calls."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid

START = (
    '중요 사항 전달 점검: 다단계 구현·조사라면 초기 조사 후, 의존 실행 전에 '
    '기존 동작·데이터에 미치는 영향과 미결사항을 권장안·다음 행동과 함께 사용자에게 짧게 설명한다. '
    '이미 확인된 사실도 사용자 선택을 바꾸면 설명 대상이다. 내부 메모나 작업 기록으로 대신하지 않는다. '
    '앞서 남긴 미결사항은 확정/권장 기본값/잔여로 연결한다. 직접 확인할 사실은 조사하고, '
    '실제 사용자 결정이 필요한 항목만 묶어 질문한다. 기존 승인·결정은 재사용하고 독립 작업은 계속한다. '
    '단순 질문·국소 수정에는 형식적인 목록이나 확인 질문을 만들지 않는다.'
)
EDIT = (
    '변경 단계의 전달 점검이다. 현재 요청·기결정과 변경 범위를 대조하고, '
    '새로 발견한 중요한 영향·미결사항·권장안을 다음 의존 실행 전에 사용자에게 전달한다. '
    '기존 동작 확장은 요청 근거를 확인한다. 이미 설명·결정된 내용은 반복하지 않는다. '
    '이 알림은 누락 판정이나 승인 요청이 아니며 현재 도구 실행을 차단하지 않는다.'
)
RELEASE = (
    '외부 반영 단계의 전달 점검이다. 기존 데이터 자동 이전 여부, 전환 중 공백, '
    '실제 적용 대상과 검증 한계를 사용자에게 설명했는지 확인한다. 권장 전환 순서를 함께 안내하고 '
    '기존 결정을 재사용한다. 확인된 중요 미결사항에 의존하는 후속 실행만 보류하고 독립 작업은 계속한다. '
    '현재 호출은 차단되지 않으므로 사전 설명을 이미 놓쳤다면 즉시 알리고 성공·승인을 추정하지 않는다.'
)
FINISH = (
    '여러 코드 영역 또는 데이터·외부 반영의 변경 시도가 있어 종료 전 전달 내용을 한 번 점검한다. '
    '이는 누락을 자동 판정한 결과가 아니다. 실제 사용자에게 보낸 설명과 요청을 대조하여 '
    '중요 영향·미결사항·권장 다음 행동, 사용자가 바로 확인할 방법, 검증 한계가 빠졌다면 짧게 보완한다. '
    '작업 기록 링크만으로 설명을 대신하지 않는다. 이미 전달했다면 반복 설명·추가 질문·테스트 없이 종료한다. '
    '승인된 작업을 다시 승인받거나 이 점검을 이유로 범위를 넓히지 않는다.'
)
PR_REVIEW = (
    'PR 작업 요청을 감지했다. PR 경계 전에 pr-lifecycle과 decision-diff-review 기준으로 실제 base 대비 '
    '전체 변경을 요구·기결정에 연결해 검토한다. 계약·데이터·인증·설정·배포 영향과 staged·unstaged·'
    '관련 미추적 상태를 확인하고 필요한 검증을 수행한다. 최종 커밋 뒤 tracked/index가 깨끗하고 '
    '현재 untracked 상태를 확인한 뒤 '
    'base/HEAD에 묶인 검토 증표를 기록해야 git push와 PR 생성·머지가 진행된다. MAJOR 또는 BLOCKER가 '
    '남아 있으면 증표를 만들지 말고 먼저 해결한다. 경계 명령이 차단되면 사유에 표시된 기록 명령을 따른다.'
)
MAX_INPUT = 2 * 1024 * 1024
REVIEW_MAX_AGE = 24 * 60 * 60


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def context(event, message):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': message}}


def deny(message):
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse',
                                   'permissionDecision': 'deny',
                                   'permissionDecisionReason': message}}


def pr_prompt(value):
    if not isinstance(value, str):
        return False
    subject = r'(?:(?<![A-Za-z0-9_])pr(?![A-Za-z0-9_])|pull\s*request|풀\s*리퀘스트|피\s*알)'
    action = r'(?:해\s*줘|해주세요|만들|생성|올려|열어|검토|리뷰|머지|merge|create)'
    return bool(re.search(subject + r'.{0,30}' + action, value, re.I | re.S)
                or re.search(action + r'.{0,30}' + subject, value, re.I | re.S))


def file_scope(paths, cwd):
    """Structural hints only. Neither paths nor content establish semantic risk."""
    groups, sensitive = set(), False
    for value in paths:
        path = Path(value)
        path = Path(cwd) / path if not path.is_absolute() else path
        parts = {p.lower() for p in path.parts}
        if parts & {'ai-input', '.git', '.codex', '.claude', 'node_modules', 'build', 'dist'}:
            continue
        if path.suffix.lower() in {'.md', '.mdc', '.txt', '.png', '.jpg', '.webp', '.svg'}:
            continue
        if parts & {'test', 'tests', '__tests__', 'docs'}:
            continue
        groups.add(digest(str(path.parent.resolve())))
        sensitive |= path.suffix.lower() == '.sql' or bool(parts & {
            'migrations', 'migration', 'schema', 'schemas', 'api', 'contracts', 'bridge',
        })
    return groups, sensitive


def shell_segments(command):
    """Tokenize direct shell segments without inspecting quoted program text."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=';&|()\n<>')
        lexer.whitespace = ' \t\r'
        tokens = list(lexer)
    except ValueError:
        return ''
    segments, segment = [], []
    for token in tokens:
        if token and all(c in ';&|()\n' for c in token):
            if segment:
                segments.append(segment)
            segment = []
        else:
            segment.append(token)
    if segment:
        segments.append(segment)
    # Heredoc bodies are opaque. A word in a script/example isn't a direct command.
    if any('<<' in segment for segment in segments):
        segments = segments[:1]
    return segments


def shell_events(command):
    """Return the reminder kind and first direct PR boundary command."""
    segments = shell_segments(command)
    kind = ''
    boundary = None
    active_cwd = None
    for words in segments:
        words = list(words)
        while words and (words[0] == 'env' or re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', words[0])):
            words.pop(0)
        if not words:
            continue
        executable = Path(words.pop(0)).name
        if executable == 'cd' and len(words) == 1:
            active_cwd = words[0]
            continue
        if executable == 'git':
            repo_arg = active_cwd
            while words and words[0].startswith('-'):
                option = words.pop(0)
                if option in {'-C', '-c', '--git-dir', '--work-tree'} and words:
                    value = words.pop(0)
                    if option == '-C':
                        repo_arg = value
                elif option.startswith('-C') and len(option) > 2:
                    repo_arg = option[2:]
            if words and words[0] == 'push' and not {'--dry-run', '-n'} & set(words):
                kind = 'release'
                boundary = boundary or {'action': 'push', 'repo': repo_arg, 'base': None}
        gh_words = list(words)
        remote_repo = False
        while gh_words and gh_words[0].startswith('-'):
            option = gh_words.pop(0)
            if option in {'-R', '--repo', '--hostname'} and gh_words:
                gh_words.pop(0)
                remote_repo |= option in {'-R', '--repo'}
            elif option.startswith('--repo='):
                remote_repo = True
        if executable == 'gh' and gh_words[:2] in (['pr', 'create'], ['pr', 'merge']):
            kind = 'release'
            base = None
            for index, word in enumerate(gh_words[2:], start=2):
                if word == '--base' and index + 1 < len(gh_words):
                    base = gh_words[index + 1]
                elif word.startswith('--base='):
                    base = word.split('=', 1)[1]
                elif word in {'-R', '--repo'} or word.startswith('--repo='):
                    remote_repo = True
            if boundary is None or boundary['action'] == 'push':
                boundary = {'action': gh_words[1], 'repo': active_cwd, 'base': base,
                            'remote_repo': remote_repo}
        if executable == 'gh' and gh_words[:2] == ['release', 'create']:
            kind = 'release'
        if executable in {'railway', 'vercel', 'fly', 'flyctl', 'firebase', 'wrangler'}:
            if words and words[0] in {'up', 'deploy', 'redeploy', 'publish'}:
                kind = 'release'
            if executable == 'vercel' and '--prod' in words:
                kind = 'release'
        if executable in {'npm', 'pnpm', 'yarn'} and words[:2] == ['run', 'deploy']:
            kind = 'release'
        if executable in {'python', 'python3', 'node', 'ruby', 'bash', 'sh', 'zsh',
                          'cp', 'mv', 'rm', 'mkdir', 'tee', 'touch', 'apply_patch'}:
            kind = 'edit'  # Opaque scripts get a reminder, not a completion gate.
    return kind, boundary


def shell_kind(command):
    return shell_events(command)[0]


def classify(payload):
    name, args = payload.get('tool_name'), payload.get('tool_input', {})
    if not isinstance(args, dict):
        return '', set(), False
    if name in {'Bash', 'exec_command'}:
        return shell_kind(str(args.get('command', args.get('cmd', '')))), set(), False
    paths = []
    if name == 'apply_patch':
        paths = re.findall(r'^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$',
                           str(args.get('command', args.get('patch', ''))), re.M)
    elif name in {'Edit', 'Write', 'MultiEdit'}:
        if isinstance(args.get('file_path'), str):
            paths = [args['file_path']]
    groups, sensitive = file_scope(paths, payload.get('cwd', '.'))
    return ('edit' if groups else ''), groups, sensitive


def safe_state_path(root):
    path = root / 'ai-input/hook-state/communication.sqlite3'
    for entry in [path, *path.parents]:
        if entry.is_symlink():
            raise ValueError('Symlink in state path')
        if entry == root:
            break
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def git_output(repo, *args, allowed=(0,)):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True,
                            timeout=5, check=False)
    if result.returncode not in allowed:
        raise ValueError('Git state could not be verified')
    return result.stdout, result.returncode


def resolve_repo(root, cwd, hint=None):
    root = root.resolve()
    candidate = Path(hint) if hint else Path(cwd)
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    top, _ = git_output(candidate, 'rev-parse', '--show-toplevel')
    repo = Path(top.decode().strip()).resolve()
    try:
        repo.relative_to(root)
    except ValueError as exc:
        raise ValueError('Repository is outside the installed workspace') from exc
    return repo


def commit_sha(repo, revision):
    if (not isinstance(revision, str) or not revision or len(revision) > 200
            or '\x00' in revision or '\n' in revision or revision.startswith('-')):
        raise ValueError('Invalid base revision')
    output, _ = git_output(repo, 'rev-parse', '--verify', '--end-of-options',
                           revision + '^{commit}')
    return output.decode().strip()


def untracked_fingerprint(repo):
    names, _ = git_output(repo, 'ls-files', '--others', '--exclude-standard', '-z')
    result = hashlib.sha256()
    for raw_name in sorted(name for name in names.split(b'\0') if name):
        relative = Path(os.fsdecode(raw_name))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Untracked path escaped the repository')
        path = repo / relative
        result.update(len(raw_name).to_bytes(8, 'big'))
        result.update(raw_name)
        if path.is_symlink():
            result.update(b'L')
            result.update(os.fsencode(os.readlink(path)))
        elif path.is_file():
            result.update(b'F')
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(chunk)
        else:
            raise ValueError('Unsupported untracked path type')
    return result.hexdigest()


def repository_state(root, repo, base):
    repo = resolve_repo(root, repo)
    status, _ = git_output(repo, 'status', '--porcelain=v1', '-z', '--untracked-files=no')
    if status:
        raise ValueError('Tracked files or index are not clean')
    base_sha = commit_sha(repo, base)
    head_sha = commit_sha(repo, 'HEAD')
    merge_base, _ = git_output(repo, 'merge-base', base_sha, head_sha)
    _, changed = git_output(repo, 'diff', '--quiet', '--no-ext-diff',
                            base_sha + '...' + head_sha, allowed=(0, 1))
    if changed == 0:
        raise ValueError('Base and HEAD have no PR diff')
    return repo, base_sha, head_sha, merge_base.decode().strip(), untracked_fingerprint(repo)


def ensure_review_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS reviews
                  (repo TEXT PRIMARY KEY, base_ref TEXT, base_sha TEXT, head_sha TEXT,
                   merge_base TEXT, untracked TEXT NOT NULL DEFAULT '', minor INTEGER,
                   updated REAL)''')
    columns = {row[1] for row in db.execute('PRAGMA table_info(reviews)')}
    if 'untracked' not in columns:
        db.execute("ALTER TABLE reviews ADD COLUMN untracked TEXT NOT NULL DEFAULT ''")


def record_review(root, repo, base, requirements, contracts, validation,
                  major=0, minor=0, blocker=0):
    if not all((requirements, contracts, validation)):
        raise ValueError('All review attestations are required')
    if any(not isinstance(value, int) or value < 0 for value in (major, minor, blocker)):
        raise ValueError('Finding counts must be non-negative integers')
    if major or blocker:
        raise ValueError('Resolve MAJOR and BLOCKER findings before recording a pass')
    repo, base_sha, head_sha, merge_base, untracked = repository_state(root, repo, base)
    with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
        ensure_review_table(db)
        db.execute('''INSERT OR REPLACE INTO reviews
                      (repo, base_ref, base_sha, head_sha, merge_base, untracked, minor, updated)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                   (digest(str(repo)), base, base_sha, head_sha, merge_base, untracked,
                    minor, time.time()))
    return {'base': base_sha, 'head': head_sha, 'minor': minor}


def review_record_command(root, repo):
    command = [sys.executable, str(Path(__file__).resolve()), '--root', str(root),
               '--record-pr-review', '--repo', str(repo), '--base', '<fetched-remote-base>',
               '--requirements-reviewed', '--contracts-reviewed', '--validation-reviewed',
               '--major', '0', '--blocker', '0', '--minor', '<count>']
    return shlex.join(command)


def check_review(root, cwd, boundary):
    try:
        if boundary.get('remote_repo'):
            raise ValueError('Run gh from the reviewed local repository without --repo/-R')
        repo = resolve_repo(root, cwd, boundary.get('repo'))
        if boundary['action'] == 'create' and not boundary.get('base'):
            raise ValueError('gh pr create must include an explicit --base')
        with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
            ensure_review_table(db)
            row = db.execute('SELECT base_ref, base_sha, head_sha, merge_base, untracked, updated '
                             'FROM reviews WHERE repo=?', (digest(str(repo)),)).fetchone()
        if not row:
            raise ValueError('No review receipt exists for this repository')
        base_ref, base_sha, head_sha, merge_base, untracked, updated = row
        if time.time() - updated > REVIEW_MAX_AGE:
            raise ValueError('The review receipt is older than 24 hours')
        current_repo, current_base, current_head, current_merge, current_untracked = repository_state(
            root, repo, base_ref)
        if current_repo != repo or (current_base, current_head, current_merge,
                                    current_untracked) != (
                base_sha, head_sha, merge_base, untracked):
            raise ValueError('Base, HEAD, or working tree changed after review')
        if boundary.get('base') and commit_sha(repo, boundary['base']) != base_sha:
            raise ValueError('PR command base does not match the reviewed base')
        return None
    except (OSError, TypeError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
        try:
            repo = resolve_repo(root, cwd, boundary.get('repo'))
            command = review_record_command(root, repo)
        except (OSError, TypeError, ValueError, subprocess.SubprocessError):
            command = review_record_command(root, Path(cwd))
        reason = str(exc) or 'PR review state could not be verified'
        return deny(
            'PR diff review gate blocked this command: ' + reason + '. Fetch the actual base, read '
            'skills/pr-lifecycle/SKILL.md and skills/execute/references/decision-diff-review.md, '
            'review the complete base...HEAD diff and validation evidence, resolve MAJOR/BLOCKER findings, '
            'then record the clean final state and retry:\n' + command)


def handle(payload, engine, root):
    if not isinstance(payload, dict):
        return {}
    event = payload.get('hook_event_name')
    if event not in {'UserPromptSubmit', 'PreToolUse', 'Stop'}:
        return {}
    boundary = None
    if event == 'PreToolUse' and payload.get('tool_name') in {'Bash', 'exec_command'}:
        args = payload.get('tool_input', {})
        if isinstance(args, dict):
            command = str(args.get('command', args.get('cmd', '')))
            _, boundary = shell_events(command)
    if boundary and boundary['action'] in {'create', 'merge'}:
        blocked = check_review(root, payload.get('cwd', root), boundary)
        if blocked:
            return blocked
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        return {}
    if event == 'Stop' and (payload.get('stop_hook_active') or payload.get('background_tasks')
                            or payload.get('session_crons')):
        return {}
    kind, groups, sensitive = classify(payload) if event == 'PreToolUse' else ('', set(), False)
    if event == 'PreToolUse' and not kind:
        return {}
    requested_pr = event == 'UserPromptSubmit' and pr_prompt(payload.get('prompt'))
    # No transcript, prompt, answer, command, credentials, or raw path is persisted.
    key = digest(engine + ':' + session)
    with closing(sqlite3.connect(safe_state_path(root), timeout=0.2)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, turn TEXT, data TEXT, updated REAL)')
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM sessions WHERE updated < ?', (time.time() - 14 * 86400,))
        row = db.execute('SELECT turn, data FROM sessions WHERE id=?', (key,)).fetchone()
        # Claude has no stable turn_id field. UserPromptSubmit establishes its boundary.
        turn = payload.get('turn_id') if engine == 'codex' else None
        if engine == 'codex' and (not isinstance(turn, str) or not turn):
            return context(event, START) if event == 'UserPromptSubmit' else {}
        state = json.loads(row[1]) if row else {}
        if (not isinstance(state, dict) or not isinstance(state.get('groups', []), list)
                or any(not isinstance(group, str) for group in state.get('groups', []))):
            raise ValueError('Invalid stored state')
        if event == 'UserPromptSubmit':
            if engine == 'claude':
                turn = uuid.uuid4().hex
            if not row or row[0] != turn:
                state = {}
        elif engine == 'claude':
            if not row:
                return {}  # No prompt boundary: don't reuse or invent a task.
            turn = row[0]
        elif not row or row[0] != turn:
            state = {}
        output = {}
        if event == 'UserPromptSubmit' and not state.get('started'):
            state['started'] = True
            state['pr_intent'] = requested_pr
            output = context(event, START + ('\n\n' + PR_REVIEW if requested_pr else ''))
        elif event == 'PreToolUse':
            state['groups'] = sorted(set(state.get('groups', [])) | groups)[:64]
            state['sensitive'] = bool(state.get('sensitive') or sensitive or kind == 'release')
            if not state.get(kind):
                state[kind] = True
                output = context(event, RELEASE if kind == 'release' else EDIT)
        elif event == 'Stop':
            needs_review = state.get('sensitive') or len(state.get('groups', [])) >= 2
            if needs_review and not state.get('reviewed') and payload.get('last_assistant_message'):
                state['reviewed'] = True
                output = ({'decision': 'block', 'reason': FINISH} if engine == 'codex'
                          else context('Stop', FINISH))
        db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?, ?, ?)',
                   (key, turn, json.dumps(state), time.time()))
    if boundary and boundary['action'] == 'push' and state.get('pr_intent'):
        blocked = check_review(root, payload.get('cwd', root), boundary)
        if blocked:
            return blocked
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('codex', 'claude'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--revision')
    parser.add_argument('--record-pr-review', action='store_true')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--base')
    parser.add_argument('--requirements-reviewed', action='store_true')
    parser.add_argument('--contracts-reviewed', action='store_true')
    parser.add_argument('--validation-reviewed', action='store_true')
    parser.add_argument('--major', type=int, default=0)
    parser.add_argument('--minor', type=int, default=0)
    parser.add_argument('--blocker', type=int, default=0)
    args = parser.parse_args()
    if args.record_pr_review:
        try:
            if args.repo is None or args.base is None:
                raise ValueError('--repo and --base are required')
            result = record_review(args.root, args.repo, args.base, args.requirements_reviewed,
                                   args.contracts_reviewed, args.validation_reviewed,
                                   args.major, args.minor, args.blocker)
        except (OSError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
            print('PR review receipt not recorded: ' + str(exc), file=sys.stderr)
            return 2
        print(json.dumps({'recorded': True, **result}, ensure_ascii=False))
        return 0
    if args.engine is None or args.revision is None:
        parser.error('--engine and --revision are required in hook mode')
    try:
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != args.revision:
            raise ValueError('Installed revision mismatch')
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('Input too large')
        output = handle(json.loads(raw), args.engine, args.root)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, sqlite3.Error):
        # Advisory failure: never echo input or block the user's work on a hook error.
        print('Communication reminder unavailable; follow the workspace instructions.', file=sys.stderr)
        output = {}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

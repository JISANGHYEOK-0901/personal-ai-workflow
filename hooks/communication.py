#!/usr/bin/env python3
"""Bounded communication reminders for Codex and Claude Code; no model calls."""
import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import shlex
import sqlite3
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
MAX_INPUT = 2 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def context(event, message):
    return {'hookSpecificOutput': {'hookEventName': event, 'additionalContext': message}}


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


def shell_kind(command):
    """Recognize common direct commands, never execute or scan quoted program text."""
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
    kind = ''
    for words in segments:
        words = list(words)
        while words and (words[0] == 'env' or re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', words[0])):
            words.pop(0)
        if not words:
            continue
        executable = Path(words.pop(0)).name
        if executable == 'git':
            while words and words[0].startswith('-'):
                option = words.pop(0)
                if option in {'-C', '-c', '--git-dir', '--work-tree'} and words:
                    words.pop(0)
            if words and words[0] == 'push' and not {'--dry-run', '-n'} & set(words):
                return 'release'
        if executable == 'gh' and words[:2] in (['pr', 'merge'], ['release', 'create']):
            return 'release'
        if executable in {'railway', 'vercel', 'fly', 'flyctl', 'firebase', 'wrangler'}:
            if words and words[0] in {'up', 'deploy', 'redeploy', 'publish'}:
                return 'release'
            if executable == 'vercel' and '--prod' in words:
                return 'release'
        if executable in {'npm', 'pnpm', 'yarn'} and words[:2] == ['run', 'deploy']:
            return 'release'
        if executable in {'python', 'python3', 'node', 'ruby', 'bash', 'sh', 'zsh',
                          'cp', 'mv', 'rm', 'mkdir', 'tee', 'touch', 'apply_patch'}:
            kind = 'edit'  # Opaque scripts get a reminder, not a completion gate.
    return kind


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


def handle(payload, engine, root):
    if not isinstance(payload, dict):
        return {}
    event = payload.get('hook_event_name')
    if event not in {'UserPromptSubmit', 'PreToolUse', 'Stop'}:
        return {}
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        return {}
    if event == 'Stop' and (payload.get('stop_hook_active') or payload.get('background_tasks')
                            or payload.get('session_crons')):
        return {}
    kind, groups, sensitive = classify(payload) if event == 'PreToolUse' else ('', set(), False)
    if event == 'PreToolUse' and not kind:
        return {}
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
            output = context(event, START)
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
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('codex', 'claude'), required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    try:
        if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != args.revision:
            raise ValueError('Installed revision mismatch')
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('Input too large')
        output = handle(json.loads(raw), args.engine, args.root)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        # Advisory failure: never echo input or block the user's work on a hook error.
        print('Communication reminder unavailable; follow the workspace instructions.', file=sys.stderr)
        output = {}
    print(json.dumps(output, ensure_ascii=False))


if __name__ == '__main__':
    main()

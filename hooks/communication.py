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
from urllib.parse import urlsplit

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
    '남아 있으면 증표를 만들지 말고 먼저 해결한다. 머지는 명시 PR 번호와 검토 HEAD를 사용하고 원격 '
    'base/head·CI가 증표와 일치해야 한다. 경계 명령이 차단되면 사유에 표시된 기록 명령을 따른다.'
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


class ShellToken(str):
    """Decoded argument or an actual (unquoted) shell operator."""
    def __new__(cls, value, operator=False, quoted=False):
        token = super().__new__(cls, value)
        token.operator = operator
        token.quoted = quoted
        return token


class ShellParseError(ValueError):
    def __init__(self, message, tokens):
        super().__init__(message)
        self.tokens = tokens


def shell_tokens(command):
    """Lex static Bash/Zsh words, retaining operators and skipping heredoc data.

    This is not an evaluator: substitutions, wrappers and shell programs remain
    outside the direct-command contract. Never execute input to classify it.
    """
    tokens, pending, word = [], [], []
    active = quoted = False
    quote = None
    delimiter = None
    i = 0

    def emit():
        nonlocal active, quoted, word, delimiter
        if active:
            token = ShellToken(''.join(word), quoted=quoted)
            tokens.append(token)
            if delimiter is not None:
                pending.append((str(token), delimiter, token.quoted))
                delimiter = None
            active = quoted = False
            word = []

    def fail(message):
        emit()
        raise ShellParseError(message, tokens)

    while i < len(command):
        char = command[i]
        if quote == "ansi":
            if char == "'":
                quote = None
                i += 1
                continue
            if char == '\\':
                i += 1
                if i == len(command):
                    fail('Incomplete ANSI-C escape')
                escape = command[i]
                simple = {'a': '\a', 'b': '\b', 'e': '\x1b', 'E': '\x1b',
                          'f': '\f', 'n': '\n', 'r': '\r', 't': '\t',
                          'v': '\v', '\\': '\\', "'": "'", '"': '"'}
                if escape in simple:
                    word.append(simple[escape])
                    i += 1
                    continue
                # Numeric/control escapes vary across shells and locales. They
                # are deliberately uncertain, rather than decoded approximately.
                fail('Unsupported ANSI-C escape; use literal text or --body-file')
            word.append(char)
            i += 1
            continue
        if quote == "'":
            if char == "'":
                quote = None
            else:
                word.append(char)
            i += 1
            continue
        if char == '\\':
            if i + 1 == len(command):
                fail('Incomplete shell escape')
            following = command[i + 1]
            if following == '\n':
                i += 2
                continue
            active = True
            quoted = True
            if quote == '"' and following not in '$`"\\':
                word.append('\\')
            word.append(following)
            i += 2
            continue
        if quote:
            if char == quote:
                quote = None
            else:
                word.append(char)
            i += 1
            continue
        if command.startswith("$'", i):
            active = quoted = True
            quote = 'ansi'
            i += 2
            continue
        if char in "'\"`":
            active = quoted = True
            quote = char
            i += 1
            continue
        if char == '#' and not active:
            end = command.find('\n', i)
            i = len(command) if end == -1 else end
            continue
        if char in ' \t\r':
            emit()
            i += 1
            continue
        if char in ';&|()<>\n':
            emit()
            operator = char
            i += 1
            if char != '\n':
                while i < len(command) and command[i] == char:
                    operator += char
                    i += 1
                if operator == '<<' and command[i:i + 1] == '-':
                    operator += '-'
                    i += 1
                elif operator in {'<', '>'} and command[i:i + 1] in {'&', '|', '>'}:
                    operator += command[i]
                    i += 1
            if delimiter is not None:
                fail('Missing heredoc delimiter')
            tokens.append(ShellToken(operator, operator=True))
            if operator in {'<<', '<<-'}:
                delimiter = operator == '<<-'
            if char == '\n':
                for marker, strip_tabs, literal in pending:
                    found = False
                    while i < len(command):
                        end = command.find('\n', i)
                        end = len(command) if end == -1 else end + 1
                        line = command[i:end]
                        i = end
                        while not literal and line.endswith('\n'):
                            tail = line[:-1]
                            if (len(tail) - len(tail.rstrip('\\'))) % 2 == 0:
                                break
                            end = command.find('\n', i)
                            end = len(command) if end == -1 else end + 1
                            line = line[:-2] + command[i:end]
                            i = end
                        candidate = line[:-1] if line.endswith('\n') else line
                        if (candidate.lstrip('\t') if strip_tabs else candidate) == marker:
                            found = True
                            break
                    if not found:
                        fail('Unterminated heredoc')
                pending.clear()
            continue
        active = True
        word.append(char)
        i += 1
    if quote:
        fail('Unterminated shell quote')
    emit()
    if delimiter is not None or pending:
        fail('Unterminated heredoc')
    return tokens


def token_segments(tokens):
    segments, segment = [], []
    for token in tokens:
        if token.operator and all(c in ';&|()\n' for c in token):
            if segment:
                segments.append(segment)
            segment = []
        else:
            segment.append(token)
    if segment:
        segments.append(segment)
    return segments


def shell_segments(command):
    return token_segments(shell_tokens(command))


def push_boundary(words, repo=None):
    """Accept one explicit destination and refspec; never infer push.default."""
    boundary = {'action': 'push', 'repo': repo, 'base': None, 'remote': None,
                'refspec': None, 'lease': None, 'delete': False, 'error': None,
                'cleanup_options': True, 'dry_run': False, 'help': False,
                'unknown_option': False}
    positional = []
    flags = True
    for word in words:
        if flags and word == '--':
            flags = False
        elif flags and word in {'-h', '--help'}:
            boundary['help'] = True
        elif flags and word in {'--dry-run', '-n'}:
            boundary['dry_run'] = True
        elif flags and word.startswith('--force-with-lease='):
            if boundary['lease'] is not None:
                boundary['error'] = 'Only one explicit force-with-lease is supported'
            boundary['lease'] = word.split('=', 1)[1]
        elif flags and word in {'--delete', '-d'}:
            boundary['cleanup_options'] = False
            boundary['delete'] = True
            boundary['error'] = 'Delete with an explicit lease and :refs/heads/<branch> refspec'
        elif flags and word in {'-u', '--set-upstream', '-q', '--quiet', '-v', '--verbose',
                                '--porcelain', '--progress', '--no-progress', '--atomic',
                                '--no-verify', '--no-follow-tags', '--force-with-lease',
                                '--force-if-includes', '-f', '--force'}:
            boundary['cleanup_options'] = False
            continue
        elif flags and word.startswith('-'):
            boundary['unknown_option'] = True
            if word.startswith('--') and (
                    (len(word) > 2 and '--delete'.startswith(word))
                    or word in {'--mirror', '--prune'}):
                boundary['delete'] = True
            if not word.startswith('--') and 'd' in word[1:]:
                boundary['delete'] = True
            boundary['error'] = 'Unsupported push option; use one explicit remote and refspec'
        else:
            positional.append(word)
    boundary['delete'] |= any(word.startswith((':', '+:')) for word in positional)
    if len(positional) != 2:
        boundary['error'] = 'git push requires one explicit named remote and one refspec'
    else:
        boundary['remote'], boundary['refspec'] = positional
    return boundary


def gh_boundary(words, repo=None):
    """Parse documented direct create/merge options without interpreting body text."""
    words = list(words)
    overridden = False
    help_requested = False
    error = None

    def global_option():
        nonlocal overridden, error, help_requested
        if not words:
            return False
        word = words[0]
        option, separator, value = word.partition('=')
        if option in {'-h', '--help'}:
            if not separator or value in {'1', 't', 'T', 'true', 'TRUE', 'True'}:
                help_requested = True
            elif value in {'0', 'f', 'F', 'false', 'FALSE', 'False'}:
                help_requested = False
            else:
                error = 'Invalid help flag value'
            words.pop(0)
            return True
        if word in {'-R', '--repo', '--hostname'}:
            overridden = True
            del words[:2]
            return True
        if word.startswith(('--repo=', '--hostname=')) or (word.startswith('-R') and len(word) > 2):
            overridden = True
            words.pop(0)
            return True
        return False

    while global_option():
        pass
    if not words or words.pop(0) != 'pr':
        return None
    while global_option():
        pass
    if not words or words[0] not in {'create', 'merge'}:
        return None
    action = words.pop(0)
    boundary = {'action': action, 'repo': repo, 'base': None, 'head': None,
                'remote_repo': False, 'pr_number': None, 'match_head': None, 'error': None}
    value_options = ({'--base': 'base', '-B': 'base', '--head': 'head', '-H': 'head',
                      '--title': None, '-t': None, '--body': None, '-b': None,
                      '--body-file': None, '-F': None, '--template': None, '-T': None,
                      '--assignee': None, '-a': None, '--reviewer': None, '-r': None,
                      '--label': None, '-l': None, '--project': None, '-p': None,
                      '--milestone': None, '-m': None, '--recover': None}
                     if action == 'create' else
                     {'--match-head-commit': 'match_head', '--subject': None, '-t': None,
                      '--body': None, '-b': None, '--body-file': None, '-F': None,
                      '--author-email': None, '-A': None})
    boolean_options = ({'--draft', '-d', '--fill', '-f', '--fill-first', '--fill-verbose',
                        '--editor', '-e', '--web', '-w', '--dry-run'}
                       if action == 'create' else
                       {'--merge', '-m', '--squash', '-s', '--rebase', '-r', '--auto',
                        '--disable-auto', '--admin', '--delete-branch', '-d'})
    positionals = []
    while words:
        if global_option():
            continue
        word = words.pop(0)
        if word == '--':
            positionals.extend(words)
            break
        option, separator, attached = word.partition('=')
        if not separator and word.startswith('-') and not word.startswith('--') and len(word) > 2:
            option, attached, separator = word[:2], word[2:], '='
        if option in value_options:
            if not separator and not words:
                error = 'A PR option is missing its value'
                break
            value = attached if separator else words.pop(0)
            key = value_options[option]
            if key:
                if boundary[key] is not None:
                    error = 'Do not repeat PR target options'
                boundary[key] = value
        elif word in {'--admin', '--delete-branch'} or (action == 'merge' and word == '-d'):
            error = 'Merge without admin bypass or branch deletion; use separate merged-PR cleanup'
        elif word in boolean_options:
            pass
        elif word.startswith('-'):
            error = 'Unsupported PR option; use documented explicit create/merge options'
        else:
            positionals.append(word)
    if action == 'merge' and len(positionals) == 1:
        boundary['pr_number'] = positionals[0]
    elif positionals:
        error = 'Use a single numeric PR number for merge and no positional target for create'
    boundary.update(remote_repo=overridden, error=error)
    return None if help_requested else boundary


def shell_events(command):
    """Identify direct commands. PR boundaries must be isolated shell commands."""
    parse_error = None
    try:
        segments = shell_segments(command)
    except ShellParseError as exc:
        segments = token_segments(exc.tokens)
        parse_error = str(exc)
    kind, boundaries = '', []
    for words in segments:
        words = list(words)
        environment = False
        if words and Path(words[0]).name == 'env':
            environment = True
            words.pop(0)
            while words and words[0].startswith('-'):
                option = words.pop(0)
                if option in {'-u', '--unset', '-C', '--chdir'} and words:
                    words.pop(0)
        while words and re.match(r'^[A-Za-z_][A-Za-z_0-9]*=', words[0]):
            environment = True
            words.pop(0)
        if not words:
            continue
        executable = Path(words.pop(0)).name
        boundary = None
        if executable == 'git':
            repo_arg, unsafe_git = None, False
            while words and words[0].startswith('-'):
                option = words.pop(0)
                if option == '-C' and words:
                    if repo_arg is not None:
                        unsafe_git = True
                    repo_arg = words.pop(0)
                elif option.startswith('-C') and len(option) > 2:
                    unsafe_git |= repo_arg is not None
                    repo_arg = option[2:]
                else:
                    unsafe_git = True
                    if option in {'-c', '--git-dir', '--work-tree', '--namespace', '--config-env'} and words:
                        words.pop(0)
            if words and words[0] == 'push':
                boundary = push_boundary(words[1:], repo_arg)
                if (boundary['dry_run'] or boundary['help']) and not boundary['unknown_option']:
                    boundary = None
                else:
                    kind = 'release'
                    if unsafe_git:
                        boundary['error'] = 'Only a single git -C directory override is supported'
        if executable == 'gh':
            boundary = gh_boundary(words)
            if boundary or words[:2] == ['release', 'create']:
                kind = 'release'
        if boundary:
            if environment:
                boundary['error'] = 'Run PR boundaries without env or inline environment assignments'
            if len(segments) != 1 or any(word.operator and any(c in '<>' for c in word)
                                         for segment in segments for word in segment):
                boundary['error'] = 'Run each PR boundary as a standalone shell command without redirection'
            boundaries.append(boundary)
        if executable in {'railway', 'vercel', 'fly', 'flyctl', 'firebase', 'wrangler'}:
            if words and words[0] in {'up', 'deploy', 'redeploy', 'publish'}:
                kind = 'release'
            if executable == 'vercel' and '--prod' in words:
                kind = 'release'
        if executable in {'npm', 'pnpm', 'yarn'} and words[:2] == ['run', 'deploy']:
            kind = 'release'
        if executable in {'python', 'python3', 'node', 'ruby', 'bash', 'sh', 'zsh',
                          'cp', 'mv', 'rm', 'mkdir', 'tee', 'touch', 'apply_patch'} and kind != 'release':
            kind = 'edit'  # Opaque scripts get a reminder, not a completion gate.
    if parse_error:
        # A failed parse is not evidence that the command contains no PR action.
        # Inspect only on failure; valid quoted examples/heredocs stay advisory.
        candidate = (boundaries
                     or any(segment and Path(segment[0]).name in {'git', 'gh'}
                            for segment in segments)
                     or re.search(r'\b(?:git\s+push|gh\s+pr\s+(?:create|merge))\b', command))
        if candidate:
            return 'release', {'action': 'parse-error', 'repo': None,
                               'error': 'PR command could not be parsed: ' + parse_error}
    # Always-gated PR/cleanup commands must not be hidden by a preceding ordinary push.
    boundary = max(boundaries, key=lambda item: 2 if item['action'] != 'push'
                   else int(item.get('delete', False)), default=None)
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


def remote_pr_state(repo, pr_number):
    fields = ('number,state,isDraft,baseRefName,baseRefOid,headRefName,headRefOid,'
              'mergeable,mergeStateStatus,statusCheckRollup,url,mergeCommit,isCrossRepository')
    environment = dict(os.environ)
    environment['GH_PROMPT_DISABLED'] = '1'
    result = subprocess.run(['gh', 'pr', 'view', str(pr_number), '--json', fields],
                            cwd=repo, env=environment, capture_output=True, timeout=8,
                            check=False)
    if result.returncode:
        raise ValueError('GitHub PR state could not be verified')
    try:
        state = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('GitHub PR state returned invalid JSON') from exc
    if not isinstance(state, dict):
        raise ValueError('GitHub PR state returned an invalid shape')
    return state


def remote_repository_identity(repo):
    """Read the repository selected by gh's own remotes/default-repository rules."""
    environment = dict(os.environ)
    environment['GH_PROMPT_DISABLED'] = '1'
    result = subprocess.run(['gh', 'repo', 'view', '--json', 'url'], cwd=repo,
                            env=environment, capture_output=True, timeout=8, check=False)
    if result.returncode:
        raise ValueError('GitHub repository selection could not be verified')
    try:
        state = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('GitHub repository selection returned invalid JSON') from exc
    if not isinstance(state, dict) or not isinstance(state.get('url'), str):
        raise ValueError('GitHub repository selection returned an invalid shape')
    return repository_identity(state['url'])


def remote_branch_sha(repo, remote, branch):
    output, _ = git_output(repo, 'ls-remote', '--heads', remote, 'refs/heads/' + branch)
    lines = output.decode().splitlines()
    if len(lines) != 1:
        raise ValueError('Push the reviewed branch before creating a PR')
    fields = lines[0].split()
    if (len(fields) != 2 or fields[1] != 'refs/heads/' + branch
            or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', fields[0])):
        raise ValueError('The remote PR branch SHA could not be verified')
    return fields[0]


def pr_repository_identity(state, pr_number):
    url = state.get('url')
    if not isinstance(url, str):
        raise ValueError('The PR repository identity could not be verified')
    parts = urlsplit(url)
    suffix = '/pull/' + str(pr_number)
    if parts.scheme != 'https' or not parts.hostname or not parts.path.endswith(suffix):
        raise ValueError('The PR URL does not identify the requested PR')
    return repository_identity('https://' + parts.hostname + parts.path[:-len(suffix)])


def reviewed_base_name(repo, base_ref):
    output, _ = git_output(repo, 'rev-parse', '--symbolic-full-name', '--verify',
                           '--end-of-options', base_ref)
    full_name = output.decode().strip()
    if full_name.startswith('refs/heads/'):
        return full_name.removeprefix('refs/heads/')
    if full_name.startswith('refs/remotes/'):
        parts = full_name.split('/', 3)
        if len(parts) == 4 and parts[3]:
            return parts[3]
    raise ValueError('The reviewed base must identify a local or remote-tracking branch')


def check_remote_pr(repo, boundary, base_ref, base_sha, head_sha, recorded_identity):
    pr_number = boundary.get('pr_number')
    if not isinstance(pr_number, str) or not pr_number.isdigit():
        raise ValueError('gh pr merge requires an explicit numeric PR number')
    if boundary.get('match_head') != head_sha:
        raise ValueError('gh pr merge --match-head-commit must equal the reviewed HEAD')
    state = remote_pr_state(repo, pr_number)
    if state.get('number') != int(pr_number):
        raise ValueError('GitHub returned a different PR number')
    if digest(pr_repository_identity(state, pr_number)) != recorded_identity:
        raise ValueError('The remote PR repository does not match the reviewed repository')
    if state.get('state') != 'OPEN' or state.get('isDraft') is not False:
        raise ValueError('The target PR is not an open non-draft PR')
    if state.get('baseRefName') != reviewed_base_name(repo, base_ref):
        raise ValueError('The remote PR base branch does not match the reviewed base')
    if state.get('baseRefOid') != base_sha:
        raise ValueError('The remote PR base SHA does not match the reviewed base')
    if state.get('headRefOid') != head_sha:
        raise ValueError('The remote PR head SHA does not match the reviewed HEAD')
    if state.get('mergeable') != 'MERGEABLE':
        raise ValueError('The remote PR is not currently mergeable')
    checks = state.get('statusCheckRollup')
    if not isinstance(checks, list):
        raise ValueError('The remote PR CI state could not be read')
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError('The remote PR CI state has an invalid shape')
        status = str(check.get('status', '')).upper()
        conclusion = str(check.get('conclusion', '')).upper()
        context_state = str(check.get('state', '')).upper()
        if status or conclusion:
            if status != 'COMPLETED':
                raise ValueError('The remote PR still has pending CI checks')
            if conclusion not in {'SUCCESS', 'NEUTRAL', 'SKIPPED'}:
                raise ValueError('The remote PR has unsuccessful CI checks')
        elif context_state != 'SUCCESS':
            raise ValueError('The remote PR has incomplete or unsuccessful CI checks')
    return state


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
    for column in ('untracked', 'remote_name', 'remote_identity', 'head_name'):
        if column not in columns:
            db.execute("ALTER TABLE reviews ADD COLUMN " + column + " TEXT NOT NULL DEFAULT ''")


def record_review(root, repo, base, requirements, contracts, validation,
                  major=0, minor=0, blocker=0):
    if not all((requirements, contracts, validation)):
        raise ValueError('All review attestations are required')
    if any(not isinstance(value, int) or value < 0 for value in (major, minor, blocker)):
        raise ValueError('Finding counts must be non-negative integers')
    if major or blocker:
        raise ValueError('Resolve MAJOR and BLOCKER findings before recording a pass')
    check_command_context({})
    repo, base_sha, head_sha, merge_base, untracked = repository_state(root, repo, base)
    remote = review_remote(repo, base)
    identity = digest(remote_identity(repo, remote))
    head_name, _ = git_output(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    head_name = head_name.decode().strip()
    with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
        ensure_review_table(db)
        db.execute('''INSERT OR REPLACE INTO reviews
                      (repo, base_ref, base_sha, head_sha, merge_base, untracked, minor, updated,
                       remote_name, remote_identity, head_name)
                      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                   (digest(str(repo)), base, base_sha, head_sha, merge_base, untracked,
                    minor, time.time(), remote, identity, head_name))
    return {'base': base_sha, 'head': head_sha, 'minor': minor}


def review_record_command(root, repo):
    command = [sys.executable, str(Path(__file__).resolve()), '--root', str(root),
               '--record-pr-review', '--repo', str(repo), '--base', '<fetched-remote-base>',
               '--requirements-reviewed', '--contracts-reviewed', '--validation-reviewed',
               '--major', '0', '--blocker', '0', '--minor', '<count>']
    return shlex.join(command)


def named_remotes(repo):
    output, _ = git_output(repo, 'remote')
    return output.decode().splitlines()


def repository_identity(url):
    """Compare destinations without retaining credentials or emitting raw URLs."""
    if '://' not in url:
        ssh = re.fullmatch(r'(?:[^/@:]+@)?([^/:]+):(.+)', url)
        if ssh:
            host, path = ssh.groups()
        else:
            return 'file:' + str(Path(url).resolve())
    else:
        parts = urlsplit(url)
        if parts.scheme not in {'https', 'http', 'ssh', 'git'} or not parts.hostname:
            raise ValueError('Unsupported remote repository URL')
        host, path = parts.hostname, parts.path
    path = path.strip('/').removesuffix('.git')
    if not path or any(part in {'', '.', '..'} for part in path.split('/')):
        raise ValueError('Invalid remote repository identity')
    return host.lower() + '/' + path.lower()


def remote_identity(repo, remote):
    if not isinstance(remote, str) or remote not in named_remotes(repo):
        raise ValueError('Use one explicitly configured remote name')
    fetch, _ = git_output(repo, 'remote', 'get-url', '--all', remote)
    push, _ = git_output(repo, 'remote', 'get-url', '--push', '--all', remote)
    fetch_urls, push_urls = fetch.decode().splitlines(), push.decode().splitlines()
    if len(fetch_urls) != 1 or len(push_urls) != 1:
        raise ValueError('Exactly one fetch URL and one push URL are required')
    identity = repository_identity(fetch_urls[0])
    if repository_identity(push_urls[0]) != identity:
        raise ValueError('Remote fetch and push repository identities differ')
    return identity


def review_remote(repo, base_ref):
    output, _ = git_output(repo, 'rev-parse', '--symbolic-full-name', '--verify',
                           '--end-of-options', base_ref)
    full_name = output.decode().strip()
    if full_name.startswith('refs/remotes/'):
        return full_name.split('/', 3)[2]
    remotes = named_remotes(repo)
    if 'origin' in remotes:
        return 'origin'
    if len(remotes) == 1:
        return remotes[0]
    raise ValueError('Review a fetched remote base or configure one unambiguous origin remote')


def check_command_context(boundary):
    if boundary.get('error'):
        raise ValueError(boundary['error'])
    if boundary.get('remote_repo'):
        raise ValueError('Run gh from the reviewed local repository without --repo/-R or hostname overrides')
    if any(os.environ.get(key) for key in ('GH_REPO', 'GH_HOST', 'GIT_DIR', 'GIT_WORK_TREE',
                                          'GIT_COMMON_DIR', 'GIT_CONFIG_COUNT', 'GIT_CONFIG_PARAMETERS')):
        raise ValueError('Clear inherited Git/GitHub repository override variables before this command')


def check_push(repo, boundary, head_sha, recorded_identity):
    remote, refspec = boundary.get('remote'), boundary.get('refspec')
    if not isinstance(refspec, str) or not refspec or refspec.startswith((':', '+')):
        raise ValueError('Use a single non-deletion refspec with an explicit reviewed source')
    if refspec.count(':') > 1 or '*' in refspec:
        raise ValueError('Wildcard or multiple push refspecs are not supported')
    source, separator, destination = refspec.partition(':')
    if separator and not destination:
        raise ValueError('Push destination must not be empty')
    branch, _ = git_output(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
    branch = branch.decode().strip()
    if (separator and destination not in {branch, 'refs/heads/' + branch}) or (
            not separator and source not in {branch, 'refs/heads/' + branch, 'HEAD'}):
        raise ValueError('Push destination must be the currently reviewed branch')
    if commit_sha(repo, source) != head_sha:
        raise ValueError('Push source SHA does not match the reviewed HEAD')
    if digest(remote_identity(repo, remote)) != recorded_identity:
        raise ValueError('Push remote does not match the reviewed base repository')
    check_single_push_config(repo, remote)


def check_single_push_config(repo, remote):
    mirror, _ = git_output(repo, 'config', '--bool', '--get', 'remote.' + remote + '.mirror', allowed=(0, 1))
    follow_tags, _ = git_output(repo, 'config', '--bool', '--get', 'push.followTags', allowed=(0, 1))
    if mirror.strip() == b'true' or follow_tags.strip() == b'true':
        raise ValueError('Disable remote mirror and push.followTags before a reviewed single-ref push')


def ensure_cleanup_table(db):
    db.execute('''CREATE TABLE IF NOT EXISTS cleanups
                  (repo TEXT, remote TEXT, pr_number TEXT, head_name TEXT, head_sha TEXT,
                   base_name TEXT, merge_sha TEXT, identity TEXT, updated REAL,
                   PRIMARY KEY (repo, remote, head_name))''')


def cleanup_state(repo, pr_number, remote):
    if not str(pr_number).isdigit():
        raise ValueError('Cleanup requires an explicit numeric PR number')
    state = remote_pr_state(repo, str(pr_number))
    if state.get('number') != int(pr_number) or state.get('state') != 'MERGED':
        raise ValueError('The cleanup target PR must be MERGED')
    if state.get('isCrossRepository') is not False:
        raise ValueError('Only a same-repository merged PR can authorize cleanup')
    head, base = state.get('headRefName'), state.get('baseRefName')
    if not isinstance(head, str) or not isinstance(base, str):
        raise ValueError('The merged PR branch names could not be verified')
    if head == base or head in {'main', 'master', 'develop', 'development', 'trunk'}:
        raise ValueError('A persistent integration branch is not a cleanup target')
    git_output(repo, 'check-ref-format', 'refs/heads/' + head)
    git_output(repo, 'check-ref-format', 'refs/heads/' + base)
    head_sha = state.get('headRefOid')
    merge = state.get('mergeCommit')
    merge_sha = merge.get('oid') if isinstance(merge, dict) else None
    if any(not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', sha)
           for sha in (head_sha, merge_sha)):
        raise ValueError('The merged PR head and merge commit SHAs could not be verified')
    identity = remote_identity(repo, remote)
    if identity != pr_repository_identity(state, pr_number):
        raise ValueError('Cleanup remote does not match the merged PR repository')
    check_single_push_config(repo, remote)
    fetched_base = commit_sha(repo, 'refs/remotes/' + remote + '/' + base)
    _, contained = git_output(repo, 'merge-base', '--is-ancestor', merge_sha, fetched_base,
                              allowed=(0, 1))
    if contained:
        raise ValueError('Fetch the merged PR base before recording or using cleanup evidence')
    return head, head_sha, base, merge_sha, digest(identity)


def record_cleanup(root, repo, pr_number, remote):
    check_command_context({})
    repo = resolve_repo(root, repo)
    values = cleanup_state(repo, pr_number, remote)
    with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
        ensure_cleanup_table(db)
        db.execute('INSERT OR REPLACE INTO cleanups VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                   (digest(str(repo)), remote, str(pr_number), *values, time.time()))
    return {'pr': int(pr_number), 'head': values[1], 'branch': values[0], 'remote': remote}


def cleanup_record_command(root, repo, remote='<remote>', pr_number='<merged-pr-number>'):
    return shlex.join([sys.executable, str(Path(__file__).resolve()), '--root', str(root),
                       '--record-pr-cleanup', '--repo', str(repo), '--pr', str(pr_number),
                       '--remote', remote])


def check_cleanup(root, cwd, boundary):
    try:
        check_command_context(boundary)
        repo = resolve_repo(root, cwd, boundary.get('repo'))
        refspec, remote, lease = boundary.get('refspec'), boundary.get('remote'), boundary.get('lease')
        if not boundary.get('cleanup_options'):
            raise ValueError('Cleanup supports only an explicit lease, named remote and deletion refspec')
        if not isinstance(refspec, str) or not refspec.startswith(':refs/heads/'):
            raise ValueError('Cleanup requires one exact :refs/heads/<branch> deletion refspec')
        head = refspec.removeprefix(':refs/heads/')
        git_output(repo, 'check-ref-format', 'refs/heads/' + head)
        with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
            ensure_cleanup_table(db)
            row = db.execute('SELECT pr_number, head_name, head_sha, base_name, merge_sha, identity, updated '
                             'FROM cleanups WHERE repo=? AND remote=? AND head_name=?',
                             (digest(str(repo)), remote, head)).fetchone()
        if not row:
            raise ValueError('No merged-PR cleanup receipt exists for this branch and remote')
        pr_number, recorded_head, head_sha, base_name, merge_sha, identity, updated = row
        if time.time() - updated > REVIEW_MAX_AGE:
            raise ValueError('The cleanup receipt is older than 24 hours')
        if lease != 'refs/heads/' + head + ':' + head_sha:
            raise ValueError('Cleanup requires --force-with-lease=refs/heads/<branch>:<merged-head-sha>')
        if cleanup_state(repo, pr_number, remote) != (recorded_head, head_sha, base_name, merge_sha, identity):
            raise ValueError('Merged PR cleanup evidence changed after it was recorded')
        return None
    except (OSError, TypeError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
        try:
            repo = resolve_repo(root, cwd, boundary.get('repo'))
        except (OSError, TypeError, ValueError, subprocess.SubprocessError):
            repo = Path(cwd)
        return deny('PR cleanup gate blocked this command: ' + (str(exc) or 'Cleanup state unavailable')
                    + '. Fetch the merged base and record separate cleanup evidence; a PR diff review '
                    'receipt cannot authorize branch deletion. Retry after:\n'
                    + cleanup_record_command(root, repo))


def check_review(root, cwd, boundary):
    try:
        check_command_context(boundary)
        repo = resolve_repo(root, cwd, boundary.get('repo'))
        if boundary['action'] == 'create' and not boundary.get('base'):
            raise ValueError('gh pr create must include an explicit --base')
        if boundary['action'] == 'create' and not boundary.get('head'):
            raise ValueError('gh pr create must include an explicit --head for the reviewed branch')
        with closing(sqlite3.connect(safe_state_path(root), timeout=1)) as db, db:
            ensure_review_table(db)
            row = db.execute('SELECT base_ref, base_sha, head_sha, merge_base, untracked, updated, '
                             'remote_name, remote_identity, head_name '
                             'FROM reviews WHERE repo=?', (digest(str(repo)),)).fetchone()
        if not row:
            raise ValueError('No review receipt exists for this repository')
        (base_ref, base_sha, head_sha, merge_base, untracked, updated, remote,
         recorded_identity, head_name) = row
        if not remote or not recorded_identity or not head_name:
            raise ValueError('The review receipt needs to be recorded again with repository identity')
        if digest(remote_identity(repo, remote)) != recorded_identity:
            raise ValueError('Reviewed remote repository changed after review')
        branch, _ = git_output(repo, 'symbolic-ref', '--quiet', '--short', 'HEAD')
        if branch.decode().strip() != head_name:
            raise ValueError('Current branch changed after review')
        if time.time() - updated > REVIEW_MAX_AGE:
            raise ValueError('The review receipt is older than 24 hours')
        current_repo, current_base, current_head, current_merge, current_untracked = repository_state(
            root, repo, base_ref)
        if current_repo != repo or (current_base, current_head, current_merge,
                                    current_untracked) != (
                base_sha, head_sha, merge_base, untracked):
            raise ValueError('Base, HEAD, or working tree changed after review')
        if boundary.get('base') and boundary['base'] != reviewed_base_name(repo, base_ref):
            raise ValueError('PR command base branch does not match the reviewed base')
        if boundary['action'] == 'create':
            if boundary['head'] != head_name:
                raise ValueError('PR command head must be the currently reviewed branch')
            if digest(remote_repository_identity(repo)) != recorded_identity:
                raise ValueError('GitHub selected repository does not match the reviewed repository')
            if remote_branch_sha(repo, remote, head_name) != head_sha:
                raise ValueError('Remote PR branch SHA does not match the reviewed HEAD; push it first')
        if boundary['action'] == 'push':
            check_push(repo, boundary, head_sha, recorded_identity)
        if boundary['action'] == 'merge':
            check_remote_pr(repo, boundary, base_ref, base_sha, head_sha, recorded_identity)
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
            'then record the clean final state. For merge, use an explicit PR number and '
            '--match-head-commit with the reviewed full HEAD SHA after remote CI succeeds. Retry after:\n'
            + command)


def session_context(payload, engine, root):
    """Return advisory output and True/False/None for this turn's PR intent."""
    event = payload.get('hook_event_name')
    session = payload.get('session_id')
    if not isinstance(session, str) or not session:
        return {}, None
    if event == 'Stop' and (payload.get('stop_hook_active') or payload.get('background_tasks')
                            or payload.get('session_crons')):
        return {}, None
    kind, groups, sensitive = classify(payload) if event == 'PreToolUse' else ('', set(), False)
    if event == 'PreToolUse' and not kind:
        return {}, None
    prompt = payload.get('prompt')
    requested_pr = pr_prompt(prompt) if isinstance(prompt, str) else None
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
            return (context(event, START) if event == 'UserPromptSubmit' else {}), None
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
                return {}, None  # No prompt boundary: don't reuse or invent a task.
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
    intent = state.get('pr_intent')
    if state.get('started') is not True or not isinstance(intent, bool):
        intent = None
    return output, intent


def handle(payload, engine, root):
    if not isinstance(payload, dict):
        return {}
    event = payload.get('hook_event_name')
    if event not in {'UserPromptSubmit', 'PreToolUse', 'Stop'}:
        return {}
    boundary = None
    command_cwd = payload.get('cwd', root)
    if event == 'PreToolUse' and payload.get('tool_name') in {'Bash', 'exec_command'}:
        args = payload.get('tool_input', {})
        if isinstance(args, dict):
            if payload.get('tool_name') == 'exec_command' and isinstance(args.get('workdir'), str):
                selected_cwd = Path(args['workdir'])
                command_cwd = (selected_cwd if selected_cwd.is_absolute()
                               else Path(command_cwd) / selected_cwd)
            command = str(args.get('command', args.get('cmd', '')))
            _, boundary = shell_events(command)
    if boundary and boundary['action'] == 'parse-error':
        return deny(boundary['error'] + '. Use a standalone direct command with literal '
                    'arguments or --body-file; a new review receipt cannot repair shell syntax.')
    if boundary and boundary.get('delete'):
        blocked = check_cleanup(root, command_cwd, boundary)
        if blocked:
            return blocked
    elif boundary and boundary['action'] in {'create', 'merge'}:
        blocked = check_review(root, command_cwd, boundary)
        if blocked:
            return blocked
    ordinary_push = boundary and boundary['action'] == 'push' and not boundary.get('delete')
    try:
        output, intent = session_context(payload, engine, root)
    except (OSError, ValueError, TypeError, subprocess.SubprocessError, sqlite3.Error):
        if not ordinary_push:
            raise  # Advisory errors remain fail open in main().
        output, intent = {}, None
    # Missing or unreadable prompt state cannot establish that review is unnecessary.
    if ordinary_push and intent is not False:
        blocked = check_review(root, command_cwd, boundary)
        if blocked:
            return blocked
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('codex', 'claude'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--revision')
    record = parser.add_mutually_exclusive_group()
    record.add_argument('--record-pr-review', action='store_true')
    record.add_argument('--record-pr-cleanup', action='store_true')
    parser.add_argument('--pr')
    parser.add_argument('--remote')
    parser.add_argument('--repo', type=Path)
    parser.add_argument('--base')
    parser.add_argument('--requirements-reviewed', action='store_true')
    parser.add_argument('--contracts-reviewed', action='store_true')
    parser.add_argument('--validation-reviewed', action='store_true')
    parser.add_argument('--major', type=int, default=0)
    parser.add_argument('--minor', type=int, default=0)
    parser.add_argument('--blocker', type=int, default=0)
    args = parser.parse_args()
    if args.record_pr_cleanup:
        try:
            if args.repo is None or args.pr is None or args.remote is None:
                raise ValueError('--repo, --pr and --remote are required')
            result = record_cleanup(args.root, args.repo, args.pr, args.remote)
        except (OSError, ValueError, subprocess.SubprocessError, sqlite3.Error) as exc:
            print('PR cleanup receipt not recorded: ' + str(exc), file=sys.stderr)
            return 2
        print(json.dumps({'recorded': True, **result}, ensure_ascii=False))
        return 0
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

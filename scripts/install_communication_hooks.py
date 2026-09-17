#!/usr/bin/env python3
"""Install communication reminders and the PR review gate in one workspace."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = '.workflow-hooks/communication.py'
MANIFEST = '.workflow-hooks/install.json'
CONFIGS = {'codex': '.codex/hooks.json', 'claude': '.claude/settings.local.json'}
IGNORE = ('/ai-input/', '/.workflow-hooks/', '/.codex/hooks.json', '/.claude/settings.local.json')


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.hook-install-', delete=False) as stream:
            temp = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temp.chmod(path.stat().st_mode & 0o777 if path.exists() else 0o600)
        os.replace(temp, path)
    finally:
        if temp:
            temp.unlink(missing_ok=True)


def guarded_path(root, name):
    path = root / name
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError(f'Symlink preserved: {item}')
        if item == root:
            break
    if path.exists() and not path.is_file():
        raise ValueError(f'Expected file: {path}')
    return path


def definitions(root, engine, revision):
    command = shlex.join([sys.executable, str(root / RUNTIME), '--engine', engine,
                          '--root', str(root), '--revision', revision])
    result = {}
    for event in ('UserPromptSubmit', 'PreToolUse', 'Stop'):
        handler = {'type': 'command', 'command': command,
                   'timeout': 20 if event == 'PreToolUse' else 3}
        if engine == 'codex' and event != 'Stop':
            handler['additionalContextLimit'] = 1200
        group = {'hooks': [handler]}
        if event == 'PreToolUse':
            group['matcher'] = r'^(Bash|exec_command|apply_patch|Edit|Write|MultiEdit)$'
        result[event] = group
    return result


def install(root, mode):
    root = Path(os.path.abspath(root))
    if not root.is_dir() or root.is_symlink():
        raise ValueError('Target must be an existing workspace directory, not a symlink')
    if not (root / 'AGENTS.md').is_file() or not (root / 'CLAUDE.md').is_file():
        raise ValueError('Connect the existing AGENTS.md and CLAUDE.md before installing hooks')
    paths = {name: guarded_path(root, name) for name in [RUNTIME, MANIFEST, '.gitignore', *CONFIGS.values()]}
    original = {name: path.read_bytes() if path.exists() else None for name, path in paths.items()}
    old = json.loads(original[MANIFEST]) if original[MANIFEST] is not None else None
    if old is not None and (not isinstance(old, dict) or old.get('owner') != 'communication-pilot-v1'):
        raise ValueError('Unmanaged installation manifest preserved')
    # Local installation must not overwrite shared tracked configuration or runtime.
    for name in [RUNTIME, MANIFEST, *CONFIGS.values()]:
        check = subprocess.run(['git', '-C', str(root), 'ls-files', '--error-unmatch', '--', name],
                               capture_output=True)
        if check.returncode == 0:
            raise ValueError(f'Tracked local-installation file preserved: {name}')
    source = (ROOT / 'hooks/communication.py').read_bytes()
    revision = hashlib.sha256(source).hexdigest()
    if original[RUNTIME] is not None:
        current_hash = hashlib.sha256(original[RUNTIME]).hexdigest()
        if not old or current_hash not in {old['revision'], revision}:
            raise ValueError('Unmanaged or modified runtime preserved')
    if mode == 'remove' and old is None:
        return 0
    planned = dict(original)
    new = {'owner': 'communication-pilot-v1', 'revision': revision, 'groups': {}, 'created': {}}
    for engine, name in CONFIGS.items():
        config = json.loads(original[name]) if original[name] is not None else {}
        if not isinstance(config, dict) or not isinstance(config.get('hooks', {}), dict):
            raise ValueError(f'Invalid hooks configuration: {name}')
        config = copy.deepcopy(config)
        hooks = config.setdefault('hooks', {})
        previous = old['groups'].get(engine, {}) if old else {}
        for event, group in previous.items():
            if group not in hooks.get(event, []):
                raise ValueError(f'Modified managed hook preserved: {name}/{event}')
            hooks[event].remove(group)
            if not hooks[event]:
                del hooks[event]
        current = definitions(root, engine, revision)
        if mode != 'remove':
            for event, group in current.items():
                existing = hooks.setdefault(event, [])
                if not isinstance(existing, list):
                    raise ValueError(f'Invalid event groups: {name}/{event}')
                # Do not adopt a pre-existing handler with no ownership manifest.
                if any(str(root / RUNTIME) in str(g) for g in existing):
                    raise ValueError(f'Unmanaged communication hook preserved: {name}/{event}')
                existing.append(group)
        if not hooks:
            config.pop('hooks')
        created = old['created'][engine] if old else original[name] is None
        planned[name] = None if mode == 'remove' and created and not config else encoded(config)
        new['groups'][engine] = current
        new['created'][engine] = created
    planned[RUNTIME] = None if mode == 'remove' else source
    planned[MANIFEST] = None if mode == 'remove' else encoded(new)
    if mode != 'remove':
        ignore = (original['.gitignore'] or b'').decode()
        missing = [rule for rule in IGNORE if rule not in ignore.splitlines()]
        if missing:
            ignore += ('\n' if ignore and not ignore.endswith('\n') else '')
            ignore += '\n# Local communication hooks and private state\n' + '\n'.join(missing) + '\n'
        planned['.gitignore'] = ignore.encode()
    changes = [name for name in paths if planned[name] != original[name]]
    if mode == 'check':
        for name in changes:
            print(f'DRIFT {root.name}/{name}')
        if not changes:
            print(f'OK {root.name}: Codex + Claude configuration and runtime match')
        return int(bool(changes))
    written = []
    try:
        # Enable configuration only after runtime and manifest are ready.
        for name in changes:
            current = paths[name].read_bytes() if paths[name].exists() else None
            if current != original[name]:
                raise ValueError(f'Concurrent modification preserved: {name}')
            if planned[name] is None:
                paths[name].unlink(missing_ok=True)
            else:
                atomic_write(paths[name], planned[name])
            written.append(name)
    except (OSError, ValueError):
        for name in reversed(written):
            current = paths[name].read_bytes() if paths[name].exists() else None
            if current != planned[name]:
                continue  # A concurrent writer owns the new content; do not roll it back.
            if original[name] is None:
                paths[name].unlink(missing_ok=True)
            else:
                atomic_write(paths[name], original[name])
        raise
    print(f'{mode.upper()} {root.name}: {len(changes)} file(s); existing settings/hooks preserved')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, required=True)
    options = parser.add_mutually_exclusive_group(required=True)
    for name in ('check', 'write', 'remove'):
        options.add_argument('--' + name, action='store_true')
    args = parser.parse_args()
    try:
        return install(args.target, 'check' if args.check else 'remove' if args.remove else 'write')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())

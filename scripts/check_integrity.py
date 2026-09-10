#!/usr/bin/env python3
"""Read-only checks of tracked workflow documents, skills and archived sources."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def inspect_repository(root, tracked):
    errors = []
    tracked = set(tracked)
    for name in tracked:
        if 'ai-input' in Path(name).parts:
            errors.append(f'Private input tracked: {name}')
    for entry in sorted((root / 'skills').glob('*/SKILL.md')):
        source = entry.read_text()
        header = re.match(r'\A---\n(.*?)\n---(?:\n|$)', source, re.S)
        name = re.search(r'^name:\s*([a-z0-9-]+)\s*$', header[1], re.M) if header else None
        description = re.search(r'^description:\s*\S.+$', header[1], re.M) if header else None
        if not name or name[1] != entry.parent.name or not description:
            errors.append(f'Invalid skill name/description header: {entry.relative_to(root)}')
        if str(entry.relative_to(root)) not in tracked:
            errors.append(f'Canonical skill is not tracked: {entry.relative_to(root)}')
    # Local link targets only; remote URLs and heading-anchor semantics are not tested.
    for name in sorted(tracked):
        if not name.endswith(('.md', '.mdc')) or name.startswith('third-party/'):
            continue
        path = root / name
        if not path.is_file():
            errors.append(f'Tracked document missing: {name}')
            continue
        content = re.sub(r'(?ms)^```.*?^```[^\n]*', '', path.read_text())
        for raw in re.findall(r'\]\(([^)]+)\)', content):
            raw = raw.strip().strip('<>')
            url = urlsplit(raw)
            if url.scheme or url.netloc or not url.path:
                continue
            target = (path.parent / unquote(url.path)).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                errors.append(f'Broken/nonportable local link: {name} -> {raw}')
    manifest = root / 'third-party/sources.json'
    try:
        repos = json.loads(manifest.read_text())
        for repo in repos:
            license_path = repo['license_file']
            if license_path not in tracked or not (root / license_path).is_file():
                errors.append(f'License missing/untracked: {license_path}')
            for item in repo['matched_files']:
                path = item['archived_path']
                if path not in tracked or not (root / path).is_file():
                    errors.append(f'Archived source missing/untracked: {path}')
                elif hashlib.sha256((root / path).read_bytes()).hexdigest() != item['sha256']:
                    errors.append(f'Archived source changed: {path}')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(f'Invalid source manifest: {exc}')
    return errors


def main():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    errors = inspect_repository(ROOT, [p for p in tracked if p])
    probes = ['ai-input/probe.txt', 'ai-input/worklog/2099-01/probe.md']
    result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'],
                            cwd=ROOT, input='\n'.join(probes)+'\n', capture_output=True, text=True)
    if result.returncode != 0 or set(result.stdout.splitlines()) != set(probes):
        errors.append('ai-input is not fully ignored')
    for error in errors:
        print(f'ERROR: {error}')
    if errors:
        return 1
    print('OK: tracked privacy boundary, skill headers, local links, archive hashes and licenses')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)

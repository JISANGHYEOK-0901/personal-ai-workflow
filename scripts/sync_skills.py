#!/usr/bin/env python3
"""Sync this repository's canonical skills to its three tool directories."""
import argparse
import os
import stat
import tempfile
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ('.agents/skills', '.claude/skills', '.cursor/skills')


def atomic_write(dest, data):
    """Replace one file atomically; a failed write leaves its old bytes intact."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(dest.stat().st_mode) if dest.exists() else 0o644
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, prefix='.sync-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, dest)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Read-only drift check')
    mode.add_argument('--write', action='store_true', help='Update managed skill copies')
    args = parser.parse_args()
    source = ROOT / 'skills'
    if source.is_symlink():
        raise ValueError(f'Canonical directory symlink not supported: {source}')
    skills = sorted(p for p in source.iterdir() if p.is_dir())
    if not skills:
        raise ValueError('No canonical skills found')
    expected = {}
    for skill in skills:
        if skill.is_symlink() or not (skill / 'SKILL.md').is_file():
            raise ValueError(f'Invalid canonical skill: {skill.name}')
        for item in skill.rglob('*'):
            if item.is_symlink():
                raise ValueError(f'Symlink not supported: {item}')
            if item.is_file():
                expected[item.relative_to(source)] = item.read_bytes()
    changes = []
    # Preflight every target before changing any file. Unknown files are preserved.
    for target in TARGETS:
        folder = ROOT / target
        for parent in (folder, folder.parent):
            if parent.is_symlink():
                raise ValueError(f'Target symlink not supported: {parent}')
        if folder.exists():
            for item in folder.rglob('*'):
                if item.is_symlink():
                    raise ValueError(f'Target symlink not supported: {item}')
                if item.is_file() and item.relative_to(folder) not in expected:
                    raise ValueError(f'Unmanaged file preserved; relocate explicitly: {item}')
        for relative, data in expected.items():
            dest = folder / relative
            if dest.exists() and not dest.is_file():
                raise ValueError(f'Expected file: {dest}')
            for parent in dest.parents:
                if parent == ROOT:
                    break
                if parent.exists() and not parent.is_dir():
                    raise ValueError(f'Expected directory: {parent}')
            if not dest.exists() or dest.read_bytes() != data:
                changes.append((dest, data))
    if args.check:
        for dest, _ in changes:
            print(f'DRIFT {dest.relative_to(ROOT)}')
        if changes:
            return 1
        print(f'OK: {len(skills)} canonical skill(s), {len(TARGETS)} synchronized tool directories')
        return 0
    for dest, data in changes:
        atomic_write(dest, data)
    print(f'Updated {len(changes)} files; unchanged files preserved')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        sys.exit(2)

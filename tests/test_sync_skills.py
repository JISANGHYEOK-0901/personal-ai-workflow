import contextlib
import importlib.util
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('sync_skills', Path(__file__).resolve().parents[1] / 'scripts/sync_skills.py')
SYNC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SYNC)


class SyncSkillsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='sync-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'skills/example/SKILL.md'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('---\nname: example\ndescription: Example skill.\n---\nOld body\n')
        self.patch = patch.object(SYNC, 'ROOT', self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def run_sync(self, mode):
        with patch('sys.argv', ['sync_skills.py', mode]), contextlib.redirect_stdout(io.StringIO()):
            return SYNC.main()

    def destination(self, target='.agents/skills'):
        return self.root / target / 'example/SKILL.md'

    def test_check_does_not_create_missing_targets(self):
        self.assertEqual(self.run_sync('--check'), 1)
        self.assertFalse((self.root / '.agents').exists())

    def test_sync_resources_and_idempotent_reexecution(self):
        ref = self.source.parent / 'references/example.md'
        ref.parent.mkdir()
        ref.write_text('resource')
        self.assertEqual(self.run_sync('--write'), 0)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for t in SYNC.TARGETS
                  for p in (self.root / t).rglob('*') if p.is_file()}
        self.assertEqual(self.run_sync('--write'), 0)
        self.assertEqual(self.run_sync('--check'), 0)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})
        for t in SYNC.TARGETS:
            self.assertEqual((self.root / t / 'example/references/example.md').read_text(), 'resource')

    def test_drift_is_reported_without_write_then_repaired(self):
        self.run_sync('--write')
        self.destination().write_text('edited copy')
        self.assertEqual(self.run_sync('--check'), 1)
        self.assertEqual(self.destination().read_text(), 'edited copy')
        self.run_sync('--write')
        self.assertEqual(self.destination().read_bytes(), self.source.read_bytes())

    def test_unknown_file_prevents_writes_in_all_targets(self):
        self.run_sync('--write')
        unknown = self.root / '.cursor/skills/other/SKILL.md'
        unknown.parent.mkdir()
        unknown.write_text('user-owned')
        self.source.write_text('new canonical body')
        old = self.destination().read_bytes()
        with self.assertRaisesRegex(ValueError, 'Unmanaged file preserved'):
            self.run_sync('--write')
        self.assertEqual(self.destination().read_bytes(), old)
        self.assertEqual(unknown.read_text(), 'user-owned')

    def test_target_symlink_is_rejected(self):
        self.run_sync('--write')
        self.destination().unlink()
        self.destination().symlink_to(self.source)
        before = self.source.read_bytes()
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_sync('--write')
        self.assertEqual(self.source.read_bytes(), before)

    def test_source_root_symlink_is_rejected(self):
        (self.root / 'skills').rename(self.root / 'real-skills')
        (self.root / 'skills').symlink_to(self.root / 'real-skills', target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_sync('--write')

    def test_missing_entrypoint_is_rejected(self):
        self.source.unlink()
        with self.assertRaisesRegex(ValueError, 'Invalid canonical skill'):
            self.run_sync('--write')

    def test_replace_failure_preserves_old_file_and_removes_temporary(self):
        self.run_sync('--write')
        dest = self.destination()
        old = dest.read_bytes()
        with patch.object(SYNC.os, 'replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                SYNC.atomic_write(dest, b'new')
        self.assertEqual(dest.read_bytes(), old)
        self.assertEqual(list(dest.parent.glob('.sync-*')), [])

    def test_partial_sync_can_be_retried(self):
        self.run_sync('--write')
        old = self.destination('.cursor/skills').read_bytes()
        self.source.write_text('new version')
        original = SYNC.atomic_write
        count = 0
        def fail_second(dest, data):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError('injected second-file failure')
            return original(dest, data)
        with patch.object(SYNC, 'atomic_write', side_effect=fail_second):
            with self.assertRaises(OSError):
                self.run_sync('--write')
        self.assertEqual(self.destination('.cursor/skills').read_bytes(), old)
        self.assertEqual(self.run_sync('--check'), 1)
        self.run_sync('--write')
        self.assertEqual(self.run_sync('--check'), 0)


if __name__ == '__main__':
    unittest.main()

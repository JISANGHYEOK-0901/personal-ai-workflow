import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('integrity', Path(__file__).resolve().parents[1] / 'scripts/check_integrity.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='integrity-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        files = {
            'skills/example/SKILL.md': '---\nname: example\ndescription: Test skill.\n---\n',
            'README.md': '[Skill](skills/example/SKILL.md)\n',
            'third-party/source.md': 'original',
            'third-party/LICENSE': 'license fixture',
        }
        self.tracked = set(files)
        for name, body in files.items():
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
        data = [{'license_file': 'third-party/LICENSE', 'matched_files': [
            {'archived_path': 'third-party/source.md', 'sha256': hashlib.sha256(b'original').hexdigest()}]}]
        (self.root / 'third-party/sources.json').write_text(json.dumps(data))
        self.tracked.add('third-party/sources.json')

    def check(self):
        return CHECK.inspect_repository(self.root, self.tracked)

    def test_valid_fixture(self):
        self.assertEqual(self.check(), [])

    def test_private_file_is_rejected_even_if_ignored(self):
        self.tracked.add('ai-input/worklog/private.md')
        self.assertTrue(any('Private input tracked' in e for e in self.check()))

    def test_broken_link_is_rejected_but_code_example_is_not(self):
        (self.root / 'README.md').write_text('```md\n[Example](missing.md)\n```\n')
        self.assertEqual(self.check(), [])
        (self.root / 'README.md').write_text('[Broken](missing.md)\n')
        self.assertTrue(any('Broken/nonportable' in e for e in self.check()))

    def test_archive_tampering_is_rejected(self):
        (self.root / 'third-party/source.md').write_text('changed')
        self.assertTrue(any('Archived source changed' in e for e in self.check()))

    def test_invalid_skill_header_is_rejected(self):
        (self.root / 'skills/example/SKILL.md').write_text('---\nname: wrong\n---\n')
        self.assertTrue(any('Invalid skill' in e for e in self.check()))


if __name__ == '__main__':
    unittest.main()

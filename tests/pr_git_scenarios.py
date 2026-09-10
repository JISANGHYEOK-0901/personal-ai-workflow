"""Git boundary scenarios for the PR instructions, not an AI behavior test."""
import subprocess
import tempfile
import unittest
from pathlib import Path


class GitScenarios(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pr-git-scenarios-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / 'work'
        self.remote = self.root / 'remote.git'
        self.run_git('init', '--bare', '-q', str(self.remote), cwd=self.root)
        self.run_git('init', '-q', '-b', 'develop', str(self.repo), cwd=self.root)
        self.run_git('config', 'user.name', 'Fixture')
        self.run_git('config', 'user.email', 'fixture@example.invalid')
        self.run_git('remote', 'add', 'origin', str(self.remote))
        (self.repo / 'contract.txt').write_text('old_field')
        (self.repo / 'consumer.txt').write_text('old_field')
        self.commit('initial')
        self.run_git('push', '-q', 'origin', 'develop')

    def run_git(self, *args, cwd=None, success=True):
        result = subprocess.run(
            ['git', '-c', 'core.hooksPath=/dev/null', *args],
            cwd=cwd or self.repo, text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def sha(self, ref='HEAD'):
        return self.run_git('rev-parse', ref).stdout.strip()

    def commit(self, message):
        self.run_git('add', '.')
        self.run_git('commit', '-qm', message)

    def test_clean_merge_can_break_cross_file_contract(self):
        base0 = self.sha()
        self.run_git('switch', '-qc', 'feat/consumer')
        (self.repo / 'consumer.txt').write_text('old_field\nadditional_behavior')
        self.commit('consumer change')
        head0 = self.sha()
        self.run_git('switch', '-q', 'develop')
        (self.repo / 'contract.txt').write_text('new_field')
        self.commit('contract change')
        base1 = self.sha()
        self.assertNotEqual(base0, base1)
        self.run_git('merge-base', '--is-ancestor', base0, base1)
        self.assertEqual(self.sha('feat/consumer'), head0)
        self.run_git('merge', '--no-ff', '-m', 'clean git merge', 'feat/consumer')
        self.assertNotEqual((self.repo / 'contract.txt').read_text(),
                            (self.repo / 'consumer.txt').read_text().splitlines()[0])

    def test_explicit_lease_preserves_advanced_remote_head(self):
        self.run_git('switch', '-qc', 'feat/shared')
        old = self.sha()
        self.run_git('push', '-q', 'origin', 'feat/shared')
        (self.repo / 'later.txt').write_text('another task')
        self.commit('later work')
        new = self.sha()
        self.run_git('push', '-q', 'origin', 'feat/shared')
        result = self.run_git('push',
            f'--force-with-lease=refs/heads/feat/shared:{old}',
            'origin', ':refs/heads/feat/shared', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(new, self.run_git('ls-remote', '--heads',
                                      'origin', 'refs/heads/feat/shared').stdout)

    def test_other_worktree_branch_is_not_deleted(self):
        other = self.root / 'other'
        self.run_git('worktree', 'add', '-q', '-b', 'feat/in-use', str(other))
        (other / 'private.txt').write_text('uncommitted work')
        result = self.run_git('branch', '-d', 'feat/in-use', success=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((other / 'private.txt').read_text(), 'uncommitted work')
        self.assertIn('refs/heads/feat/in-use',
                      self.run_git('worktree', 'list', '--porcelain').stdout)

    def test_rewritten_base_is_not_fast_forward(self):
        (self.repo / 'first.txt').write_text('old baseline')
        self.commit('old baseline')
        base0 = self.sha()
        self.run_git('switch', '-qc', 'rewritten-base', 'HEAD~1')
        (self.repo / 'second.txt').write_text('rewritten history')
        self.commit('replacement baseline')
        result = self.run_git('merge-base', '--is-ancestor', base0, 'HEAD', success=False)
        self.assertEqual(result.returncode, 1)


if __name__ == '__main__':
    unittest.main()

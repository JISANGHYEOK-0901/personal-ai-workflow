"""PR lifecycle regressions using local Git and mocked GitHub reads only."""
import importlib.util
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('pr_gate_regressions', ROOT / 'hooks/communication.py')
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class PRGateRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pr-gate-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        identity = patch.object(HOOK, 'remote_repository_identity', return_value='github.com/audit/sample')
        identity.start()
        self.addCleanup(identity.stop)
        self.repo = self.root / 'app'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'develop')
        self.git('config', 'user.name', 'PR Gate Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('remote', 'add', 'origin', 'https://github.com/audit/sample.git')
        (self.repo / 'app.txt').write_text('base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        self.base = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/develop', self.base)
        self.git('switch', '-qc', 'feature')
        (self.repo / 'app.txt').write_text('feature\n')
        self.git('commit', '-qam', 'feature')
        self.head = self.git('rev-parse', 'HEAD')
        remote_head = patch.object(HOOK, 'remote_branch_sha', return_value=self.head)
        remote_head.start()
        self.addCleanup(remote_head.stop)
        self.review()
        self.event('UserPromptSubmit', prompt='PR해줘')

    def git(self, *args):
        return subprocess.run(
            ['git', '-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false',
             '-C', str(self.repo), *args],
            check=True, capture_output=True, text=True).stdout.strip()

    def review(self):
        return HOOK.record_review(self.root, self.repo, 'origin/develop', True, True, True)

    def event(self, name, **fields):
        return HOOK.handle({'hook_event_name': name, 'session_id': 'regression',
                            'turn_id': 'one', 'cwd': str(self.repo), **fields},
                           'codex', self.root)

    def command(self, command):
        return self.event('PreToolUse', tool_name='Bash', tool_input={'command': command})

    def assert_denied(self, command):
        result = self.command(command)
        self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'),
                         'deny', (command, result))

    def assert_allowed(self, command):
        result = self.command(command)
        self.assertNotEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'),
                            'deny', (command, result))

    def merged_state(self):
        self.git('switch', '-q', 'develop')
        self.git('merge', '--no-ff', '-qm', 'merge feature', 'feature')
        merged = self.git('rev-parse', 'HEAD')
        self.git('update-ref', 'refs/remotes/origin/develop', merged)
        return {'number': 17, 'state': 'MERGED', 'isDraft': False,
                'baseRefName': 'develop', 'baseRefOid': merged,
                'headRefName': 'feature', 'headRefOid': self.head,
                'mergeCommit': {'oid': merged}, 'isCrossRepository': False,
                'url': 'https://github.com/audit/sample/pull/17'}

    def deletion(self, head=None, branch='feature', remote='origin'):
        return (f'git push --force-with-lease=refs/heads/{branch}:{head or self.head} '
                f'{remote} :refs/heads/{branch}')

    def test_pr_commands_must_run_separately_from_other_commands(self):
        for command in (
            'gh pr create --base develop --head feature && gh pr merge 999 --merge',
            'git push origin feature && gh pr create --base develop --head feature',
            'git switch develop && gh pr create --base develop --head feature',
            'gh pr create --base develop --head feature; git push origin feature',
            'gh pr create --base develop --head feature | cat',
            "cat <<'EOF'\nPR body\nEOF\ngh pr merge 999 --merge",
        ):
            with self.subTest(command=command):
                self.assert_denied(command)
        self.assert_allowed('gh pr create --base develop --head feature --title "A && B" --body-file /tmp/body.md')
        self.assert_allowed("cat <<'EOF'\ngh pr merge 999 --merge\nEOF")

    def test_continued_direct_commands_require_the_same_review(self):
        continuation = '\\\n'
        commands = (
            'git push ' + continuation + ' origin HEAD:refs/heads/feature',
            'git ' + continuation + ' push origin feature',
            'gi' + continuation + 't push origin feature',
            'gh ' + continuation + ' pr create --base develop --head feature',
            'gh pr ' + continuation + ' create --base develop --head feature',
            'gh pr create --base ' + continuation + 'develop --head feature',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_allowed(command)
        (self.repo / 'app.txt').write_text('unreviewed change\n')
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_continuation_tokens_match_actual_shell_arguments(self):
        # These executables only print argv; no GitHub or Git writes can run.
        executable_dir = self.root / 'bin'
        executable_dir.mkdir()
        for name in ('git', 'gh'):
            executable = executable_dir / name
            executable.write_text('#!/bin/sh\nprintf \'%s\\000\' "${0##*/}" "$@"\n')
            executable.chmod(0o700)
        continuation = '\\\n'
        commands = (
            'git ' + continuation + 'push origin feature',
            'g' + continuation + 'h pr create --base develop --head feature',
            'gh pr create --title "two' + continuation + ' words"',
            "gh pr create --title 'literal " + continuation + "text'",
            'gh pr create --title "# quoted" --body word#part',
            '# comment ' + continuation + 'gh pr create --base develop --head feature',
        )
        for command in commands:
            with self.subTest(command=command):
                result = subprocess.run(
                    ['/bin/sh', '-c', command], check=True, capture_output=True,
                    env={**os.environ, 'PATH': str(executable_dir) + os.pathsep + os.environ['PATH']})
                actual = result.stdout.decode().split('\0')[:-1]
                self.assertEqual(HOOK.shell_segments(command), [actual])

    def test_heredoc_and_comment_continuations_do_not_hide_commands(self):
        continuation = '\\\n'
        literal = "cat <<'EOF'\ngh " + continuation + 'pr merge 999 --merge\nEOF'
        self.assert_allowed(literal)
        _, boundary = HOOK.shell_events(literal)
        self.assertIsNone(boundary)
        self.assert_denied(literal + '\ngh pr create --base develop --head feature')
        self.assert_denied('echo before # comment ' + continuation
                           + 'gh pr create --base develop --head feature')

    def test_continued_heredoc_delimiters_preserve_following_boundary(self):
        executable_dir = self.root / 'bin'
        executable_dir.mkdir()
        for name, body in (('cat', 'exit 0'), ('gh', "printf 'direct-gh-command\\n'")):
            executable = executable_dir / name
            executable.write_text('#!/bin/sh\n' + body + '\n')
            executable.chmod(0o700)
        continuation = '\\\n'
        headers = (
            'cat <<' + continuation + "'EOF'\n",
            'cat <<EO' + continuation + 'F\n',
            'cat ' + continuation + "<<'EOF'\n",
            "cat <<'EOF' " + continuation + '# comment\n',
            'cat word\\ #part ' + continuation + "<<'EOF'\n",
        )
        for header in headers:
            with self.subTest(header=header):
                literal = header + 'gh ' + continuation + 'pr merge 999 --merge\nEOF\n'
                self.assertIsNone(HOOK.shell_events(literal)[1])
                command = literal + 'gh pr create --base develop --head feature'
                result = subprocess.run(
                    ['/bin/sh', '-c', command], check=True, capture_output=True, text=True,
                    env={**os.environ, 'PATH': str(executable_dir) + os.pathsep + os.environ['PATH']})
                self.assertEqual(result.stdout, 'direct-gh-command\n')
                self.assert_denied(command)

    def test_heredoc_end_continuations_follow_delimiter_quoting(self):
        executable_dir = self.root / 'bin'
        executable_dir.mkdir()
        for name, body in (('cat', 'exit 0'), ('gh', "printf 'direct-gh-command\\n'")):
            executable = executable_dir / name
            executable.write_text('#!/bin/sh\n' + body + '\n')
            executable.chmod(0o700)
        continuation = '\\\n'
        cases = (
            ('EOF', 'EO' + continuation + 'F\n', True),
            ('EOF', 'E' + continuation + 'O' + continuation + 'F\n', True),
            ("'EOF'", 'EO' + continuation + 'F\n', False),
            ('"EOF"', 'EO' + continuation + 'F\n', False),
            ('EO\\F', 'EO' + continuation + 'F\n', False),
            ("EO''F", 'EO' + continuation + 'F\n', False),
            ('EOF', 'EO\\' + continuation + 'F\n', False),
            ('-EOF', '\tEO' + continuation + 'F\n', True),
            ('-EOF', 'EO' + continuation + '\tF\n', False),
        )
        for delimiter, ending, executes in cases:
            with self.subTest(delimiter=delimiter, ending=ending):
                command = ('cat <<' + delimiter + '\nbody\n' + ending
                           + 'gh pr create --base develop --head feature\n')
                if not executes:
                    command += 'EOF\n'
                result = subprocess.run(
                    ['/bin/sh', '-c', command], check=True, capture_output=True, text=True,
                    env={**os.environ, 'PATH': str(executable_dir) + os.pathsep + os.environ['PATH']})
                self.assertEqual(result.stdout, 'direct-gh-command\n' if executes else '')
                if executes:
                    self.assert_denied(command)
                else:
                    self.assertIsNone(HOOK.shell_events(command)[1])
                    self.assert_allowed(command)

    def test_help_flags_do_not_require_review_or_remote_reads(self):
        (self.repo / 'app.txt').write_text('unreviewed change\n')
        commands = (
            'gh pr create --help', 'gh pr merge -h',
            'gh pr merge 17 --help', 'gh pr create --help=true',
            'gh --help=1 pr create', 'gh pr --help=T merge',
            'gh pr create --help=false --help',
            'git push -h', 'git push --help', 'git push origin feature -h',
        )
        with patch.object(HOOK, 'remote_pr_state', side_effect=AssertionError('Help queried GitHub')):
            for command in commands:
                with self.subTest(command=command):
                    self.assertEqual(HOOK.shell_events(command), ('', None))
                    self.assert_allowed(command)

    def test_help_option_values_and_false_flags_keep_review_gate(self):
        (self.repo / 'app.txt').write_text('unreviewed change\n')
        create = 'gh pr create --base develop --head feature '
        commands = (
            create + '--title --help', create + '--body "--help"',
            create + '--title=--help', create + '-t--help',
            create + '--body-file --help', create + '--help=false',
            create + '--help=0', create + '--help=true --help=False',
            'gh --help=false pr create --base develop --head feature',
            'gh pr --help=f create --base develop --head feature',
            create + '-- --help',
            'gh pr merge 17 --body --help --match-head-commit ' + self.head,
            'git push --push-option --help origin feature',
            'git push --repo --help origin feature',
            'git push -- origin --help',
        )
        for command in commands:
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_help_does_not_exempt_other_commands_in_the_same_shell(self):
        for command in (
            'gh pr create --help && gh pr create --base develop --head feature',
            'gh pr create --base develop --head feature && gh pr create --help',
            'git push -h; git push origin feature',
            'git push origin feature; gh pr merge --help',
        ):
            with self.subTest(command=command):
                self.assert_denied(command)

    def test_create_requires_explicit_head_even_with_different_tracking_branch(self):
        self.git('update-ref', 'refs/remotes/origin/other', self.head)
        self.git('config', 'branch.feature.remote', 'origin')
        self.git('config', 'branch.feature.merge', 'refs/heads/other')
        result = self.command('gh pr create --base develop')
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('explicit --head', result['hookSpecificOutput']['permissionDecisionReason'])
        self.assert_allowed('gh pr create --base develop --head feature')
        self.assert_allowed('gh pr create -Bdevelop -Hfeature')

    def test_explicit_head_and_push_source_must_be_reviewed(self):
        self.git('branch', 'other', self.base)
        for command in ('gh pr create --base develop --head other',
                        'gh pr create -B develop -Hother',
                        'git push origin other:other',
                        'git push origin HEAD:refs/heads/develop',
                        'git push origin HEAD:refs/tags/release',
                        'git push --push-option --dry-run origin feature',
                        'git push origin feature other',
                        'git push --all origin', 'git push origin'):
            with self.subTest(command=command):
                self.assert_denied(command)
        self.assert_allowed('gh pr create --base develop --head feature')
        self.assert_allowed('git push origin feature')
        self.assert_allowed('git push -u origin HEAD:refs/heads/feature')
        self.assert_allowed('git push --dry-run origin feature')

    def test_repository_overrides_cannot_change_the_checked_target(self):
        suffix = 'pr merge 17 --merge --match-head-commit ' + self.head
        for command in (
            'GH_REPO=other/target gh ' + suffix,
            'env GH_REPO=other/target gh ' + suffix,
            'gh -Rother/target ' + suffix,
            'gh ' + suffix + ' -Rother/target',
            'gh ' + suffix + ' --repo=other/target',
            'git -c remote.origin.url=https://github.com/other/target.git push origin feature',
        ):
            with self.subTest(command=command):
                self.assert_denied(command)
        with patch.dict(HOOK.os.environ, {'GH_REPO': 'other/target'}):
            self.assert_denied('gh pr create --base develop --head feature')

    def test_push_remote_must_match_reviewed_remote(self):
        self.git('remote', 'add', 'other', 'https://github.com/other/target.git')
        self.assert_denied('git push other feature')
        self.git('remote', 'set-url', '--push', 'origin', 'https://github.com/other/target.git')
        self.assert_denied('git push origin feature')

    def test_exec_workdir_selects_the_reviewed_nested_repository(self):
        result = HOOK.handle({'hook_event_name': 'PreToolUse', 'session_id': 'nested',
                              'turn_id': 'one', 'cwd': str(self.root),
                              'tool_name': 'exec_command', 'tool_input': {
                                  'cmd': 'gh pr create --base develop --head feature',
                                  'workdir': str(self.repo)}}, 'codex', self.root)
        self.assertNotEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'),
                            'deny', result)

    def test_remote_changes_after_review_invalidate_receipt(self):
        self.git('remote', 'set-url', 'origin', 'https://github.com/other/target.git')
        self.assert_denied('git push origin feature')
        self.assert_denied('gh pr create --base develop --head feature')

    def test_gh_selected_repository_must_match_the_receipt(self):
        with patch.object(HOOK, 'remote_repository_identity', return_value='github.com/other/target'):
            self.assert_denied('gh pr create --base develop --head feature')
        with patch.object(HOOK, 'remote_repository_identity', side_effect=ValueError('GitHub unavailable')):
            self.assert_denied('gh pr create --base develop --head feature')

    def test_create_requires_actual_remote_head_equal_to_reviewed_head(self):
        with patch.object(HOOK, 'remote_branch_sha', return_value=self.base):
            self.assert_denied('gh pr create --base develop --head feature')
            self.assert_denied('gh pr create -Bdevelop -Hfeature')
        with patch.object(HOOK, 'remote_branch_sha', side_effect=ValueError('Remote branch not found')):
            self.assert_denied('gh pr create --base develop --head feature')

    def test_legacy_receipt_requires_fresh_review_after_schema_upgrade(self):
        with closing(sqlite3.connect(self.root / 'ai-input/hook-state/communication.sqlite3')) as db, db:
            row = db.execute('SELECT repo, base_ref, base_sha, head_sha, merge_base, untracked, minor, updated '
                             'FROM reviews').fetchone()
            db.execute('DROP TABLE reviews')
            db.execute('CREATE TABLE reviews (repo TEXT PRIMARY KEY, base_ref TEXT, base_sha TEXT, '
                       'head_sha TEXT, merge_base TEXT, untracked TEXT, minor INTEGER, updated REAL)')
            db.execute('INSERT INTO reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?)', row)
        self.assert_denied('gh pr create --base develop --head feature')
        self.review()
        self.assert_allowed('gh pr create --base develop --head feature')

    def test_changing_branch_with_same_sha_invalidates_review(self):
        self.git('switch', '-qc', 'another-feature')
        self.assert_denied('gh pr create --base develop --head another-feature')

    def test_remote_base_review_does_not_require_updating_local_branch(self):
        self.git('switch', '-qc', 'new-base', 'develop')
        (self.repo / 'base.txt').write_text('advanced base\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'advance remote base')
        self.git('update-ref', 'refs/remotes/origin/develop', self.git('rev-parse', 'HEAD'))
        self.git('switch', '-q', 'feature')
        self.review()
        self.assert_allowed('gh pr create --base develop --head feature')
        self.git('branch', 'release', 'origin/develop')
        self.assert_denied('gh pr create --base release --head feature')

    def test_cleanup_after_merge_uses_merged_evidence_not_nonempty_diff(self):
        state = self.merged_state()
        with patch.object(HOOK, 'remote_pr_state', return_value=state):
            HOOK.record_cleanup(self.root, self.repo, '17', 'origin')
            self.assert_allowed(self.deletion())
            self.event('UserPromptSubmit', turn_id='two', prompt='정리해줘')
            # A new turn without PR wording still checks cleanup evidence.
            result = self.event('PreToolUse', turn_id='two', tool_name='Bash',
                                tool_input={'command': self.deletion()})
            self.assertNotEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_cleanup_requires_exact_branch_sha_remote_and_lease(self):
        state = self.merged_state()
        with patch.object(HOOK, 'remote_pr_state', return_value=state):
            self.assert_denied(self.deletion())
            HOOK.record_cleanup(self.root, self.repo, '17', 'origin')
            for command in (self.deletion(head='0' * 40), self.deletion(branch='develop'),
                            self.deletion(remote='other'), 'git push origin :refs/heads/feature',
                            'git push --force-with-lease origin :refs/heads/feature'):
                with self.subTest(command=command):
                    self.assert_denied(command)

    def test_cleanup_rejects_unmerged_fork_wrong_repo_and_unfetched_merge(self):
        state = self.merged_state()
        for invalid in ({**state, 'state': 'OPEN'}, {**state, 'isCrossRepository': True},
                        {**state, 'url': 'https://github.com/other/target/pull/17'},
                        {**state, 'headRefName': 'develop'}):
            with self.subTest(state=invalid), patch.object(HOOK, 'remote_pr_state', return_value=invalid):
                with self.assertRaises(ValueError):
                    HOOK.record_cleanup(self.root, self.repo, '17', 'origin')
        self.git('update-ref', 'refs/remotes/origin/develop', self.base)
        with patch.object(HOOK, 'remote_pr_state', return_value=state), self.assertRaises(ValueError):
            HOOK.record_cleanup(self.root, self.repo, '17', 'origin')

    def test_cleanup_rechecks_remote_pr_before_deletion(self):
        state = self.merged_state()
        with patch.object(HOOK, 'remote_pr_state', return_value=state):
            HOOK.record_cleanup(self.root, self.repo, '17', 'origin')
        for changed in ({**state, 'state': 'OPEN'}, {**state, 'headRefOid': '0' * 40}):
            with self.subTest(state=changed), patch.object(HOOK, 'remote_pr_state', return_value=changed):
                self.assert_denied(self.deletion())
        with patch.object(HOOK, 'remote_pr_state', side_effect=ValueError('GitHub unavailable')):
            self.assert_denied(self.deletion())

    def test_cleanup_receipt_expires(self):
        state = self.merged_state()
        with patch.object(HOOK, 'remote_pr_state', return_value=state):
            HOOK.record_cleanup(self.root, self.repo, '17', 'origin')
        with patch.object(HOOK.time, 'time', return_value=HOOK.time.time() + 25 * 3600):
            self.assert_denied(self.deletion())

    def test_combined_delete_flags_are_gated_without_pr_prompt(self):
        self.event('UserPromptSubmit', turn_id='cleanup-only', prompt='정리해줘')
        for command in ('git push -vd origin feature', 'git push -df origin feature',
                        'git push --delete origin feature', 'git push --del origin feature',
                        'git push --delet origin feature', 'git push origin +:refs/heads/feature'):
            with self.subTest(command=command):
                result = self.event('PreToolUse', turn_id='cleanup-only', tool_name='Bash',
                                    tool_input={'command': command})
                self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')


if __name__ == '__main__':
    unittest.main()

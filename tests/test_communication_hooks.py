import importlib.util
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOOK = load('communication', 'hooks/communication.py')
INSTALL = load('install_communication_hooks', 'scripts/install_communication_hooks.py')


class CommunicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='communication-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def event(self, event, engine='codex', **fields):
        payload = {'hook_event_name': event, 'session_id': 'session', 'turn_id': 'turn',
                   'cwd': str(self.root), **fields}
        return HOOK.handle(payload, engine, self.root)

    def edit(self, name, engine='codex'):
        return self.event('PreToolUse', engine, tool_name='Write', tool_input={'file_path': name})

    def stop(self, engine='codex', **fields):
        return self.event('Stop', engine, last_assistant_message='작업 기록에 남겼습니다.', **fields)

    def git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def feature_repo(self):
        repo = self.root / 'app'
        repo.mkdir()
        self.git(repo, 'init', '-q', '-b', 'main')
        self.git(repo, 'config', 'user.name', 'Hook Test')
        self.git(repo, 'config', 'user.email', 'hook@example.invalid')
        (repo / 'app.txt').write_text('base\n')
        self.git(repo, 'add', 'app.txt')
        self.git(repo, 'commit', '-q', '-m', 'base')
        self.git(repo, 'checkout', '-q', '-b', 'feature')
        (repo / 'app.txt').write_text('feature\n')
        self.git(repo, 'commit', '-qam', 'feature')
        return repo

    def test_read_only_and_single_local_edit_do_not_continue(self):
        for engine in ('codex', 'claude'):
            with self.subTest(engine=engine):
                self.assertIn('additionalContext', self.event('UserPromptSubmit', engine)['hookSpecificOutput'])
                self.assertEqual(self.event('PreToolUse', engine, tool_name='Bash',
                                           tool_input={'command': 'git diff --check && rg TODO src'}), {})
                self.assertEqual(self.stop(engine), {})
                self.assertTrue(self.edit('src/title.js', engine))
                self.assertEqual(self.stop(engine), {})

    def test_minjisuper_two_components_prompt_one_handoff_review(self):
        for engine in ('codex', 'claude'):
            self.event('UserPromptSubmit', engine)
            self.assertTrue(self.edit('FE/src/PopupModal.jsx', engine))
            self.assertEqual(self.edit('BE/src/PopupController.java', engine), {})
            first = self.stop(engine)
            self.assertTrue(first)
            if engine == 'codex':
                self.assertEqual(first['decision'], 'block')
            else:
                self.assertEqual(first['hookSpecificOutput']['hookEventName'], 'Stop')
            self.assertEqual(self.stop(engine), {})

    def test_review_is_not_satisfied_by_magic_words_or_worklog(self):
        for answer in ('미결사항 없음 권장안 완료', '작업 기록을 작성했습니다.', '실제 영향을 설명했습니다.'):
            self.event('UserPromptSubmit', 'claude')
            self.edit('db/migrations/001.sql', 'claude')
            result = self.event('Stop', 'claude', last_assistant_message=answer)
            self.assertTrue(result)  # A reminder, not a semantic pass/fail assertion.

    def test_stop_active_background_and_new_turn_do_not_loop(self):
        self.edit('db/migrations/001.sql')
        self.assertEqual(self.stop(stop_hook_active=True), {})
        self.assertEqual(self.stop(background_tasks=[{'id': 'a'}]), {})
        self.assertEqual(self.stop(session_crons=[{'id': 'a'}]), {})
        self.assertTrue(self.stop())
        self.assertEqual(self.stop(turn_id='different'), {})

    def test_claude_new_prompt_resets_previous_work(self):
        self.event('UserPromptSubmit', 'claude')
        self.edit('db/migrations/001.sql', 'claude')
        self.assertTrue(self.stop('claude'))
        self.event('UserPromptSubmit', 'claude')
        self.assertEqual(self.stop('claude'), {})

    def test_session_engine_and_missing_boundary_are_isolated(self):
        self.edit('db/migrations/001.sql')
        self.assertEqual(self.stop('claude'), {})
        self.assertEqual(self.stop(session_id='other'), {})
        self.assertEqual(self.stop(turn_id=None), {})
        self.assertTrue(self.stop())

    def test_patch_paths_and_docs_exclusions(self):
        result = self.event('PreToolUse', tool_name='apply_patch', tool_input={'command':
            '*** Begin Patch\n*** Update File: FE/src/a.js\n@@\n-a\n+b\n'
            '*** Add File: BE/src/b.py\n+x\n*** End Patch'})
        self.assertTrue(result)
        self.assertTrue(self.stop())
        self.event('UserPromptSubmit', 'claude')
        for name in ('docs/a.md', 'ai-input/worklog/a.md', 'tests/test_api.py', '.codex/hooks.json'):
            self.assertEqual(self.edit(name, 'claude'), {})
        self.assertEqual(self.stop('claude'), {})

    def test_release_detected_but_examples_and_dry_runs_are_not(self):
        for cmd in ('git -C FE push origin feature', 'npm test && gh pr merge 1 --merge',
                    'gh pr create --base develop', 'cd FE && gh pr create --base develop',
                    'gh --repo owner/repo pr create --base develop',
                    'env FOO=bar railway up', 'vercel --prod'):
            self.assertEqual(HOOK.shell_kind(cmd), 'release', cmd)
        self.assertEqual(HOOK.shell_events('git push && gh pr create --base develop')[1]['action'],
                         'create')
        for cmd in ('echo "git push origin main"', 'rg "gh pr merge" docs',
                    'git push --dry-run', 'git -C FE status',
                    'python3 -c "print(\'railway up\')"',
                    "python3 - <<'PY'\nprint('example')\nrailway up\nPY"):
            self.assertNotEqual(HOOK.shell_kind(cmd), 'release', cmd)

    def test_release_reminder_is_separate_and_never_denies_tool(self):
        self.edit('src/a.py')
        args = {'tool_name': 'Bash', 'tool_input': {'command': 'git push origin feature'}}
        result = self.event('PreToolUse', **args)
        self.assertNotIn('permissionDecision', result['hookSpecificOutput'])
        self.assertEqual(self.event('PreToolUse', **args), {})
        self.assertTrue(self.stop())

    def test_pr_prompt_triggers_fresh_review_gate(self):
        repo = self.feature_repo()
        self.assertTrue(HOOK.pr_prompt('피알 만들어줘'))
        start = self.event('UserPromptSubmit', prompt='이 변경 PR해줘')
        self.assertIn('검토 증표', start['hookSpecificOutput']['additionalContext'])
        push = {'tool_name': 'Bash', 'tool_input': {'command': 'git push origin feature'},
                'cwd': str(repo)}
        blocked = self.event('PreToolUse', **push)
        self.assertEqual(blocked['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('--record-pr-review', blocked['hookSpecificOutput']['permissionDecisionReason'])

        (repo / 'local-note.txt').write_text('preserved untracked file\n')
        receipt = HOOK.record_review(self.root, repo, 'main', True, True, True)
        self.assertEqual(receipt['minor'], 0)
        state_bytes = (self.root / 'ai-input/hook-state/communication.sqlite3').read_bytes()
        self.assertNotIn(b'preserved untracked file', state_bytes)
        allowed = self.event('PreToolUse', **push)
        self.assertNotEqual(allowed.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')
        create = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                            tool_input={'command': 'gh pr create --base main --title test'})
        self.assertNotEqual(create.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

        (repo / 'local-note.txt').write_text('changed untracked file\n')
        stale_untracked = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                                     tool_input={'command': 'gh pr create --base main --title test'})
        self.assertEqual(stale_untracked['hookSpecificOutput']['permissionDecision'], 'deny')
        (repo / 'local-note.txt').write_text('preserved untracked file\n')
        (repo / 'app.txt').write_text('changed after review\n')
        stale = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                           tool_input={'command': 'gh pr create --base main --title test'})
        self.assertEqual(stale['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('Tracked files or index are not clean',
                      stale['hookSpecificOutput']['permissionDecisionReason'])

    def test_pr_create_always_requires_matching_explicit_base_and_clean_pass(self):
        repo = self.feature_repo()
        no_receipt = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                                tool_input={'command': 'gh pr create --base main'})
        self.assertEqual(no_receipt['hookSpecificOutput']['permissionDecision'], 'deny')
        with self.assertRaisesRegex(ValueError, 'MAJOR'):
            HOOK.record_review(self.root, repo, 'main', True, True, True, major=1)
        HOOK.record_review(self.root, repo, 'main', True, True, True, minor=2)
        missing_base = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                                  tool_input={'command': 'gh pr create --title test'})
        self.assertEqual(missing_base['hookSpecificOutput']['permissionDecision'], 'deny')
        wrong_base = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                                tool_input={'command': 'gh pr create --base HEAD'})
        self.assertEqual(wrong_base['hookSpecificOutput']['permissionDecision'], 'deny')
        remote_repo = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                                 tool_input={'command':
                                             'gh pr create --base main --repo owner/repository'})
        self.assertEqual(remote_repo['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('without --repo/-R',
                      remote_repo['hookSpecificOutput']['permissionDecisionReason'])

        state = (self.root / 'ai-input/hook-state/communication.sqlite3').read_bytes()
        self.assertNotIn(str(repo).encode(), state)

    def test_base_advance_invalidates_receipt(self):
        repo = self.feature_repo()
        self.event('UserPromptSubmit', prompt='PR 만들어줘')
        HOOK.record_review(self.root, repo, 'main', True, True, True)
        self.git(repo, 'checkout', '-q', 'main')
        (repo / 'base.txt').write_text('advanced\n')
        self.git(repo, 'add', 'base.txt')
        self.git(repo, 'commit', '-q', '-m', 'advance base')
        self.git(repo, 'checkout', '-q', 'feature')
        result = self.event('PreToolUse', tool_name='Bash', cwd=str(repo),
                            tool_input={'command': 'git push origin feature'})
        self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('Base, HEAD', result['hookSpecificOutput']['permissionDecisionReason'])

    def test_parallel_events_only_emit_one_reminder_and_one_review(self):
        def call(_):
            return self.edit('db/migrations/001.sql')
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(8)))
        self.assertEqual(sum(bool(r) for r in results), 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.stop(), range(8)))
        self.assertEqual(sum(bool(r) for r in results), 1)

    def test_state_has_no_raw_input_and_old_sessions_expire(self):
        self.event('UserPromptSubmit', prompt='secret-user-value')
        self.event('PreToolUse', tool_name='Bash', tool_input={'command': 'env SECRET=token-value railway up'})
        self.stop()
        path = self.root / 'ai-input/hook-state/communication.sqlite3'
        data = path.read_bytes()
        for private in (b'secret-user-value', b'token-value', b'railway', str(self.root).encode()):
            self.assertNotIn(private, data)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('UPDATE sessions SET updated=0')
        self.event('UserPromptSubmit', session_id='new')
        with closing(sqlite3.connect(path)) as db, db:
            self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0], 1)


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="hooks space '$-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        quiet = redirect_stdout(io.StringIO())
        quiet.__enter__()
        self.addCleanup(quiet.__exit__, None, None, None)
        (self.root / 'AGENTS.md').write_text('existing codex instructions')
        (self.root / 'CLAUDE.md').write_text('existing claude instructions')

    def test_check_is_read_only_and_write_is_idempotent(self):
        self.assertEqual(INSTALL.install(self.root, 'check'), 1)
        self.assertFalse((self.root / '.workflow-hooks').exists())
        INSTALL.install(self.root, 'write')
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob('*') if p.is_file()}
        INSTALL.install(self.root, 'write')
        self.assertEqual(INSTALL.install(self.root, 'check'), 0)
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in before})

    def test_preserve_existing_settings_hooks_and_remove_only_ours(self):
        user = {'permissions': {'deny': ['Bash(rm *)']}, 'hooks': {'Stop': [
            {'hooks': [{'type': 'command', 'command': 'echo existing'}]}]}}
        path = self.root / '.claude/settings.local.json'
        path.parent.mkdir()
        path.write_text(json.dumps(user))
        INSTALL.install(self.root, 'write')
        self.assertEqual(json.loads(path.read_text())['permissions'], user['permissions'])
        INSTALL.install(self.root, 'remove')
        self.assertEqual(json.loads(path.read_text()), user)
        self.assertFalse((self.root / INSTALL.RUNTIME).exists())
        self.assertFalse((self.root / '.codex/hooks.json').exists())
        self.assertEqual((self.root / 'AGENTS.md').read_text(), 'existing codex instructions')

    def test_modified_managed_hook_blocks_all_writes(self):
        INSTALL.install(self.root, 'write')
        path = self.root / '.claude/settings.local.json'
        path.write_text(path.read_text().replace('"timeout": 3', '"timeout": 5'))
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'Modified managed hook'):
            INSTALL.install(self.root, 'write')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_symlink_and_unmanaged_runtime_are_preserved(self):
        folder = self.root / '.workflow-hooks'
        folder.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            INSTALL.install(self.root, 'write')
        folder.unlink()
        folder.mkdir()
        (folder / 'communication.py').write_text('user file')
        with self.assertRaisesRegex(ValueError, 'Unmanaged'):
            INSTALL.install(self.root, 'write')

    def test_failure_rolls_back_and_retry_succeeds(self):
        original = INSTALL.atomic_write
        count = 0
        def fail_third(path, data):
            nonlocal count
            count += 1
            if count == 3:
                raise OSError('injected failure')
            original(path, data)
        with patch.object(INSTALL, 'atomic_write', side_effect=fail_third):
            with self.assertRaises(OSError):
                INSTALL.install(self.root, 'write')
        self.assertFalse((self.root / INSTALL.MANIFEST).exists())
        self.assertFalse((self.root / INSTALL.RUNTIME).exists())
        self.assertFalse((self.root / '.codex/hooks.json').exists())
        self.assertEqual(INSTALL.install(self.root, 'write'), 0)

    def test_runtime_upgrade_changes_hook_definition_and_relative_target_is_stable(self):
        INSTALL.install(self.root, 'write')
        first = json.loads((self.root / '.codex/hooks.json').read_text())
        (self.root / 'child').mkdir()
        self.assertEqual(INSTALL.install(self.root / 'child/..', 'check'), 0)
        source = self.root / 'source/hooks/communication.py'
        source.parent.mkdir(parents=True)
        source.write_bytes((ROOT / 'hooks/communication.py').read_bytes() + b'\n# next revision\n')
        with patch.object(INSTALL, 'ROOT', source.parents[1]):
            INSTALL.install(self.root, 'write')
            self.assertEqual(INSTALL.install(self.root, 'check'), 0)
        second = json.loads((self.root / '.codex/hooks.json').read_text())
        self.assertNotEqual(first, second)

    def test_rollback_preserves_a_concurrent_edit(self):
        original = INSTALL.atomic_write
        count = 0
        def intervene(path, data):
            nonlocal count
            count += 1
            if count == 3:
                (self.root / INSTALL.RUNTIME).write_text('concurrent user change')
                raise OSError('injected failure after concurrent edit')
            original(path, data)
        with patch.object(INSTALL, 'atomic_write', side_effect=intervene):
            with self.assertRaises(OSError):
                INSTALL.install(self.root, 'write')
        self.assertEqual((self.root / INSTALL.RUNTIME).read_text(), 'concurrent user change')

    def test_shared_tracked_configuration_is_not_overwritten(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        path = self.root / '.claude/settings.local.json'
        path.parent.mkdir()
        path.write_text('{"existing": true}\n')
        subprocess.run(['git', '-C', str(self.root), 'add', '.claude/settings.local.json'], check=True)
        with self.assertRaisesRegex(ValueError, 'Tracked'):
            INSTALL.install(self.root, 'write')
        self.assertEqual(path.read_text(), '{"existing": true}\n')
        self.assertFalse((self.root / INSTALL.RUNTIME).exists())

    def test_installed_commands_work_from_child_directory_and_fail_open(self):
        INSTALL.install(self.root, 'write')
        child = self.root / 'nested/app'
        child.mkdir(parents=True)
        for engine, name in INSTALL.CONFIGS.items():
            config = json.loads((self.root / name).read_text())
            command = config['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
            payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'test',
                       'turn_id': 'turn', 'cwd': str(child)}
            run = subprocess.run(command, shell=True, cwd=child, input=json.dumps(payload),
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn('additionalContext', json.loads(run.stdout)['hookSpecificOutput'])
            run = subprocess.run(command, shell=True, cwd=child, input='{invalid',
                                 capture_output=True, text=True)
            self.assertEqual(run.returncode, 0)
            self.assertEqual(json.loads(run.stdout), {})
            self.assertNotIn('{invalid', run.stderr)

    def test_installed_runtime_records_and_enforces_pr_review(self):
        INSTALL.install(self.root, 'write')
        repo = self.root / 'app'
        repo.mkdir()
        subprocess.run(['git', '-C', str(repo), 'init', '-q', '-b', 'main'], check=True)
        subprocess.run(['git', '-C', str(repo), 'config', 'user.name', 'Hook Test'], check=True)
        subprocess.run(['git', '-C', str(repo), 'config', 'user.email', 'hook@example.invalid'], check=True)
        (repo / 'app.txt').write_text('base\n')
        subprocess.run(['git', '-C', str(repo), 'add', 'app.txt'], check=True)
        subprocess.run(['git', '-C', str(repo), 'commit', '-q', '-m', 'base'], check=True)
        subprocess.run(['git', '-C', str(repo), 'checkout', '-q', '-b', 'feature'], check=True)
        (repo / 'app.txt').write_text('feature\n')
        subprocess.run(['git', '-C', str(repo), 'commit', '-qam', 'feature'], check=True)

        runtime = self.root / INSTALL.RUNTIME
        record = subprocess.run([
            sys.executable, str(runtime), '--root', str(self.root), '--record-pr-review',
            '--repo', str(repo), '--base', 'main', '--requirements-reviewed',
            '--contracts-reviewed', '--validation-reviewed', '--major', '0', '--minor', '0',
            '--blocker', '0'], capture_output=True, text=True)
        self.assertEqual(record.returncode, 0, record.stderr)
        self.assertTrue(json.loads(record.stdout)['recorded'])

        (repo / 'app.txt').write_text('dirty after receipt\n')
        rejected = subprocess.run([
            sys.executable, str(runtime), '--root', str(self.root), '--record-pr-review',
            '--repo', str(repo), '--base', 'main', '--requirements-reviewed',
            '--contracts-reviewed', '--validation-reviewed'], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        (repo / 'app.txt').write_text('feature\n')

        config = json.loads((self.root / '.codex/hooks.json').read_text())
        command = config['hooks']['PreToolUse'][0]['hooks'][0]['command']
        payload = {'hook_event_name': 'PreToolUse', 'session_id': 'test', 'turn_id': 'turn',
                   'cwd': str(repo), 'tool_name': 'Bash',
                   'tool_input': {'command': 'gh pr create --base main'}}
        run = subprocess.run(command, shell=True, input=json.dumps(payload),
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertNotEqual(json.loads(run.stdout).get('hookSpecificOutput', {}).get(
            'permissionDecision'), 'deny')

    def test_corrupt_state_and_changed_runtime_warn_without_blocking_or_leaking(self):
        INSTALL.install(self.root, 'write')
        config = json.loads((self.root / '.codex/hooks.json').read_text())
        command = config['hooks']['UserPromptSubmit'][0]['hooks'][0]['command']
        state = self.root / 'ai-input/hook-state/communication.sqlite3'
        state.parent.mkdir(parents=True)
        state.write_text('private-corrupt-state')
        payload = json.dumps({'hook_event_name': 'UserPromptSubmit', 'session_id': 's', 'turn_id': 't'})
        result = subprocess.run(command, shell=True, input=payload, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertNotIn('private-corrupt-state', result.stderr)
        state.unlink()
        subprocess.run(command, shell=True, input=payload, capture_output=True, text=True, check=True)
        with closing(sqlite3.connect(state)) as db, db:
            db.execute("UPDATE sessions SET data='[]'")
        result = subprocess.run(command, shell=True, input=payload, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        runtime = self.root / INSTALL.RUNTIME
        runtime.write_bytes(runtime.read_bytes() + b'\n# local edit\n')
        result = subprocess.run(command, shell=True, input=payload, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})
        self.assertTrue(result.stderr)


if __name__ == '__main__':
    unittest.main()

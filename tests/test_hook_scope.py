"""Installation boundaries and notification turns, without PR/network writes."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shlex
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'scope_hook', Path(__file__).resolve().parents[1] / 'hooks/communication.py')
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class HookScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        parent = Path(self.temp.name).resolve()
        self.root = parent / 'installed'
        self.root.mkdir()
        self.outside = parent / 'installed-other'
        self.outside.mkdir()
        self.inside = self.root / 'app'
        self.inside.mkdir()
        self.alias = self.root / 'outside-link'
        self.alias.symlink_to(self.outside, target_is_directory=True)

    def event(self, engine, event='PreToolUse', cwd=None, **fields):
        return HOOK.handle({'hook_event_name': event, 'session_id': engine,
                            'turn_id': 'user', 'cwd': str(cwd or self.root), **fields},
                           engine, self.root)

    def test_external_targets_skip_gates_and_state(self):
        commands = ('gh pr create --base develop --head feature', 'gh pr merge 17 --merge',
                    'git push origin HEAD:refs/heads/feature', 'git push origin :refs/heads/feature')
        for engine in ('codex', 'claude'):
            for cwd in (self.outside, self.alias):
                for command in commands:
                    with self.subTest(engine=engine, cwd=cwd, command=command):
                        self.assertEqual(self.event(engine, cwd=cwd, tool_name='Bash',
                                                    tool_input={'command': command}), {})
            for directory in (str(self.outside), '../installed-other'):
                self.assertEqual(self.event(engine, tool_name='exec_command', tool_input={
                    'cmd': commands[0], 'workdir': directory}), {})
                self.assertEqual(self.event(engine, tool_name='Bash', tool_input={
                    'command': f'git -C {shlex.quote(directory)} push origin feature'}), {})
            self.assertEqual(self.event(engine, tool_name='Bash', tool_input={
                'command': f'cd {shlex.quote(str(self.outside))} && gh pr create --base develop --head feature'}), {})
            for event in ('UserPromptSubmit', 'Stop'):
                self.assertEqual(self.event(engine, event, cwd=self.outside, prompt='PR 만들어줘',
                                            last_assistant_message='완료'), {})
            self.assertEqual(self.event(engine, tool_name='Write', tool_input={
                'file_path': str(self.outside / 'db/migration.sql')}), {})
            self.assertEqual(self.event(engine, tool_name='apply_patch', tool_input={
                'patch': '*** Update File: ' + str(self.outside / 'api/app.py')}), {})
        self.assertFalse((self.root / 'ai-input').exists())

    def test_internal_targets_and_ambiguous_commands_keep_gate(self):
        denied = HOOK.deny('in-scope review required')
        for engine in ('codex', 'claude'):
            for fields in (
                {'cwd': self.outside, 'tool_name': 'exec_command', 'tool_input': {
                    'cmd': 'gh pr create --base develop --head feature', 'workdir': str(self.inside)}},
                {'cwd': self.outside, 'tool_name': 'Bash', 'tool_input': {
                    'command': f'git -C {shlex.quote(str(self.inside))} push origin feature'}},
                {'tool_name': 'Bash', 'tool_input': {'command': 'gh pr create --base develop --head feature'}},
                {'tool_name': 'Bash', 'tool_input': {'command':
                    f'cd {shlex.quote(str(self.outside))} && gh pr create; git -C {shlex.quote(str(self.inside))} push origin feature'}},
                {'tool_name': 'Bash', 'tool_input': {'command': 'git -C "$TARGET" push origin feature'}},
            ):
                with self.subTest(engine=engine, fields=fields), patch.object(HOOK, 'check_review', return_value=denied):
                    result = self.event(engine, **fields)
                    self.assertEqual(result.get('hookSpecificOutput', {}).get('permissionDecision'), 'deny')

    def test_notification_keeps_previous_user_intent_and_turn(self):
        for engine in ('codex', 'claude'):
            for requested_pr in (False, True):
                user_turn = 'pr' if requested_pr else 'nonpr'
                self.event(engine, 'UserPromptSubmit', turn_id=user_turn,
                           prompt='PR 만들어줘' if requested_pr else '코드를 점검해줘')
                output = self.event(engine, 'UserPromptSubmit', turn_id='notification',
                                    prompt='<task-notification>PR 생성·머지 완료</task-notification>')
                self.assertEqual(output, {})
                with patch.object(HOOK, 'check_review', return_value=HOOK.deny('review')) as check:
                    output = self.event(engine, turn_id='notification', tool_name='Bash',
                                        tool_input={'command': 'git push origin feature'})
                self.assertEqual(check.called, requested_pr)
                self.assertEqual(output.get('hookSpecificOutput', {}).get('permissionDecision') == 'deny', requested_pr)
                with closing(sqlite3.connect(self.root / 'ai-input/hook-state/communication.sqlite3')) as db:
                    turn, data = db.execute('SELECT turn,data FROM sessions WHERE id=?',
                                            (HOOK.digest(engine + ':' + engine),)).fetchone()
                self.assertEqual(json.loads(data)['pr_intent'], requested_pr)
                if engine == 'codex':
                    self.assertEqual(turn, user_turn)

    def test_notification_without_user_boundary_does_not_inject_pr_context(self):
        for engine in ('codex', 'claude'):
            self.assertEqual(self.event(engine, 'UserPromptSubmit',
                                        prompt='<task-notification>PR 생성 완료</task-notification>'), {})
            self.assertEqual(self.event(engine, 'UserPromptSubmit', turn_id=None,
                                        prompt='<task-notification>PR 생성 완료</task-notification>'), {})
            with patch.object(HOOK, 'check_review', return_value=HOOK.deny('unknown intent')) as check:
                self.event(engine, tool_name='Bash', tool_input={'command': 'git push origin feature'})
                self.assertTrue(check.called)

    def test_failure_guidance_names_actual_git_C_target(self):
        target = self.inside / 'missing'
        output = HOOK.check_review(self.root, self.root, {
            'action': 'push', 'repo': str(target), 'error': None})
        reason = output['hookSpecificOutput']['permissionDecisionReason']
        self.assertIn('--repo ' + str(target), reason)

    def test_mixed_patch_tracks_only_internal_files(self):
        kind, groups, sensitive = HOOK.classify({
            'cwd': str(self.root), 'tool_name': 'apply_patch', 'tool_input': {
                'patch': f'*** Update File: {self.inside}/app.py\n*** Update File: {self.outside}/db/migration.sql'}}, self.root)
        self.assertEqual(kind, 'edit')
        self.assertEqual(len(groups), 1)
        self.assertFalse(sensitive)

    def test_external_prompt_cannot_reuse_old_nonpr_intent_for_internal_push(self):
        for engine in ('codex', 'claude'):
            self.event(engine, 'UserPromptSubmit', prompt='코드를 점검해줘')
            self.event(engine, 'UserPromptSubmit', cwd=self.outside,
                       turn_id='external', prompt='PR 만들어줘')
            with patch.object(HOOK, 'check_review', return_value=HOOK.deny('review required')) as check:
                result = self.event(engine, cwd=self.outside, turn_id='external',
                                    tool_name='exec_command', tool_input={
                                        'cmd': 'git push origin feature', 'workdir': str(self.inside)})
                self.assertTrue(check.called, engine)
                self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')


if __name__ == '__main__':
    unittest.main()

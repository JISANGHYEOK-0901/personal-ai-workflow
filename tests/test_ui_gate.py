"""UI gate contract tests use a fixture verifier; real browser evidence is produced by the app verifier."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('ui_communication', Path(__file__).resolve().parents[1] / 'hooks/communication.py')
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class UIGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='ui-gate-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-qb', 'main')
        self.git('config', 'user.name', 'UI Test')
        self.git('config', 'user.email', 'ui@example.invalid')
        (self.root / '.gitignore').write_text('ai-input/\n.workflow-hooks/\n')
        (self.root / 'frontend').mkdir()
        (self.root / 'frontend/main.js').write_text('base')
        (self.root / 'api.py').write_text('base')
        (self.root / 'verifier.py').write_text("""import json,sys
from pathlib import Path
report=Path(sys.argv[1])
(report.parent/'screen.png').write_bytes(b'\\x89PNG\\r\\n\\x1a\\n'+b'x'*100)
report.write_text(json.dumps({'framework':'playwright','passed':True,'checks':[{'name':'fixture','passed':True,'interaction':'click'}],
'screenshots':[{'path':'screen.png','viewport':{'width':390,'height':844}}],'consoleErrors':[],'networkErrors':[]}))
""")
        self.config = {'paths': ['frontend/**'], 'inputs': ['api.py', 'verifier.py'], 'base': 'main',
                       'command': [sys.executable, 'verifier.py', '{report}']}
        self.write_config()
        self.git('add', '.')
        self.git('commit', '-qm', 'base')
        (self.root / 'frontend/main.js').write_text('changed')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, check=True)

    def write_config(self):
        (self.root / '.workflow-ui.json').write_text(json.dumps(self.config))

    def event(self, event='Stop', **fields):
        return HOOK.handle({'hook_event_name': event, 'cwd': str(self.root),
                            'session_id': 'ui', 'turn_id': 'ui', **fields}, 'codex', self.root)

    def test_stop_requires_current_evidence_including_repeat_stop(self):
        for engine in ('codex', 'claude'):
            result = HOOK.handle({'hook_event_name': 'Stop', 'cwd': str(self.root), 'stop_hook_active': True}, engine, self.root)
            self.assertEqual(result.get('decision'), 'block')
        HOOK.verify_ui(self.root)
        self.assertEqual(self.event(), {})
        (self.root / 'frontend/main.js').write_text('changed again')
        self.assertEqual(self.event().get('decision'), 'block')

    def test_inputs_and_report_tampering_invalidate_receipt(self):
        HOOK.verify_ui(self.root)
        (self.root / 'api.py').write_text('new contract')
        self.assertEqual(self.event().get('decision'), 'block')
        result = HOOK.verify_ui(self.root)
        (self.root / result['report']).write_text('{}')
        self.assertEqual(self.event().get('decision'), 'block')

    def test_failed_process_cannot_reuse_previous_receipt_for_changed_source(self):
        HOOK.verify_ui(self.root)
        (self.root / 'frontend/main.js').write_text('new')
        self.config['command'] = [sys.executable, '-c', 'import sys;sys.exit(1)', '{report}']
        self.write_config()
        with self.assertRaisesRegex(ValueError, 'failed'):
            HOOK.verify_ui(self.root)
        self.assertEqual(self.event().get('decision'), 'block')

    def test_evidence_requires_assertions_interaction_images_and_no_errors(self):
        result = HOOK.verify_ui(self.root)
        path = self.root / result['report']
        original = json.loads(path.read_text())
        for field, value in [('checks', []), ('checks', [1]), ('screenshots', []), ('consoleErrors', ['error']), ('networkErrors', ['404'])]:
            with self.subTest(field=field):
                path.write_text(json.dumps({**original, field: value}))
                with self.assertRaises(ValueError):
                    HOOK.ui_report_evidence(self.root, path)
        path.write_text(json.dumps({**original, 'checks': [{'passed': True, 'interaction': 'selectOption'}]}))
        with self.assertRaisesRegex(ValueError, 'actual interaction'):
            HOOK.ui_report_evidence(self.root, path)

    def test_committing_ui_does_not_bypass_pr_gate(self):
        self.git('checkout', '-qb', 'feature')
        self.git('commit', '-qam', 'ui')
        result = self.event('PreToolUse', tool_name='exec_command', tool_input={'cmd': 'gh pr create', 'workdir': str(self.root)})
        self.assertIn('--verify-ui', result['hookSpecificOutput']['permissionDecisionReason'])
        HOOK.verify_ui(self.root)
        self.assertIsNone(HOOK.ui_gate(self.root, 'PreToolUse', release=True))

    def test_commit_during_turn_does_not_bypass_stop(self):
        self.event('UserPromptSubmit', prompt='UI를 수정해 줘')
        (self.root / 'frontend/main.js').write_text('edited during turn')
        self.git('commit', '-qam', 'ui on main')
        self.assertEqual(self.event().get('decision'), 'block')

    def test_external_repository_is_never_examined(self):
        outside = self.root.parent / 'not-installed'
        self.assertEqual(self.event(cwd=str(outside)), {})
        self.assertFalse((self.root / '.workflow-hooks').exists())

    def test_explicit_blocked_report_allows_incomplete_stop_but_not_pr(self):
        self.assertEqual(self.event(last_assistant_message='UI_VALIDATION_BLOCKED: browser unavailable; install browser to resume'), {})
        self.assertIsNotNone(HOOK.ui_gate(self.root, 'PreToolUse', release=True))

    def test_backend_only_change_does_not_start_ui_gate(self):
        (self.root / 'frontend/main.js').write_text('base')
        (self.root / 'api.py').write_text('changed')
        self.assertEqual(self.event(), {})


if __name__ == '__main__':
    unittest.main()

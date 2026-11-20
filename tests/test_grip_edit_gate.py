import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location(
    'communication', Path(__file__).resolve().parents[1] / 'hooks' / 'communication.py'
)
HOOK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOOK)


class GripEditGateTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        parent = Path(directory.name).resolve()
        self.root = parent / 'practice-skill'
        self.target = parent / 'ai-office'
        self.register = self.root / 'ai-input/grip/test-task/GRIP_REGISTER.md'
        self.register.parent.mkdir(parents=True)
        (self.target / 'docs').mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', '-b', 'review-flow', str(self.target)], check=True)
        self.dependent = self.target / 'dashboard/server.mjs'
        self.scope = {
            'worktree': str(self.target),
            'branch': 'review-flow',
            'blocked_by': {'T1': ['dashboard/server.mjs']},
        }
        self.write_register('status:UNRESOLVED')

    def write_register(self, status, topic='T1'):
        self.register.write_text(
            '# Review flow\n\n'
            f'- [ ] {topic} | CORE | Reviewer | depends:- | {status}\n\n'
            '```grip-edit-scope\n' + json.dumps(self.scope) + '\n```\n',
            encoding='utf-8',
        )

    def run_hook(self, engine, name, args, cwd=None):
        return HOOK.handle({
            'hook_event_name': 'PreToolUse',
            'tool_name': name,
            'tool_input': args,
            'cwd': str(cwd or self.root),
        }, engine, self.root)

    def edit(self, path):
        return self.run_hook('claude', 'Edit', {'file_path': str(path)})

    def assert_denied(self, result, topic='T1'):
        output = result['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertIn(topic, output['permissionDecisionReason'])

    def test_blocks_only_the_registered_edit_from_both_clients(self):
        self.assert_denied(self.edit(self.dependent))
        self.assert_denied(self.run_hook('codex', 'apply_patch', {
            'patch': '*** Begin Patch\n*** Add File: ../ai-office/dashboard/server.mjs\n*** End Patch',
        }))
        self.assertEqual(self.edit(self.target / 'docs/DECISIONS.md'), {})
        self.assertEqual(self.edit(self.target / 'dashboard/unrelated.mjs'), {})

    def test_resolution_requires_the_recorded_documents_to_exist(self):
        self.write_register('status:RESOLVED | decision:Chief | applied:["docs/DECISIONS.md"]')
        self.assert_denied(self.edit(self.dependent))
        (self.target / 'docs/DECISIONS.md').write_text('Chief is final reviewer.\n')
        self.assertEqual(self.edit(self.dependent), {})

    def test_topic_ids_from_the_automatic_interview(self):
        self.scope['blocked_by'] = {'REVIEW-01': ['dashboard/server.mjs']}
        self.write_register('status:UNRESOLVED', topic='REVIEW-01')
        self.assert_denied(self.edit(self.dependent), topic='REVIEW-01')

    def test_dropped_topic_requires_a_reason(self):
        self.write_register('status:DROPPED')
        self.assert_denied(self.edit(self.dependent))
        self.write_register('status:DROPPED | reason:The user confirmed the issue is out of scope.')
        self.assertEqual(self.edit(self.dependent), {})

    def test_different_branch_and_workspace_continue(self):
        subprocess.run(['git', '-C', str(self.target), 'symbolic-ref', 'HEAD', 'refs/heads/other'],
                       check=True)
        self.assertEqual(self.edit(self.dependent), {})
        self.assertEqual(HOOK.handle({
            'hook_event_name': 'PreToolUse', 'tool_name': 'Edit',
            'tool_input': {'file_path': str(self.dependent)}, 'cwd': str(self.target),
        }, 'claude', self.target), {})

    def test_a_removed_topic_cannot_clear_its_explicitly_registered_paths(self):
        self.register.write_text(
            '```grip-edit-scope\n' + json.dumps(self.scope) + '\n```\n', encoding='utf-8',
        )
        self.assert_denied(self.edit(self.dependent))

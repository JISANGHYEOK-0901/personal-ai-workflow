"""Baseline sensitivity and local preview disclosure boundary."""
import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.request import urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class LabTests(unittest.TestCase):
    def test_evaluator_detects_bug_and_fix_without_claiming_agent_actions(self):
        evaluator = load('evaluator', 'experiments/exp001/evaluate.py')
        baseline = evaluator.evaluate(ROOT / 'experiments/exp001/fixture')
        self.assertEqual(baseline['correctness'], 'fail')
        self.assertFalse(baseline['cases'][0]['passed'])
        self.assertTrue(all(case['passed'] for case in baseline['cases'][1:]))
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'average.py').write_text('def average(values):\n    return sum(values) / len(values) if values else None\n')
            fixed = evaluator.evaluate(folder)
        self.assertEqual(fixed['correctness'], 'pass')
        for field in ('agent_validation', 'review', 'merge', 'cleanup', 'scope_preservation'):
            self.assertEqual(fixed[field], 'unknown')

    def test_preview_only_serves_allowlisted_assets(self):
        preview = load('preview', 'scripts/serve_lab.py')
        server = ThreadingHTTPServer(('127.0.0.1', 0), preview.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = f'http://127.0.0.1:{server.server_port}'
        try:
            with urlopen(root) as response:
                self.assertIn('DEMO', response.read().decode())
            for path in ('/ai-input/worklog/', '/../AGENTS.md', '/%2e%2e/AGENTS.md', '/.git/config', '/unknown'):
                with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                    urlopen(root + path)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

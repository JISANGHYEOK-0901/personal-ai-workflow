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
                self.assertIn('가상', response.read().decode())
            for path in ('/ai-input/worklog/', '/../AGENTS.md', '/%2e%2e/AGENTS.md', '/.git/config', '/unknown'):
                with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                    urlopen(root + path)
                self.assertEqual(error.exception.code, 404)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_local_report_is_exact_plain_text_and_missing_or_symlink_is_not_served(self):
        preview = load('case_preview', 'scripts/serve_lab.py')
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder).resolve() / 'report.md'
            preview.CASE_REPORT = report
            server = ThreadingHTTPServer(('127.0.0.1', 0), preview.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/local-case-study'
            try:
                for mode in ('missing', 'regular', 'symlink', 'parent-symlink'):
                    if mode == 'regular':
                        report.write_text('<script>alert(1)</script>\n개인 사례')
                        with urlopen(url) as response:
                            self.assertEqual(response.headers.get_content_type(), 'text/plain')
                            self.assertEqual(response.headers['Cache-Control'], 'no-store')
                            self.assertEqual(response.read(), report.read_bytes())
                    else:
                        if mode == 'symlink':
                            report.unlink()
                            report.symlink_to(ROOT / 'AGENTS.md')
                        if mode == 'parent-symlink':
                            target = Path(folder).resolve() / 'target'
                            target.mkdir()
                            (target / 'report.md').write_text('must not be served')
                            alias = Path(folder).resolve() / 'alias'
                            alias.symlink_to(target, target_is_directory=True)
                            preview.CASE_REPORT = alias / 'report.md'
                        with self.assertRaises(HTTPError) as error:
                            urlopen(url)
                        self.assertEqual(error.exception.code, 404)
                        error.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

"""Serve only the curated web directory on loopback; no repository browsing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
CASE_REPORT = ROOT / 'ai-input/experiments/EXP-002/CASE_STUDY_01.md'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8')}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = self.path.split('?', 1)[0]
        if route == '/local-case-study':
            # Only this deliberate local report is readable; reject symlink escapes.
            try:
                if CASE_REPORT.resolve() != CASE_REPORT.absolute():
                    raise FileNotFoundError
                data = CASE_REPORT.read_bytes()
            except OSError:
                self.send_error(404)
                return
            self.respond(data, 'text/plain; charset=utf-8')
            return
        asset = ASSETS.get(route)
        if not asset:
            self.send_error(404)
            return
        path = WEB / asset[0]
        if path.is_symlink():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.respond(data, asset[1])

    def respond(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

if __name__ == '__main__':
    print('Workflow Lab: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()

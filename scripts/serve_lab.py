"""Serve only the curated web directory on loopback; no repository browsing."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / 'web'
ASSETS = {'/': ('index.html', 'text/html; charset=utf-8'),
          '/index.html': ('index.html', 'text/html; charset=utf-8'),
          '/style.css': ('style.css', 'text/css; charset=utf-8'),
          '/app.js': ('app.js', 'text/javascript; charset=utf-8')}

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        asset = ASSETS.get(self.path.split('?', 1)[0])
        if not asset:
            self.send_error(404)
            return
        path = WEB / asset[0]
        if path.is_symlink():
            self.send_error(404)
            return
        data = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', asset[1])
        self.send_header('Content-Length', str(len(data)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

if __name__ == '__main__':
    print('Workflow Lab: http://127.0.0.1:8765', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8765), Handler).serve_forever()

#!/usr/bin/env python3
"""Fallback dev server for environments where `npm run dev` (Vite) cannot run
(e.g. `npm install` is blocked by a corporate proxy).

Serves the repo's raw ES module sources directly, with an import map that
resolves `three` and `three/examples/jsm/` from a CDN, so the app runs in a
normal browser without any build step or installed dependency.

ALWAYS TRY `npm run dev` FIRST. This server is a substitute, not an upgrade:
it skips Vite's bundling/minification, so first paint is slower and there is
no HMR. It is meant only to unblock manual verification (screenshots, console
checks) when Vite is unavailable.

Usage:
    python tools/devserver.py [--port 5188]

Then open http://127.0.0.1:5188/ in a browser, or drive it headlessly with
tools/screenshot.py.
"""
import argparse
import http.server
import os
import socketserver
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root

IMPORT_MAP = (
    '<script type="importmap">{"imports":{'
    '"three":"https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",'
    '"three/examples/jsm/":"https://cdn.jsdelivr.net/npm/three@0.170.0/examples/jsm/"'
    '}}</script>'
    '<script>window.__BUILD__="dev";</script>'  # main.js reads __BUILD__ at build time via Vite `define`; the raw source references it directly, so define it as a global here instead
)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path in ('/', '/index.html'):
            text = open(os.path.join(ROOT, 'index.html'), encoding='utf-8').read()
            # inject the import map before the first <link>, and rewrite the Vite-only __BUILD__ global reference is not needed in HTML
            text = text.replace('<link rel="stylesheet"', IMPORT_MAP + '<link rel="stylesheet"', 1)
            data = text.encode('utf-8')
            self._send(data, 'text/html; charset=utf-8')
            return
        if path.endswith('.js') and path.startswith('/src/'):
            text = open(os.path.join(ROOT, path[1:]), encoding='utf-8').read()
            # only non-standard bit main.js needs at module-eval time: import.meta.env.BASE_URL (Vite-injected). Substitute the same default Vite gives for a root-deployed app.
            text = text.replace('import.meta.env.BASE_URL', "'/'")
            data = text.encode('utf-8')
            self._send(data, 'text/javascript; charset=utf-8')
            return
        if path.startswith(('/models/', '/draco/')) or path in ('/favicon.svg', '/og.jpg', '/manifest.webmanifest', '/icon-192.png', '/icon-512.png', '/sw.js'):
            self.path = '/public' + self.path
            return super().do_GET()
        return super().do_GET()

    def _send(self, data, content_type):
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass  # keep stdout quiet; screenshot.py doesn't need the access log


def serve(port=5188):
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer(('127.0.0.1', port), Handler).serve_forever()


def ensure_running(port=5188):
    """Start the server in a background thread if nothing is listening on `port` yet.
    Called by screenshot.py so a caller never has to manage the server process by hand."""
    import socket
    s = socket.socket()
    try:
        s.connect(('127.0.0.1', port))
        s.close()
        return  # already running
    except OSError:
        pass
    threading.Thread(target=serve, args=(port,), daemon=True).start()
    import time
    time.sleep(0.8)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=5188)
    args = ap.parse_args()
    print(f'serving {ROOT} at http://127.0.0.1:{args.port}/  (Ctrl+C to stop)')
    serve(args.port)

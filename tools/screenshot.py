#!/usr/bin/env python3
"""Headless-Chrome verification helper: loads a page (starting devserver.py if
needed), optionally runs a JS snippet in the page, waits, then captures a
screenshot and any console errors / exceptions.

Built for verifying this project's visual/behavioural changes without a
working `npm run dev` + real browser session. If `npm run dev` DOES work on
this machine, prefer that + a normal browser or Playwright/Puppeteer — this
script is a minimal-dependency (stdlib + `websocket-client` only) fallback.

Requires: a Chrome or Edge binary, and `pip install websocket-client` (falls
back to a clear error message if missing).

Usage examples:
    # smoke test: does the page load without console errors?
    python tools/screenshot.py --out out.png

    # with a setup script: run arbitrary JS after the app is ready, before the shot
    python tools/screenshot.py --path "/?q=medium" --eval eval_snippet.js --out out.png

    # the eval snippet can use `window.__enoden` (see src/main.js's debug handle:
    # camera, scene, renderer, player, train, ground, tod, settings, goto(), setCam(),
    # setTime(), board(), applyQuality(), sim(dt, cmd) to step the simulation
    # headlessly without rendering — see src/main.js's `window.__enoden` block for
    # the full list before adding new debug hooks).

Exit code is 0 even on page errors — the point is to capture, not to gate;
read the printed console/exception lines yourself.
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

try:
    import websocket
except ImportError:
    sys.exit("pip install websocket-client  # required by tools/screenshot.py")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import devserver  # noqa: E402

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    for p in CHROME_CANDIDATES:
        if os.path.exists(p):
            return p
    sys.exit("no Chrome/Edge binary found at the usual install paths; edit CHROME_CANDIDATES in tools/screenshot.py")


def run(path='/', eval_js=None, out=None, port=5188, timeout=60, width=1280, height=720, wait_ready=True, settle_ms=1500, debug_port=9333):
    devserver.ensure_running(port)
    browser = find_browser()
    profile = os.path.join(os.environ.get('TEMP', '/tmp'), f'enoden_shot_{os.getpid()}')
    proc = subprocess.Popen(
        [browser, '--headless=new', f'--remote-debugging-port={debug_port}', '--remote-allow-origins=*',
         f'--user-data-dir={profile}', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
         '--ignore-gpu-blocklist', '--disable-gpu-sandbox', f'--window-size={width},{height}', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    console = []
    try:
        tabs = None
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{debug_port}/json'))
                break
            except Exception:
                time.sleep(0.3)
        page = next(t for t in tabs if t['type'] == 'page')
        ws = websocket.create_connection(page['webSocketDebuggerUrl'], max_size=None)
        msg_id = [0]

        def call(method, **params):
            msg_id[0] += 1
            ws.send(json.dumps({'id': msg_id[0], 'method': method, 'params': params}))
            while True:
                r = json.loads(ws.recv())
                if r.get('method') == 'Runtime.exceptionThrown':
                    ex = r['params']['exceptionDetails']
                    console.append(f"[exception] {ex.get('text')} {ex.get('exception', {}).get('description', '')}"[:400])
                elif r.get('method') == 'Log.entryAdded' and r['params']['entry'].get('level') == 'error':
                    console.append(f"[error] {r['params']['entry'].get('text')}"[:400])
                if r.get('id') == msg_id[0]:
                    return r

        call('Runtime.enable')
        call('Log.enable')
        call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        call('Page.navigate', url=f'http://127.0.0.1:{port}{path}')

        if wait_ready:
            t0 = time.time()
            while time.time() - t0 < timeout:
                r = call('Runtime.evaluate', expression="window.__enoden && window.__enoden.ready", returnByValue=True)
                if r.get('result', {}).get('result', {}).get('value'):
                    break
                time.sleep(0.5)

        if eval_js:
            src = eval_js if not os.path.exists(eval_js) else open(eval_js, encoding='utf-8').read()
            r = call('Runtime.evaluate', expression=f'(async () => {{\n{src}\n}})()', awaitPromise=True, returnByValue=True)
            if 'exceptionDetails' in r.get('result', {}):
                console.append(f"[eval exception] {r['result']['exceptionDetails']}"[:600])

        time.sleep(settle_ms / 1000)

        if out:
            r = call('Page.captureScreenshot', format='png')
            with open(out, 'wb') as f:
                f.write(base64.b64decode(r['result']['data']))
    finally:
        proc.kill()

    for line in console[:20]:
        print(line)
    if out:
        print(f'saved {out}')
    return console


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--path', default='/', help='path + query string to load, e.g. "/?q=high"')
    ap.add_argument('--eval', dest='eval_js', default=None, help='JS file (or inline snippet) to run after the app is ready; awaited if it returns a Promise')
    ap.add_argument('--out', default=None, help='PNG path to save a screenshot to')
    ap.add_argument('--port', type=int, default=5188)
    ap.add_argument('--timeout', type=int, default=60, help='seconds to wait for window.__enoden.ready')
    ap.add_argument('--settle-ms', type=int, default=1500, help='extra wait before the screenshot, after --eval resolves')
    ap.add_argument('--no-wait-ready', dest='wait_ready', action='store_false')
    args = ap.parse_args()
    run(path=args.path, eval_js=args.eval_js, out=args.out, port=args.port, timeout=args.timeout, settle_ms=args.settle_ms, wait_ready=args.wait_ready)

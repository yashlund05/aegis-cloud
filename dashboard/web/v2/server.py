"""
Tiny stdlib-only server for the Aegis evaluation dashboard.

  GET  /                -> index.html
  GET  /data/<name>     -> snapshot JSONs from ./data
  POST /run-demo        -> runs scripts/demo.ps1 and streams its output back
                           (chunked, unbuffered, as the script produces it)

Start:  python server.py        (then open http://localhost:8080)
"""

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))          # dashboard/web/v2
REPO = os.path.dirname(os.path.dirname(os.path.dirname(ROOT)))  # repo root
DEMO = os.path.join(REPO, "scripts", "demo.ps1")

PORT = 8080
_demo_lock = threading.Lock()


def _chunked_write(handler, data: bytes):
    handler.wfile.write(f"{len(data):x}\r\n".encode())
    handler.wfile.write(data)
    handler.wfile.write(b"\r\n")
    handler.wfile.flush()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter logs
        print("[http]", fmt % args)

    # ---------------- GET ----------------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            return self._file(os.path.join(ROOT, "index.html"), "text/html; charset=utf-8")
        if path.startswith("/data/"):
            name = os.path.basename(path)  # basename prevents traversal
            return self._file(os.path.join(ROOT, "data", name), "application/json")
        if path == "/favicon.ico":
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", "9")
        self.end_headers()
        self.wfile.write(b"not found")

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "9")
            self.end_headers()
            self.wfile.write(b"not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---------------- POST /run-demo ----------------
    def do_POST(self):
        if self.path != "/run-demo":
            self.send_response(404); self.end_headers(); return
        if not _demo_lock.acquire(blocking=False):
            self.send_response(409)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"a demo is already running")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", DEMO]
            _chunked_write(self, f"$ {cmd}\r\n".encode())
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    bufsize=1, text=True, errors="replace", cwd=REPO)
            try:
                for line in proc.stdout:
                    _chunked_write(self, line.encode("utf-8", "replace"))
            finally:
                code = proc.wait()
            _chunked_write(self, f"\r\n[exit code {code}]\r\n".encode())
            self.wfile.write(b"0\r\n\r\n")  # terminal chunk
        except (BrokenPipeError, ConnectionAbortedError):
            pass  # browser navigated away
        finally:
            _demo_lock.release()


if __name__ == "__main__":
    print(f"Serving {ROOT} on http://localhost:{PORT} (Ctrl+C to stop)")
    print(f"Demo script: {DEMO} ({'found' if os.path.exists(DEMO) else 'MISSING - /run-demo will fail'})")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

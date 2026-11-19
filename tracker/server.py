#!/usr/bin/env python3
"""Live Mission Control Web Tracker Server for Operation Dumb Bunny."""
import http.server
import json
import mimetypes
import os
import socketserver
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path("/Volumes/mini-m4-2tb/src/3D/dumb-bunny").resolve()
TRACKER_DIR = ROOT / "tracker"
STATE_PATH = ROOT / "work" / "tracker_state.json"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class TrackerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html = (TRACKER_DIR / "index.html").read_bytes()
            return self._send_bytes(html, "text/html; charset=utf-8")

        if path == "/api/state":
            try:
                raw = STATE_PATH.read_bytes()
            except Exception as exc:
                raw = json.dumps({"error": str(exc)}).encode("utf-8")
            return self._send_bytes(raw, "application/json; charset=utf-8")

        # Serve allowed project subdirectories safely
        allowed_prefixes = ("/work/", "/tracker/", "/output/", "/models/")
        if any(path.startswith(p) for p in allowed_prefixes):
            rel = path.lstrip("/")
            target = (ROOT / rel).resolve()
            if not str(target).startswith(str(ROOT)) or not target.is_file():
                return self._send_bytes(b"Not found", "text/plain", 404)
            ctype, _ = mimetypes.guess_type(str(target))
            if not ctype:
                if target.suffix.lower() in (".obj", ".mtl"):
                    ctype = "text/plain; charset=utf-8"
                elif target.suffix.lower() == ".stl":
                    ctype = "application/octet-stream"
                else:
                    ctype = "application/octet-stream"
            return self._send_bytes(target.read_bytes(), ctype)

        return self._send_bytes(b"Not found", "text/plain", 404)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), TrackerHandler)
    print(f"Operation Dumb Bunny Live Tracker running at http://127.0.0.1:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass

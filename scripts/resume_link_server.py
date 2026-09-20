"""Open Gecko resume links from Google Sheets through a localhost-only bridge."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
RESUME_DIR = (ROOT / "output" / "resumes").resolve()
HOST = "127.0.0.1"
PORT = 8765


def resolve_resume(request_path: str) -> Path | None:
    prefix = "/open/"
    if not request_path.startswith(prefix):
        return None
    filename = Path(unquote(request_path[len(prefix):])).name
    candidate = (RESUME_DIR / filename).resolve()
    if candidate.parent != RESUME_DIR or candidate.suffix.lower() != ".docx" or not candidate.is_file():
        return None
    return candidate


class ResumeHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            payload = json.dumps({"status": "ok", "resume_directory": str(RESUME_DIR)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        resume = resolve_resume(path)
        if resume is None:
            self.send_error(404, "Resume not found")
            return

        word_uri = f"ms-word:ofe|u|{resume.as_uri()}"
        safe_name = html.escape(resume.name)
        safe_uri = html.escape(word_uri, quote=True)
        page = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Open {safe_name}</title></head>
<body style="font-family:Segoe UI,Arial,sans-serif;padding:2rem">
<p>Opening <strong>{safe_name}</strong> in Microsoft Word…</p>
<p><a id="open" href="{safe_uri}">Open in Microsoft Word</a></p>
<script>document.getElementById('open').click();</script>
</body></html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    print(f"Gecko resume link server: http://{HOST}:{PORT}")
    print(f"Serving: {RESUME_DIR}")
    ThreadingHTTPServer((HOST, PORT), ResumeHandler).serve_forever()

"""Vercel Serverless Function entry point for forensic-drug-analysis API."""
import os
import sys
from pathlib import Path

# Ensure temporary writable directory for SQLite history and notebook store in Vercel's read-only environment
os.environ.setdefault("FORENSIC_STORAGE_DIR", "/tmp/forensic_storage")

# Add the project root to sys.path so server and core modules can be imported
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server

class handler(server.Handler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / "frontend"), **kwargs)

    def _normalize_request(self):
        # On Vercel reverse proxy, ensure self.path reflects original path
        forwarded_uri = (
            self.headers.get("x-forwarded-uri")
            or self.headers.get("x-matched-path")
            or self.headers.get("x-now-route-matches")
        )
        if forwarded_uri and "/api" in forwarded_uri:
            self.path = forwarded_uri

        # Forwarded host handling for origin verification
        forwarded_host = self.headers.get("x-forwarded-host")
        if forwarded_host and "Host" in self.headers:
            self.headers["Host"] = forwarded_host

    def do_GET(self):
        self._normalize_request()
        return super().do_GET()

    def do_POST(self):
        self._normalize_request()
        return super().do_POST()

# Export top-level variables expected by Vercel's Python runtime
app = handler
application = handler


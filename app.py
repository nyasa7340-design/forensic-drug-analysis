"""Vercel Serverless Function entrypoint bridge for forensic-drug-analysis."""
import os
import sys
from pathlib import Path

# Redirect storage to /tmp for serverless runtime
os.environ.setdefault("FORENSIC_STORAGE_DIR", "/tmp/forensic_storage")

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.index import handler, app, application

__all__ = ["handler", "app", "application"]

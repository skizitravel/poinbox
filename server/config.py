from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_env() -> None:
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
DATABASE_PATH = ROOT / os.getenv("DATABASE_PATH", "data/poinbox_po.sqlite")
STORAGE_DIR = ROOT / os.getenv("STORAGE_DIR", "storage")
SAMPLES_DIR = ROOT / os.getenv("SAMPLES_DIR", "samples/inbox")
PUBLIC_DIR = ROOT / "public"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
USE_OPENAI_EXTRACTION = os.getenv("USE_OPENAI_EXTRACTION", "0") == "1"
INITIAL_ADMIN_EMAIL = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com")
INITIAL_ADMIN_NAME = os.getenv("INITIAL_ADMIN_NAME", "Local Admin")
TEST_CORPUS_DIR = ROOT / os.getenv("TEST_CORPUS_DIR", "samples/test-corpus")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", f"http://{APP_HOST}:{APP_PORT}/api/oauth/gmail/callback")
GMAIL_SCOPES = os.getenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly")
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "")
OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET", "")
OUTLOOK_TENANT = os.getenv("OUTLOOK_TENANT", "common")
OUTLOOK_REDIRECT_URI = os.getenv("OUTLOOK_REDIRECT_URI", f"http://{APP_HOST}:{APP_PORT}/api/oauth/outlook/callback")
OUTLOOK_SCOPES = os.getenv("OUTLOOK_SCOPES", "offline_access User.Read Mail.Read")

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

APP_ENV = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower() or "development"
IS_PRODUCTION = APP_ENV == "production"
APP_HOST = os.getenv("APP_HOST", "0.0.0.0" if IS_PRODUCTION else "127.0.0.1")
APP_PORT = int(os.getenv("PORT", os.getenv("APP_PORT", "8000")))
APP_BASE_URL = os.getenv("APP_BASE_URL", f"http://{APP_HOST}:{APP_PORT}").rstrip("/")


def app_path(env_name: str, default: str) -> Path:
    configured = Path(os.getenv(env_name, default))
    return configured if configured.is_absolute() else ROOT / configured


DATABASE_PATH = app_path("DATABASE_PATH", "data/poinbox_po.sqlite")
STORAGE_DIR = app_path("STORAGE_DIR", "storage")
SAMPLES_DIR = app_path("SAMPLES_DIR", "samples/inbox")
PUBLIC_DIR = ROOT / "public"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
USE_OPENAI_EXTRACTION = os.getenv("USE_OPENAI_EXTRACTION", "0") == "1"
INITIAL_ADMIN_EMAIL = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com")
INITIAL_ADMIN_NAME = os.getenv("INITIAL_ADMIN_NAME", "Local Admin")
INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD", "")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "168"))
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "mountaingoat_session")
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1" if IS_PRODUCTION else "0") == "1"
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY", "")
OCR_PROVIDER = os.getenv("OCR_PROVIDER", "none").strip().lower() or "none"
TEST_CORPUS_DIR = app_path("TEST_CORPUS_DIR", "samples/test-corpus")
GMAIL_CLIENT_ID = os.getenv("GMAIL_CLIENT_ID", "")
GMAIL_CLIENT_SECRET = os.getenv("GMAIL_CLIENT_SECRET", "")
GMAIL_REDIRECT_URI = os.getenv("GMAIL_REDIRECT_URI", f"{APP_BASE_URL}/api/oauth/gmail/callback")
GMAIL_SCOPES = os.getenv("GMAIL_SCOPES", "https://www.googleapis.com/auth/gmail.readonly")
OUTLOOK_CLIENT_ID = os.getenv("OUTLOOK_CLIENT_ID", "")
OUTLOOK_CLIENT_SECRET = os.getenv("OUTLOOK_CLIENT_SECRET", "")
OUTLOOK_TENANT = os.getenv("OUTLOOK_TENANT", "common")
OUTLOOK_REDIRECT_URI = os.getenv("OUTLOOK_REDIRECT_URI", f"{APP_BASE_URL}/api/oauth/outlook/callback")
OUTLOOK_SCOPES = os.getenv("OUTLOOK_SCOPES", "offline_access User.Read Mail.Read")
ENABLE_BACKGROUND_SYNC = os.getenv("ENABLE_BACKGROUND_SYNC", "0") == "1"


def validate_production_config() -> None:
    if IS_PRODUCTION and not ENCRYPTION_KEY:
        raise RuntimeError("ENCRYPTION_KEY is required when APP_ENV=production.")

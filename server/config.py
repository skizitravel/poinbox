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

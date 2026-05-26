from __future__ import annotations

import base64
import hashlib

from server.config import APP_ENV, ENCRYPTION_KEY, IS_PRODUCTION


ENCRYPTED_PREFIX = "enc:v1:"
DEV_ENCRYPTION_KEY = "mountaingoat-local-development-encryption-key"


def encryption_key_configured() -> bool:
    return bool(ENCRYPTION_KEY)


def _fernet_key() -> bytes:
    source = ENCRYPTION_KEY.strip()
    if not source:
        if IS_PRODUCTION:
            raise RuntimeError("ENCRYPTION_KEY is required for encrypted secret storage in production.")
        source = DEV_ENCRYPTION_KEY
    try:
        raw = base64.urlsafe_b64decode(source.encode("ascii"))
        if len(raw) == 32:
            return source.encode("ascii")
    except Exception:
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except Exception as exc:
        raise RuntimeError("Install dependencies from requirements.txt to enable encrypted secret storage.") from exc
    return Fernet(_fernet_key())


def encrypt_secret(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text or text.startswith(ENCRYPTED_PREFIX):
        return text
    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return f"{ENCRYPTED_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    if not text.startswith(ENCRYPTED_PREFIX):
        return text
    token = text.removeprefix(ENCRYPTED_PREFIX).encode("ascii")
    return _fernet().decrypt(token).decode("utf-8")


def encrypted_secret_label() -> str:
    return "configured" if encryption_key_configured() else f"development-fallback ({APP_ENV})"

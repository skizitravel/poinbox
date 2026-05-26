from __future__ import annotations

import os
from dataclasses import dataclass

from server.config import DATABASE_PATH, OPENAI_MODEL, USE_OPENAI_EXTRACTION
from server.crypto_utils import decrypt_secret, encrypt_secret, encrypted_secret_label
from server.db import connect, initialize


OPENAI_API_KEY_SETTING = "openai_api_key"
OPENAI_MODEL_SETTING = "openai_model"
OPENAI_USE_AI_SETTING = "openai_use_ai_extraction"


@dataclass
class OpenAIExtractionConfig:
    api_key: str
    model: str
    use_ai_extraction: bool
    api_key_configured: bool


def get_app_setting(conn, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value, is_sensitive FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row and row["value"] is not None:
        return decrypt_secret(row["value"]) if row["is_sensitive"] else row["value"]
    return default


def set_app_setting(conn, key: str, value: str, is_sensitive: bool = False) -> None:
    stored_value = encrypt_secret(value) if is_sensitive and value else value
    conn.execute(
        """
        INSERT INTO app_settings (key, value, is_sensitive)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, is_sensitive = excluded.is_sensitive,
            updated_at = CURRENT_TIMESTAMP
        """,
        (key, stored_value, 1 if is_sensitive else 0),
    )


def bool_from_setting(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_openai_extraction_config() -> dict:
    config = get_openai_runtime_config()
    return {
        "api_key_configured": config.api_key_configured,
        "model": config.model,
        "use_ai_extraction": config.use_ai_extraction,
        "encrypted_storage": encrypted_secret_label(),
    }


def save_openai_extraction_config(payload: dict) -> dict:
    model = (payload.get("model") or "").strip()
    if not model:
        return {"error": "Model is required."}
    with connect(DATABASE_PATH) as conn:
        initialize(conn)
        api_key = (payload.get("api_key") or "").strip()
        try:
            if api_key:
                set_app_setting(conn, OPENAI_API_KEY_SETTING, api_key, True)
            set_app_setting(conn, OPENAI_MODEL_SETTING, model, False)
            set_app_setting(conn, OPENAI_USE_AI_SETTING, "1" if bool(payload.get("use_ai_extraction")) else "0", False)
            conn.commit()
        except RuntimeError as exc:
            return {"error": str(exc), **get_openai_extraction_config()}
    return get_openai_extraction_config()


def get_openai_runtime_config() -> OpenAIExtractionConfig:
    env_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    env_model = os.getenv("OPENAI_MODEL", OPENAI_MODEL).strip() or "gpt-4.1-mini"
    env_use_ai = USE_OPENAI_EXTRACTION
    try:
        with connect(DATABASE_PATH) as conn:
            initialize(conn)
            api_key = (get_app_setting(conn, OPENAI_API_KEY_SETTING, env_api_key) or "").strip()
            model = (get_app_setting(conn, OPENAI_MODEL_SETTING, env_model) or env_model).strip()
            stored_use_ai = get_app_setting(conn, OPENAI_USE_AI_SETTING)
            use_ai = bool_from_setting(stored_use_ai, env_use_ai)
    except Exception:
        api_key = env_api_key
        model = env_model
        use_ai = env_use_ai
    return OpenAIExtractionConfig(
        api_key=api_key,
        model=model or "gpt-4.1-mini",
        use_ai_extraction=use_ai,
        api_key_configured=bool(api_key),
    )

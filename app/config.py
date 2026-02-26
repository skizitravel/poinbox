"""Application configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Central settings object populated from environment variables."""

    APP_ENV: str = os.getenv("APP_ENV", "dev")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./po_inbox_monitor.db")
    MAILBOX_MODE: str = os.getenv("MAILBOX_MODE", "mock")
    MOCK_CSV_PATH: str = os.getenv("MOCK_CSV_PATH", "data/sample_inbox_messages.csv")

    # Microsoft Graph placeholders — not used in first draft
    GRAPH_TENANT_ID: str = os.getenv("GRAPH_TENANT_ID", "")
    GRAPH_CLIENT_ID: str = os.getenv("GRAPH_CLIENT_ID", "")
    GRAPH_CLIENT_SECRET: str = os.getenv("GRAPH_CLIENT_SECRET", "")
    GRAPH_MAILBOX_USER: str = os.getenv("GRAPH_MAILBOX_USER", "")
    GRAPH_FOLDER_NAME: str = os.getenv("GRAPH_FOLDER_NAME", "Inbox")


settings = Settings()

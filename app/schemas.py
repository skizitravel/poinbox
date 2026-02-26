"""Pydantic / SQLModel schemas used across the application."""

from typing import Optional
from pydantic import BaseModel


class InboxMessage(BaseModel):
    """Represents a single email with one attachment as fetched from a mailbox adapter."""

    email_id: str
    received_at: str
    sender: str
    subject: str
    attachment_id: str
    attachment_name: str
    attachment_hash: Optional[str] = None


class SyncResult(BaseModel):
    """Summary returned after a sync run."""

    total_seen: int
    inserted: int
    skipped_duplicates: int
    ignored_non_po: int

"""SQLModel ORM models for the PO Inbox Monitor."""

from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


class POWorklist(SQLModel, table=True):
    """A single worklist record representing one email/attachment pair."""

    __tablename__ = "po_worklist"

    record_id: str = Field(primary_key=True)
    email_id: str = Field(index=True)
    received_at: str
    sender: str
    subject: str
    attachment_id: str = Field(index=True)
    attachment_name: str
    attachment_hash: Optional[str] = Field(default=None)
    is_likely_po: bool
    status: str = Field(default="NEW")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

"""SQLite database storage helpers: insert, query, and duplicate detection."""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlmodel import Session, select
from sqlalchemy.exc import IntegrityError

from app.models import POWorklist
from app.schemas import InboxMessage


def record_exists(session: Session, email_id: str, attachment_id: str) -> bool:
    """Return True if a record with this (email_id, attachment_id) already exists."""
    statement = select(POWorklist).where(
        POWorklist.email_id == email_id,
        POWorklist.attachment_id == attachment_id,
    )
    result = session.exec(statement).first()
    return result is not None


def insert_worklist_record(
    session: Session,
    message: InboxMessage,
    is_likely_po: bool,
    status: str = "NEW",
) -> Optional[POWorklist]:
    """Insert a new POWorklist record.

    Returns the created record, or None if a duplicate was detected.
    """
    if record_exists(session, message.email_id, message.attachment_id):
        return None

    record = POWorklist(
        record_id=str(uuid.uuid4()),
        email_id=message.email_id,
        received_at=message.received_at,
        sender=message.sender,
        subject=message.subject,
        attachment_id=message.attachment_id,
        attachment_name=message.attachment_name,
        attachment_hash=message.attachment_hash,
        is_likely_po=is_likely_po,
        status=status,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    session.add(record)
    try:
        session.commit()
        session.refresh(record)
        return record
    except IntegrityError:
        session.rollback()
        return None


def get_worklist(
    session: Session,
    status_filter: Optional[str] = None,
    likely_po_filter: Optional[bool] = None,
) -> List[POWorklist]:
    """Return worklist records, optionally filtered, sorted newest first."""
    statement = select(POWorklist)

    if status_filter:
        statement = statement.where(POWorklist.status == status_filter)
    if likely_po_filter is not None:
        statement = statement.where(POWorklist.is_likely_po == likely_po_filter)

    results = session.exec(statement).all()
    # Sort newest first by received_at (ISO strings sort correctly)
    return sorted(results, key=lambda r: r.received_at, reverse=True)


def count_by_status(session: Session) -> dict:
    """Return a dict with total and per-status counts."""
    all_records = session.exec(select(POWorklist)).all()
    counts: dict = {"total": len(all_records)}
    for record in all_records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts

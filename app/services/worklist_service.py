"""Worklist sync service — orchestrates fetch → classify → store."""

from sqlmodel import Session

from app.mailbox.base import MailboxAdapter
from app.schemas import SyncResult
from app.services.po_classifier import is_likely_po
from app.storage import insert_worklist_record, record_exists


def sync_inbox(adapter: MailboxAdapter, session: Session) -> SyncResult:
    """Pull messages from the mailbox adapter, classify them, and persist POs.

    Args:
        adapter: A MailboxAdapter implementation (mock or Graph).
        session: An active SQLModel database session.

    Returns:
        A SyncResult with counts for total_seen, inserted, skipped_duplicates,
        and ignored_non_po.
    """
    messages = adapter.fetch_messages()

    total_seen = len(messages)
    inserted = 0
    skipped_duplicates = 0
    ignored_non_po = 0

    for message in messages:
        likely = is_likely_po(message.subject, message.attachment_name)

        if not likely:
            ignored_non_po += 1
            continue

        if record_exists(session, message.email_id, message.attachment_id):
            skipped_duplicates += 1
            continue

        result = insert_worklist_record(session, message, is_likely_po=True)
        if result is not None:
            inserted += 1
        else:
            skipped_duplicates += 1

    return SyncResult(
        total_seen=total_seen,
        inserted=inserted,
        skipped_duplicates=skipped_duplicates,
        ignored_non_po=ignored_non_po,
    )

"""Tests for the worklist sync service."""

import os
import csv
import tempfile
import pytest
from sqlmodel import SQLModel, create_engine, Session

from app.schemas import InboxMessage
from app.mailbox.mock_adapter import MockMailboxAdapter
from app.services.worklist_service import sync_inbox
from app.storage import get_worklist


@pytest.fixture
def session():
    """Fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def sample_csv(tmp_path):
    """Write a small deterministic CSV to a temp file and return its path."""
    rows = [
        {
            "email_id": "E001",
            "received_at": "2024-01-15T08:30:00",
            "sender": "supplier@acme.com",
            "subject": "PO #1234 Office Supplies",
            "attachment_id": "A001",
            "attachment_name": "PO_1234.pdf",
            "attachment_hash": "aaa",
        },
        {
            "email_id": "E002",
            "received_at": "2024-01-15T09:00:00",
            "sender": "orders@trader.com",
            "subject": "Purchase Order REV2",
            "attachment_id": "A002",
            "attachment_name": "PurchaseOrder_REV2.xlsx",
            "attachment_hash": "bbb",
        },
        {
            "email_id": "E003",
            "received_at": "2024-01-15T10:00:00",
            "sender": "newsletter@promo.com",
            "subject": "January Promotions",
            "attachment_id": "A003",
            "attachment_name": "January_Newsletter.pdf",
            "attachment_hash": "ccc",
        },
        # Duplicate of E001/A001 — should be skipped on second sync
        {
            "email_id": "E001",
            "received_at": "2024-01-15T08:30:00",
            "sender": "supplier@acme.com",
            "subject": "PO #1234 Office Supplies",
            "attachment_id": "A001",
            "attachment_name": "PO_1234.pdf",
            "attachment_hash": "aaa",
        },
    ]
    csv_path = tmp_path / "test_inbox.csv"
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return str(csv_path)


def test_sync_imports_only_likely_pos(session, sample_csv):
    """Sync should insert the 2 PO rows and ignore the newsletter row."""
    adapter = MockMailboxAdapter(csv_path=sample_csv)
    result = sync_inbox(adapter, session)

    assert result.total_seen == 4
    assert result.inserted == 2
    assert result.ignored_non_po == 1
    # The duplicate E001/A001 row is seen as a duplicate
    assert result.skipped_duplicates == 1


def test_rerun_sync_does_not_duplicate(session, sample_csv):
    """Running sync twice should not create duplicate rows."""
    adapter = MockMailboxAdapter(csv_path=sample_csv)

    first = sync_inbox(adapter, session)
    second = sync_inbox(adapter, session)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.skipped_duplicates == 3

    records = get_worklist(session)
    assert len(records) == 2


def test_non_po_emails_not_stored(session, sample_csv):
    """Non-PO emails should not appear in the worklist."""
    adapter = MockMailboxAdapter(csv_path=sample_csv)
    sync_inbox(adapter, session)

    records = get_worklist(session)
    for r in records:
        assert r.is_likely_po is True

"""Tests for storage insert and duplicate-prevention logic."""

import pytest
from sqlmodel import SQLModel, create_engine, Session

from app.models import POWorklist
from app.schemas import InboxMessage
from app.storage import insert_worklist_record, record_exists


@pytest.fixture
def session():
    """Create a fresh in-memory SQLite session for each test."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def _make_message(email_id: str = "EMAIL001", attachment_id: str = "ATT001") -> InboxMessage:
    return InboxMessage(
        email_id=email_id,
        received_at="2024-01-15T08:30:00",
        sender="supplier@acme.com",
        subject="PO #1234",
        attachment_id=attachment_id,
        attachment_name="PO_1234.pdf",
        attachment_hash="abc123",
    )


def test_insert_creates_record(session):
    """A new record should be inserted and returned."""
    msg = _make_message()
    result = insert_worklist_record(session, msg, is_likely_po=True)
    assert result is not None
    assert result.email_id == "EMAIL001"
    assert result.attachment_id == "ATT001"
    assert result.is_likely_po is True
    assert result.status == "NEW"


def test_insert_returns_none_on_duplicate(session):
    """Inserting the same (email_id, attachment_id) twice should return None."""
    msg = _make_message()
    first = insert_worklist_record(session, msg, is_likely_po=True)
    second = insert_worklist_record(session, msg, is_likely_po=True)
    assert first is not None
    assert second is None


def test_record_exists_true(session):
    msg = _make_message()
    insert_worklist_record(session, msg, is_likely_po=True)
    assert record_exists(session, "EMAIL001", "ATT001") is True


def test_record_exists_false(session):
    assert record_exists(session, "UNKNOWN", "ATT999") is False


def test_different_attachment_same_email_allowed(session):
    """Same email_id but different attachment_id should both be inserted."""
    msg1 = _make_message(email_id="EMAIL001", attachment_id="ATT001")
    msg2 = _make_message(email_id="EMAIL001", attachment_id="ATT002")
    r1 = insert_worklist_record(session, msg1, is_likely_po=True)
    r2 = insert_worklist_record(session, msg2, is_likely_po=True)
    assert r1 is not None
    assert r2 is not None

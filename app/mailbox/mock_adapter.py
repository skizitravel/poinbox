"""Mock mailbox adapter — reads sample emails from a local CSV file."""

import csv
import os
from typing import List

from app.mailbox.base import MailboxAdapter
from app.schemas import InboxMessage


class MockMailboxAdapter(MailboxAdapter):
    """Reads inbox messages from a CSV file to simulate a live mailbox."""

    def __init__(self, csv_path: str) -> None:
        self.csv_path = csv_path

    def fetch_messages(self) -> List[InboxMessage]:
        """Parse the CSV file and return a list of InboxMessage objects."""
        messages: List[InboxMessage] = []
        abs_path = os.path.abspath(self.csv_path)
        with open(abs_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                messages.append(
                    InboxMessage(
                        email_id=row["email_id"].strip(),
                        received_at=row["received_at"].strip(),
                        sender=row["sender"].strip(),
                        subject=row["subject"].strip(),
                        attachment_id=row["attachment_id"].strip(),
                        attachment_name=row["attachment_name"].strip(),
                        attachment_hash=row.get("attachment_hash", "").strip() or None,
                    )
                )
        return messages

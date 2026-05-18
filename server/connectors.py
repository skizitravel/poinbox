from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from email import policy
from email.parser import BytesParser
from pathlib import Path


@dataclass
class IncomingAttachment:
    filename: str
    content_type: str
    local_path: Path


@dataclass
class IncomingEmail:
    provider: str
    provider_message_id: str
    sender: str
    recipients: str
    subject: str
    received_at: str
    body_text: str
    attachments: list[IncomingAttachment] = field(default_factory=list)


class InboxConnector:
    def fetch_recent(self) -> list[IncomingEmail]:
        raise NotImplementedError


class SampleInboxConnector(InboxConnector):
    def __init__(self, sample_dir: Path, storage_dir: Path):
        self.sample_dir = sample_dir
        self.storage_dir = storage_dir

    def fetch_recent(self) -> list[IncomingEmail]:
        self.sample_dir.mkdir(parents=True, exist_ok=True)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        messages: list[IncomingEmail] = []
        for path in sorted(self.sample_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".txt", ".eml", ".pdf"}:
                continue
            if path.suffix.lower() == ".eml":
                messages.append(self._read_eml(path))
            elif path.suffix.lower() == ".pdf":
                messages.append(self._read_standalone_attachment(path, "application/pdf"))
            else:
                messages.append(self._read_text(path))
        return messages

    def _message_id(self, path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        return f"sample:{path.name}:{digest}"

    def _copy_attachment(self, path: Path) -> Path:
        target = self.storage_dir / path.name
        shutil.copy2(path, target)
        return target

    def _read_text(self, path: Path) -> IncomingEmail:
        text = path.read_text(encoding="utf-8")
        first_line = text.splitlines()[0] if text.splitlines() else path.stem
        return IncomingEmail(
            provider="sample",
            provider_message_id=self._message_id(path),
            sender="sample.customer@example.com",
            recipients="orders@example.com",
            subject=first_line[:140],
            received_at="2026-05-16T09:00:00",
            body_text=text,
        )

    def _read_standalone_attachment(self, path: Path, content_type: str) -> IncomingEmail:
        copied = self._copy_attachment(path)
        return IncomingEmail(
            provider="sample",
            provider_message_id=self._message_id(path),
            sender="sample.customer@example.com",
            recipients="orders@example.com",
            subject=f"Purchase order attachment {path.name}",
            received_at="2026-05-16T10:00:00",
            body_text=f"Please see attached purchase order {path.name}.",
            attachments=[IncomingAttachment(path.name, content_type, copied)],
        )

    def _read_eml(self, path: Path) -> IncomingEmail:
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body_parts: list[str] = []
        attachments: list[IncomingAttachment] = []
        for part in msg.walk():
            disposition = part.get_content_disposition()
            content_type = part.get_content_type()
            if disposition == "attachment":
                filename = part.get_filename() or "attachment.bin"
                target = self.storage_dir / filename
                target.write_bytes(part.get_payload(decode=True) or b"")
                attachments.append(IncomingAttachment(filename, content_type, target))
            elif content_type == "text/plain":
                body_parts.append(part.get_content())
        return IncomingEmail(
            provider="sample",
            provider_message_id=msg.get("Message-ID") or self._message_id(path),
            sender=msg.get("From", ""),
            recipients=msg.get("To", ""),
            subject=msg.get("Subject", path.stem),
            received_at=msg.get("Date", "2026-05-16T11:00:00"),
            body_text="\n\n".join(body_parts),
            attachments=attachments,
        )


class GmailInboxConnector(InboxConnector):
    """Gmail API connector placeholder.

    The app has the account schema and OAuth entry points now. This connector is
    intentionally narrow until a local Google OAuth client is configured and the
    token exchange can be tested against a real mailbox.
    """

    def fetch_recent(self) -> list[IncomingEmail]:
        raise NotImplementedError("Gmail manual sync requires a connected OAuth token.")


class OutlookInboxConnector(InboxConnector):
    def fetch_recent(self) -> list[IncomingEmail]:
        raise NotImplementedError("Outlook connector is planned after Gmail MVP testing.")


GmailConnector = GmailInboxConnector
OutlookConnector = OutlookInboxConnector

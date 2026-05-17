from __future__ import annotations

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from server.connectors import IncomingAttachment, IncomingEmail, SampleInboxConnector
from server.db import log
from server.extraction import classify_purchase_order, extract_purchase_order, normalize_date


def import_samples(conn: sqlite3.Connection, sample_dir: Path, storage_dir: Path) -> dict[str, Any]:
    connector = SampleInboxConnector(sample_dir, storage_dir)
    imported = 0
    skipped = 0
    created_pos = 0
    for incoming in connector.fetch_recent():
        existing = conn.execute(
            "SELECT id FROM emails WHERE provider_message_id = ?", (incoming.provider_message_id,)
        ).fetchone()
        if existing:
            skipped += 1
            continue
        email_id = insert_email(conn, incoming)
        attachment_rows = [insert_attachment(conn, email_id, att) for att in incoming.attachments]
        created_pos += process_email(conn, email_id, attachment_rows)
        imported += 1
    return {"imported": imported, "skipped": skipped, "purchase_orders": created_pos}


def insert_email(conn: sqlite3.Connection, incoming: IncomingEmail) -> int:
    cur = conn.execute(
        """
        INSERT INTO emails (provider, provider_message_id, sender, recipients, subject, received_at, body_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            incoming.provider,
            incoming.provider_message_id,
            incoming.sender,
            incoming.recipients,
            incoming.subject,
            incoming.received_at,
            incoming.body_text,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_attachment(conn: sqlite3.Connection, email_id: int, attachment: IncomingAttachment) -> dict[str, Any]:
    extracted_text = ""
    method = "unsupported"
    page_count = None
    if attachment.content_type == "application/pdf" or attachment.filename.lower().endswith(".pdf"):
        extracted_text, page_count = extract_pdf_text(attachment.local_path)
        method = "pdf_text" if extracted_text.strip() else "ocr_unavailable"
    elif attachment.filename.lower().endswith(".txt"):
        extracted_text = attachment.local_path.read_text(encoding="utf-8")
        method = "text"
    cur = conn.execute(
        """
        INSERT INTO attachments (email_id, filename, content_type, local_path, extracted_text, extraction_method, page_count)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id,
            attachment.filename,
            attachment.content_type,
            str(attachment.local_path),
            extracted_text,
            method,
            page_count,
        ),
    )
    conn.commit()
    if method == "ocr_unavailable":
        log(conn, "warning", "PDF had little or no embedded text; OCR is not configured.", email_id, int(cur.lastrowid))
    return {
        "id": int(cur.lastrowid),
        "filename": attachment.filename,
        "extracted_text": extracted_text,
        "extraction_method": method,
    }


def extract_pdf_text(path: Path) -> tuple[str, int | None]:
    try:
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return text, len(reader.pages)
    except Exception:
        return "", None


def process_email(conn: sqlite3.Connection, email_id: int, attachments: list[dict[str, Any]]) -> int:
    email = conn.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
    email_dict = dict(email)
    attachment_text = "\n\n".join(att.get("extracted_text") or "" for att in attachments)
    filenames = [att["filename"] for att in attachments]
    classification = classify_purchase_order(
        email_dict.get("subject") or "",
        email_dict.get("body_text") or "",
        attachment_text,
        filenames,
    )
    conn.execute(
        """
        UPDATE emails
        SET classification = ?, classification_confidence = ?, classification_explanation = ?, processed_at = ?
        WHERE id = ?
        """,
        (
            classification.label,
            classification.confidence,
            classification.explanation,
            datetime.utcnow().isoformat(),
            email_id,
        ),
    )
    conn.commit()
    if classification.label not in {"possible_po", "purchase_order"}:
        log(conn, "info", "Email was not classified as a purchase order.", email_id)
        return 0

    source_text = attachment_text.strip() or email_dict.get("body_text") or ""
    source_attachment = attachments[0] if attachments else None
    extraction = extract_purchase_order(source_text, email_dict, source_attachment["filename"] if source_attachment else None)
    apply_cross_references(conn, extraction)
    po_id = insert_purchase_order(conn, email_id, source_attachment["id"] if source_attachment else None, extraction)
    for line in extraction.get("lines", []):
        insert_po_line(conn, po_id, extraction.get("po_number"), line)
    recalculate_po_total(conn, po_id, extracted_total=extraction.get("total_value"))
    log(conn, "info", "Purchase order created for review.", email_id, source_attachment["id"] if source_attachment else None, {"po_id": po_id})
    return 1


def insert_purchase_order(conn: sqlite3.Connection, email_id: int, attachment_id: int | None, data: dict[str, Any]) -> int:
    order_type_id = default_order_type_id(conn)
    cur = conn.execute(
        """
        INSERT INTO purchase_orders (
            email_id, attachment_id, status, customer_company_name, customer_contact_name, bill_to_address,
            ship_to_address, po_number, date_received, request_date, total_value, currency, source_sender,
            source_subject, source_attachment_filename, extraction_confidence, extraction_notes, order_type_id,
            field_confidence_json, quote_number, payment_terms, freight_terms
        )
        VALUES (?, ?, 'Received', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id,
            attachment_id,
            data.get("customer_company_name"),
            data.get("customer_contact_name"),
            data.get("bill_to_address"),
            data.get("ship_to_address"),
            data.get("po_number"),
            normalize_date(data.get("date_received")),
            normalize_date(data.get("request_date")),
            data.get("total_value"),
            data.get("currency"),
            data.get("source_sender"),
            data.get("source_subject"),
            data.get("source_attachment_filename"),
            data.get("extraction_confidence"),
            data.get("extraction_notes"),
            order_type_id,
            json.dumps(data.get("field_confidence") or {}),
            data.get("quote_number"),
            data.get("payment_terms"),
            data.get("freight_terms"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def insert_po_line(conn: sqlite3.Connection, purchase_order_id: int, po_number: str | None, line: dict[str, Any]) -> int:
    line_total = normalized_line_total(line.get("quantity"), line.get("unit_price"), line.get("line_total"))
    cur = conn.execute(
        """
        INSERT INTO purchase_order_lines (
            purchase_order_id, po_number, line_number, customer_part_number, internal_part_number, description,
            quantity, unit_of_measure, unit_price, line_total, requested_date, extraction_confidence, extraction_notes,
            field_confidence_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            purchase_order_id,
            line.get("po_number") or po_number,
            line.get("line_number"),
            line.get("customer_part_number"),
            line.get("internal_part_number"),
            line.get("description"),
            line.get("quantity"),
            line.get("unit_of_measure"),
            line.get("unit_price"),
            line_total,
            line.get("requested_date"),
            line.get("extraction_confidence"),
            line.get("extraction_notes"),
            json.dumps(line.get("field_confidence") or {}),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def default_order_type_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT id FROM order_types WHERE name = 'Standard' AND is_active = 1").fetchone()
    return row["id"] if row else None


def normalized_line_total(quantity: Any, unit_price: Any, line_total: Any) -> float | None:
    if quantity not in (None, "") and unit_price not in (None, ""):
        return round(float(quantity) * float(unit_price), 2)
    return None if line_total in (None, "") else float(line_total)


def recalculate_po_total(conn: sqlite3.Connection, po_id: int, extracted_total: float | None = None) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(line_total, quantity * unit_price)), 0) AS total FROM purchase_order_lines WHERE purchase_order_id = ?",
        (po_id,),
    ).fetchone()
    total = round(float(row["total"] or 0), 2)
    po = conn.execute("SELECT extraction_notes FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    notes = po["extraction_notes"] or ""
    if extracted_total not in (None, "") and abs(float(extracted_total) - total) > 0.01:
        warning = f" Header total {extracted_total} differed from calculated line total {total}; review."
        if warning not in notes:
            notes = (notes + warning).strip()
    conn.execute(
        "UPDATE purchase_orders SET total_value = ?, extraction_notes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (total, notes, po_id),
    )
    conn.commit()
    return total


def apply_cross_references(conn: sqlite3.Connection, extraction: dict[str, Any]) -> None:
    customer = (extraction.get("customer_company_name") or "").strip().lower()
    if not customer:
        return
    for line in extraction.get("lines", []):
        if line.get("internal_part_number"):
            continue
        customer_part = (line.get("customer_part_number") or "").strip().lower()
        if not customer_part:
            continue
        row = conn.execute(
            """
            SELECT internal_part_number
            FROM customer_part_xrefs
            WHERE LOWER(TRIM(customer_name)) = ? AND LOWER(TRIM(customer_part_number)) = ?
            """,
            (customer, customer_part),
        ).fetchone()
        if not row:
            continue
        line["internal_part_number"] = row["internal_part_number"]
        notes = line.get("extraction_notes") or ""
        line["extraction_notes"] = (notes + " Matched from customer part cross reference.").strip()
        confidence = line.setdefault("field_confidence", {})
        confidence["internal_part_number"] = 0.95

from __future__ import annotations

import sqlite3
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from server.connectors import IncomingAttachment, IncomingEmail, SampleInboxConnector
from server.db import log
from server.extraction import classify_purchase_order, extract_purchase_order, normalize_date
from server.master_data import parse_structured_address, run_master_data_reviews


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


def extract_pdf_with_vision_or_ocr(path: Path) -> tuple[str, str]:
    return "", "OCR/vision extraction is not configured for this MVP."


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
    prior_examples = find_similar_extraction_examples(conn, None, source_text)
    started = time.perf_counter()
    extraction = extract_purchase_order(
        source_text,
        email_dict,
        source_attachment["filename"] if source_attachment else None,
        None,
        prior_examples,
    )
    extraction_run_id = log_document_extraction_run(
        conn,
        email_id=email_id,
        attachment_id=source_attachment["id"] if source_attachment else None,
        raw_input_text=source_text,
        extraction=extraction,
        latency_ms=elapsed_ms(started),
        success=True,
    )
    apply_cross_references(conn, extraction)
    duplicate = find_duplicate_purchase_order(conn, extraction)
    if duplicate:
        log(
            conn,
            "warning",
            "Duplicate purchase order skipped.",
            email_id,
            source_attachment["id"] if source_attachment else None,
            {
                "existing_purchase_order_id": duplicate["id"],
                "po_number": extraction.get("po_number"),
                "po_revision": extraction.get("po_revision"),
            },
        )
        return 0
    po_id = insert_purchase_order(conn, email_id, source_attachment["id"] if source_attachment else None, extraction)
    link_extraction_run(conn, extraction_run_id, po_id)
    for line in extraction.get("lines", []):
        insert_po_line(conn, po_id, extraction.get("po_number"), line)
    recalculate_po_total(conn, po_id, extracted_total=extraction.get("total_value"))
    run_master_data_reviews(conn, po_id)
    log(conn, "info", "Purchase order created for review.", email_id, source_attachment["id"] if source_attachment else None, {"po_id": po_id})
    return 1


def log_document_extraction_run(
    conn: sqlite3.Connection,
    *,
    email_id: int | None = None,
    attachment_id: int | None = None,
    purchase_order_id: int | None = None,
    test_document_id: int | None = None,
    raw_input_text: str = "",
    extraction: dict[str, Any] | None = None,
    latency_ms: int | None = None,
    success: bool = True,
    error_message: str | None = None,
) -> int:
    extraction = extraction or {}
    parsed = {key: value for key, value in extraction.items() if not key.startswith("_")}
    cur = conn.execute(
        """
        INSERT INTO document_extraction_runs (
            email_id, attachment_id, purchase_order_id, test_document_id, extraction_method,
            model_name, prompt_version, raw_input_text, raw_output_json, parsed_output_json,
            success, error_message, latency_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id,
            attachment_id,
            purchase_order_id,
            test_document_id,
            extraction.get("_extraction_method") or "rule_based",
            extraction.get("_model_name"),
            extraction.get("_prompt_version"),
            raw_input_text,
            extraction.get("_raw_output_json"),
            json.dumps(parsed),
            1 if success else 0,
            error_message or extraction.get("_error_message"),
            latency_ms,
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def link_extraction_run(conn: sqlite3.Connection, run_id: int | None, po_id: int) -> None:
    if not run_id:
        return
    conn.execute("UPDATE document_extraction_runs SET purchase_order_id = ? WHERE id = ?", (po_id, run_id))
    conn.commit()


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def insert_purchase_order(conn: sqlite3.Connection, email_id: int, attachment_id: int | None, data: dict[str, Any]) -> int:
    order_type_id = default_order_type_id(conn)
    source_type = source_type_for_email(conn, email_id)
    bill_to_structured = parse_structured_address(data.get("bill_to_address"))
    ship_to_structured = parse_structured_address(data.get("ship_to_address"))
    cur = conn.execute(
        """
        INSERT INTO purchase_orders (
            email_id, attachment_id, status, customer_company_name, customer_contact_name, bill_to_address,
            ship_to_address, bill_to_address_structured_json, ship_to_address_structured_json,
            po_number, po_revision, date_received, request_date, total_value, currency, source_type, source_sender,
            source_subject, source_attachment_filename, extraction_confidence, extraction_notes, order_type_id,
            field_confidence_json, quote_number, payment_terms, freight_terms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            email_id,
            attachment_id,
            "Received",
            data.get("customer_company_name"),
            data.get("customer_contact_name"),
            data.get("bill_to_address"),
            data.get("ship_to_address"),
            json.dumps(bill_to_structured),
            json.dumps(ship_to_structured),
            data.get("po_number"),
            data.get("po_revision"),
            normalize_date(data.get("date_received")),
            normalize_date(data.get("request_date")),
            data.get("total_value"),
            data.get("currency"),
            source_type,
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


def source_type_for_email(conn: sqlite3.Connection, email_id: int) -> str:
    row = conn.execute("SELECT provider FROM emails WHERE id = ?", (email_id,)).fetchone()
    provider = (row["provider"] if row else "") or ""
    if provider in {"gmail", "outlook"}:
        return "email"
    if provider == "sample":
        return "sample_import"
    return "manual" if provider == "manual" else "unknown"


def find_duplicate_purchase_order(conn: sqlite3.Connection, data: dict[str, Any]) -> sqlite3.Row | None:
    po_number = (data.get("po_number") or "").strip()
    if not po_number:
        return None
    revision = (data.get("po_revision") or "").strip()
    customer = (data.get("customer_company_name") or "").strip()
    rows = conn.execute(
        """
        SELECT id, customer_company_name, po_number, po_revision
        FROM purchase_orders
        WHERE LOWER(TRIM(po_number)) = LOWER(TRIM(?))
          AND COALESCE(NULLIF(TRIM(po_revision), ''), '') = COALESCE(NULLIF(TRIM(?), ''), '')
        ORDER BY id
        """,
        (po_number, revision),
    ).fetchall()
    if not rows:
        return None
    if customer:
        customer_key = customer.lower()
        for row in rows:
            existing_customer = (row["customer_company_name"] or "").strip().lower()
            if not existing_customer or existing_customer == customer_key:
                return row
        return None
    return rows[0]


def find_similar_extraction_examples(
    conn: sqlite3.Connection,
    customer_company_name: str | None,
    source_text: str | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    customer = (customer_company_name or "").strip().lower()
    rows = conn.execute(
        """
        SELECT po.id, po.customer_company_name, po.po_number, po.source_attachment_filename,
               po.extraction_notes, po.updated_at
        FROM purchase_orders po
        WHERE po.extraction_feedback_count > 0 OR po.extraction_reviewed_at IS NOT NULL
        ORDER BY
            CASE WHEN LOWER(TRIM(COALESCE(po.customer_company_name, ''))) = ? THEN 0 ELSE 1 END,
            po.updated_at DESC
        LIMIT ?
        """,
        (customer, limit),
    ).fetchall()
    examples = []
    for row in rows:
        feedback = conn.execute(
            """
            SELECT entity_type, field_name, extracted_value, corrected_value, confidence
            FROM extraction_feedback
            WHERE purchase_order_id = ?
            ORDER BY created_at DESC LIMIT 20
            """,
            (row["id"],),
        ).fetchall()
        header = conn.execute(
            """
            SELECT customer_company_name, customer_contact_name, bill_to_address, ship_to_address,
                   po_number, po_revision, quote_number, payment_terms, freight_terms, total_value, currency
            FROM purchase_orders WHERE id = ?
            """,
            (row["id"],),
        ).fetchone()
        lines = conn.execute(
            """
            SELECT line_number, customer_part_number, internal_part_number, description, quantity,
                   unit_of_measure, unit_price, line_total, requested_date
            FROM purchase_order_lines WHERE purchase_order_id = ? ORDER BY id LIMIT 5
            """,
            (row["id"],),
        ).fetchall()
        examples.append(
            {
                "customer_company_name": row["customer_company_name"],
                "source_attachment_filename": row["source_attachment_filename"],
                "corrected_header_fields": dict(header) if header else {},
                "corrected_line_examples": [dict(line) for line in lines],
                "feedback_rows": [dict(item) for item in feedback],
                "extraction_notes": row["extraction_notes"],
            }
        )
    return examples


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

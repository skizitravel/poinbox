from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


def normalize_match_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def format_structured_address(row: sqlite3.Row | dict | None) -> str:
    if not row:
        return ""
    getter = row.get if isinstance(row, dict) else lambda key, default=None: row[key] if key in row.keys() else default
    line_parts = [
        getter("address_line_1") or "",
        getter("address_line_2") or "",
        getter("address_line_3") or "",
    ]
    locality = " ".join(part for part in [getter("city") or "", getter("state") or "", getter("zip_code") or ""] if part).strip()
    if locality:
        line_parts.append(locality)
    if getter("country"):
        line_parts.append(getter("country"))
    structured = "\n".join(part.strip() for part in line_parts if part and part.strip())
    return structured or (getter("address_text") or "")


def parse_structured_address(address_text: str | None) -> dict[str, str]:
    """Best-effort parser for extracted PO address blocks.

    The goal is to prefill master-data forms, not to make claims. Ambiguous
    pieces stay blank and the original text remains stored on the PO.
    """
    lines = [line.strip(" ,") for line in str(address_text or "").splitlines() if line.strip(" ,")]
    result = {
        "address_line_1": "",
        "address_line_2": "",
        "address_line_3": "",
        "city": "",
        "state": "",
        "country": "",
        "zip_code": "",
    }
    if not lines:
        return result

    locality_index = None
    locality_pattern = re.compile(r"^(.+?),\s*([A-Z]{2,3})\s+([A-Z0-9][A-Z0-9 -]{2,10})$", re.IGNORECASE)
    for index in range(len(lines) - 1, -1, -1):
        match = locality_pattern.match(lines[index])
        if match:
            result["city"] = match.group(1).strip()
            result["state"] = match.group(2).strip()
            result["zip_code"] = match.group(3).strip()
            locality_index = index
            break

    address_lines = lines[:locality_index] if locality_index is not None else lines[:3]
    trailing = lines[locality_index + 1 :] if locality_index is not None else []
    if trailing:
        result["country"] = trailing[0]
    for key, value in zip(["address_line_1", "address_line_2", "address_line_3"], address_lines[:3]):
        result[key] = value
    return result


def find_matching_customer(conn: sqlite3.Connection, customer_name: str | None) -> sqlite3.Row | None:
    needle = normalize_match_text(customer_name)
    if not needle:
        return None
    for row in conn.execute("SELECT * FROM customers").fetchall():
        if normalize_match_text(row["customer_name"]) == needle:
            return row
    return None


def find_matching_address(
    conn: sqlite3.Connection, customer_id: int | None, address_type: str, extracted_address: str | None
) -> sqlite3.Row | None:
    needle = normalize_match_text(extracted_address)
    if not customer_id or not needle:
        return None
    rows = conn.execute(
        "SELECT * FROM customer_addresses WHERE customer_id = ? AND address_type = ?",
        (customer_id, address_type),
    ).fetchall()
    for row in rows:
        formatted = format_structured_address(row)
        if normalize_match_text(formatted) == needle or normalize_match_text(row["address_text"]) == needle:
            return row
    return None


def find_matching_contact(conn: sqlite3.Connection, customer_id: int | None, contact_name: str | None) -> sqlite3.Row | None:
    needle = normalize_match_text(contact_name)
    if not customer_id or not needle:
        return None
    rows = conn.execute("SELECT * FROM customer_contacts WHERE customer_id = ?", (customer_id,)).fetchall()
    for row in rows:
        full_name = " ".join(part for part in [row["first_name"], row["last_name"]] if part).strip()
        if normalize_match_text(full_name) == needle:
            return row
    return None


def run_master_data_reviews(conn: sqlite3.Connection, po_id: int) -> list[dict[str, Any]]:
    po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not po:
        return []

    customer = find_matching_customer(conn, po["customer_company_name"])
    if customer:
        resolve_open_review(conn, po_id, "customer", customer["id"], customer["id"])
    elif po["customer_company_name"]:
        create_open_review(
            conn,
            po_id,
            "customer",
            f"Customer '{po['customer_company_name']}' was not found in master data.",
            {"customer_name": po["customer_company_name"], "payment_terms": po["payment_terms"] or ""},
        )

    customer_id = customer["id"] if customer else None
    for review_type, address_type, field, label in [
        ("bill_to_address", "bill_to", "bill_to_address", "Bill-to address"),
        ("ship_to_address", "ship_to", "ship_to_address", "Ship-to address"),
    ]:
        value = po[field]
        if not value:
            continue
        structured_column = f"{field}_structured_json"
        structured = {}
        if structured_column in po.keys() and po[structured_column]:
            try:
                structured = json.loads(po[structured_column])
            except json.JSONDecodeError:
                structured = {}
        match = find_matching_address(conn, customer_id, address_type, value)
        if match:
            resolve_open_review(conn, po_id, review_type, customer_id, match["id"])
        else:
            create_open_review(
                conn,
                po_id,
                review_type,
                f"{label} was not found for the matched customer.",
                {"address_type": address_type, "address_text": value, **structured},
                customer_id,
            )

    contact_name = po["customer_contact_name"]
    if contact_name:
        match = find_matching_contact(conn, customer_id, contact_name)
        if match:
            resolve_open_review(conn, po_id, "contact", customer_id, match["id"])
        else:
            create_open_review(
                conn,
                po_id,
                "contact",
                f"Contact '{contact_name}' was not found for the matched customer.",
                split_contact_name(contact_name),
                customer_id,
            )

    conn.commit()
    return list_reviews(conn, po_id)


def create_open_review(
    conn: sqlite3.Connection,
    po_id: int,
    review_type: str,
    message: str,
    suggested_value: dict[str, Any],
    matched_customer_id: int | None = None,
) -> None:
    existing = conn.execute(
        """
        SELECT id FROM po_master_data_reviews
        WHERE purchase_order_id = ? AND review_type = ? AND status = 'open'
        """,
        (po_id, review_type),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE po_master_data_reviews
            SET message = ?, suggested_value_json = ?, matched_customer_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (message, json.dumps(suggested_value), matched_customer_id, existing["id"]),
        )
        return
    conn.execute(
        """
        INSERT INTO po_master_data_reviews (
            purchase_order_id, review_type, status, message, suggested_value_json, matched_customer_id
        )
        VALUES (?, ?, 'open', ?, ?, ?)
        """,
        (po_id, review_type, message, json.dumps(suggested_value), matched_customer_id),
    )


def resolve_open_review(
    conn: sqlite3.Connection,
    po_id: int,
    review_type: str,
    matched_customer_id: int | None = None,
    matched_record_id: int | None = None,
) -> None:
    conn.execute(
        """
        UPDATE po_master_data_reviews
        SET status = 'resolved', matched_customer_id = COALESCE(?, matched_customer_id),
            matched_record_id = COALESCE(?, matched_record_id), updated_at = CURRENT_TIMESTAMP
        WHERE purchase_order_id = ? AND review_type = ? AND status = 'open'
        """,
        (matched_customer_id, matched_record_id, po_id, review_type),
    )


def resolve_review(conn: sqlite3.Connection, review_id: int, matched_customer_id: int | None = None, matched_record_id: int | None = None) -> None:
    conn.execute(
        """
        UPDATE po_master_data_reviews
        SET status = 'resolved', matched_customer_id = COALESCE(?, matched_customer_id),
            matched_record_id = COALESCE(?, matched_record_id), updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (matched_customer_id, matched_record_id, review_id),
    )
    conn.commit()


def list_reviews(conn: sqlite3.Connection, po_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM po_master_data_reviews
        WHERE purchase_order_id = ?
        ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'resolved' THEN 1 ELSE 2 END, id
        """,
        (po_id,),
    ).fetchall()
    reviews: list[dict[str, Any]] = []
    for row in rows:
        item = {key: row[key] for key in row.keys()}
        try:
            item["suggested_value"] = json.loads(item.get("suggested_value_json") or "{}")
        except json.JSONDecodeError:
            item["suggested_value"] = {}
        reviews.append(item)
    return reviews


def split_contact_name(name: str) -> dict[str, str]:
    parts = name.strip().split()
    if not parts:
        return {"first_name": "", "last_name": ""}
    if len(parts) == 1:
        return {"first_name": parts[0], "last_name": ""}
    return {"first_name": parts[0], "last_name": " ".join(parts[1:])}

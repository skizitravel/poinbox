from __future__ import annotations

import json
import re
import sqlite3
from typing import Any


def normalize_match_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def normalize_address_for_match(value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, dict):
        text = format_structured_address(value)
    elif isinstance(value, sqlite3.Row):
        text = format_structured_address(value)
    else:
        text = str(value or "")
    text = text.replace(",", " ")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
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


def address_match_values(value: Any) -> set[str]:
    values: set[str] = set()
    if not value:
        return values
    values.add(normalize_address_for_match(value))
    if isinstance(value, str):
        parsed = parse_structured_address(value)
        values.add(normalize_address_for_match(parsed))
    elif isinstance(value, dict):
        values.add(normalize_address_for_match(value.get("address_text")))
    elif isinstance(value, sqlite3.Row):
        values.add(normalize_address_for_match(value["address_text"] if "address_text" in value.keys() else ""))
    return {item for item in values if item}


def addresses_match(extracted_address: Any, customer_address: Any) -> bool:
    extracted_values = address_match_values(extracted_address)
    customer_values = address_match_values(customer_address)
    if not extracted_values or not customer_values:
        return False
    return bool(extracted_values & customer_values)


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
    canonical = conn.execute(
        """
        SELECT legacy_source_id
        FROM trading_partner_account
        WHERE legacy_source_table = 'customers'
          AND LOWER(TRIM(account_name)) = LOWER(TRIM(?))
        LIMIT 1
        """,
        (customer_name,),
    ).fetchone()
    if canonical:
        return conn.execute("SELECT * FROM customers WHERE id = ?", (canonical["legacy_source_id"],)).fetchone()
    return None


def find_matching_address(
    conn: sqlite3.Connection, customer_id: int | None, address_type: str, extracted_address: Any
) -> sqlite3.Row | None:
    if not customer_id or not address_match_values(extracted_address):
        return None
    rows = conn.execute(
        "SELECT * FROM customer_addresses WHERE customer_id = ? AND address_type = ?",
        (customer_id, address_type),
    ).fetchall()
    for row in rows:
        if addresses_match(extracted_address, row):
            return row
    role_code = "BILL_TO" if address_type == "bill_to" else "SHIP_TO" if address_type == "ship_to" else "SOLD_TO"
    canonical_rows = conn.execute(
        """
        SELECT ca.*
        FROM partner_role_assignment pra
        JOIN trading_partner_account tpa ON tpa.id = pra.trading_partner_account_id
        JOIN trading_partner_site tps ON tps.id = pra.trading_partner_site_id
        JOIN customer_addresses ca
          ON ca.id = CAST(tps.legacy_source_id AS INTEGER)
         AND tps.legacy_source_table = 'customer_addresses'
        WHERE tpa.legacy_source_table = 'customers'
          AND tpa.legacy_source_id = ?
          AND pra.role_code = ?
          AND pra.active_flag = 1
        ORDER BY pra.primary_flag DESC, pra.id
        """,
        (str(customer_id), role_code),
    ).fetchall()
    for row in canonical_rows:
        if addresses_match(extracted_address, row):
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
        match = find_matching_address(conn, customer_id, address_type, structured or value)
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
    resolved = conn.execute(
        """
        SELECT suggested_value_json FROM po_master_data_reviews
        WHERE purchase_order_id = ? AND review_type = ? AND status = 'resolved'
        ORDER BY updated_at DESC, id DESC LIMIT 1
        """,
        (po_id, review_type),
    ).fetchone()
    if resolved:
        try:
            previous_value = json.loads(resolved["suggested_value_json"] or "{}")
        except json.JSONDecodeError:
            previous_value = {}
        if review_type in {"bill_to_address", "ship_to_address"} and addresses_match(suggested_value, previous_value):
            return
        if review_type not in {"bill_to_address", "ship_to_address"} and normalize_match_text(suggested_value) == normalize_match_text(previous_value):
            return
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

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            provider_message_id TEXT NOT NULL UNIQUE,
            sender TEXT,
            recipients TEXT,
            subject TEXT,
            received_at TEXT,
            body_text TEXT,
            classification TEXT DEFAULT 'not_po',
            classification_confidence REAL DEFAULT 0,
            classification_explanation TEXT,
            processed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            filename TEXT NOT NULL,
            content_type TEXT,
            local_path TEXT,
            extracted_text TEXT,
            extraction_method TEXT,
            page_count INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
            attachment_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'Received',
            customer_company_name TEXT,
            customer_contact_name TEXT,
            bill_to_address TEXT,
            ship_to_address TEXT,
            po_number TEXT,
            date_received TEXT,
            request_date TEXT,
            total_value REAL,
            currency TEXT,
            source_sender TEXT,
            source_subject TEXT,
            source_attachment_filename TEXT,
            extraction_confidence REAL DEFAULT 0,
            extraction_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS purchase_order_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            po_number TEXT,
            line_number TEXT,
            customer_part_number TEXT,
            internal_part_number TEXT,
            description TEXT,
            quantity REAL,
            unit_of_measure TEXT,
            unit_price REAL,
            line_total REAL,
            requested_date TEXT,
            extraction_confidence REAL DEFAULT 0,
            extraction_notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS processing_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
            attachment_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_part_xrefs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_part_number TEXT NOT NULL,
            internal_part_number TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(customer_name, customer_part_number)
        );

        CREATE TABLE IF NOT EXISTS order_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    ensure_column(conn, "purchase_orders", "order_type_id", "INTEGER REFERENCES order_types(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "field_confidence_json", "TEXT")
    ensure_column(conn, "purchase_orders", "quote_number", "TEXT")
    ensure_column(conn, "purchase_orders", "payment_terms", "TEXT")
    ensure_column(conn, "purchase_orders", "freight_terms", "TEXT")
    ensure_column(conn, "purchase_order_lines", "field_confidence_json", "TEXT")
    seed_order_types(conn)
    standard = conn.execute("SELECT id FROM order_types WHERE name = 'Standard'").fetchone()
    if standard:
        conn.execute("UPDATE purchase_orders SET order_type_id = ? WHERE order_type_id IS NULL", (standard["id"],))
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_order_types(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM order_types").fetchone()["count"]
    if count:
        return
    for name in ("Standard", "Expedite", "Blanket", "Sample", "Drop Ship"):
        conn.execute("INSERT INTO order_types (name, is_active) VALUES (?, 1)", (name,))


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows if row is not None]


def log(
    conn: sqlite3.Connection,
    level: str,
    message: str,
    email_id: int | None = None,
    attachment_id: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO processing_logs (email_id, attachment_id, level, message, metadata_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (email_id, attachment_id, level, message, json.dumps(metadata or {})),
    )
    conn.commit()

from __future__ import annotations

import json
import sqlite3
import os
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
            bill_to_address_structured_json TEXT,
            ship_to_address_structured_json TEXT,
            po_number TEXT,
            po_revision TEXT,
            date_received TEXT,
            request_date TEXT,
            total_value REAL,
            currency TEXT,
            source_type TEXT,
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

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            job_title TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            can_access_admin INTEGER NOT NULL DEFAULT 0,
            can_access_po_dashboard INTEGER NOT NULL DEFAULT 1,
            po_dashboard_access_level TEXT NOT NULL DEFAULT 'view_only',
            invited_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            customer_number TEXT,
            payment_terms TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            address_type TEXT NOT NULL,
            label TEXT,
            address_text TEXT,
            address_line_1 TEXT,
            address_line_2 TEXT,
            address_line_3 TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            zip_code TEXT,
            is_default INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            first_name TEXT,
            last_name TEXT,
            job_title TEXT,
            phone_number TEXT,
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS po_master_data_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            review_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            message TEXT NOT NULL,
            suggested_value_json TEXT,
            matched_customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            matched_record_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS test_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_filename TEXT NOT NULL,
            local_path TEXT NOT NULL,
            content_type TEXT,
            document_type TEXT DEFAULT 'other',
            expected_classification TEXT DEFAULT 'not_po',
            notes TEXT,
            source TEXT DEFAULT 'upload',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS golden_po_headers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_document_id INTEGER NOT NULL UNIQUE REFERENCES test_documents(id) ON DELETE CASCADE,
            expected_is_po INTEGER NOT NULL DEFAULT 1,
            customer_company_name TEXT,
            customer_contact_name TEXT,
            bill_to_address TEXT,
            ship_to_address TEXT,
            po_number TEXT,
            quote_number TEXT,
            date_received TEXT,
            payment_terms TEXT,
            freight_terms TEXT,
            total_value REAL,
            currency TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS golden_po_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            golden_po_header_id INTEGER NOT NULL REFERENCES golden_po_headers(id) ON DELETE CASCADE,
            line_number TEXT,
            customer_part_number TEXT,
            internal_part_number TEXT,
            description TEXT,
            quantity REAL,
            unit_of_measure TEXT,
            unit_price REAL,
            line_total REAL,
            requested_date TEXT,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS extraction_evaluation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_name TEXT,
            extraction_mode TEXT DEFAULT 'rule_based',
            started_at TEXT,
            finished_at TEXT,
            document_count INTEGER DEFAULT 0,
            true_positives INTEGER DEFAULT 0,
            false_positives INTEGER DEFAULT 0,
            true_negatives INTEGER DEFAULT 0,
            false_negatives INTEGER DEFAULT 0,
            field_match_rate REAL DEFAULT 0,
            line_match_rate REAL DEFAULT 0,
            average_confidence REAL DEFAULT 0,
            notes TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS extraction_evaluation_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL REFERENCES extraction_evaluation_runs(id) ON DELETE CASCADE,
            test_document_id INTEGER NOT NULL REFERENCES test_documents(id) ON DELETE CASCADE,
            detected_classification TEXT,
            expected_classification TEXT,
            detection_correct INTEGER,
            extraction_purchase_order_id INTEGER,
            field_results_json TEXT,
            line_results_json TEXT,
            missed_fields_json TEXT,
            hallucinated_fields_json TEXT,
            confidence_json TEXT,
            processing_latency_ms INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS document_extraction_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
            attachment_id INTEGER REFERENCES attachments(id) ON DELETE SET NULL,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
            test_document_id INTEGER REFERENCES test_documents(id) ON DELETE SET NULL,
            extraction_method TEXT,
            model_name TEXT,
            prompt_version TEXT,
            raw_input_text TEXT,
            raw_output_json TEXT,
            parsed_output_json TEXT,
            success INTEGER DEFAULT 1,
            error_message TEXT,
            latency_ms INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS extraction_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            extracted_value TEXT,
            corrected_value TEXT,
            confidence REAL,
            source_text_snippet TEXT,
            customer_company_name TEXT,
            source_attachment_filename TEXT,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inbox_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            display_name TEXT,
            connected_email TEXT,
            monitored_email TEXT,
            folder TEXT DEFAULT 'INBOX',
            sync_status TEXT DEFAULT 'not_connected',
            last_sync_at TEXT,
            delta_token TEXT,
            history_id TEXT,
            access_token TEXT,
            refresh_token TEXT,
            token_expires_at TEXT,
            granted_scopes TEXT,
            evaluate_without_attachments INTEGER NOT NULL DEFAULT 0,
            sync_interval_hours INTEGER DEFAULT 24,
            sync_start_time TEXT DEFAULT '02:00',
            next_sync_at TEXT,
            is_enabled INTEGER NOT NULL DEFAULT 1,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inbox_labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inbox_account_id INTEGER NOT NULL REFERENCES inbox_accounts(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            label_id TEXT NOT NULL,
            label_name TEXT,
            label_type TEXT,
            is_selected INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(inbox_account_id, label_id)
        );

        CREATE TABLE IF NOT EXISTS inbox_sync_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inbox_account_id INTEGER NOT NULL REFERENCES inbox_accounts(id) ON DELETE CASCADE,
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            messages_seen INTEGER DEFAULT 0,
            messages_imported INTEGER DEFAULT 0,
            messages_skipped INTEGER DEFAULT 0,
            purchase_orders_created INTEGER DEFAULT 0,
            errors_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inbox_detection_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inbox_sync_run_id INTEGER REFERENCES inbox_sync_runs(id) ON DELETE CASCADE,
            email_id INTEGER REFERENCES emails(id) ON DELETE SET NULL,
            provider_message_id TEXT,
            expected_classification TEXT,
            detected_classification TEXT,
            detection_confidence REAL,
            detection_correct INTEGER,
            had_attachments INTEGER DEFAULT 0,
            attachment_count INTEGER DEFAULT 0,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
            processing_latency_ms INTEGER,
            duplicate_skipped INTEGER DEFAULT 0,
            error_message TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            is_sensitive INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS oauth_states (
            state TEXT PRIMARY KEY,
            provider TEXT NOT NULL,
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            inbox_account_id INTEGER REFERENCES inbox_accounts(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    ensure_column(conn, "purchase_orders", "order_type_id", "INTEGER REFERENCES order_types(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "field_confidence_json", "TEXT")
    ensure_column(conn, "purchase_orders", "quote_number", "TEXT")
    ensure_column(conn, "purchase_orders", "payment_terms", "TEXT")
    ensure_column(conn, "purchase_orders", "freight_terms", "TEXT")
    ensure_column(conn, "purchase_orders", "po_revision", "TEXT")
    ensure_column(conn, "purchase_orders", "bill_to_address_structured_json", "TEXT")
    ensure_column(conn, "purchase_orders", "ship_to_address_structured_json", "TEXT")
    ensure_column(conn, "purchase_orders", "source_type", "TEXT")
    ensure_column(conn, "purchase_orders", "extraction_reviewed_at", "TEXT")
    ensure_column(conn, "purchase_orders", "extraction_reviewed_by_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "extraction_feedback_count", "INTEGER DEFAULT 0")
    ensure_column(conn, "purchase_order_lines", "field_confidence_json", "TEXT")
    ensure_column(conn, "extraction_evaluation_runs", "extraction_mode", "TEXT DEFAULT 'rule_based'")
    ensure_column(conn, "users", "first_name", "TEXT")
    ensure_column(conn, "users", "last_name", "TEXT")
    ensure_column(conn, "users", "job_title", "TEXT")
    ensure_column(conn, "inbox_accounts", "access_token", "TEXT")
    ensure_column(conn, "inbox_accounts", "refresh_token", "TEXT")
    ensure_column(conn, "inbox_accounts", "token_expires_at", "TEXT")
    ensure_column(conn, "inbox_accounts", "granted_scopes", "TEXT")
    ensure_column(conn, "inbox_accounts", "is_enabled", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "inbox_accounts", "evaluate_without_attachments", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "inbox_accounts", "sync_interval_hours", "INTEGER DEFAULT 24")
    ensure_column(conn, "inbox_accounts", "sync_start_time", "TEXT DEFAULT '02:00'")
    ensure_column(conn, "inbox_accounts", "next_sync_at", "TEXT")
    for column in ("address_line_1", "address_line_2", "address_line_3", "city", "state", "country", "zip_code"):
        ensure_column(conn, "customer_addresses", column, "TEXT")
    backfill_user_profile_names(conn)
    seed_order_types(conn)
    seed_departments(conn)
    seed_initial_admin(conn)
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


def seed_departments(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM departments").fetchone()["count"]
    if count:
        return
    for name in ("Sales", "Customer Service", "Operations", "Accounting"):
        conn.execute("INSERT INTO departments (name, is_active) VALUES (?, 1)", (name,))


def seed_initial_admin(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    if count:
        return
    email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com").strip().lower()
    name = os.getenv("INITIAL_ADMIN_NAME", "Local Admin").strip() or "Local Admin"
    first_name, last_name = split_name(name)
    conn.execute(
        """
        INSERT INTO users (
            email, name, first_name, last_name, is_active, is_admin, can_access_admin,
            can_access_po_dashboard, po_dashboard_access_level
        )
        VALUES (?, ?, ?, ?, 1, 1, 1, 1, 'edit')
        """,
        (email, name, first_name, last_name),
    )


def backfill_user_profile_names(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT id, name, first_name, last_name FROM users WHERE COALESCE(first_name, '') = '' AND COALESCE(name, '') != ''"
    ).fetchall()
    for row in rows:
        first_name, last_name = split_name(row["name"])
        conn.execute("UPDATE users SET first_name = ?, last_name = ? WHERE id = ?", (first_name, last_name, row["id"]))


def split_name(name: str) -> tuple[str, str]:
    parts = name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


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

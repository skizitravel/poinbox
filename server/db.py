from __future__ import annotations

import json
import sqlite3
import os
from pathlib import Path
from typing import Any

from server.auth import hash_password


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
            sha256_hash TEXT,
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
            customer_part_revision TEXT,
            internal_part_number TEXT,
            internal_part_revision TEXT,
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
            customer_part_revision TEXT,
            internal_part_number TEXT NOT NULL,
            internal_part_revision TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(customer_name, customer_part_number)
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            internal_part_number TEXT NOT NULL UNIQUE,
            internal_part_revision TEXT,
            description TEXT,
            unit_of_measure TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
            password_hash TEXT,
            password_set_at TEXT,
            password_reset_required INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_admin INTEGER NOT NULL DEFAULT 0,
            can_access_admin INTEGER NOT NULL DEFAULT 0,
            can_access_po_dashboard INTEGER NOT NULL DEFAULT 1,
            po_dashboard_access_level TEXT NOT NULL DEFAULT 'view_only',
            invited_at TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS user_admin_tab_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tab_key TEXT NOT NULL,
            access_level TEXT NOT NULL DEFAULT 'no_access',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, tab_key)
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

        CREATE TABLE IF NOT EXISTS payment_terms (
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
            sync_mode TEXT DEFAULT 'manual',
            started_at TEXT,
            finished_at TEXT,
            status TEXT,
            start_at TEXT,
            end_at TEXT,
            provider_cursor_before TEXT,
            provider_cursor_after TEXT,
            messages_seen INTEGER DEFAULT 0,
            messages_imported INTEGER DEFAULT 0,
            messages_skipped INTEGER DEFAULT 0,
            purchase_orders_created INTEGER DEFAULT 0,
            error_count INTEGER DEFAULT 0,
            warning_count INTEGER DEFAULT 0,
            duration_ms INTEGER,
            status_detail TEXT,
            errors_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS inbox_message_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inbox_account_id INTEGER REFERENCES inbox_accounts(id) ON DELETE CASCADE,
            provider TEXT NOT NULL,
            provider_message_id TEXT NOT NULL,
            subject TEXT,
            sender TEXT,
            received_at TEXT,
            attachment_count INTEGER DEFAULT 0,
            supported_attachment_count INTEGER DEFAULT 0,
            processing_status TEXT,
            last_processed_at TEXT,
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(provider, provider_message_id)
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

        CREATE TABLE IF NOT EXISTS user_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS export_destinations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            destination_type TEXT NOT NULL DEFAULT 'csv',
            endpoint_url TEXT,
            config_json TEXT,
            secret_json TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS review_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE CASCADE,
            purchase_order_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE CASCADE,
            entity_type TEXT NOT NULL,
            entity_id INTEGER,
            reason_code TEXT NOT NULL,
            message TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'warning',
            status TEXT NOT NULL DEFAULT 'open',
            field_name TEXT,
            current_value TEXT,
            extracted_value TEXT,
            suggested_value_json TEXT,
            source_snippet TEXT,
            confidence REAL,
            created_by_system INTEGER NOT NULL DEFAULT 1,
            assigned_to_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            due_at TEXT,
            resolved_reason TEXT,
            resolution_note TEXT,
            source_reference_json TEXT,
            priority INTEGER DEFAULT 2,
            last_seen_at TEXT,
            resolved_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            resolved_at TEXT,
            ignored_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            ignored_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS po_audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata_json TEXT,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS export_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            output_type TEXT NOT NULL DEFAULT 'csv',
            include_lines INTEGER NOT NULL DEFAULT 1,
            field_mapping_json TEXT,
            date_format TEXT,
            number_format TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS erp_system (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_name TEXT NOT NULL,
            erp_family TEXT NOT NULL,
            erp_version TEXT,
            environment TEXT,
            connection_mode TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            config_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(system_name, erp_family, environment)
        );

        CREATE TABLE IF NOT EXISTS erp_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE CASCADE,
            profile_name TEXT NOT NULL UNIQUE,
            transaction_type TEXT NOT NULL DEFAULT 'entered_sales_order',
            adapter_code TEXT,
            profile_version TEXT,
            write_mode TEXT NOT NULL DEFAULT 'preview',
            defaulting_strategy TEXT,
            validation_strategy TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            settings_json TEXT,
            secret_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS organization_unit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            org_type TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT,
            parent_org_id INTEGER REFERENCES organization_unit(id) ON DELETE SET NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS selling_context (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            selling_org_id INTEGER REFERENCES organization_unit(id) ON DELETE SET NULL,
            channel_code TEXT,
            division_code TEXT,
            name TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS fulfillment_location (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            location_code TEXT,
            location_name TEXT NOT NULL,
            location_type TEXT,
            parent_location_id INTEGER REFERENCES fulfillment_location(id) ON DELETE SET NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trading_partner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            party_name TEXT NOT NULL,
            normalized_name TEXT,
            tax_id_optional TEXT,
            website_domain_optional TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trading_partner_account (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trading_partner_id INTEGER NOT NULL REFERENCES trading_partner(id) ON DELETE CASCADE,
            account_number TEXT,
            account_name TEXT NOT NULL,
            account_type TEXT NOT NULL DEFAULT 'customer',
            selling_org_id INTEGER REFERENCES organization_unit(id) ON DELETE SET NULL,
            currency_code TEXT,
            payment_terms_id INTEGER REFERENCES payment_terms(id) ON DELETE SET NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS trading_partner_site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trading_partner_account_id INTEGER NOT NULL REFERENCES trading_partner_account(id) ON DELETE CASCADE,
            site_code TEXT,
            site_name TEXT,
            address_line_1 TEXT,
            address_line_2 TEXT,
            address_line_3 TEXT,
            city TEXT,
            state_region TEXT,
            postal_code TEXT,
            country TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS partner_role_assignment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trading_partner_account_id INTEGER NOT NULL REFERENCES trading_partner_account(id) ON DELETE CASCADE,
            trading_partner_site_id INTEGER REFERENCES trading_partner_site(id) ON DELETE SET NULL,
            role_code TEXT NOT NULL,
            selling_org_id INTEGER REFERENCES organization_unit(id) ON DELETE SET NULL,
            primary_flag INTEGER NOT NULL DEFAULT 0,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            product_number TEXT NOT NULL,
            normalized_product_number TEXT,
            description TEXT,
            product_type TEXT,
            primary_uom_code TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS product_org_attributes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES product(id) ON DELETE CASCADE,
            org_unit_id INTEGER REFERENCES organization_unit(id) ON DELETE SET NULL,
            fulfillment_location_id INTEGER REFERENCES fulfillment_location(id) ON DELETE SET NULL,
            sales_channel_id INTEGER REFERENCES selling_context(id) ON DELETE SET NULL,
            sellable_flag INTEGER NOT NULL DEFAULT 1,
            orderable_flag INTEGER NOT NULL DEFAULT 1,
            status_code TEXT,
            default_uom_code TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS customer_product_alias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trading_partner_account_id INTEGER REFERENCES trading_partner_account(id) ON DELETE SET NULL,
            product_id INTEGER REFERENCES product(id) ON DELETE SET NULL,
            customer_product_number TEXT NOT NULL,
            normalized_customer_product_number TEXT,
            customer_product_revision TEXT,
            customer_product_description TEXT,
            product_revision TEXT,
            uom_code TEXT,
            start_date TEXT,
            end_date TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS unit_of_measure (
            uom_code TEXT PRIMARY KEY,
            uom_name TEXT,
            uom_class TEXT,
            iso_code TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS uom_alias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uom_code TEXT NOT NULL REFERENCES unit_of_measure(uom_code) ON DELETE CASCADE,
            source_value TEXT NOT NULL,
            source_system TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uom_code, source_value, source_system)
        );

        CREATE TABLE IF NOT EXISTS uom_conversion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_uom_code TEXT NOT NULL REFERENCES unit_of_measure(uom_code) ON DELETE CASCADE,
            to_uom_code TEXT NOT NULL REFERENCES unit_of_measure(uom_code) ON DELETE CASCADE,
            conversion_rate REAL NOT NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(from_uom_code, to_uom_code)
        );

        CREATE TABLE IF NOT EXISTS currency (
            currency_code TEXT PRIMARY KEY,
            currency_name TEXT,
            symbol TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS shipping_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT NOT NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS freight_terms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT NOT NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS delivery_method (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            name TEXT NOT NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS price_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            price_reference_type TEXT,
            name TEXT NOT NULL,
            code TEXT,
            currency_code TEXT REFERENCES currency(currency_code) ON DELETE SET NULL,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS order_document_type (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            document_type_code TEXT,
            document_type_name TEXT NOT NULL,
            transaction_category TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS line_document_type (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE SET NULL,
            line_type_code TEXT,
            line_type_name TEXT NOT NULL,
            line_category TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            legacy_source_table TEXT,
            legacy_source_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS custom_field_definition (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_profile_id INTEGER REFERENCES erp_profile(id) ON DELETE CASCADE,
            field_code TEXT NOT NULL,
            field_label TEXT,
            scope TEXT NOT NULL,
            data_type TEXT NOT NULL DEFAULT 'string',
            required_rule TEXT,
            default_rule TEXT,
            validation_rule TEXT,
            source_strategy TEXT,
            target_strategy TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS custom_field_value (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id INTEGER NOT NULL,
            field_definition_id INTEGER NOT NULL REFERENCES custom_field_definition(id) ON DELETE CASCADE,
            value_text TEXT,
            value_number REAL,
            value_date TEXT,
            value_boolean INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_type, entity_id, field_definition_id)
        );

        CREATE TABLE IF NOT EXISTS external_id_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_system_id INTEGER REFERENCES erp_system(id) ON DELETE CASCADE,
            canonical_entity_type TEXT NOT NULL,
            canonical_entity_id INTEGER NOT NULL,
            external_entity_type TEXT NOT NULL,
            external_id TEXT,
            external_code TEXT,
            external_name TEXT,
            source_table_or_api TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            last_synced_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS validation_rule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erp_profile_id INTEGER REFERENCES erp_profile(id) ON DELETE CASCADE,
            rule_code TEXT NOT NULL,
            rule_name TEXT,
            scope TEXT,
            severity TEXT NOT NULL DEFAULT 'warning',
            rule_json TEXT,
            active_flag INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS extraction_field_evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE CASCADE,
            purchase_order_line_id INTEGER REFERENCES purchase_order_lines(id) ON DELETE CASCADE,
            field_name TEXT NOT NULL,
            extracted_value TEXT,
            source_snippet TEXT,
            source_document_id INTEGER,
            source_attachment_filename TEXT,
            page_number INTEGER,
            sheet_name TEXT,
            row_number INTEGER,
            paragraph_index INTEGER,
            table_index INTEGER,
            email_section TEXT,
            confidence REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS po_duplicate_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE CASCADE,
            candidate_purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE CASCADE,
            match_type TEXT NOT NULL,
            match_score REAL DEFAULT 0,
            reason TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            resolved_at TEXT,
            resolution_note TEXT,
            UNIQUE(purchase_order_id, candidate_purchase_order_id, match_type)
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
    ensure_column(conn, "purchase_orders", "trading_partner_account_id", "INTEGER REFERENCES trading_partner_account(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "sold_to_partner_role_id", "INTEGER REFERENCES partner_role_assignment(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "ship_to_partner_role_id", "INTEGER REFERENCES partner_role_assignment(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "bill_to_partner_role_id", "INTEGER REFERENCES partner_role_assignment(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_orders", "payer_partner_role_id", "INTEGER REFERENCES partner_role_assignment(id) ON DELETE SET NULL")
    ensure_column(conn, "customers", "payment_terms_id", "INTEGER REFERENCES payment_terms(id) ON DELETE SET NULL")
    ensure_column(conn, "inbox_sync_runs", "start_at", "TEXT")
    ensure_column(conn, "inbox_sync_runs", "end_at", "TEXT")
    ensure_column(conn, "inbox_sync_runs", "sync_mode", "TEXT DEFAULT 'manual'")
    ensure_column(conn, "inbox_sync_runs", "provider_cursor_before", "TEXT")
    ensure_column(conn, "inbox_sync_runs", "provider_cursor_after", "TEXT")
    ensure_column(conn, "inbox_sync_runs", "error_count", "INTEGER DEFAULT 0")
    ensure_column(conn, "inbox_sync_runs", "warning_count", "INTEGER DEFAULT 0")
    ensure_column(conn, "inbox_sync_runs", "duration_ms", "INTEGER")
    ensure_column(conn, "inbox_sync_runs", "status_detail", "TEXT")
    ensure_column(conn, "attachments", "sha256_hash", "TEXT")
    ensure_column(conn, "review_tasks", "assigned_to_user_id", "INTEGER REFERENCES users(id) ON DELETE SET NULL")
    ensure_column(conn, "review_tasks", "due_at", "TEXT")
    ensure_column(conn, "review_tasks", "resolved_reason", "TEXT")
    ensure_column(conn, "review_tasks", "resolution_note", "TEXT")
    ensure_column(conn, "review_tasks", "source_reference_json", "TEXT")
    ensure_column(conn, "review_tasks", "priority", "INTEGER DEFAULT 2")
    ensure_column(conn, "review_tasks", "last_seen_at", "TEXT")
    ensure_column(conn, "purchase_order_lines", "field_confidence_json", "TEXT")
    ensure_column(conn, "purchase_order_lines", "customer_part_revision", "TEXT")
    ensure_column(conn, "purchase_order_lines", "internal_part_revision", "TEXT")
    ensure_column(conn, "purchase_order_lines", "product_match_status", "TEXT")
    ensure_column(conn, "purchase_order_lines", "matched_product_id", "INTEGER REFERENCES products(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_order_lines", "product_match_score", "REAL")
    ensure_column(conn, "purchase_order_lines", "product_match_reason", "TEXT")
    ensure_column(conn, "purchase_order_lines", "canonical_product_id", "INTEGER REFERENCES product(id) ON DELETE SET NULL")
    ensure_column(conn, "purchase_order_lines", "customer_product_alias_id", "INTEGER REFERENCES customer_product_alias(id) ON DELETE SET NULL")
    ensure_column(conn, "customer_part_xrefs", "customer_part_revision", "TEXT")
    ensure_column(conn, "customer_part_xrefs", "internal_part_revision", "TEXT")
    ensure_column(conn, "extraction_evaluation_runs", "extraction_mode", "TEXT DEFAULT 'rule_based'")
    ensure_column(conn, "users", "first_name", "TEXT")
    ensure_column(conn, "users", "last_name", "TEXT")
    ensure_column(conn, "users", "job_title", "TEXT")
    ensure_column(conn, "users", "password_hash", "TEXT")
    ensure_column(conn, "users", "password_set_at", "TEXT")
    ensure_column(conn, "users", "password_reset_required", "INTEGER NOT NULL DEFAULT 0")
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
    backfill_initial_admin_password(conn)
    seed_order_types(conn)
    seed_departments(conn)
    seed_payment_terms(conn)
    seed_initial_admin(conn)
    create_canonical_indexes(conn)
    backfill_canonical_master_data(conn)
    standard = conn.execute("SELECT id FROM order_types WHERE name = 'Standard'").fetchone()
    if standard:
        conn.execute("UPDATE purchase_orders SET order_type_id = ? WHERE order_type_id IS NULL", (standard["id"],))
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def create_canonical_indexes(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_trading_partner_legacy ON trading_partner(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_trading_partner_norm ON trading_partner(normalized_name);
        CREATE INDEX IF NOT EXISTS idx_trading_partner_account_legacy ON trading_partner_account(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_trading_partner_account_name ON trading_partner_account(account_name);
        CREATE INDEX IF NOT EXISTS idx_trading_partner_account_number ON trading_partner_account(account_number, active_flag);
        CREATE INDEX IF NOT EXISTS idx_trading_partner_site_legacy ON trading_partner_site(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_partner_role_legacy ON partner_role_assignment(legacy_source_table, legacy_source_id, role_code);
        CREATE INDEX IF NOT EXISTS idx_partner_role_account ON partner_role_assignment(trading_partner_account_id, role_code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_product_legacy ON product(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_product_number ON product(normalized_product_number);
        CREATE INDEX IF NOT EXISTS idx_product_uom_active ON product(primary_uom_code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_customer_product_alias_legacy ON customer_product_alias(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_customer_product_alias_lookup ON customer_product_alias(trading_partner_account_id, normalized_customer_product_number, customer_product_revision, active_flag);
        CREATE INDEX IF NOT EXISTS idx_customer_product_alias_product ON customer_product_alias(product_id, active_flag);
        CREATE INDEX IF NOT EXISTS idx_organization_unit_lookup ON organization_unit(erp_system_id, org_type, code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_selling_context_lookup ON selling_context(erp_system_id, selling_org_id, channel_code, division_code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_fulfillment_location_lookup ON fulfillment_location(erp_system_id, location_code, location_type, active_flag);
        CREATE INDEX IF NOT EXISTS idx_order_document_type_legacy ON order_document_type(legacy_source_table, legacy_source_id);
        CREATE INDEX IF NOT EXISTS idx_order_document_type_lookup ON order_document_type(erp_system_id, document_type_code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_line_document_type_lookup ON line_document_type(erp_system_id, line_type_code, active_flag);
        CREATE INDEX IF NOT EXISTS idx_external_id_map_entity ON external_id_map(canonical_entity_type, canonical_entity_id, erp_system_id, active_flag);
        CREATE INDEX IF NOT EXISTS idx_external_id_map_external ON external_id_map(erp_system_id, external_entity_type, external_id, external_code, active_flag);
        """
    )


def canonical_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return " ".join(text.split())


def canonical_code(value: Any) -> str:
    return str(value or "").strip().upper()


def canonical_legacy_id(value: Any) -> str:
    return str(value or "").strip()


def legacy_row(conn: sqlite3.Connection, table: str, legacy_source_table: str, legacy_source_id: Any) -> sqlite3.Row | None:
    return conn.execute(
        f"SELECT * FROM {table} WHERE legacy_source_table = ? AND legacy_source_id = ? LIMIT 1",
        (legacy_source_table, canonical_legacy_id(legacy_source_id)),
    ).fetchone()


def upsert_uom(conn: sqlite3.Connection, raw_code: Any) -> str | None:
    code = canonical_code(raw_code)
    if not code:
        return None
    conn.execute(
        """
        INSERT INTO unit_of_measure (uom_code, uom_name, active_flag)
        VALUES (?, ?, 1)
        ON CONFLICT(uom_code) DO UPDATE SET
            uom_name = COALESCE(NULLIF(unit_of_measure.uom_name, ''), excluded.uom_name),
            active_flag = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (code, code),
    )
    conn.execute(
        """
        INSERT INTO uom_alias (uom_code, source_value, source_system, active_flag)
        VALUES (?, ?, 'mountaingoat_legacy', 1)
        ON CONFLICT(uom_code, source_value, source_system) DO UPDATE SET
            active_flag = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (code, str(raw_code or "").strip()),
    )
    return code


def upsert_currency(conn: sqlite3.Connection, raw_code: Any) -> str | None:
    code = canonical_code(raw_code)
    if not code:
        return None
    conn.execute(
        """
        INSERT INTO currency (currency_code, currency_name, active_flag)
        VALUES (?, ?, 1)
        ON CONFLICT(currency_code) DO UPDATE SET
            active_flag = 1,
            updated_at = CURRENT_TIMESTAMP
        """,
        (code, code),
    )
    return code


def ensure_trading_partner_for_customer(conn: sqlite3.Connection, customer: sqlite3.Row, stats: dict[str, int]) -> int:
    existing = legacy_row(conn, "trading_partner", "customers", customer["id"])
    name = (customer["customer_name"] or customer["customer_number"] or "").strip()
    if existing:
        conn.execute(
            """
            UPDATE trading_partner
            SET party_name = ?, normalized_name = ?, active_flag = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, canonical_key(name), existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO trading_partner (
            party_name, normalized_name, active_flag, legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, 1, 'customers', ?)
        """,
        (name, canonical_key(name), canonical_legacy_id(customer["id"])),
    )
    stats["trading_partners_created"] += 1
    return int(cur.lastrowid)


def ensure_trading_partner_account_for_customer(conn: sqlite3.Connection, customer: sqlite3.Row, stats: dict[str, int]) -> int:
    partner_id = ensure_trading_partner_for_customer(conn, customer, stats)
    existing = legacy_row(conn, "trading_partner_account", "customers", customer["id"])
    name = (customer["customer_name"] or customer["customer_number"] or "").strip()
    number = (customer["customer_number"] or "").strip()
    payment_terms_id = customer["payment_terms_id"] if "payment_terms_id" in customer.keys() else None
    if existing:
        conn.execute(
            """
            UPDATE trading_partner_account
            SET trading_partner_id = ?, account_number = ?, account_name = ?, payment_terms_id = ?,
                active_flag = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (partner_id, number, name, payment_terms_id, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO trading_partner_account (
            trading_partner_id, account_number, account_name, account_type, payment_terms_id,
            active_flag, legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, 'customer', ?, 1, 'customers', ?)
        """,
        (partner_id, number, name, payment_terms_id, canonical_legacy_id(customer["id"])),
    )
    stats["trading_partner_accounts_created"] += 1
    return int(cur.lastrowid)


def ensure_partner_account_for_name(conn: sqlite3.Connection, customer_name: str, stats: dict[str, int]) -> int | None:
    name = customer_name.strip()
    if not name:
        return None
    customer = conn.execute(
        "SELECT * FROM customers WHERE LOWER(TRIM(customer_name)) = LOWER(TRIM(?)) LIMIT 1",
        (name,),
    ).fetchone()
    if customer:
        return ensure_trading_partner_account_for_customer(conn, customer, stats)
    row = conn.execute(
        "SELECT * FROM trading_partner_account WHERE LOWER(TRIM(account_name)) = LOWER(TRIM(?)) LIMIT 1",
        (name,),
    ).fetchone()
    if row:
        return int(row["id"])
    source_id = canonical_key(name)
    partner = legacy_row(conn, "trading_partner", "customer_part_xrefs_customer", source_id)
    if partner:
        partner_id = int(partner["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO trading_partner (
                party_name, normalized_name, active_flag, legacy_source_table, legacy_source_id
            )
            VALUES (?, ?, 1, 'customer_part_xrefs_customer', ?)
            """,
            (name, canonical_key(name), source_id),
        )
        partner_id = int(cur.lastrowid)
        stats["trading_partners_created"] += 1
    account = legacy_row(conn, "trading_partner_account", "customer_part_xrefs_customer", source_id)
    if account:
        return int(account["id"])
    cur = conn.execute(
        """
        INSERT INTO trading_partner_account (
            trading_partner_id, account_name, account_type, active_flag, legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, 'customer', 1, 'customer_part_xrefs_customer', ?)
        """,
        (partner_id, name, source_id),
    )
    stats["trading_partner_accounts_created"] += 1
    return int(cur.lastrowid)


def address_role_code(address_type: str | None) -> str:
    return "BILL_TO" if address_type == "bill_to" else "SHIP_TO" if address_type == "ship_to" else "SOLD_TO"


def ensure_site_for_address(conn: sqlite3.Connection, address: sqlite3.Row, account_id: int, stats: dict[str, int]) -> int:
    existing = legacy_row(conn, "trading_partner_site", "customer_addresses", address["id"])
    site_name = (address["label"] or address["address_type"] or f"Address {address['id']}").strip()
    site_code = f"CUST{address['customer_id']}-ADDR{address['id']}"
    values = (
        account_id,
        site_code,
        site_name,
        address["address_line_1"] if "address_line_1" in address.keys() else None,
        address["address_line_2"] if "address_line_2" in address.keys() else None,
        address["address_line_3"] if "address_line_3" in address.keys() else None,
        address["city"] if "city" in address.keys() else None,
        address["state"] if "state" in address.keys() else None,
        address["zip_code"] if "zip_code" in address.keys() else None,
        address["country"] if "country" in address.keys() else None,
    )
    if existing:
        conn.execute(
            """
            UPDATE trading_partner_site
            SET trading_partner_account_id = ?, site_code = ?, site_name = ?, address_line_1 = ?,
                address_line_2 = ?, address_line_3 = ?, city = ?, state_region = ?, postal_code = ?,
                country = ?, active_flag = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*values, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO trading_partner_site (
            trading_partner_account_id, site_code, site_name, address_line_1, address_line_2,
            address_line_3, city, state_region, postal_code, country, active_flag,
            legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 'customer_addresses', ?)
        """,
        (*values, canonical_legacy_id(address["id"])),
    )
    stats["trading_partner_sites_created"] += 1
    return int(cur.lastrowid)


def ensure_role_for_address(conn: sqlite3.Connection, address: sqlite3.Row, account_id: int, site_id: int, stats: dict[str, int]) -> int:
    role = address_role_code(address["address_type"])
    existing = conn.execute(
        """
        SELECT * FROM partner_role_assignment
        WHERE legacy_source_table = 'customer_addresses' AND legacy_source_id = ? AND role_code = ?
        LIMIT 1
        """,
        (canonical_legacy_id(address["id"]), role),
    ).fetchone()
    primary_flag = 1 if int(address["is_default"] or 0) else 0
    if existing:
        conn.execute(
            """
            UPDATE partner_role_assignment
            SET trading_partner_account_id = ?, trading_partner_site_id = ?, primary_flag = ?,
                active_flag = 1, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (account_id, site_id, primary_flag, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO partner_role_assignment (
            trading_partner_account_id, trading_partner_site_id, role_code, primary_flag, active_flag,
            legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, ?, 1, 'customer_addresses', ?)
        """,
        (account_id, site_id, role, primary_flag, canonical_legacy_id(address["id"])),
    )
    stats["partner_roles_created"] += 1
    return int(cur.lastrowid)


def ensure_product_from_legacy(conn: sqlite3.Connection, product_row: sqlite3.Row, stats: dict[str, int]) -> int:
    existing = legacy_row(conn, "product", "products", product_row["id"])
    number = (product_row["internal_part_number"] or "").strip()
    uom_code = upsert_uom(conn, product_row["unit_of_measure"])
    active = 1 if int(product_row["is_active"] or 0) else 0
    if existing:
        conn.execute(
            """
            UPDATE product
            SET product_number = ?, normalized_product_number = ?, description = ?,
                primary_uom_code = ?, active_flag = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (number, canonical_key(number), product_row["description"], uom_code, active, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO product (
            product_number, normalized_product_number, description, product_type, primary_uom_code,
            active_flag, legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, 'item', ?, ?, 'products', ?)
        """,
        (number, canonical_key(number), product_row["description"], uom_code, active, canonical_legacy_id(product_row["id"])),
    )
    stats["products_created"] += 1
    return int(cur.lastrowid)


def ensure_product_for_part(conn: sqlite3.Connection, internal_part_number: str, internal_revision: str | None, stats: dict[str, int]) -> int | None:
    part = internal_part_number.strip()
    if not part:
        return None
    product_row = conn.execute(
        "SELECT * FROM products WHERE LOWER(TRIM(internal_part_number)) = LOWER(TRIM(?)) LIMIT 1",
        (part,),
    ).fetchone()
    if product_row:
        return ensure_product_from_legacy(conn, product_row, stats)
    row = conn.execute(
        "SELECT * FROM product WHERE normalized_product_number = ? LIMIT 1",
        (canonical_key(part),),
    ).fetchone()
    if row:
        return int(row["id"])
    source_id = f"{canonical_key(part)}::{canonical_key(internal_revision)}"
    cur = conn.execute(
        """
        INSERT INTO product (
            product_number, normalized_product_number, product_type, active_flag,
            legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, 'item', 1, 'customer_part_xrefs_product', ?)
        """,
        (part, canonical_key(part), source_id),
    )
    stats["products_created"] += 1
    return int(cur.lastrowid)


def ensure_product_org_attributes(conn: sqlite3.Connection, product_id: int, product_row: sqlite3.Row, stats: dict[str, int]) -> None:
    existing = legacy_row(conn, "product_org_attributes", "products", product_row["id"])
    status = "active" if int(product_row["is_active"] or 0) else "inactive"
    uom_code = upsert_uom(conn, product_row["unit_of_measure"])
    if existing:
        conn.execute(
            """
            UPDATE product_org_attributes
            SET product_id = ?, sellable_flag = ?, orderable_flag = ?, status_code = ?,
                default_uom_code = ?, active_flag = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (product_id, int(product_row["is_active"] or 0), int(product_row["is_active"] or 0), status, uom_code, int(product_row["is_active"] or 0), existing["id"]),
        )
        return
    conn.execute(
        """
        INSERT INTO product_org_attributes (
            product_id, sellable_flag, orderable_flag, status_code, default_uom_code, active_flag,
            legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, ?, ?, ?, 'products', ?)
        """,
        (product_id, int(product_row["is_active"] or 0), int(product_row["is_active"] or 0), status, uom_code, int(product_row["is_active"] or 0), canonical_legacy_id(product_row["id"])),
    )
    stats["product_org_attributes_created"] += 1


def ensure_customer_product_alias(conn: sqlite3.Connection, xref: sqlite3.Row, stats: dict[str, int]) -> int:
    existing = legacy_row(conn, "customer_product_alias", "customer_part_xrefs", xref["id"])
    account_id = ensure_partner_account_for_name(conn, xref["customer_name"] or "", stats)
    product_id = ensure_product_for_part(conn, xref["internal_part_number"] or "", xref["internal_part_revision"], stats)
    customer_part = (xref["customer_part_number"] or "").strip()
    customer_revision = xref["customer_part_revision"] if "customer_part_revision" in xref.keys() else None
    internal_revision = xref["internal_part_revision"] if "internal_part_revision" in xref.keys() else None
    values = (
        account_id,
        product_id,
        customer_part,
        canonical_key(customer_part),
        (customer_revision or "").strip(),
        (internal_revision or "").strip(),
        1,
    )
    if existing:
        conn.execute(
            """
            UPDATE customer_product_alias
            SET trading_partner_account_id = ?, product_id = ?, customer_product_number = ?,
                normalized_customer_product_number = ?, customer_product_revision = ?,
                product_revision = ?, active_flag = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*values, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO customer_product_alias (
            trading_partner_account_id, product_id, customer_product_number, normalized_customer_product_number,
            customer_product_revision, product_revision, active_flag, legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'customer_part_xrefs', ?)
        """,
        (*values, canonical_legacy_id(xref["id"])),
    )
    stats["customer_product_aliases_created"] += 1
    return int(cur.lastrowid)


def ensure_order_document_type(conn: sqlite3.Connection, order_type: sqlite3.Row, stats: dict[str, int]) -> int:
    existing = legacy_row(conn, "order_document_type", "order_types", order_type["id"])
    name = (order_type["name"] or "").strip()
    code = canonical_code(name).replace(" ", "_")
    active = 1 if int(order_type["is_active"] or 0) else 0
    if existing:
        conn.execute(
            """
            UPDATE order_document_type
            SET document_type_code = ?, document_type_name = ?, transaction_category = ?, active_flag = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (code, name, canonical_key(name).replace(" ", "_") or "standard_order", active, existing["id"]),
        )
        return int(existing["id"])
    cur = conn.execute(
        """
        INSERT INTO order_document_type (
            document_type_code, document_type_name, transaction_category, active_flag,
            legacy_source_table, legacy_source_id
        )
        VALUES (?, ?, ?, ?, 'order_types', ?)
        """,
        (code, name, canonical_key(name).replace(" ", "_") or "standard_order", active, canonical_legacy_id(order_type["id"])),
    )
    stats["order_document_types_created"] += 1
    return int(cur.lastrowid)


def find_alias_for_line(conn: sqlite3.Connection, account_id: int | None, customer_part: str, customer_revision: str | None) -> sqlite3.Row | None:
    if not account_id or not customer_part.strip():
        return None
    revision = canonical_key(customer_revision)
    row = conn.execute(
        """
        SELECT * FROM customer_product_alias
        WHERE trading_partner_account_id = ?
          AND normalized_customer_product_number = ?
          AND LOWER(TRIM(COALESCE(customer_product_revision, ''))) = ?
          AND active_flag = 1
        LIMIT 1
        """,
        (account_id, canonical_key(customer_part), revision),
    ).fetchone()
    if row:
        return row
    return conn.execute(
        """
        SELECT * FROM customer_product_alias
        WHERE trading_partner_account_id = ?
          AND normalized_customer_product_number = ?
          AND COALESCE(NULLIF(TRIM(customer_product_revision), ''), '') = ''
          AND active_flag = 1
        LIMIT 1
        """,
        (account_id, canonical_key(customer_part)),
    ).fetchone()


def default_role_id(conn: sqlite3.Connection, account_id: int | None, role_code: str) -> int | None:
    if not account_id:
        return None
    row = conn.execute(
        """
        SELECT id FROM partner_role_assignment
        WHERE trading_partner_account_id = ? AND role_code = ? AND active_flag = 1
        ORDER BY primary_flag DESC, id
        LIMIT 1
        """,
        (account_id, role_code),
    ).fetchone()
    return int(row["id"]) if row else None


def backfill_purchase_order_canonical_refs(conn: sqlite3.Connection, stats: dict[str, int]) -> None:
    for po in conn.execute("SELECT * FROM purchase_orders").fetchall():
        account_id = po["trading_partner_account_id"] if "trading_partner_account_id" in po.keys() else None
        if not account_id and po["customer_company_name"]:
            account_id = ensure_partner_account_for_name(conn, po["customer_company_name"], stats)
        if account_id:
            conn.execute(
                """
                UPDATE purchase_orders
                SET trading_partner_account_id = COALESCE(trading_partner_account_id, ?),
                    sold_to_partner_role_id = COALESCE(sold_to_partner_role_id, ?),
                    ship_to_partner_role_id = COALESCE(ship_to_partner_role_id, ?),
                    bill_to_partner_role_id = COALESCE(bill_to_partner_role_id, ?),
                    payer_partner_role_id = COALESCE(payer_partner_role_id, ?)
                WHERE id = ?
                """,
                (
                    account_id,
                    default_role_id(conn, account_id, "SOLD_TO"),
                    default_role_id(conn, account_id, "SHIP_TO"),
                    default_role_id(conn, account_id, "BILL_TO"),
                    default_role_id(conn, account_id, "PAYER"),
                    po["id"],
                ),
            )
    for line in conn.execute(
        """
        SELECT pol.*, po.customer_company_name, po.trading_partner_account_id
        FROM purchase_order_lines pol
        JOIN purchase_orders po ON po.id = pol.purchase_order_id
        """
    ).fetchall():
        account_id = line["trading_partner_account_id"]
        if not account_id and line["customer_company_name"]:
            account_id = ensure_partner_account_for_name(conn, line["customer_company_name"], stats)
        alias = find_alias_for_line(conn, account_id, line["customer_part_number"] or "", line["customer_part_revision"])
        product_id = alias["product_id"] if alias and alias["product_id"] else None
        if not product_id and line["matched_product_id"]:
            product_row = conn.execute("SELECT * FROM products WHERE id = ?", (line["matched_product_id"],)).fetchone()
            if product_row:
                product_id = ensure_product_from_legacy(conn, product_row, stats)
        if not product_id and line["internal_part_number"]:
            product_id = ensure_product_for_part(conn, line["internal_part_number"], line["internal_part_revision"], stats)
        if alias or product_id:
            conn.execute(
                """
                UPDATE purchase_order_lines
                SET canonical_product_id = COALESCE(canonical_product_id, ?),
                    customer_product_alias_id = COALESCE(customer_product_alias_id, ?)
                WHERE id = ?
                """,
                (product_id, alias["id"] if alias else None, line["id"]),
            )


def backfill_canonical_master_data(conn: sqlite3.Connection) -> dict[str, int]:
    stats = {
        "trading_partners_created": 0,
        "trading_partner_accounts_created": 0,
        "trading_partner_sites_created": 0,
        "partner_roles_created": 0,
        "products_created": 0,
        "product_org_attributes_created": 0,
        "customer_product_aliases_created": 0,
        "order_document_types_created": 0,
    }
    for product_row in conn.execute("SELECT * FROM products").fetchall():
        product_id = ensure_product_from_legacy(conn, product_row, stats)
        ensure_product_org_attributes(conn, product_id, product_row, stats)
    for po_line in conn.execute("SELECT DISTINCT unit_of_measure FROM purchase_order_lines WHERE COALESCE(unit_of_measure, '') != ''").fetchall():
        upsert_uom(conn, po_line["unit_of_measure"])
    for po in conn.execute("SELECT DISTINCT currency FROM purchase_orders WHERE COALESCE(currency, '') != ''").fetchall():
        upsert_currency(conn, po["currency"])
    for customer in conn.execute("SELECT * FROM customers").fetchall():
        ensure_trading_partner_account_for_customer(conn, customer, stats)
    for address in conn.execute("SELECT * FROM customer_addresses").fetchall():
        customer = conn.execute("SELECT * FROM customers WHERE id = ?", (address["customer_id"],)).fetchone()
        if not customer:
            continue
        account_id = ensure_trading_partner_account_for_customer(conn, customer, stats)
        site_id = ensure_site_for_address(conn, address, account_id, stats)
        ensure_role_for_address(conn, address, account_id, site_id, stats)
    for xref in conn.execute("SELECT * FROM customer_part_xrefs").fetchall():
        ensure_customer_product_alias(conn, xref, stats)
    for order_type in conn.execute("SELECT * FROM order_types").fetchall():
        ensure_order_document_type(conn, order_type, stats)
    backfill_purchase_order_canonical_refs(conn, stats)
    return stats


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


def seed_payment_terms(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM payment_terms").fetchone()["count"]
    if count:
        return
    for name in ("Net 30", "Net 90", "Prepay"):
        conn.execute("INSERT INTO payment_terms (name, is_active) VALUES (?, 1)", (name,))


def seed_initial_admin(conn: sqlite3.Connection) -> None:
    count = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()["count"]
    if count:
        return
    email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com").strip().lower()
    name = os.getenv("INITIAL_ADMIN_NAME", "Local Admin").strip() or "Local Admin"
    password = initial_admin_password()
    first_name, last_name = split_name(name)
    conn.execute(
        """
        INSERT INTO users (
            email, name, first_name, last_name, password_hash, password_set_at, is_active, is_admin, can_access_admin,
            can_access_po_dashboard, po_dashboard_access_level
        )
        VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1, 1, 1, 1, 'edit')
        """,
        (email, name, first_name, last_name, hash_password(password)),
    )


def backfill_initial_admin_password(conn: sqlite3.Connection) -> None:
    email = os.getenv("INITIAL_ADMIN_EMAIL", "admin@example.com").strip().lower()
    row = conn.execute(
        """
        SELECT id FROM users
        WHERE LOWER(email) = ? AND is_active = 1 AND is_admin = 1
          AND COALESCE(password_hash, '') = ''
        """,
        (email,),
    ).fetchone()
    if not row:
        return
    conn.execute(
        "UPDATE users SET password_hash = ?, password_set_at = CURRENT_TIMESTAMP WHERE id = ?",
        (hash_password(initial_admin_password()), row["id"]),
    )


def initial_admin_password() -> str:
    password = os.getenv("INITIAL_ADMIN_PASSWORD", "").strip()
    if password:
        return password
    if os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower() == "production":
        raise RuntimeError("INITIAL_ADMIN_PASSWORD is required for production first-admin setup.")
    return "admin"


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

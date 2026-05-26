from __future__ import annotations

import json
import re
import sys
import threading
import uuid
import base64
import cgi
import csv
import html
import io
import mimetypes
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config import (
    APP_BASE_URL,
    APP_ENV,
    APP_HOST,
    APP_PORT,
    DATABASE_PATH,
    ENABLE_BACKGROUND_SYNC,
    GMAIL_CLIENT_ID,
    GMAIL_CLIENT_SECRET,
    GMAIL_REDIRECT_URI,
    GMAIL_SCOPES,
    OUTLOOK_CLIENT_ID,
    OUTLOOK_CLIENT_SECRET,
    OUTLOOK_REDIRECT_URI,
    OUTLOOK_SCOPES,
    OUTLOOK_TENANT,
    PUBLIC_DIR,
    SAMPLES_DIR,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_SECURE,
    SESSION_TTL_HOURS,
    STORAGE_DIR,
    TEST_CORPUS_DIR,
    validate_production_config,
)
from server.auth import generate_temporary_password, hash_password, hash_session_token, new_session_token, verify_password
from server.crypto_utils import decrypt_secret, encrypt_secret, encrypted_secret_label
from server.db import backfill_canonical_master_data, connect, initialize, row_to_dict, rows_to_dicts
from server.connectors import IncomingAttachment, IncomingEmail
from server.processing import (
    extract_pdf_text,
    find_similar_extraction_examples,
    generate_review_tasks_for_po,
    import_samples,
    insert_attachment,
    insert_email,
    log_document_extraction_run,
    match_product_for_line,
    process_email,
    recalculate_po_total,
)
from server.extraction import classify_purchase_order, extract_purchase_order, normalize_date
from server.erp_adapters import (
    ORACLE_EBS_ORDER_ENTRY_MANIFEST,
    adapter_manifests,
    oracle_payload_preview,
    oracle_profile_response,
)
from server.master_data import addresses_match, format_structured_address, list_reviews, parse_structured_address, resolve_review, run_master_data_reviews
from server.openai_settings import get_openai_extraction_config, get_openai_runtime_config, save_openai_extraction_config


SYNC_LOCKS: set[int] = set()
ADMIN_TABS = ("users", "master", "setup", "testing", "analytics", "erp")
ADMIN_TAB_LABELS = {
    "users": "Users & Access",
    "master": "Master Data",
    "setup": "Setup",
    "testing": "Testing",
    "analytics": "Analytics",
    "erp": "ERP",
}
ADMIN_ACCESS_LEVELS = {"no_access", "view_only", "full_access"}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path == "/health":
            return self.respond_json({"ok": True, "app": "mountaingoat", "environment": APP_ENV})
        if parsed.path == "/api/me":
            return self.respond_json({"user": public_user(self.current_user())})
        if parsed.path == "/api/summary":
            if not self.require_permission("po_dashboard:view"):
                return
            return self.respond_json(get_summary())
        if parsed.path == "/api/purchase-orders":
            if not self.require_permission("po_dashboard:view"):
                return
            return self.respond_json(list_purchase_orders(params))
        if parsed.path == "/api/users":
            if not self.require_permission("users:view"):
                return
            return self.respond_json(list_users())
        if parsed.path == "/api/customers":
            if not self.require_admin_tab("master"):
                return
            return self.respond_json(list_customers())
        if parsed.path == "/api/products":
            if not self.require_admin_tab("master"):
                return
            return self.respond_json({"products": list_products()})
        if parsed.path == "/api/canonical-master-data":
            if not self.require_any_admin_tab(("master", "setup", "erp")):
                return
            return self.respond_json(list_canonical_master_data())
        if parsed.path == "/api/products.csv":
            if not self.require_admin_tab("master"):
                return
            return self.respond_csv(products_csv(), "products.csv")
        if parsed.path == "/api/customers.csv":
            if not self.require_admin_tab("master"):
                return
            mode = params.get("mode", ["customers"])[0]
            filename = "customers-with-addresses.csv" if mode == "addresses" else "customers.csv"
            return self.respond_csv(customers_csv(mode), filename)
        if parsed.path == "/api/customer-contacts.csv":
            if not self.require_admin_tab("master"):
                return
            return self.respond_csv(customer_contacts_csv(), "customer-contacts.csv")
        if parsed.path.startswith("/api/customers/"):
            if not self.require_admin_tab("master"):
                return
            customer_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(get_customer(customer_id))
        if parsed.path == "/api/order-types":
            if not self.require_admin_tab("setup"):
                return
            return self.respond_json(list_order_types())
        if parsed.path == "/api/departments":
            if not self.require_admin_tab("setup"):
                return
            return self.respond_json(list_departments())
        if parsed.path == "/api/payment-terms":
            if not self.require_admin_tab("setup"):
                return
            return self.respond_json(list_payment_terms())
        if parsed.path == "/api/testing/documents":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(list_test_documents())
        if parsed.path.startswith("/api/testing/documents/") and parsed.path.endswith("/golden-answer"):
            if not self.require_admin_tab("testing"):
                return
            document_id = int(parsed.path.split("/")[-2])
            return self.respond_json(get_golden_answer(document_id))
        if parsed.path == "/api/testing/evaluations":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(list_evaluation_runs())
        if parsed.path.startswith("/api/testing/evaluations/"):
            if not self.require_admin_tab("testing"):
                return
            run_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(get_evaluation_run(run_id))
        if parsed.path == "/api/inbox-accounts":
            if not self.require_admin_tab("setup"):
                return
            return self.respond_json(list_inbox_accounts())
        if parsed.path.startswith("/api/inbox-accounts/") and parsed.path.endswith("/config"):
            if not self.require_admin_tab("setup"):
                return
            account_id = int(parsed.path.split("/")[-2])
            return self.respond_json(get_inbox_config(account_id))
        if parsed.path == "/api/gmail-oauth-config":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(get_gmail_oauth_config())
        if parsed.path == "/api/outlook-oauth-config":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(get_outlook_oauth_config())
        if parsed.path == "/api/openai-extraction-config":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(get_openai_extraction_config())
        if parsed.path == "/api/inbox-detection-results":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(list_inbox_detection_results())
        if parsed.path == "/api/export-destinations":
            if not self.require_admin_tab("setup"):
                return
            return self.respond_json(list_export_destinations())
        if parsed.path == "/api/erp/adapters":
            if not self.require_admin_tab("erp"):
                return
            return self.respond_json({"adapters": adapter_manifests()})
        if parsed.path == "/api/erp/oracle-ebs":
            if not self.require_admin_tab("erp"):
                return
            return self.respond_json(get_oracle_ebs_profile())
        if parsed.path == "/api/extraction-learning":
            if not self.require_admin_tab("testing"):
                return
            return self.respond_json(extraction_learning_dashboard(params))
        if parsed.path == "/api/review-tasks":
            if not self.require_permission("po_dashboard:view"):
                return
            return self.respond_json(list_review_tasks(params))
        if parsed.path == "/api/reporting/operations":
            if not self.require_admin_tab("analytics"):
                return
            return self.respond_json(operations_reporting())
        if parsed.path == "/api/reporting/summary.csv":
            if not self.require_admin_tab("analytics"):
                return
            return self.respond_csv(reporting_summary_csv(params), "operations-summary.csv")
        if parsed.path == "/api/reporting/exceptions.csv":
            if not self.require_admin_tab("analytics"):
                return
            return self.respond_csv(reporting_exceptions_csv(params), "exceptions-report.csv")
        if parsed.path == "/api/reporting/corrections.csv":
            if not self.require_admin_tab("analytics"):
                return
            return self.respond_csv(reporting_corrections_csv(params), "corrections-report.csv")
        if parsed.path == "/api/oauth/gmail/callback":
            body, status = gmail_oauth_callback(parsed.query)
            return self.respond_html(body, status)
        if parsed.path == "/api/oauth/outlook/callback":
            body, status = outlook_oauth_callback(parsed.query)
            return self.respond_html(body, status)
        if parsed.path == "/api/customer-part-xrefs":
            if not self.require_admin_tab("master"):
                return
            return self.respond_json(list_customer_part_xrefs())
        if parsed.path == "/api/customer-part-xrefs.csv":
            if not self.require_admin_tab("master"):
                return
            return self.respond_csv(customer_part_xrefs_csv(), "customer-part-cross-reference.csv")
        if parsed.path == "/api/export/purchase-orders.csv":
            if not self.require_permission("po_dashboard:view"):
                return
            params = parse_qs(parsed.query)
            mode = params.get("mode", ["header"])[0]
            filename = "purchase-orders-with-lines.csv" if mode == "lines" else "purchase-orders-header.csv"
            return self.respond_csv(purchase_orders_csv(params, mode), filename)
        if parsed.path.startswith("/api/attachments/") and parsed.path.endswith("/view"):
            if not self.require_permission("po_dashboard:view"):
                return
            attachment_id = int(parsed.path.split("/")[-2])
            return self.serve_attachment(attachment_id)
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/confirmed-order"):
            if not self.require_permission("po_dashboard:view"):
                return
            po_id = int(parsed.path.split("/")[-2])
            return self.respond_json(confirmed_order_view(po_id))
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/acknowledgment-draft"):
            if not self.require_permission("po_dashboard:view"):
                return
            po_id = int(parsed.path.split("/")[-2])
            return self.respond_json(acknowledgment_draft(po_id))
        if parsed.path.startswith("/api/purchase-orders/"):
            if not self.require_permission("po_dashboard:view"):
                return
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(get_purchase_order(po_id))
        if parsed.path == "/api/logs":
            if not self.require_permission("po_dashboard:view"):
                return
            return self.respond_json(get_logs())
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/login":
            return self.login()
        if parsed.path == "/api/logout":
            return self.logout()
        if parsed.path == "/api/upload-samples":
            if not self.require_permission("po_dashboard:edit"):
                return
            return self.respond_json(upload_samples(self))
        if parsed.path == "/api/customer-part-xrefs/upload":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(upload_customer_part_xrefs(self))
        if parsed.path == "/api/products/upload-csv":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(upload_products_csv(self))
        if parsed.path == "/api/customers/upload-csv":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(upload_customers_csv(self))
        if parsed.path == "/api/customer-contacts/upload-csv":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(upload_customer_contacts_csv(self))
        if parsed.path == "/api/customer-part-xrefs":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(create_customer_part_xref(self.read_json()))
        if parsed.path == "/api/canonical-master-data/backfill":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(run_canonical_master_data_backfill())
        if parsed.path == "/api/products":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(create_product(self.read_json()))
        if parsed.path == "/api/order-types":
            if not self.require_admin_tab("setup", "edit"):
                return
            return self.respond_json(create_order_type(self.read_json()))
        if parsed.path == "/api/departments":
            if not self.require_admin_tab("setup", "edit"):
                return
            return self.respond_json(create_department(self.read_json()))
        if parsed.path == "/api/payment-terms":
            if not self.require_admin_tab("setup", "edit"):
                return
            return self.respond_json(create_payment_term(self.read_json()))
        if parsed.path == "/api/testing/documents/upload":
            if not self.require_admin_tab("testing", "edit"):
                return
            return self.respond_json(upload_test_documents(self))
        if parsed.path == "/api/testing/evaluations/run":
            if not self.require_admin_tab("testing", "edit"):
                return
            return self.respond_json(run_extraction_evaluation(self.read_json()))
        if parsed.path == "/api/inbox-accounts/gmail/connect":
            actor = self.require_admin_tab("setup", "edit")
            if not actor:
                return
            return self.respond_json(connect_gmail_account(self.read_json(), actor))
        if parsed.path == "/api/inbox-accounts/outlook/connect":
            actor = self.require_admin_tab("setup", "edit")
            if not actor:
                return
            return self.respond_json(connect_outlook_account(self.read_json(), actor))
        if parsed.path == "/api/inbox-accounts":
            actor = self.require_admin_tab("setup", "edit")
            if not actor:
                return
            return self.respond_json(create_inbox_account(self.read_json(), actor))
        if parsed.path == "/api/gmail-oauth-config":
            if not self.require_admin_tab("testing", "edit"):
                return
            return self.respond_json(save_gmail_oauth_config(self.read_json()))
        if parsed.path == "/api/outlook-oauth-config":
            if not self.require_admin_tab("testing", "edit"):
                return
            return self.respond_json(save_outlook_oauth_config(self.read_json()))
        if parsed.path == "/api/openai-extraction-config":
            if not self.require_admin_tab("testing", "edit"):
                return
            return self.respond_json(save_openai_extraction_config(self.read_json()))
        if parsed.path.startswith("/api/inbox-accounts/") and parsed.path.endswith("/sync"):
            if not self.require_admin_tab("setup", "edit"):
                return
            account_id = int(parsed.path.split("/")[-2])
            return self.respond_json(sync_inbox_account(account_id, self.read_json()))
        if parsed.path.startswith("/api/inbox-accounts/") and parsed.path.endswith("/labels/refresh"):
            if not self.require_admin_tab("setup", "edit"):
                return
            account_id = int(parsed.path.split("/")[-3])
            return self.respond_json(refresh_inbox_labels_response(account_id))
        if parsed.path == "/api/export-destinations":
            if not self.require_admin_tab("setup", "edit"):
                return
            return self.respond_json(save_export_destination(self.read_json()))
        if parsed.path == "/api/erp/oracle-ebs":
            if not self.require_admin_tab("erp", "edit"):
                return
            return self.respond_json(save_oracle_ebs_profile(self.read_json()))
        if parsed.path.startswith("/api/testing/golden-answers/") and parsed.path.endswith("/lines"):
            if not self.require_admin_tab("testing", "edit"):
                return
            header_id = int(parsed.path.split("/")[-2])
            return self.respond_json(create_golden_line(header_id, self.read_json()))
        if parsed.path.startswith("/api/master-data-reviews/") and parsed.path.endswith("/resolve"):
            if not self.require_admin_tab("master", "edit"):
                return
            review_id = int(parsed.path.split("/")[-2])
            return self.respond_json(resolve_master_data_review(review_id, self.read_json()))
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/master-data-reviews/run"):
            if not self.require_permission("po_dashboard:edit"):
                return
            po_id = int(parsed.path.split("/")[-3])
            return self.respond_json(run_purchase_order_master_data_reviews(po_id))
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/erp/oracle-ebs/preview"):
            if not self.require_permission("po_dashboard:view"):
                return
            if not self.require_admin_tab("erp", "edit"):
                return
            po_id = int(parsed.path.split("/")[-4])
            return self.respond_json(preview_oracle_ebs_payload(po_id))
        if parsed.path.startswith("/api/review-tasks/") and parsed.path.endswith("/resolve"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            task_id = int(parsed.path.split("/")[-2])
            return self.respond_json(resolve_review_task_action(task_id, actor, self.read_json()))
        if parsed.path.startswith("/api/review-tasks/") and parsed.path.endswith("/ignore"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            task_id = int(parsed.path.split("/")[-2])
            return self.respond_json(ignore_review_task_action(task_id, actor, self.read_json()))
        if parsed.path == "/api/review-tasks/bulk":
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            return self.respond_json(bulk_review_tasks_action(self.read_json(), actor))
        if parsed.path.startswith("/api/review-tasks/") and parsed.path.endswith("/assign"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            task_id = int(parsed.path.split("/")[-2])
            return self.respond_json(assign_review_task_action(task_id, self.read_json(), actor))
        if parsed.path.startswith("/api/duplicate-candidates/") and parsed.path.endswith("/action"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            candidate_id = int(parsed.path.split("/")[-2])
            return self.respond_json(duplicate_candidate_action(candidate_id, self.read_json(), actor))
        if parsed.path.startswith("/api/inbox-message-records/") and parsed.path.endswith("/retry"):
            if not self.require_admin_tab("testing", "edit"):
                return
            record_id = int(parsed.path.split("/")[-2])
            return self.respond_json(retry_inbox_message(record_id))
        if parsed.path.startswith("/api/inbox-accounts/") and parsed.path.endswith("/reprocess-range"):
            if not self.require_admin_tab("setup", "edit"):
                return
            account_id = int(parsed.path.split("/")[-2])
            payload = self.read_json()
            payload["sync_mode"] = "retry"
            return self.respond_json(sync_inbox_account(account_id, payload))
        if parsed.path == "/api/users":
            actor = self.require_permission("users:manage")
            if not actor:
                return
            return self.respond_json(create_user(self.read_json(), actor))
        if parsed.path == "/api/customers":
            if not self.require_admin_tab("master", "edit"):
                return
            return self.respond_json(create_customer(self.read_json()))
        if parsed.path.startswith("/api/customers/") and parsed.path.endswith("/addresses"):
            if not self.require_admin_tab("master", "edit"):
                return
            customer_id = int(parsed.path.split("/")[-2])
            return self.respond_json(create_customer_address(customer_id, self.read_json()))
        if parsed.path.startswith("/api/customers/") and parsed.path.endswith("/contacts"):
            if not self.require_admin_tab("master", "edit"):
                return
            customer_id = int(parsed.path.split("/")[-2])
            return self.respond_json(create_customer_contact(customer_id, self.read_json()))
        if parsed.path == "/api/import-samples":
            if not self.require_permission("po_dashboard:edit"):
                return
            with db() as conn:
                result = import_samples(conn, SAMPLES_DIR, STORAGE_DIR)
            return self.respond_json(result)
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/lines"):
            if not self.require_permission("po_dashboard:edit"):
                return
            po_id = int(parsed.path.split("/")[-2])
            payload = self.read_json()
            return self.respond_json(add_line(po_id, payload))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/users/"):
            actor = self.require_permission("users:manage")
            if not actor:
                return
            user_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_user(user_id, self.read_json(), actor))
        if parsed.path.startswith("/api/customer-addresses/"):
            if not self.require_admin_tab("master", "edit"):
                return
            address_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_customer_address(address_id, self.read_json()))
        if parsed.path.startswith("/api/customer-contacts/"):
            if not self.require_admin_tab("master", "edit"):
                return
            contact_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_customer_contact(contact_id, self.read_json()))
        if parsed.path.startswith("/api/customers/"):
            if not self.require_admin_tab("master", "edit"):
                return
            customer_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_customer(customer_id, self.read_json()))
        if parsed.path.startswith("/api/customer-part-xrefs/"):
            if not self.require_admin_tab("master", "edit"):
                return
            xref_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_customer_part_xref(xref_id, self.read_json()))
        if parsed.path.startswith("/api/products/"):
            if not self.require_admin_tab("master", "edit"):
                return
            product_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_product(product_id, self.read_json()))
        if parsed.path.startswith("/api/order-types/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            order_type_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_order_type(order_type_id, self.read_json()))
        if parsed.path.startswith("/api/departments/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            department_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_department(department_id, self.read_json()))
        if parsed.path.startswith("/api/payment-terms/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            payment_term_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_payment_term(payment_term_id, self.read_json()))
        if parsed.path.startswith("/api/testing/documents/") and parsed.path.endswith("/golden-answer"):
            if not self.require_admin_tab("testing", "edit"):
                return
            document_id = int(parsed.path.split("/")[-2])
            return self.respond_json(save_golden_answer(document_id, self.read_json()))
        if parsed.path.startswith("/api/testing/documents/"):
            if not self.require_admin_tab("testing", "edit"):
                return
            document_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_test_document(document_id, self.read_json()))
        if parsed.path.startswith("/api/testing/golden-lines/"):
            if not self.require_admin_tab("testing", "edit"):
                return
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_golden_line(line_id, self.read_json()))
        if parsed.path.startswith("/api/inbox-accounts/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            if parsed.path.endswith("/config"):
                account_id = int(parsed.path.split("/")[-2])
                return self.respond_json(save_inbox_config(account_id, self.read_json()))
            account_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_inbox_account(account_id, self.read_json()))
        if parsed.path.startswith("/api/export-destinations/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            destination_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(save_export_destination(self.read_json(), destination_id))
        if parsed.path.startswith("/api/purchase-orders/") and "/lines/" in parsed.path:
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_line(line_id, self.read_json(), actor))
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/mark-reviewed"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            po_id = int(parsed.path.split("/")[-2])
            return self.respond_json(mark_extraction_reviewed(po_id, actor))
        if parsed.path.startswith("/api/purchase-orders/"):
            actor = self.require_permission("po_dashboard:edit")
            if not actor:
                return
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_purchase_order(po_id, self.read_json(), actor))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/users/"):
            actor = self.require_permission("users:manage")
            if not actor:
                return
            user_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(deactivate_user(user_id, actor))
        if parsed.path.startswith("/api/customer-addresses/"):
            if not self.require_admin_tab("master", "edit"):
                return
            address_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_customer_address(address_id))
        if parsed.path.startswith("/api/customer-contacts/"):
            if not self.require_admin_tab("master", "edit"):
                return
            contact_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_customer_contact(contact_id))
        if parsed.path.startswith("/api/customers/"):
            if not self.require_admin_tab("master", "edit"):
                return
            customer_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_customer(customer_id))
        if parsed.path.startswith("/api/customer-part-xrefs/"):
            if not self.require_admin_tab("master", "edit"):
                return
            xref_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_customer_part_xref(xref_id))
        if parsed.path.startswith("/api/products/"):
            if not self.require_admin_tab("master", "edit"):
                return
            product_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_product(product_id))
        if parsed.path.startswith("/api/order-types/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            order_type_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_order_type(order_type_id))
        if parsed.path.startswith("/api/departments/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            department_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_department(department_id))
        if parsed.path.startswith("/api/payment-terms/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            payment_term_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_payment_term(payment_term_id))
        if parsed.path.startswith("/api/testing/documents/"):
            if not self.require_admin_tab("testing", "edit"):
                return
            document_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_test_document(document_id))
        if parsed.path.startswith("/api/testing/golden-lines/"):
            if not self.require_admin_tab("testing", "edit"):
                return
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_golden_line(line_id))
        if parsed.path.startswith("/api/inbox-accounts/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            account_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_inbox_account(account_id))
        if parsed.path.startswith("/api/export-destinations/"):
            if not self.require_admin_tab("setup", "edit"):
                return
            destination_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_export_destination(destination_id))
        if parsed.path.startswith("/api/purchase-orders/") and "/lines/" in parsed.path:
            if not self.require_permission("po_dashboard:edit"):
                return
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_line(line_id))
        if parsed.path.startswith("/api/purchase-orders/"):
            if not self.require_permission("po_dashboard:edit"):
                return
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_purchase_order(po_id))
        self.send_error(HTTPStatus.NOT_FOUND)

    def current_user(self) -> dict | None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        raw_token = cookie.get(SESSION_COOKIE_NAME)
        if not raw_token:
            return None
        token_hash = hash_session_token(raw_token.value)
        now = datetime.now(timezone.utc)
        with db() as conn:
            row = conn.execute(
                """
                SELECT us.id AS session_id, us.expires_at, u.*
                FROM user_sessions us
                JOIN users u ON u.id = us.user_id
                WHERE us.token_hash = ? AND us.revoked_at IS NULL AND u.is_active = 1
                """,
                (token_hash,),
            ).fetchone()
            if not row:
                return None
            expires_at = parse_iso_datetime(row["expires_at"])
            if not expires_at or expires_at <= now:
                conn.execute("UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE id = ?", (row["session_id"],))
                conn.commit()
                return None
            conn.execute("UPDATE user_sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE id = ?", (row["session_id"],))
            conn.commit()
            user = row_to_dict(row)
        user.pop("session_id", None)
        user.pop("expires_at", None)
        return user

    def session_cookie_header(self, token: str, max_age: int | None = None) -> str:
        parts = [f"{SESSION_COOKIE_NAME}={token}", "Path=/", "SameSite=Lax", "HttpOnly"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        if SESSION_COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_legacy_cookie_header(self) -> str:
        parts = ["poinbox_user_id=", "Path=/", "Max-Age=0", "SameSite=Lax", "HttpOnly"]
        if SESSION_COOKIE_SECURE:
            parts.append("Secure")
        return "; ".join(parts)

    def revoke_current_session(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        raw_token = cookie.get(SESSION_COOKIE_NAME)
        if not raw_token:
            return None
        with db() as conn:
            conn.execute(
                "UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE token_hash = ? AND revoked_at IS NULL",
                (hash_session_token(raw_token.value),),
            )
            conn.commit()

    def require_permission(self, permission: str) -> dict | None:
        user = self.current_user()
        if has_permission(user, permission):
            return user
        status = HTTPStatus.UNAUTHORIZED if not user else HTTPStatus.FORBIDDEN
        with db() as conn:
            conn.execute(
                """
                INSERT INTO processing_logs (level, message, metadata_json)
                VALUES ('warning', ?, ?)
                """,
                (
                    "Denied access attempt.",
                    json.dumps({"permission": permission, "user_id": user.get("id") if user else None, "path": self.path}),
                ),
            )
            conn.commit()
        self.respond_json({"error": "permission_denied", "permission": permission}, status)
        return None

    def require_admin_tab(self, tab_key: str, mode: str = "view") -> dict | None:
        permission = f"admin:{tab_key}:{'edit' if mode == 'edit' else 'view'}"
        return self.require_permission(permission)

    def require_any_admin_tab(self, tab_keys: tuple[str, ...], mode: str = "view") -> dict | None:
        user = self.current_user()
        action = "edit" if mode == "edit" else "view"
        permissions = [f"admin:{tab}:{action}" for tab in tab_keys]
        if user and any(has_permission(user, permission) for permission in permissions):
            return user
        status = HTTPStatus.UNAUTHORIZED if not user else HTTPStatus.FORBIDDEN
        with db() as conn:
            conn.execute(
                """
                INSERT INTO processing_logs (level, message, metadata_json)
                VALUES ('warning', ?, ?)
                """,
                (
                    "Denied access attempt.",
                    json.dumps({"permission": "any_admin_tab", "permissions": permissions, "user_id": user.get("id") if user else None, "path": self.path}),
                ),
            )
            conn.commit()
        self.respond_json({"error": "permission_denied", "permissions": permissions}, status)
        return None

    def login(self) -> None:
        payload = self.read_json()
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        with db() as conn:
            user = row_to_dict(conn.execute("SELECT * FROM users WHERE LOWER(email) = ? AND is_active = 1", (email,)).fetchone())
        if not user:
            return self.respond_json({"error": "No active user found for that email."}, HTTPStatus.UNAUTHORIZED)
        if not verify_password(password, user.get("password_hash")):
            return self.respond_json({"error": "Invalid email or password."}, HTTPStatus.UNAUTHORIZED)
        token = new_session_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)
        with db() as conn:
            conn.execute(
                """
                INSERT INTO user_sessions (user_id, token_hash, expires_at)
                VALUES (?, ?, ?)
                """,
                (user["id"], hash_session_token(token), expires_at.isoformat()),
            )
            conn.commit()
        body = json.dumps({"user": public_user(user)}, default=str).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", self.session_cookie_header(token))
        self.send_header("Set-Cookie", self.clear_legacy_cookie_header())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def logout(self) -> None:
        self.revoke_current_session()
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Set-Cookie", self.session_cookie_header("", 0))
        self.send_header("Set-Cookie", self.clear_legacy_cookie_header())
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def respond_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_csv(self, body_text: str, filename: str) -> None:
        body = body_text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_html(self, body_text: str, status: int = 200) -> None:
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_attachment(self, attachment_id: int) -> None:
        with db() as conn:
            attachment = conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()
        if not attachment:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        path = Path(attachment["local_path"]).resolve()
        storage_root = STORAGE_DIR.resolve()
        try:
            path.relative_to(storage_root)
        except ValueError:
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        if not path.exists() or path.suffix.lower() != ".pdf":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        data = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/pdf")
        self.send_header("Content-Disposition", f'inline; filename="{path.name}"')
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def db():
    conn = connect(DATABASE_PATH)
    initialize(conn)
    return conn


def clean_admin_tab_access_level(value: object) -> str:
    text = str(value or "no_access").strip().lower()
    aliases = {
        "full": "full_access",
        "edit": "full_access",
        "full_access": "full_access",
        "view": "view_only",
        "view_only": "view_only",
        "none": "no_access",
        "no": "no_access",
        "no_access": "no_access",
    }
    return aliases.get(text, "no_access")


def default_admin_tab_permissions(user: dict | None) -> dict[str, str]:
    permissions = {tab: "no_access" for tab in ADMIN_TABS}
    if not user:
        return permissions
    if int(user.get("is_admin") or 0):
        return {tab: "full_access" for tab in ADMIN_TABS}
    if int(user.get("can_access_admin") or 0):
        for tab in ("master", "setup", "testing", "analytics", "erp"):
            permissions[tab] = "full_access"
    return permissions


def admin_tab_permissions_for_user(user: dict | None) -> dict[str, str]:
    permissions = default_admin_tab_permissions(user)
    if not user:
        return permissions
    if int(user.get("is_admin") or 0):
        return permissions
    with db() as conn:
        rows = conn.execute(
            "SELECT tab_key, access_level FROM user_admin_tab_permissions WHERE user_id = ?",
            (user.get("id"),),
        ).fetchall()
    for row in rows:
        tab = row["tab_key"]
        if tab in permissions:
            permissions[tab] = clean_admin_tab_access_level(row["access_level"])
    if not int(user.get("can_access_admin") or 0):
        permissions = {tab: "no_access" for tab in ADMIN_TABS}
    return permissions


def save_admin_tab_permissions(conn, user_id: int, permissions: dict | None, is_admin: int, can_access_admin: int) -> None:
    clean_permissions = default_admin_tab_permissions({"is_admin": is_admin, "can_access_admin": can_access_admin})
    if permissions:
        for tab in ADMIN_TABS:
            if tab in permissions:
                clean_permissions[tab] = clean_admin_tab_access_level(permissions.get(tab))
    if is_admin:
        clean_permissions = {tab: "full_access" for tab in ADMIN_TABS}
    elif not can_access_admin:
        clean_permissions = {tab: "no_access" for tab in ADMIN_TABS}
    for tab, access_level in clean_permissions.items():
        conn.execute(
            """
            INSERT INTO user_admin_tab_permissions (user_id, tab_key, access_level)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, tab_key) DO UPDATE SET
                access_level = excluded.access_level,
                updated_at = CURRENT_TIMESTAMP
            """,
            (user_id, tab, access_level),
        )


def permissions_for(user: dict | None) -> list[str]:
    if not user:
        return []
    permissions: list[str] = []
    tab_permissions = admin_tab_permissions_for_user(user)
    if any(level != "no_access" for level in tab_permissions.values()):
        permissions.append("admin:view")
    for tab, level in tab_permissions.items():
        if level in {"view_only", "full_access"}:
            permissions.append(f"admin:{tab}:view")
        if level == "full_access":
            permissions.append(f"admin:{tab}:edit")
    if tab_permissions.get("users") in {"view_only", "full_access"}:
        permissions.append("users:view")
    if tab_permissions.get("users") == "full_access":
        permissions.append("users:manage")
    if tab_permissions.get("setup") in {"view_only", "full_access"} or tab_permissions.get("testing") in {"view_only", "full_access"}:
        permissions.append("integrations:view")
    if tab_permissions.get("setup") == "full_access" or tab_permissions.get("testing") == "full_access":
        permissions.append("integrations:manage")
    if int(user.get("can_access_po_dashboard") or 0):
        permissions.append("po_dashboard:view")
        if user.get("po_dashboard_access_level") == "edit":
            permissions.append("po_dashboard:edit")
    return permissions


def has_permission(user: dict | None, permission: str) -> bool:
    return permission in permissions_for(user)


def public_user(user: dict | None) -> dict | None:
    if not user:
        return None
    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    display_name = " ".join(part for part in (first_name, last_name) if part).strip() or user.get("name") or user.get("email")
    clean = {
        "id": user.get("id"),
        "email": user.get("email"),
        "name": display_name,
        "display_name": display_name,
        "first_name": first_name,
        "last_name": last_name,
        "job_title": user.get("job_title") or "",
        "is_active": bool(user.get("is_active")),
        "is_admin": bool(user.get("is_admin")),
        "can_access_admin": bool(user.get("can_access_admin")),
        "can_access_po_dashboard": bool(user.get("can_access_po_dashboard")),
        "po_dashboard_access_level": user.get("po_dashboard_access_level"),
        "password_configured": bool(user.get("password_hash")),
        "password_reset_required": bool(user.get("password_reset_required")),
        "invited_at": user.get("invited_at"),
        "created_at": user.get("created_at"),
        "updated_at": user.get("updated_at"),
    }
    clean["admin_tab_permissions"] = admin_tab_permissions_for_user(user)
    clean["permissions"] = permissions_for(user)
    return clean


def bool_int(value: object) -> int:
    return 1 if value in (True, 1, "1", "true", "on", "yes") else 0


def clean_access_level(value: object) -> str:
    text = str(value or "none")
    return text if text in {"none", "view_only", "edit"} else "none"


def list_users() -> list[dict]:
    with db() as conn:
        rows = rows_to_dicts(conn.execute("SELECT * FROM users ORDER BY is_active DESC, last_name, first_name, name").fetchall())
    return [public_user(row) for row in rows]


def create_user(payload: dict, actor: dict) -> dict:
    email = (payload.get("email") or "").strip().lower()
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    job_title = (payload.get("job_title") or "").strip()
    name = " ".join(part for part in (first_name, last_name) if part).strip() or (payload.get("name") or "").strip()
    if not email or not first_name or not last_name:
        return {"error": "first_last_and_email_required", "users": list_users()}
    password = (payload.get("password") or "").strip()
    generated_password = ""
    if not password:
        generated_password = generate_temporary_password()
        password = generated_password
    is_admin = bool_int(payload.get("is_admin"))
    can_access_admin = bool_int(payload.get("can_access_admin") or is_admin)
    can_access_po_dashboard = bool_int(payload.get("can_access_po_dashboard", True) or is_admin)
    access_level = clean_access_level(payload.get("po_dashboard_access_level") or ("edit" if is_admin else "view_only"))
    if not can_access_po_dashboard:
        access_level = "none"
    with db() as conn:
        try:
            cur = conn.execute(
                """
                INSERT INTO users (
                    email, name, first_name, last_name, job_title, is_active, is_admin, can_access_admin,
                    can_access_po_dashboard, po_dashboard_access_level, password_hash, password_set_at,
                    password_reset_required
                )
                VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                """,
                (
                    email,
                    name,
                    first_name,
                    last_name,
                    job_title,
                    is_admin,
                    can_access_admin,
                    can_access_po_dashboard,
                    access_level,
                    hash_password(password),
                    bool_int(bool(generated_password)),
                ),
            )
            save_admin_tab_permissions(conn, int(cur.lastrowid), payload.get("admin_tab_permissions"), is_admin, can_access_admin)
        except Exception:
            return {"error": "A user with that email already exists.", "users": list_users()}
        conn.execute(
            """
            INSERT INTO processing_logs (level, message, metadata_json)
            VALUES ('info', ?, ?)
            """,
            ("User invited/created.", json.dumps({"email": email, "actor_id": actor.get("id")})),
        )
        conn.commit()
    result = {"users": list_users()}
    if generated_password:
        result["temporary_password"] = generated_password
    return result


def update_user(user_id: int, payload: dict, actor: dict) -> dict:
    allowed = {
        "email",
        "name",
        "first_name",
        "last_name",
        "job_title",
        "is_active",
        "is_admin",
        "can_access_admin",
        "can_access_po_dashboard",
        "po_dashboard_access_level",
    }
    with db() as conn:
        existing = row_to_dict(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())
        if not existing:
            return {"error": "not_found", "users": list_users()}
        updated = dict(existing)
        for key in allowed:
            if key not in payload:
                continue
            if key in {"is_active", "is_admin", "can_access_admin", "can_access_po_dashboard"}:
                updated[key] = bool_int(payload[key])
            elif key == "po_dashboard_access_level":
                updated[key] = clean_access_level(payload[key])
            elif key == "email":
                updated[key] = (payload[key] or "").strip().lower()
            else:
                updated[key] = (payload[key] or "").strip()
        if "first_name" in payload or "last_name" in payload:
            updated["name"] = " ".join(part for part in (updated.get("first_name"), updated.get("last_name")) if part).strip()
        if not updated["can_access_po_dashboard"]:
            updated["po_dashboard_access_level"] = "none"
        if active_admin_count(conn) <= 1 and int(existing.get("is_active") or 0) and int(existing.get("is_admin") or 0):
            if not int(updated.get("is_active") or 0) or not int(updated.get("is_admin") or 0):
                return {"error": "Cannot remove or deactivate the last active admin.", "users": list_users()}
        if not updated["email"] or not updated.get("first_name") or not updated.get("last_name"):
            return {"error": "First name, last name, and email are required.", "users": list_users()}
        try:
            conn.execute(
                """
                UPDATE users
                SET email = ?, name = ?, first_name = ?, last_name = ?, job_title = ?,
                    is_active = ?, is_admin = ?, can_access_admin = ?,
                    can_access_po_dashboard = ?, po_dashboard_access_level = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    updated["email"],
                    updated["name"],
                    updated.get("first_name"),
                    updated.get("last_name"),
                    updated.get("job_title"),
                    updated["is_active"],
                    updated["is_admin"],
                    updated["can_access_admin"],
                    updated["can_access_po_dashboard"],
                    updated["po_dashboard_access_level"],
                    user_id,
                ),
            )
            new_password = (payload.get("new_password") or "").strip()
            if new_password:
                conn.execute(
                    """
                    UPDATE users
                    SET password_hash = ?, password_set_at = CURRENT_TIMESTAMP, password_reset_required = 0,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (hash_password(new_password), user_id),
                )
                conn.execute(
                    "UPDATE user_sessions SET revoked_at = CURRENT_TIMESTAMP WHERE user_id = ? AND revoked_at IS NULL",
                    (user_id,),
                )
            if "admin_tab_permissions" in payload or "is_admin" in payload or "can_access_admin" in payload:
                save_admin_tab_permissions(
                    conn,
                    user_id,
                    payload.get("admin_tab_permissions"),
                    int(updated.get("is_admin") or 0),
                    int(updated.get("can_access_admin") or 0),
                )
        except Exception:
            return {"error": "A user with that email already exists.", "users": list_users()}
        conn.execute(
            """
            INSERT INTO processing_logs (level, message, metadata_json)
            VALUES ('info', ?, ?)
            """,
            ("User permissions updated.", json.dumps({"user_id": user_id, "actor_id": actor.get("id")})),
        )
        conn.commit()
    return {"users": list_users()}


def deactivate_user(user_id: int, actor: dict) -> dict:
    return update_user(user_id, {"is_active": False}, actor)


def active_admin_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS count FROM users WHERE is_active = 1 AND is_admin = 1").fetchone()["count"]


MASTER_BRIDGE_TABLES = [
    ("trading_partner", "Trading Partners"),
    ("trading_partner_account", "Trading Partner Accounts"),
    ("trading_partner_site", "Trading Partner Sites"),
    ("partner_role_assignment", "Partner Roles"),
    ("product", "Canonical Products"),
    ("product_org_attributes", "Product Org Attributes"),
    ("customer_product_alias", "Customer Product Aliases"),
]

SETUP_REFERENCE_TABLES = [
    ("organization_unit", "Organization Units"),
    ("selling_context", "Selling Contexts / Sales Areas"),
    ("fulfillment_location", "Fulfillment Locations"),
    ("unit_of_measure", "Units of Measure"),
    ("uom_alias", "UOM Aliases"),
    ("uom_conversion", "UOM Conversions"),
    ("currency", "Currencies"),
    ("payment_terms", "Payment Terms"),
    ("shipping_terms", "Shipping Terms"),
    ("freight_terms", "Freight Terms"),
    ("delivery_method", "Delivery Methods"),
    ("price_reference", "Price References"),
    ("order_document_type", "Order Document Types"),
    ("line_document_type", "Line Document Types"),
]

ERP_DIAGNOSTIC_TABLES = [
    ("erp_system", "ERP Systems"),
    ("erp_profile", "ERP Profiles"),
    ("custom_field_definition", "Custom Field Definitions"),
    ("custom_field_value", "Custom Field Values"),
    ("external_id_map", "External ID Maps"),
    ("validation_rule", "Validation Rules"),
]

CANONICAL_MASTER_TABLES = ERP_DIAGNOSTIC_TABLES[:2] + MASTER_BRIDGE_TABLES + SETUP_REFERENCE_TABLES + ERP_DIAGNOSTIC_TABLES[2:]


def canonical_table_counts(conn, table_defs: list[tuple[str, str]]) -> list[dict]:
    return [
        {
            "table": table,
            "label": label,
            "count": conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"],
        }
        for table, label in table_defs
    ]


def list_canonical_master_data() -> dict:
    with db() as conn:
        counts = canonical_table_counts(conn, CANONICAL_MASTER_TABLES)
        groups = {
            "master_bridge": canonical_table_counts(conn, MASTER_BRIDGE_TABLES),
            "setup_reference": canonical_table_counts(conn, SETUP_REFERENCE_TABLES),
            "erp_diagnostics": canonical_table_counts(conn, ERP_DIAGNOSTIC_TABLES),
        }
        bridge_counts = {
            "customers_to_accounts": conn.execute(
                "SELECT COUNT(*) AS count FROM trading_partner_account WHERE legacy_source_table = 'customers'"
            ).fetchone()["count"],
            "addresses_to_sites": conn.execute(
                "SELECT COUNT(*) AS count FROM trading_partner_site WHERE legacy_source_table = 'customer_addresses'"
            ).fetchone()["count"],
            "xrefs_to_aliases": conn.execute(
                "SELECT COUNT(*) AS count FROM customer_product_alias WHERE legacy_source_table = 'customer_part_xrefs'"
            ).fetchone()["count"],
            "products_to_canonical": conn.execute(
                "SELECT COUNT(*) AS count FROM product WHERE legacy_source_table = 'products'"
            ).fetchone()["count"],
            "order_types_to_document_types": conn.execute(
                "SELECT COUNT(*) AS count FROM order_document_type WHERE legacy_source_table = 'order_types'"
            ).fetchone()["count"],
        }
        samples = {
            "accounts": rows_to_dicts(
                conn.execute(
                    """
                    SELECT id, account_name, account_number, legacy_source_table, legacy_source_id
                    FROM trading_partner_account
                    ORDER BY id DESC LIMIT 5
                    """
                ).fetchall()
            ),
            "aliases": rows_to_dicts(
                conn.execute(
                    """
                    SELECT cpa.id, tpa.account_name, cpa.customer_product_number,
                           p.product_number, cpa.legacy_source_table, cpa.legacy_source_id
                    FROM customer_product_alias cpa
                    LEFT JOIN trading_partner_account tpa ON tpa.id = cpa.trading_partner_account_id
                    LEFT JOIN product p ON p.id = cpa.product_id
                    ORDER BY cpa.id DESC LIMIT 5
                    """
                ).fetchall()
            ),
            "external_id_maps": rows_to_dicts(
                conn.execute(
                    """
                    SELECT id, canonical_entity_type, canonical_entity_id, external_entity_type,
                           external_id, external_code, external_name
                    FROM external_id_map
                    ORDER BY id DESC LIMIT 5
                    """
                ).fetchall()
            ),
            "setup_references": rows_to_dicts(
                conn.execute(
                    """
                    SELECT 'Organization Unit' AS surface, name AS display_name, COALESCE(code, org_type) AS detail
                    FROM organization_unit
                    UNION ALL
                    SELECT 'Selling Context', COALESCE(name, channel_code || ' / ' || division_code), COALESCE(channel_code, '') || COALESCE(' / ' || division_code, '')
                    FROM selling_context
                    UNION ALL
                    SELECT 'Fulfillment Location', location_name, COALESCE(location_code, location_type)
                    FROM fulfillment_location
                    UNION ALL
                    SELECT 'Order Document Type', document_type_name, COALESCE(document_type_code, transaction_category)
                    FROM order_document_type
                    UNION ALL
                    SELECT 'Line Document Type', line_type_name, COALESCE(line_type_code, line_category)
                    FROM line_document_type
                    UNION ALL
                    SELECT 'UOM', uom_code, COALESCE(uom_name, uom_class)
                    FROM unit_of_measure
                    UNION ALL
                    SELECT 'Currency', currency_code, currency_name
                    FROM currency
                    UNION ALL
                    SELECT 'Price Reference', name, COALESCE(code, price_reference_type)
                    FROM price_reference
                    LIMIT 12
                    """
                ).fetchall()
            ),
        }
    return {"counts": counts, "groups": groups, "bridge_counts": bridge_counts, "samples": samples}


def run_canonical_master_data_backfill() -> dict:
    with db() as conn:
        stats = backfill_canonical_master_data(conn)
        conn.commit()
    data = list_canonical_master_data()
    data["backfill"] = stats
    return data


def list_customers() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(
            conn.execute(
                """
                SELECT c.*,
                    COALESCE(pt.name, c.payment_terms) AS payment_terms_display,
                    COUNT(DISTINCT CASE WHEN ca.address_type = 'bill_to' THEN ca.id END) AS bill_to_count,
                    COUNT(DISTINCT CASE WHEN ca.address_type = 'ship_to' THEN ca.id END) AS ship_to_count,
                    COUNT(DISTINCT cc.id) AS contact_count
                FROM customers c
                LEFT JOIN customer_addresses ca ON ca.customer_id = c.id
                LEFT JOIN customer_contacts cc ON cc.customer_id = c.id
                LEFT JOIN payment_terms pt ON pt.id = c.payment_terms_id
                GROUP BY c.id
                ORDER BY c.customer_name
                """
            ).fetchall()
        )


def get_customer(customer_id: int) -> dict:
    with db() as conn:
        customer = row_to_dict(
            conn.execute(
                """
                SELECT c.*, COALESCE(pt.name, c.payment_terms) AS payment_terms_display
                FROM customers c
                LEFT JOIN payment_terms pt ON pt.id = c.payment_terms_id
                WHERE c.id = ?
                """,
                (customer_id,),
            ).fetchone()
        )
        if not customer:
            return {"error": "not_found"}
        addresses = rows_to_dicts(
            conn.execute("SELECT * FROM customer_addresses WHERE customer_id = ? ORDER BY address_type, is_default DESC, label", (customer_id,)).fetchall()
        )
        contacts = rows_to_dicts(
            conn.execute("SELECT * FROM customer_contacts WHERE customer_id = ? ORDER BY last_name, first_name", (customer_id,)).fetchall()
        )
    return {"customer": customer, "addresses": addresses, "contacts": contacts}


def create_customer(payload: dict) -> dict:
    name = (payload.get("customer_name") or "").strip()
    if not name:
        return {"error": "customer_name_required", "customers": list_customers()}
    payment_terms_id, payment_terms = resolve_payment_term_payload(payload)
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO customers (customer_name, customer_number, payment_terms, payment_terms_id) VALUES (?, ?, ?, ?)",
            (name, (payload.get("customer_number") or "").strip(), payment_terms, payment_terms_id),
        )
        conn.commit()
        return get_customer(int(cur.lastrowid))


def update_customer(customer_id: int, payload: dict) -> dict:
    name = (payload.get("customer_name") or "").strip()
    if not name:
        return {"error": "customer_name_required"}
    payment_terms_id, payment_terms = resolve_payment_term_payload(payload)
    with db() as conn:
        conn.execute(
            """
            UPDATE customers
            SET customer_name = ?, customer_number = ?, payment_terms = ?, payment_terms_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, (payload.get("customer_number") or "").strip(), payment_terms, payment_terms_id, customer_id),
        )
        conn.commit()
    return get_customer(customer_id)


def resolve_payment_term_payload(payload: dict) -> tuple[int | None, str]:
    payment_terms_id = int(payload.get("payment_terms_id") or 0) or None
    payment_terms = (payload.get("payment_terms") or "").strip()
    with db() as conn:
        if payment_terms_id:
            row = conn.execute("SELECT name FROM payment_terms WHERE id = ?", (payment_terms_id,)).fetchone()
            if row:
                return payment_terms_id, row["name"]
        if payment_terms:
            row = conn.execute("SELECT id, name FROM payment_terms WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (payment_terms,)).fetchone()
            if row:
                return row["id"], row["name"]
    return None, payment_terms


def delete_customer(customer_id: int) -> dict:
    with db() as conn:
        conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        conn.commit()
    return {"ok": True, "customers": list_customers()}


def create_customer_address(customer_id: int, payload: dict) -> dict:
    address_type = payload.get("address_type") if payload.get("address_type") in {"bill_to", "ship_to"} else "bill_to"
    address = clean_address_payload(payload)
    with db() as conn:
        cur = conn.execute(
            """
            INSERT INTO customer_addresses (
                customer_id, address_type, label, address_text, address_line_1, address_line_2,
                address_line_3, city, state, country, zip_code, is_default
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                address_type,
                address["label"],
                address["address_text"],
                address["address_line_1"],
                address["address_line_2"],
                address["address_line_3"],
                address["city"],
                address["state"],
                address["country"],
                address["zip_code"],
                bool_int(payload.get("is_default")),
            ),
        )
        resolve_matching_address_reviews_for_customer(conn, customer_id, address_type, int(cur.lastrowid))
        conn.commit()
    return get_customer(customer_id)


def update_customer_address(address_id: int, payload: dict) -> dict:
    address_type = payload.get("address_type") if payload.get("address_type") in {"bill_to", "ship_to"} else "bill_to"
    address = clean_address_payload(payload)
    with db() as conn:
        row = conn.execute("SELECT customer_id FROM customer_addresses WHERE id = ?", (address_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE customer_addresses
            SET address_type = ?, label = ?, address_text = ?, address_line_1 = ?, address_line_2 = ?,
                address_line_3 = ?, city = ?, state = ?, country = ?, zip_code = ?, is_default = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                address_type,
                address["label"],
                address["address_text"],
                address["address_line_1"],
                address["address_line_2"],
                address["address_line_3"],
                address["city"],
                address["state"],
                address["country"],
                address["zip_code"],
                bool_int(payload.get("is_default")),
                address_id,
            ),
        )
        resolve_matching_address_reviews_for_customer(conn, row["customer_id"], address_type, address_id)
        conn.commit()
        return get_customer(row["customer_id"])


def clean_address_payload(payload: dict) -> dict:
    address = {
        "label": (payload.get("label") or "").strip(),
        "address_line_1": (payload.get("address_line_1") or "").strip(),
        "address_line_2": (payload.get("address_line_2") or "").strip(),
        "address_line_3": (payload.get("address_line_3") or "").strip(),
        "city": (payload.get("city") or "").strip(),
        "state": (payload.get("state") or "").strip(),
        "country": (payload.get("country") or "").strip(),
        "zip_code": (payload.get("zip_code") or "").strip(),
    }
    address["address_text"] = (payload.get("address_text") or "").strip() or format_structured_address(address)
    return address


def resolve_matching_address_reviews_for_customer(conn, customer_id: int, address_type: str, address_id: int) -> None:
    review_type = "ship_to_address" if address_type == "ship_to" else "bill_to_address"
    address = conn.execute("SELECT * FROM customer_addresses WHERE id = ?", (address_id,)).fetchone()
    if not address:
        return
    rows = conn.execute(
        """
        SELECT r.*, po.bill_to_address, po.ship_to_address, po.bill_to_address_structured_json,
               po.ship_to_address_structured_json
        FROM po_master_data_reviews r
        JOIN purchase_orders po ON po.id = r.purchase_order_id
        WHERE r.review_type = ? AND r.status = 'open'
          AND (r.matched_customer_id = ? OR r.matched_customer_id IS NULL)
        """,
        (review_type, customer_id),
    ).fetchall()
    for row in rows:
        text_value = row["ship_to_address"] if review_type == "ship_to_address" else row["bill_to_address"]
        json_value = row["ship_to_address_structured_json"] if review_type == "ship_to_address" else row["bill_to_address_structured_json"]
        structured = {}
        if json_value:
            try:
                structured = json.loads(json_value)
            except json.JSONDecodeError:
                structured = {}
        suggested = {}
        try:
            suggested = json.loads(row["suggested_value_json"] or "{}")
        except json.JSONDecodeError:
            suggested = {}
        if addresses_match(structured or text_value or suggested, address) or addresses_match(suggested, address):
            resolve_review(conn, row["id"], customer_id, address_id)
            conn.execute(
                """
                INSERT INTO processing_logs (level, message, metadata_json)
                VALUES ('info', ?, ?)
                """,
                (
                    "Master-data address review resolved by adding customer address.",
                    json.dumps({"purchase_order_id": row["purchase_order_id"], "review_id": row["id"], "customer_id": customer_id, "address_id": address_id, "review_type": review_type}),
                ),
            )


def delete_customer_address(address_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT customer_id FROM customer_addresses WHERE id = ?", (address_id,)).fetchone()
        if not row:
            return {"ok": True}
        conn.execute("DELETE FROM customer_addresses WHERE id = ?", (address_id,))
        conn.commit()
        return get_customer(row["customer_id"])


def create_customer_contact(customer_id: int, payload: dict) -> dict:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO customer_contacts (customer_id, first_name, last_name, job_title, phone_number, email)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                customer_id,
                (payload.get("first_name") or "").strip(),
                (payload.get("last_name") or "").strip(),
                (payload.get("job_title") or "").strip(),
                (payload.get("phone_number") or "").strip(),
                (payload.get("email") or "").strip(),
            ),
        )
        conn.commit()
    return get_customer(customer_id)


def update_customer_contact(contact_id: int, payload: dict) -> dict:
    with db() as conn:
        row = conn.execute("SELECT customer_id FROM customer_contacts WHERE id = ?", (contact_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE customer_contacts
            SET first_name = ?, last_name = ?, job_title = ?, phone_number = ?, email = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                (payload.get("first_name") or "").strip(),
                (payload.get("last_name") or "").strip(),
                (payload.get("job_title") or "").strip(),
                (payload.get("phone_number") or "").strip(),
                (payload.get("email") or "").strip(),
                contact_id,
            ),
        )
        conn.commit()
        return get_customer(row["customer_id"])


def delete_customer_contact(contact_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT customer_id FROM customer_contacts WHERE id = ?", (contact_id,)).fetchone()
        if not row:
            return {"ok": True}
        conn.execute("DELETE FROM customer_contacts WHERE id = ?", (contact_id,))
        conn.commit()
        return get_customer(row["customer_id"])


def customers_csv(mode: str) -> str:
    output = io.StringIO()
    if mode == "addresses":
        fields = [
            "customer_name",
            "customer_number",
            "payment_terms",
            "address_type",
            "label",
            "address_line_1",
            "address_line_2",
            "address_line_3",
            "city",
            "state",
            "country",
            "zip_code",
            "is_default",
        ]
    else:
        fields = ["customer_name", "customer_number", "payment_terms"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    with db() as conn:
        customers = rows_to_dicts(conn.execute("SELECT * FROM customers ORDER BY customer_name").fetchall())
        for customer in customers:
            base = {
                "customer_name": customer.get("customer_name"),
                "customer_number": customer.get("customer_number"),
                "payment_terms": customer.get("payment_terms"),
            }
            if mode != "addresses":
                writer.writerow(base)
                continue
            addresses = rows_to_dicts(
                conn.execute("SELECT * FROM customer_addresses WHERE customer_id = ? ORDER BY address_type, is_default DESC, label", (customer["id"],)).fetchall()
            )
            if not addresses:
                writer.writerow({**base, **{field: "" for field in fields if field not in base}})
                continue
            for address in addresses:
                writer.writerow(
                    {
                        **base,
                        "address_type": address.get("address_type"),
                        "label": address.get("label"),
                        "address_line_1": address.get("address_line_1"),
                        "address_line_2": address.get("address_line_2"),
                        "address_line_3": address.get("address_line_3"),
                        "city": address.get("city"),
                        "state": address.get("state"),
                        "country": address.get("country"),
                        "zip_code": address.get("zip_code"),
                        "is_default": address.get("is_default"),
                    }
                )
    return output.getvalue()


def customer_contacts_csv() -> str:
    output = io.StringIO()
    fields = ["customer_name", "customer_number", "first_name", "last_name", "job_title", "phone_number", "email"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    with db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT c.customer_name, c.customer_number, cc.first_name, cc.last_name, cc.job_title, cc.phone_number, cc.email
                FROM customer_contacts cc
                JOIN customers c ON c.id = cc.customer_id
                ORDER BY c.customer_name, cc.last_name, cc.first_name
                """
            ).fetchall()
        )
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def get_summary() -> dict:
    with db() as conn:
        rows = conn.execute("SELECT status, COUNT(*) AS count FROM purchase_orders GROUP BY status").fetchall()
        total_emails = conn.execute("SELECT COUNT(*) AS count FROM emails").fetchone()["count"]
        total_pos = conn.execute("SELECT COUNT(*) AS count FROM purchase_orders").fetchone()["count"]
    counts = {"Received": 0, "Needs Review": 0, "Booked": 0, "Rejected": 0}
    for row in rows:
        counts[row["status"]] = row["count"]
    return {"status_counts": counts, "total_emails": total_emails, "total_purchase_orders": total_pos}


def list_purchase_orders(params: dict[str, list[str]]) -> list[dict]:
    query, args = purchase_order_query(params)
    query += " GROUP BY po.id ORDER BY po.updated_at DESC"
    with db() as conn:
        return rows_to_dicts(conn.execute(query, args).fetchall())


def purchase_order_query(params: dict[str, list[str]]) -> tuple[str, list[object]]:
    status = params.get("status", [""])[0]
    search = params.get("search", [""])[0].lower()
    query = """
        SELECT po.*, ot.name AS order_type_name, e.provider AS email_provider,
            CASE
                WHEN po.source_type = 'email' OR e.provider IN ('gmail', 'outlook') THEN COALESCE(NULLIF(po.source_sender, ''), 'Email')
                WHEN po.source_type = 'sample_import' OR e.provider = 'sample' THEN 'Sample Import'
                WHEN po.source_type = 'manual' THEN 'Manually Entered'
                ELSE 'Unknown'
            END AS source_display,
            COUNT(DISTINCT pol.id) AS line_count,
            COUNT(DISTINCT CASE WHEN rt.status = 'open' THEN rt.id END) AS open_exception_count
        FROM purchase_orders po
        LEFT JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id
        LEFT JOIN review_tasks rt ON rt.purchase_order_id = po.id
        LEFT JOIN order_types ot ON ot.id = po.order_type_id
        LEFT JOIN emails e ON e.id = po.email_id
    """
    clauses = []
    args: list[object] = []
    if status:
        clauses.append("po.status = ?")
        args.append(status)
    if search:
        clauses.append("(LOWER(po.customer_company_name) LIKE ? OR LOWER(po.po_number) LIKE ? OR LOWER(po.source_sender) LIKE ?)")
        args.extend([f"%{search}%", f"%{search}%", f"%{search}%"])
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    return query, args


def get_purchase_order(po_id: int) -> dict:
    with db() as conn:
        po = row_to_dict(conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone())
        if not po:
            return {"error": "not_found"}
        email = row_to_dict(conn.execute("SELECT * FROM emails WHERE id = ?", (po["email_id"],)).fetchone())
        po["source_display"] = source_display(po, email)
        lines = rows_to_dicts(conn.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id = ? ORDER BY id", (po_id,)).fetchall())
        attachment = None
        if po["attachment_id"]:
            attachment = row_to_dict(conn.execute("SELECT * FROM attachments WHERE id = ?", (po["attachment_id"],)).fetchone())
        order_types = rows_to_dicts(
            conn.execute(
                "SELECT * FROM order_types WHERE is_active = 1 OR id = ? ORDER BY is_active DESC, name",
                (po.get("order_type_id") or -1,),
            ).fetchall()
        )
        if po.get("order_type_id"):
            order_type = row_to_dict(conn.execute("SELECT * FROM order_types WHERE id = ?", (po["order_type_id"],)).fetchone())
            po["order_type_name"] = order_type["name"] if order_type else None
        run_master_data_reviews(conn, po_id)
        generate_review_tasks_for_po(conn, po_id)
        review_tasks = list_review_tasks_for_po(conn, po_id)
        evidence = list_extraction_evidence_for_po(conn, po_id)
        duplicate_candidates = list_duplicate_candidates_for_po(conn, po_id)
        audit_events = list_audit_events_for_po(conn, po_id)
        reviews = list_reviews(conn, po_id)
        return {
            "purchase_order": po,
            "lines": lines,
            "email": email,
            "attachment": attachment,
            "order_types": order_types,
            "master_data_reviews": reviews,
            "review_tasks": review_tasks,
            "source_evidence": evidence,
            "duplicate_candidates": duplicate_candidates,
            "audit_events": audit_events,
        }


def source_display(po: dict, email: dict | None = None) -> str:
    provider = (email or {}).get("provider") or ""
    source_type = po.get("source_type") or ""
    if source_type == "email" or provider in {"gmail", "outlook"}:
        return po.get("source_sender") or "Email"
    if source_type == "sample_import" or provider == "sample":
        return "Sample Import"
    if source_type == "manual":
        return "Manually Entered"
    return "Unknown"


def update_purchase_order(po_id: int, payload: dict, actor: dict | None = None) -> dict:
    allowed = [
        "status",
        "customer_company_name",
        "customer_contact_name",
        "bill_to_address",
        "ship_to_address",
        "bill_to_address_structured_json",
        "ship_to_address_structured_json",
        "po_number",
        "po_revision",
        "quote_number",
        "date_received",
        "request_date",
        "payment_terms",
        "freight_terms",
        "currency",
        "order_type_id",
        "extraction_notes",
    ]
    if "date_received" in payload:
        payload["date_received"] = normalize_date(payload.get("date_received"))
    if "request_date" in payload:
        payload["request_date"] = normalize_date(payload.get("request_date"))
    apply_structured_address_payload(payload, "bill_to_address", "bill_to_address_structured_json")
    apply_structured_address_payload(payload, "ship_to_address", "ship_to_address_structured_json")
    capture_feedback_before_update("purchase_orders", po_id, "header", po_id, payload, allowed, actor)
    update_fields("purchase_orders", po_id, payload, allowed)
    if "bill_to_address" in payload or "ship_to_address" in payload:
        with db() as conn:
            if "bill_to_address" in payload and "bill_to_address_structured_json" not in payload:
                conn.execute(
                    "UPDATE purchase_orders SET bill_to_address_structured_json = ? WHERE id = ?",
                    (json.dumps(parse_structured_address(payload.get("bill_to_address"))), po_id),
                )
            if "ship_to_address" in payload and "ship_to_address_structured_json" not in payload:
                conn.execute(
                    "UPDATE purchase_orders SET ship_to_address_structured_json = ? WHERE id = ?",
                    (json.dumps(parse_structured_address(payload.get("ship_to_address"))), po_id),
                )
            conn.commit()
    mark_fields_reviewed("purchase_orders", po_id, payload.keys())
    with db() as conn:
        resolve_review_tasks_for_fields(conn, po_id, None, payload.keys(), actor)
        run_master_data_reviews(conn, po_id)
        generate_review_tasks_for_po(conn, po_id)
        record_audit_event(conn, po_id, "po_updated", "PO header saved.", actor, {"fields": list(payload.keys())})
    return get_purchase_order(po_id)


def apply_structured_address_payload(payload: dict, text_key: str, json_key: str) -> None:
    if json_key not in payload:
        return
    structured = normalize_structured_address_payload(payload.get(json_key))
    payload[json_key] = json.dumps(structured)
    payload[text_key] = format_structured_address(structured)


def normalize_structured_address_payload(value: object) -> dict[str, str]:
    keys = ["address_line_1", "address_line_2", "address_line_3", "city", "state", "country", "zip_code"]
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return parse_structured_address(value)
    if isinstance(value, dict):
        return {key: str(value.get(key) or "").strip() for key in keys}
    return {key: "" for key in keys}


def add_line(po_id: int, payload: dict) -> dict:
    with db() as conn:
        po_number = conn.execute("SELECT po_number FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()["po_number"]
        line_total = line_total_from_payload(payload)
        product_match = match_product_for_line(conn, po_id, payload)
        conn.execute(
            """
            INSERT INTO purchase_order_lines (
                purchase_order_id, po_number, line_number, customer_part_number, customer_part_revision,
                internal_part_number, internal_part_revision, description,
                quantity, unit_of_measure, unit_price, line_total, requested_date, extraction_confidence, extraction_notes,
                field_confidence_json, product_match_status, matched_product_id, product_match_score, product_match_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.5, 'Manually added', ?, ?, ?, ?, ?)
            """,
            (
                po_id,
                po_number,
                payload.get("line_number"),
                payload.get("customer_part_number"),
                payload.get("customer_part_revision"),
                payload.get("internal_part_number"),
                payload.get("internal_part_revision"),
                payload.get("description"),
                payload.get("quantity"),
                payload.get("unit_of_measure"),
                payload.get("unit_price"),
                line_total,
                payload.get("requested_date"),
                json.dumps({key: 1.0 for key in payload.keys()}),
                product_match["status"],
                product_match["product_id"],
                product_match["score"],
                product_match["reason"],
            ),
        )
        conn.execute("UPDATE purchase_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (po_id,))
        generate_review_tasks_for_po(conn, po_id)
        conn.commit()
        recalculate_po_total(conn, po_id)
    return get_purchase_order(po_id)


def update_line(line_id: int, payload: dict, actor: dict | None = None) -> dict:
    allowed = [
        "line_number",
        "customer_part_number",
        "customer_part_revision",
        "internal_part_number",
        "internal_part_revision",
        "description",
        "quantity",
        "unit_of_measure",
        "unit_price",
        "requested_date",
        "extraction_notes",
    ]
    payload.pop("line_total", None)
    if "requested_date" in payload:
        payload["requested_date"] = normalize_date(payload.get("requested_date"))
    capture_feedback_before_update("purchase_order_lines", line_id, "line", line_id, payload, allowed, actor)
    update_fields("purchase_order_lines", line_id, payload, allowed)
    mark_fields_reviewed("purchase_order_lines", line_id, payload.keys())
    with db() as conn:
        po_id = conn.execute("SELECT purchase_order_id FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()["purchase_order_id"]
        row = conn.execute("SELECT quantity, unit_price FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()
        calculated = line_total_from_payload(dict(row))
        conn.execute("UPDATE purchase_order_lines SET line_total = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (calculated, line_id))
        line = row_to_dict(conn.execute("SELECT * FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone())
        product_match = match_product_for_line(conn, po_id, line or {})
        conn.execute(
            """
            UPDATE purchase_order_lines
            SET product_match_status = ?, matched_product_id = ?, product_match_score = ?,
                product_match_reason = ?, internal_part_number = COALESCE(NULLIF(internal_part_number, ''), ?),
                internal_part_revision = COALESCE(NULLIF(internal_part_revision, ''), ?)
            WHERE id = ?
            """,
            (
                product_match["status"],
                product_match["product_id"],
                product_match["score"],
                product_match["reason"],
                (line or {}).get("internal_part_number"),
                (line or {}).get("internal_part_revision"),
                line_id,
            ),
        )
        recalculate_po_total(conn, po_id)
        resolve_review_tasks_for_fields(conn, po_id, line_id, payload.keys(), actor)
        generate_review_tasks_for_po(conn, po_id)
        record_audit_event(conn, po_id, "line_updated", "PO line saved.", actor, {"line_id": line_id, "fields": list(payload.keys())})
    return get_purchase_order(po_id)


def capture_feedback_before_update(
    table: str,
    row_id: int,
    entity_type: str,
    entity_id: int,
    payload: dict,
    allowed: list[str],
    actor: dict | None,
) -> None:
    fields = [field for field in allowed if field in payload and field not in {"extraction_notes", "status", "bill_to_address_structured_json", "ship_to_address_structured_json"}]
    if not fields:
        return
    try:
        with db() as conn:
            current = row_to_dict(conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone())
            if not current:
                return
            po_id = row_id if table == "purchase_orders" else current["purchase_order_id"]
            po = row_to_dict(
                conn.execute(
                    """
                    SELECT po.*, a.extracted_text
                    FROM purchase_orders po
                    LEFT JOIN attachments a ON a.id = po.attachment_id
                    WHERE po.id = ?
                    """,
                    (po_id,),
                ).fetchone()
            )
            confidence_map = parse_json_dict(current.get("field_confidence_json"))
            inserted = 0
            for field in fields:
                old_value = current.get(field)
                new_value = payload.get(field)
                if normalize_feedback_value(old_value) == normalize_feedback_value(new_value):
                    continue
                conn.execute(
                    """
                    INSERT INTO extraction_feedback (
                        purchase_order_id, entity_type, entity_id, field_name, extracted_value,
                        corrected_value, confidence, source_text_snippet, customer_company_name,
                        source_attachment_filename, created_by_user_id
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        po_id,
                        entity_type,
                        entity_id,
                        field,
                        "" if old_value is None else str(old_value),
                        "" if new_value is None else str(new_value),
                        confidence_map.get(field),
                        source_snippet(po.get("extracted_text") if po else "", old_value),
                        po.get("customer_company_name") if po else None,
                        po.get("source_attachment_filename") if po else None,
                        actor.get("id") if actor else None,
                    ),
                )
                inserted += 1
            if inserted:
                conn.execute(
                    """
                    UPDATE purchase_orders
                    SET extraction_feedback_count = (
                        SELECT COUNT(*) FROM extraction_feedback WHERE purchase_order_id = ?
                    ), updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (po_id, po_id),
                )
            conn.commit()
    except Exception as exc:
        with db() as conn:
            conn.execute(
                "INSERT INTO processing_logs (level, message, metadata_json) VALUES ('error', ?, ?)",
                ("Extraction feedback logging failed.", json.dumps({"error": str(exc), "table": table, "row_id": row_id})),
            )
            conn.commit()


def normalize_feedback_value(value: object) -> str:
    return "" if value is None else str(value).strip()


def source_snippet(text: str | None, value: object) -> str | None:
    source = text or ""
    needle = normalize_feedback_value(value)
    if not source:
        return None
    if needle:
        index = source.lower().find(needle.lower())
        if index >= 0:
            return source[max(0, index - 160) : index + len(needle) + 160]
    return source[:320]


def parse_json_dict(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def mark_extraction_reviewed(po_id: int, actor: dict) -> dict:
    with db() as conn:
        conn.execute(
            """
            UPDATE purchase_orders
            SET extraction_reviewed_at = ?, extraction_reviewed_by_user_id = ?,
                extraction_feedback_count = (
                    SELECT COUNT(*) FROM extraction_feedback WHERE purchase_order_id = ?
                ),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (now_iso(), actor.get("id"), po_id, po_id),
        )
        conn.commit()
    return get_purchase_order(po_id)


def delete_line(line_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT purchase_order_id FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()
        if not row:
            return {"ok": True}
        po_id = row["purchase_order_id"]
        conn.execute("DELETE FROM purchase_order_lines WHERE id = ?", (line_id,))
        conn.execute("UPDATE purchase_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (po_id,))
        recalculate_po_total(conn, po_id)
        generate_review_tasks_for_po(conn, po_id)
        conn.commit()
    return get_purchase_order(po_id)


def delete_purchase_order(po_id: int) -> dict:
    with db() as conn:
        po = conn.execute("SELECT po_number FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if not po:
            return {"ok": True, "deleted": False}
        po_number = po["po_number"]
        conn.execute("DELETE FROM purchase_order_lines WHERE purchase_order_id = ?", (po_id,))
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))
        conn.execute(
            """
            INSERT INTO processing_logs (level, message, metadata_json)
            VALUES ('warning', ?, ?)
            """,
            ("Purchase order deleted from review queue.", json.dumps({"purchase_order_id": po_id, "po_number": po_number})),
        )
        conn.commit()
    return {"ok": True, "deleted": True, "id": po_id}


def update_fields(table: str, row_id: int, payload: dict, allowed: list[str]) -> None:
    fields = [key for key in allowed if key in payload]
    if not fields:
        return
    assignments = ", ".join(f"{field} = ?" for field in fields)
    args = [payload[field] for field in fields]
    if table in {"purchase_orders", "purchase_order_lines"}:
        assignments += ", updated_at = CURRENT_TIMESTAMP"
    with db() as conn:
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", [*args, row_id])
        conn.commit()


def get_logs() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM processing_logs ORDER BY created_at DESC LIMIT 100").fetchall())


def list_order_types() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM order_types ORDER BY is_active DESC, name").fetchall())


def create_order_type(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "name_required"}
    with db() as conn:
        conn.execute(
            "INSERT INTO order_types (name, is_active) VALUES (?, 1) ON CONFLICT(name) DO UPDATE SET is_active = 1, updated_at = CURRENT_TIMESTAMP",
            (name,),
        )
        conn.commit()
    return {"order_types": list_order_types()}


def update_order_type(order_type_id: int, payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    is_active = 1 if payload.get("is_active", True) else 0
    with db() as conn:
        if name:
            conn.execute("UPDATE order_types SET name = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (name, is_active, order_type_id))
        else:
            conn.execute("UPDATE order_types SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (is_active, order_type_id))
        conn.commit()
    return {"order_types": list_order_types()}


def delete_order_type(order_type_id: int) -> dict:
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) AS count FROM purchase_orders WHERE order_type_id = ?", (order_type_id,)).fetchone()["count"]
        if used:
            conn.execute("UPDATE order_types SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (order_type_id,))
            conn.commit()
            return {"order_types": list_order_types(), "message": "Order type is used by existing POs, so it was deactivated instead of deleted."}
        conn.execute("DELETE FROM order_types WHERE id = ?", (order_type_id,))
        conn.commit()
    return {"order_types": list_order_types()}


def list_departments() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM departments ORDER BY is_active DESC, name").fetchall())


def create_department(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "name_required", "departments": list_departments()}
    with db() as conn:
        conn.execute(
            """
            INSERT INTO departments (name, is_active)
            VALUES (?, 1)
            ON CONFLICT(name) DO UPDATE SET is_active = 1, updated_at = CURRENT_TIMESTAMP
            """,
            (name,),
        )
        conn.commit()
    return {"departments": list_departments()}


def update_department(department_id: int, payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    is_active = 1 if payload.get("is_active", True) else 0
    with db() as conn:
        if name:
            conn.execute(
                "UPDATE departments SET name = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, is_active, department_id),
            )
        else:
            conn.execute("UPDATE departments SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (is_active, department_id))
        conn.commit()
    return {"departments": list_departments()}


def delete_department(department_id: int) -> dict:
    with db() as conn:
        conn.execute("DELETE FROM departments WHERE id = ?", (department_id,))
        conn.commit()
    return {"departments": list_departments()}


def list_payment_terms() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM payment_terms ORDER BY is_active DESC, name").fetchall())


def create_payment_term(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        return {"error": "name_required", "payment_terms": list_payment_terms()}
    with db() as conn:
        conn.execute(
            """
            INSERT INTO payment_terms (name, is_active)
            VALUES (?, 1)
            ON CONFLICT(name) DO UPDATE SET is_active = 1, updated_at = CURRENT_TIMESTAMP
            """,
            (name,),
        )
        conn.commit()
    return {"payment_terms": list_payment_terms()}


def update_payment_term(payment_term_id: int, payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    is_active = 1 if payload.get("is_active", True) else 0
    with db() as conn:
        if name:
            conn.execute(
                "UPDATE payment_terms SET name = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (name, is_active, payment_term_id),
            )
            conn.execute("UPDATE customers SET payment_terms = ? WHERE payment_terms_id = ?", (name, payment_term_id))
        else:
            conn.execute("UPDATE payment_terms SET is_active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (is_active, payment_term_id))
        conn.commit()
    return {"payment_terms": list_payment_terms()}


def delete_payment_term(payment_term_id: int) -> dict:
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) AS count FROM customers WHERE payment_terms_id = ?", (payment_term_id,)).fetchone()["count"]
        if used:
            conn.execute("UPDATE payment_terms SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (payment_term_id,))
            conn.commit()
            return {"payment_terms": list_payment_terms(), "message": "Payment term is used by customers, so it was deactivated instead of deleted."}
        conn.execute("DELETE FROM payment_terms WHERE id = ?", (payment_term_id,))
        conn.commit()
    return {"payment_terms": list_payment_terms()}


TEST_DOCUMENT_TYPES = {"po_pdf", "po_email_body", "scanned_po_pdf", "quote", "order_confirmation", "invoice", "rfq", "random_email", "other"}
TEST_CLASSIFICATIONS = {"purchase_order", "possible_po", "not_po"}
TEST_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".eml", ".csv", ".xlsx", ".docx"}


def list_test_documents() -> dict:
    with db() as conn:
        documents = rows_to_dicts(
            conn.execute(
                """
                SELECT td.*,
                    CASE WHEN gh.id IS NULL THEN 0 ELSE 1 END AS has_golden_answer,
                    er.detected_classification AS last_detected_classification,
                    er.detection_correct AS last_detection_correct,
                    er.field_results_json AS last_field_results_json,
                    er.line_results_json AS last_line_results_json,
                    er.processing_latency_ms AS last_processing_latency_ms
                FROM test_documents td
                LEFT JOIN golden_po_headers gh ON gh.test_document_id = td.id
                LEFT JOIN extraction_evaluation_results er ON er.id = (
                    SELECT er2.id FROM extraction_evaluation_results er2
                    WHERE er2.test_document_id = td.id
                    ORDER BY er2.created_at DESC LIMIT 1
                )
                ORDER BY td.created_at DESC
                """
            ).fetchall()
        )
    return {"documents": documents}


def upload_test_documents(handler: AppHandler) -> dict:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        return {"error": "expected_multipart", **list_test_documents()}
    TEST_CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
        },
    )
    fields = form["files"] if "files" in form else form["file"] if "file" in form else []
    if not isinstance(fields, list):
        fields = [fields]
    imported = 0
    rejected: list[dict[str, str]] = []
    with db() as conn:
        for field in fields:
            raw_name = getattr(field, "filename", "") or ""
            filename = safe_upload_filename(raw_name)
            extension = Path(filename).suffix.lower()
            if not filename or extension not in TEST_UPLOAD_EXTENSIONS:
                rejected.append({"filename": raw_name or "(missing)", "reason": "Allowed: .pdf, .txt, .eml, .csv, .xlsx, .docx"})
                continue
            target = unique_upload_path(TEST_CORPUS_DIR, filename)
            with target.open("wb") as output:
                output.write(field.file.read())
            conn.execute(
                """
                INSERT INTO test_documents (
                    filename, original_filename, local_path, content_type, document_type,
                    expected_classification, notes, source
                )
                VALUES (?, ?, ?, ?, 'other', 'not_po', '', 'upload')
                """,
                (target.name, raw_name, str(target), mimetypes.guess_type(target.name)[0] or "application/octet-stream"),
            )
            imported += 1
        conn.commit()
    return {"imported": imported, "rejected_files": rejected, **list_test_documents()}


def update_test_document(document_id: int, payload: dict) -> dict:
    document_type = payload.get("document_type") if payload.get("document_type") in TEST_DOCUMENT_TYPES else "other"
    expected = payload.get("expected_classification") if payload.get("expected_classification") in TEST_CLASSIFICATIONS else "not_po"
    with db() as conn:
        conn.execute(
            """
            UPDATE test_documents
            SET document_type = ?, expected_classification = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (document_type, expected, (payload.get("notes") or "").strip(), document_id),
        )
        conn.commit()
    return list_test_documents()


def delete_test_document(document_id: int) -> dict:
    with db() as conn:
        row = conn.execute("SELECT local_path FROM test_documents WHERE id = ?", (document_id,)).fetchone()
        conn.execute("DELETE FROM test_documents WHERE id = ?", (document_id,))
        conn.commit()
    if row:
        path = Path(row["local_path"])
        try:
            if path.resolve().is_relative_to(TEST_CORPUS_DIR.resolve()) and path.exists():
                path.unlink()
        except OSError:
            pass
    return list_test_documents()


def get_golden_answer(document_id: int) -> dict:
    with db() as conn:
        header = row_to_dict(conn.execute("SELECT * FROM golden_po_headers WHERE test_document_id = ?", (document_id,)).fetchone())
        lines: list[dict] = []
        if header:
            lines = rows_to_dicts(conn.execute("SELECT * FROM golden_po_lines WHERE golden_po_header_id = ? ORDER BY id", (header["id"],)).fetchall())
    return {"header": header, "lines": lines}


def save_golden_answer(document_id: int, payload: dict) -> dict:
    header = payload.get("header") or payload
    fields = clean_golden_header(header)
    with db() as conn:
        existing = conn.execute("SELECT id FROM golden_po_headers WHERE test_document_id = ?", (document_id,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE golden_po_headers
                SET expected_is_po = ?, customer_company_name = ?, customer_contact_name = ?, bill_to_address = ?,
                    ship_to_address = ?, po_number = ?, quote_number = ?, date_received = ?, payment_terms = ?,
                    freight_terms = ?, total_value = ?, currency = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*fields, existing["id"]),
            )
            header_id = existing["id"]
        else:
            cur = conn.execute(
                """
                INSERT INTO golden_po_headers (
                    test_document_id, expected_is_po, customer_company_name, customer_contact_name, bill_to_address,
                    ship_to_address, po_number, quote_number, date_received, payment_terms, freight_terms,
                    total_value, currency, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (document_id, *fields),
            )
            header_id = int(cur.lastrowid)
        conn.commit()
    return {"golden_answer": get_golden_answer(document_id), "header_id": header_id}


def clean_golden_header(payload: dict) -> tuple:
    return (
        bool_int(payload.get("expected_is_po", True)),
        (payload.get("customer_company_name") or "").strip(),
        (payload.get("customer_contact_name") or "").strip(),
        (payload.get("bill_to_address") or "").strip(),
        (payload.get("ship_to_address") or "").strip(),
        (payload.get("po_number") or "").strip(),
        (payload.get("quote_number") or "").strip(),
        normalize_date(payload.get("date_received")),
        (payload.get("payment_terms") or "").strip(),
        (payload.get("freight_terms") or "").strip(),
        numeric_or_none(payload.get("total_value")),
        (payload.get("currency") or "").strip(),
        (payload.get("notes") or "").strip(),
    )


def create_golden_line(header_id: int, payload: dict) -> dict:
    with db() as conn:
        row = conn.execute("SELECT test_document_id FROM golden_po_headers WHERE id = ?", (header_id,)).fetchone()
        if not row:
            return {"error": "not_found"}
        conn.execute(
            """
            INSERT INTO golden_po_lines (
                golden_po_header_id, line_number, customer_part_number, internal_part_number, description,
                quantity, unit_of_measure, unit_price, line_total, requested_date, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (header_id, *clean_golden_line(payload)),
        )
        conn.commit()
    return get_golden_answer(row["test_document_id"])


def update_golden_line(line_id: int, payload: dict) -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT gh.test_document_id
            FROM golden_po_lines gl
            JOIN golden_po_headers gh ON gh.id = gl.golden_po_header_id
            WHERE gl.id = ?
            """,
            (line_id,),
        ).fetchone()
        if not row:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE golden_po_lines
            SET line_number = ?, customer_part_number = ?, internal_part_number = ?, description = ?,
                quantity = ?, unit_of_measure = ?, unit_price = ?, line_total = ?, requested_date = ?,
                notes = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*clean_golden_line(payload), line_id),
        )
        conn.commit()
    return get_golden_answer(row["test_document_id"])


def delete_golden_line(line_id: int) -> dict:
    with db() as conn:
        row = conn.execute(
            """
            SELECT gh.test_document_id
            FROM golden_po_lines gl
            JOIN golden_po_headers gh ON gh.id = gl.golden_po_header_id
            WHERE gl.id = ?
            """,
            (line_id,),
        ).fetchone()
        if not row:
            return {"ok": True}
        conn.execute("DELETE FROM golden_po_lines WHERE id = ?", (line_id,))
        conn.commit()
    return get_golden_answer(row["test_document_id"])


def clean_golden_line(payload: dict) -> tuple:
    quantity = numeric_or_none(payload.get("quantity"))
    unit_price = numeric_or_none(payload.get("unit_price"))
    line_total = round(quantity * unit_price, 2) if quantity is not None and unit_price is not None else numeric_or_none(payload.get("line_total"))
    return (
        (payload.get("line_number") or "").strip(),
        (payload.get("customer_part_number") or "").strip(),
        (payload.get("internal_part_number") or "").strip(),
        (payload.get("description") or "").strip(),
        quantity,
        (payload.get("unit_of_measure") or "").strip(),
        unit_price,
        line_total,
        normalize_date(payload.get("requested_date")),
        (payload.get("notes") or "").strip(),
    )


def numeric_or_none(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except ValueError:
        return None


HEADER_COMPARE_FIELDS = [
    "customer_company_name",
    "customer_contact_name",
    "bill_to_address",
    "ship_to_address",
    "po_number",
    "quote_number",
    "date_received",
    "payment_terms",
    "freight_terms",
    "total_value",
    "currency",
]

LINE_COMPARE_FIELDS = [
    "line_number",
    "customer_part_number",
    "customer_part_revision",
    "internal_part_number",
    "internal_part_revision",
    "description",
    "quantity",
    "unit_of_measure",
    "unit_price",
    "line_total",
    "requested_date",
]


def run_extraction_evaluation(payload: dict) -> dict:
    started = now_iso()
    run_name = (payload.get("run_name") or f"Evaluation {started}").strip()
    mode = payload.get("extraction_mode") if payload.get("extraction_mode") in {"rule_based", "ai_text", "ai_with_examples"} else "rule_based"
    if mode in {"ai_text", "ai_with_examples"} and not get_openai_runtime_config().api_key_configured:
        return {"error": "AI extraction is not configured. Add OPENAI_API_KEY before running this mode.", **list_evaluation_runs()}
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO extraction_evaluation_runs (run_name, extraction_mode, started_at, notes) VALUES (?, ?, ?, ?)",
            (run_name, mode, started, ""),
        )
        run_id = int(cur.lastrowid)
        documents = rows_to_dicts(conn.execute("SELECT * FROM test_documents ORDER BY id").fetchall())
        conn.commit()
    totals = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "field_rates": [], "line_rates": [], "confidences": []}
    for document in documents:
        result = evaluate_document(document, run_id, mode)
        totals[result["bucket"]] += 1
        if result["field_match_rate"] is not None:
            totals["field_rates"].append(result["field_match_rate"])
        if result["line_match_rate"] is not None:
            totals["line_rates"].append(result["line_match_rate"])
        if result["confidence"] is not None:
            totals["confidences"].append(result["confidence"])
        with db() as conn:
            conn.execute(
                """
                INSERT INTO extraction_evaluation_results (
                    run_id, test_document_id, detected_classification, expected_classification, detection_correct,
                    field_results_json, line_results_json, missed_fields_json, hallucinated_fields_json,
                    confidence_json, processing_latency_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    document["id"],
                    result["detected_classification"],
                    result["expected_classification"],
                    bool_int(result["detection_correct"]),
                    json.dumps(result["field_results"]),
                    json.dumps(result["line_results"]),
                    json.dumps(result["missed_fields"]),
                    json.dumps(result["hallucinated_fields"]),
                    json.dumps(result["confidence_json"]),
                    result["latency_ms"],
                ),
            )
            conn.commit()
    with db() as conn:
        conn.execute(
            """
            UPDATE extraction_evaluation_runs
            SET finished_at = ?, document_count = ?, true_positives = ?, false_positives = ?,
                true_negatives = ?, false_negatives = ?, field_match_rate = ?, line_match_rate = ?,
                average_confidence = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                len(documents),
                totals["tp"],
                totals["fp"],
                totals["tn"],
                totals["fn"],
                average(totals["field_rates"]),
                average(totals["line_rates"]),
                average(totals["confidences"]),
                run_id,
            ),
        )
        conn.commit()
    return get_evaluation_run(run_id)


def evaluate_document(document: dict, run_id: int, mode: str = "rule_based") -> dict:
    start = time.perf_counter()
    text, method = test_document_text(document)
    email = {
        "provider": "test_corpus",
        "provider_message_id": f"test:{document['id']}:{document['filename']}",
        "sender": "test-corpus@example.com",
        "recipients": "orders@example.com",
        "subject": document["original_filename"],
        "received_at": document["created_at"],
        "body_text": text if Path(document["filename"]).suffix.lower() in {".txt", ".eml"} else "",
    }
    classification = classify_purchase_order(email["subject"], email["body_text"], "" if method == "body" else text, [document["filename"]])
    extraction = {}
    if classification.label in {"possible_po", "purchase_order"}:
        with db() as conn:
            examples = find_similar_extraction_examples(conn, None, text) if mode == "ai_with_examples" else []
        extraction = extract_purchase_order(text, email, document["filename"], mode, examples)
        with db() as conn:
            log_document_extraction_run(
                conn,
                test_document_id=document["id"],
                raw_input_text=text,
                extraction=extraction,
                latency_ms=int((time.perf_counter() - start) * 1000),
                success=True,
            )
    with db() as conn:
        golden = row_to_dict(conn.execute("SELECT * FROM golden_po_headers WHERE test_document_id = ?", (document["id"],)).fetchone())
        golden_lines = []
        if golden:
            golden_lines = rows_to_dicts(conn.execute("SELECT * FROM golden_po_lines WHERE golden_po_header_id = ? ORDER BY id", (golden["id"],)).fetchall())
    expected = document["expected_classification"] or ("purchase_order" if golden and golden["expected_is_po"] else "not_po")
    detection_correct = classification_matches(expected, classification.label)
    field_results, missed, hallucinated, field_rate = compare_header(golden, extraction)
    line_results, line_rate = compare_lines(golden_lines, extraction.get("lines", []))
    is_expected_po = expected in {"purchase_order", "possible_po"}
    is_detected_po = classification.label in {"purchase_order", "possible_po"}
    bucket = "tp" if is_expected_po and is_detected_po else "fp" if not is_expected_po and is_detected_po else "tn" if not is_expected_po else "fn"
    return {
        "bucket": bucket,
        "detected_classification": classification.label,
        "expected_classification": expected,
        "detection_correct": detection_correct,
        "field_results": field_results,
        "line_results": line_results,
        "missed_fields": missed,
        "hallucinated_fields": hallucinated,
        "field_match_rate": field_rate,
        "line_match_rate": line_rate,
        "confidence": classification.confidence,
        "confidence_json": {"classification": classification.confidence, "extraction": extraction.get("extraction_confidence")},
        "latency_ms": int((time.perf_counter() - start) * 1000),
    }


def test_document_text(document: dict) -> tuple[str, str]:
    path = Path(document["local_path"])
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, _pages = extract_pdf_text(path)
        if len(text.strip()) < 50:
            return text, "needs_ocr"
        return text, "pdf_text"
    if suffix in {".txt", ".eml", ".csv"}:
        return path.read_text(encoding="utf-8", errors="replace"), "body"
    if suffix in {".xlsx", ".docx"}:
        from server.processing import extract_docx_text, extract_xlsx_text

        return (extract_xlsx_text(path), "excel_text") if suffix == ".xlsx" else (extract_docx_text(path), "docx_text")
    return "", "unsupported"


def classification_matches(expected: str, detected: str) -> bool:
    if expected == detected:
        return True
    return expected == "purchase_order" and detected == "possible_po"


def compare_header(golden: dict | None, extraction: dict) -> tuple[dict, list[str], list[str], float | None]:
    if not golden:
        return {}, [], [key for key in HEADER_COMPARE_FIELDS if extraction.get(key)], None
    results = {}
    missed = []
    hallucinated = []
    matches = 0
    compared = 0
    for field in HEADER_COMPARE_FIELDS:
        expected = golden.get(field)
        actual = extraction.get(field)
        match = values_match(expected, actual, field)
        if expected not in (None, "") or actual not in (None, ""):
            compared += 1
            matches += 1 if match else 0
        if expected not in (None, "") and actual in (None, ""):
            missed.append(field)
        if expected in (None, "") and actual not in (None, ""):
            hallucinated.append(field)
        results[field] = {"expected": expected, "actual": actual, "match": match}
    return results, missed, hallucinated, round(matches / compared, 3) if compared else None


def compare_lines(golden_lines: list[dict], extracted_lines: list[dict]) -> tuple[dict, float | None]:
    results = {"expected_count": len(golden_lines), "actual_count": len(extracted_lines), "lines": []}
    if not golden_lines and not extracted_lines:
        return results, None
    matches = 0
    compared = 0
    for index, expected in enumerate(golden_lines):
        actual = extracted_lines[index] if index < len(extracted_lines) else {}
        field_results = {}
        for field in LINE_COMPARE_FIELDS:
            match = values_match(expected.get(field), actual.get(field), field)
            compared += 1
            matches += 1 if match else 0
            field_results[field] = {"expected": expected.get(field), "actual": actual.get(field), "match": match}
        results["lines"].append(field_results)
    return results, round(matches / compared, 3) if compared else 0


def values_match(expected: object, actual: object, field: str) -> bool:
    if expected in (None, "") and actual in (None, ""):
        return True
    if field in {"quantity", "unit_price", "line_total", "total_value"}:
        left = numeric_or_none(expected)
        right = numeric_or_none(actual)
        return left is not None and right is not None and abs(left - right) <= 0.01
    if "date" in field:
        return normalize_date(str(expected) if expected is not None else None) == normalize_date(str(actual) if actual is not None else None)
    return normalize_compare_text(expected) == normalize_compare_text(actual)


def normalize_compare_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0


def list_evaluation_runs() -> dict:
    with db() as conn:
        runs = rows_to_dicts(conn.execute("SELECT * FROM extraction_evaluation_runs ORDER BY created_at DESC LIMIT 20").fetchall())
        latest = get_evaluation_run(runs[0]["id"]) if runs else {"run": None, "results": []}
    return {"runs": runs, "latest": latest}


def extraction_learning_dashboard(params: dict[str, list[str]]) -> dict:
    customer_filter = (params.get("customer", [""])[0] or "").strip().lower()
    field_filter = (params.get("field", [""])[0] or "").strip().lower()
    clauses = []
    args: list[object] = []
    if customer_filter:
        clauses.append("LOWER(COALESCE(ef.customer_company_name, '')) LIKE ?")
        args.append(f"%{customer_filter}%")
    if field_filter:
        clauses.append("LOWER(ef.field_name) LIKE ?")
        args.append(f"%{field_filter}%")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    with db() as conn:
        run_counts = row_to_dict(
            conn.execute(
                """
                SELECT COUNT(*) AS total_runs,
                       SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successful_runs,
                       SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failed_runs
                FROM document_extraction_runs
                """
            ).fetchone()
        )
        total_feedback = conn.execute("SELECT COUNT(*) AS count FROM extraction_feedback").fetchone()["count"]
        corrected_fields = rows_to_dicts(
            conn.execute(
                """
                SELECT field_name, COUNT(*) AS count
                FROM extraction_feedback
                GROUP BY field_name
                ORDER BY count DESC, field_name
                LIMIT 10
                """
            ).fetchall()
        )
        corrections_by_customer = rows_to_dicts(
            conn.execute(
                """
                SELECT COALESCE(customer_company_name, 'Unknown') AS customer_company_name, COUNT(*) AS count
                FROM extraction_feedback
                GROUP BY COALESCE(customer_company_name, 'Unknown')
                ORDER BY count DESC
                LIMIT 10
                """
            ).fetchall()
        )
        failures = rows_to_dicts(
            conn.execute(
                """
                SELECT *
                FROM document_extraction_runs
                WHERE success = 0 OR COALESCE(error_message, '') != ''
                ORDER BY created_at DESC
                LIMIT 10
                """
            ).fetchall()
        )
        feedback = rows_to_dicts(
            conn.execute(
                f"""
                SELECT ef.*, po.po_number, u.email AS user_email
                FROM extraction_feedback ef
                LEFT JOIN purchase_orders po ON po.id = ef.purchase_order_id
                LEFT JOIN users u ON u.id = ef.created_by_user_id
                {where}
                ORDER BY ef.created_at DESC
                LIMIT 50
                """,
                args,
            ).fetchall()
        )
    return {
        "summary": {
            "total_runs": run_counts.get("total_runs") or 0,
            "successful_runs": run_counts.get("successful_runs") or 0,
            "failed_runs": run_counts.get("failed_runs") or 0,
            "total_feedback": total_feedback,
        },
        "corrected_fields": corrected_fields,
        "corrections_by_customer": corrections_by_customer,
        "recent_failures": failures,
        "recent_feedback": feedback,
    }


def get_evaluation_run(run_id: int) -> dict:
    with db() as conn:
        run = row_to_dict(conn.execute("SELECT * FROM extraction_evaluation_runs WHERE id = ?", (run_id,)).fetchone())
        results = rows_to_dicts(
            conn.execute(
                """
                SELECT er.*, td.filename, td.original_filename
                FROM extraction_evaluation_results er
                JOIN test_documents td ON td.id = er.test_document_id
                WHERE er.run_id = ?
                ORDER BY er.id
                """,
                (run_id,),
            ).fetchall()
        )
    for result in results:
        for key in ("field_results_json", "line_results_json", "missed_fields_json", "hallucinated_fields_json", "confidence_json"):
            try:
                result[key.replace("_json", "")] = json.loads(result.get(key) or "{}")
            except json.JSONDecodeError:
                result[key.replace("_json", "")] = {}
    return {"run": run, "results": results}


def list_inbox_accounts() -> dict:
    with db() as conn:
        accounts = rows_to_dicts(
            conn.execute(
                """
                SELECT id, provider, display_name, connected_email, monitored_email, folder, sync_status,
                    last_sync_at, delta_token, history_id, evaluate_without_attachments, sync_interval_hours,
                    sync_start_time, next_sync_at, is_enabled, created_by_user_id, created_at, updated_at
                FROM inbox_accounts
                ORDER BY created_at DESC
                """
            ).fetchall()
        )
        runs = rows_to_dicts(
            conn.execute(
                """
                SELECT sr.*, ia.display_name, ia.provider
                FROM inbox_sync_runs sr
                JOIN inbox_accounts ia ON ia.id = sr.inbox_account_id
                ORDER BY sr.created_at DESC LIMIT 20
                """
            ).fetchall()
        )
    gmail_config = gmail_oauth_values()
    outlook_config = outlook_oauth_values()
    return {
        "accounts": accounts,
        "sync_runs": runs,
        "gmail_configured": bool(gmail_config["client_id"] and gmail_config["client_secret"]),
        "outlook_configured": bool(outlook_config["client_id"] and outlook_config["client_secret"]),
    }


def create_inbox_account(payload: dict, actor: dict) -> dict:
    provider = payload.get("provider") if payload.get("provider") in {"gmail", "outlook"} else "gmail"
    default_folder = "Inbox" if provider == "outlook" else "INBOX"
    with db() as conn:
        conn.execute(
            """
            INSERT INTO inbox_accounts (
                provider, display_name, connected_email, monitored_email, folder, sync_status, is_enabled,
                evaluate_without_attachments, sync_interval_hours, sync_start_time, next_sync_at, created_by_user_id
            )
            VALUES (?, ?, ?, ?, ?, 'not_connected', ?, ?, ?, ?, ?, ?)
            """,
            (
                provider,
                (payload.get("display_name") or f"{provider.title()} Inbox").strip(),
                (payload.get("connected_email") or "").strip(),
                (payload.get("monitored_email") or "").strip(),
                (payload.get("folder") or default_folder).strip(),
                bool_int(payload.get("is_enabled", True)),
                bool_int(payload.get("evaluate_without_attachments")),
                clean_sync_interval(payload.get("sync_interval_hours", 24)),
                clean_sync_start_time(payload.get("sync_start_time") or "02:00"),
                calculate_next_sync_at(clean_sync_interval(payload.get("sync_interval_hours", 24)), clean_sync_start_time(payload.get("sync_start_time") or "02:00")),
                actor.get("id"),
            ),
        )
        conn.commit()
    return list_inbox_accounts()


def connect_gmail_account(payload: dict, actor: dict) -> dict:
    config = gmail_oauth_values()
    if not config["client_id"] or not config["client_secret"]:
        return {"error": "Gmail OAuth is not configured. Add the client ID, client secret, redirect URI, and scopes in the Gmail OAuth App Configuration panel.", **list_inbox_accounts()}
    state = uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, provider, user_id, inbox_account_id) VALUES (?, 'gmail', ?, ?)",
            (state, actor.get("id"), payload.get("inbox_account_id")),
        )
        conn.commit()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": config["scopes"],
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return {"auth_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params), **list_inbox_accounts()}


def connect_outlook_account(payload: dict, actor: dict) -> dict:
    config = outlook_oauth_values()
    if not config["client_id"] or not config["client_secret"]:
        return {"error": "Outlook OAuth is not configured. Add the client ID, client secret, tenant, redirect URI, and scopes in the Outlook / Microsoft Graph Configuration panel.", **list_inbox_accounts()}
    state = uuid.uuid4().hex
    with db() as conn:
        conn.execute(
            "INSERT INTO oauth_states (state, provider, user_id, inbox_account_id) VALUES (?, 'outlook', ?, ?)",
            (state, actor.get("id"), payload.get("inbox_account_id")),
        )
        conn.commit()
    tenant = config["tenant"] or "common"
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "response_mode": "query",
        "scope": config["scopes"],
        "state": state,
    }
    return {"auth_url": f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/authorize?" + urllib.parse.urlencode(params), **list_inbox_accounts()}


def gmail_oauth_values() -> dict[str, str]:
    return {
        "client_id": setting_value("gmail_client_id") or GMAIL_CLIENT_ID,
        "client_secret": setting_value("gmail_client_secret") or GMAIL_CLIENT_SECRET,
        "redirect_uri": setting_value("gmail_redirect_uri") or GMAIL_REDIRECT_URI,
        "scopes": setting_value("gmail_scopes") or GMAIL_SCOPES,
    }


def outlook_oauth_values() -> dict[str, str]:
    return {
        "client_id": setting_value("outlook_client_id") or OUTLOOK_CLIENT_ID,
        "client_secret": setting_value("outlook_client_secret") or OUTLOOK_CLIENT_SECRET,
        "tenant": setting_value("outlook_tenant") or OUTLOOK_TENANT,
        "redirect_uri": setting_value("outlook_redirect_uri") or OUTLOOK_REDIRECT_URI,
        "scopes": setting_value("outlook_scopes") or OUTLOOK_SCOPES,
    }


def get_gmail_oauth_config() -> dict:
    values = gmail_oauth_values()
    return {
        "client_id": values["client_id"],
        "client_secret_configured": bool(values["client_secret"]),
        "redirect_uri": values["redirect_uri"],
        "scopes": values["scopes"],
        "encrypted_storage": encrypted_secret_label(),
        "source": {
            "client_id": "database" if setting_value("gmail_client_id") else "env" if GMAIL_CLIENT_ID else "missing",
            "client_secret": "database" if setting_value("gmail_client_secret") else "env" if GMAIL_CLIENT_SECRET else "missing",
            "redirect_uri": "database" if setting_value("gmail_redirect_uri") else "env/default",
            "scopes": "database" if setting_value("gmail_scopes") else "env/default",
        },
    }


def get_outlook_oauth_config() -> dict:
    values = outlook_oauth_values()
    return {
        "client_id": values["client_id"],
        "client_secret_configured": bool(values["client_secret"]),
        "tenant": values["tenant"],
        "redirect_uri": values["redirect_uri"],
        "scopes": values["scopes"],
        "encrypted_storage": encrypted_secret_label(),
        "source": {
            "client_id": "database" if setting_value("outlook_client_id") else "env" if OUTLOOK_CLIENT_ID else "missing",
            "client_secret": "database" if setting_value("outlook_client_secret") else "env" if OUTLOOK_CLIENT_SECRET else "missing",
            "tenant": "database" if setting_value("outlook_tenant") else "env/default",
            "redirect_uri": "database" if setting_value("outlook_redirect_uri") else "env/default",
            "scopes": "database" if setting_value("outlook_scopes") else "env/default",
        },
    }


def save_gmail_oauth_config(payload: dict) -> dict:
    try:
        upsert_setting("gmail_client_id", (payload.get("client_id") or "").strip(), False)
        if payload.get("client_secret"):
            upsert_setting("gmail_client_secret", str(payload.get("client_secret")).strip(), True)
        upsert_setting("gmail_redirect_uri", (payload.get("redirect_uri") or GMAIL_REDIRECT_URI).strip(), False)
        upsert_setting("gmail_scopes", (payload.get("scopes") or GMAIL_SCOPES).strip(), False)
    except RuntimeError as exc:
        return {"error": str(exc), **get_gmail_oauth_config()}
    return get_gmail_oauth_config()


def save_outlook_oauth_config(payload: dict) -> dict:
    try:
        upsert_setting("outlook_client_id", (payload.get("client_id") or "").strip(), False)
        if payload.get("client_secret"):
            upsert_setting("outlook_client_secret", str(payload.get("client_secret")).strip(), True)
        upsert_setting("outlook_tenant", (payload.get("tenant") or OUTLOOK_TENANT).strip() or "common", False)
        upsert_setting("outlook_redirect_uri", (payload.get("redirect_uri") or OUTLOOK_REDIRECT_URI).strip(), False)
        upsert_setting("outlook_scopes", (payload.get("scopes") or OUTLOOK_SCOPES).strip(), False)
    except RuntimeError as exc:
        return {"error": str(exc), **get_outlook_oauth_config()}
    return get_outlook_oauth_config()


def setting_value(key: str) -> str:
    with db() as conn:
        row = conn.execute("SELECT value, is_sensitive FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row or row["value"] is None:
            return ""
        return decrypt_secret(row["value"]) if row["is_sensitive"] else row["value"]


def upsert_setting(key: str, value: str, is_sensitive: bool) -> None:
    stored_value = encrypt_secret(value) if is_sensitive and value else value
    with db() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, is_sensitive)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, is_sensitive = excluded.is_sensitive,
                updated_at = CURRENT_TIMESTAMP
            """,
            (key, stored_value, bool_int(is_sensitive)),
        )
        conn.commit()


def clean_choice(value: object, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def get_oracle_ebs_profile() -> dict:
    with db() as conn:
        response = oracle_profile_response(conn)
    response["encrypted_storage"] = encrypted_secret_label()
    return response


def save_oracle_ebs_profile(payload: dict) -> dict:
    system_name = (payload.get("system_name") or "Oracle EBS").strip()
    environment = clean_choice(payload.get("environment"), {"sandbox", "uat", "production"}, "sandbox")
    connection_mode = clean_choice(payload.get("connection_mode"), {"api", "middleware", "file", "db_readonly"}, "api")
    write_mode = clean_choice(payload.get("write_mode"), {"preview", "entered_only"}, "preview")
    active_flag = bool_int(payload.get("active_flag", True))
    settings_fields = [
        "user_id",
        "responsibility_id",
        "resp_application_id",
        "security_group_id",
        "org_id",
        "nls_language",
        "order_source_id",
        "order_type_id",
        "line_type_id",
        "price_reference_id",
        "fulfillment_org_id",
        "endpoint_url",
        "credential_reference",
        "api_username",
    ]
    settings = {field: str(payload.get(field) or "").strip() for field in settings_fields}
    settings["nls_language"] = settings["nls_language"] or "AMERICAN"
    system_config = {
        "adapter_code": ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"],
        "supported_transaction": ORACLE_EBS_ORDER_ENTRY_MANIFEST["supported_transaction"],
    }
    with db() as conn:
        existing_profile = conn.execute(
            "SELECT * FROM erp_profile WHERE adapter_code = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"],),
        ).fetchone()
        secrets = parse_json_dict(existing_profile["secret_json"] if existing_profile else None)
        if payload.get("api_password"):
            try:
                secrets["api_password"] = encrypt_secret(str(payload.get("api_password")).strip())
            except RuntimeError as exc:
                return {"error": str(exc), **oracle_profile_response(conn)}
        cur = conn.execute(
            """
            INSERT INTO erp_system (
                system_name, erp_family, environment, connection_mode, active_flag, config_json
            )
            VALUES (?, 'oracle_ebs', ?, ?, ?, ?)
            ON CONFLICT(system_name, erp_family, environment) DO UPDATE SET
                connection_mode = excluded.connection_mode,
                active_flag = excluded.active_flag,
                config_json = excluded.config_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (system_name, environment, connection_mode, active_flag, json.dumps(system_config, sort_keys=True)),
        )
        system = conn.execute(
            """
            SELECT id FROM erp_system
            WHERE system_name = ? AND erp_family = 'oracle_ebs' AND environment = ?
            """,
            (system_name, environment),
        ).fetchone()
        erp_system_id = int(system["id"] if system else cur.lastrowid)
        profile_values = (
            erp_system_id,
            "Oracle EBS Order Entry",
            ORACLE_EBS_ORDER_ENTRY_MANIFEST["supported_transaction"],
            ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"],
            "v1",
            write_mode,
            "profile_defaults",
            "canonical_then_adapter",
            active_flag,
            json.dumps(settings, sort_keys=True),
            json.dumps(secrets, sort_keys=True),
        )
        if existing_profile:
            conn.execute(
                """
                UPDATE erp_profile
                SET erp_system_id = ?, profile_name = ?, transaction_type = ?, adapter_code = ?,
                    profile_version = ?, write_mode = ?, defaulting_strategy = ?, validation_strategy = ?,
                    active_flag = ?, settings_json = ?, secret_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (*profile_values, existing_profile["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO erp_profile (
                    erp_system_id, profile_name, transaction_type, adapter_code, profile_version,
                    write_mode, defaulting_strategy, validation_strategy, active_flag, settings_json, secret_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                profile_values,
            )
        conn.commit()
        response = oracle_profile_response(conn)
    response["encrypted_storage"] = encrypted_secret_label()
    return response


def preview_oracle_ebs_payload(po_id: int) -> dict:
    with db() as conn:
        return oracle_payload_preview(conn, po_id)


def list_export_destinations() -> dict:
    with db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT id, name, destination_type, endpoint_url, config_json, is_active,
                       CASE WHEN COALESCE(secret_json, '') = '' THEN 0 ELSE 1 END AS secret_configured,
                       created_at, updated_at
                FROM export_destinations
                ORDER BY is_active DESC, name COLLATE NOCASE
                """
            ).fetchall()
        )
    return {"destinations": rows}


def save_export_destination(payload: dict, destination_id: int | None = None) -> dict:
    name = (payload.get("name") or "").strip()
    destination_type = (payload.get("destination_type") or "csv").strip().lower()
    if destination_type not in {"csv", "webhook", "erp_placeholder"}:
        destination_type = "csv"
    if not name:
        return {"error": "Destination name is required.", **list_export_destinations()}
    config_json = json.dumps(payload.get("config") or {}, sort_keys=True)
    raw_secret = payload.get("secret")
    try:
        encrypted_secret = encrypt_secret(json.dumps(raw_secret, sort_keys=True)) if raw_secret else None
    except RuntimeError as exc:
        return {"error": str(exc), **list_export_destinations()}
    endpoint_url = (payload.get("endpoint_url") or "").strip()
    is_active = bool_int(payload.get("is_active", True))
    with db() as conn:
        try:
            if destination_id:
                if encrypted_secret:
                    conn.execute(
                        """
                        UPDATE export_destinations
                        SET name = ?, destination_type = ?, endpoint_url = ?, config_json = ?, secret_json = ?,
                            is_active = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (name, destination_type, endpoint_url, config_json, encrypted_secret, is_active, destination_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE export_destinations
                        SET name = ?, destination_type = ?, endpoint_url = ?, config_json = ?,
                            is_active = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (name, destination_type, endpoint_url, config_json, is_active, destination_id),
                    )
            else:
                conn.execute(
                    """
                    INSERT INTO export_destinations (name, destination_type, endpoint_url, config_json, secret_json, is_active)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, destination_type, endpoint_url, config_json, encrypted_secret, is_active),
                )
        except Exception:
            return {"error": "An export destination with that name already exists.", **list_export_destinations()}
        conn.commit()
    return list_export_destinations()


def delete_export_destination(destination_id: int) -> dict:
    with db() as conn:
        conn.execute("UPDATE export_destinations SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (destination_id,))
        conn.commit()
    return list_export_destinations()


def gmail_oauth_callback(query: str) -> tuple[str, int]:
    params = parse_qs(query)
    if params.get("error"):
        return oauth_result_page("Gmail connection failed", params["error"][0]), 400
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if not code or not state:
        return oauth_result_page("Gmail connection failed", "Missing code or state."), 400
    with db() as conn:
        state_row = conn.execute("SELECT * FROM oauth_states WHERE state = ? AND provider = 'gmail'", (state,)).fetchone()
        if not state_row:
            return oauth_result_page("Gmail connection failed", "OAuth state was invalid or expired."), 400
        try:
            token = exchange_gmail_code(code)
            access_token = token.get("access_token")
            refresh_token = token.get("refresh_token")
            if not access_token:
                raise ValueError("Google did not return an access token.")
            profile = gmail_api_get("/gmail/v1/users/me/profile", access_token)
            email = profile.get("emailAddress") or ""
            expires_at = token_expiry_iso(token.get("expires_in", 3600))
            stored_access_token = encrypt_secret(access_token)
            stored_refresh_token = encrypt_secret(refresh_token) if refresh_token else None
            existing = conn.execute("SELECT id, refresh_token FROM inbox_accounts WHERE provider = 'gmail' AND connected_email = ?", (email,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE inbox_accounts
                    SET access_token = ?, refresh_token = COALESCE(?, refresh_token), token_expires_at = ?,
                        granted_scopes = ?, monitored_email = COALESCE(NULLIF(monitored_email, ''), ?),
                        folder = COALESCE(NULLIF(folder, ''), 'INBOX'), sync_status = 'connected',
                        is_enabled = 1, next_sync_at = COALESCE(next_sync_at, ?), updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (stored_access_token, stored_refresh_token, expires_at, token.get("scope") or "", email, calculate_next_sync_at(24, "02:00"), existing["id"]),
                )
                account_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO inbox_accounts (
                        provider, display_name, connected_email, monitored_email, folder, sync_status,
                        access_token, refresh_token, token_expires_at, granted_scopes, is_enabled,
                        evaluate_without_attachments, sync_interval_hours, sync_start_time, next_sync_at,
                        created_by_user_id
                    )
                    VALUES ('gmail', ?, ?, ?, 'INBOX', 'connected', ?, ?, ?, ?, 1, 0, 24, '02:00', ?, ?)
                    """,
                    (f"Gmail - {email}", email, email, stored_access_token, stored_refresh_token, expires_at, token.get("scope") or "", calculate_next_sync_at(24, "02:00"), state_row["user_id"]),
                )
                account_id = int(cur.lastrowid)
            refresh_inbox_labels(conn, account_id)
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
            return oauth_result_page("Gmail connected", f"{email} is connected. You can close this tab and return to POInbox."), 200
        except Exception as exc:
            conn.execute(
                "INSERT INTO processing_logs (level, message, metadata_json) VALUES ('error', ?, ?)",
                ("Gmail OAuth callback failed.", json.dumps({"error": str(exc)})),
            )
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
            return oauth_result_page("Gmail connection failed", "The token exchange failed. Check the Gmail OAuth configuration and server logs."), 500


def outlook_oauth_callback(query: str) -> tuple[str, int]:
    params = parse_qs(query)
    if params.get("error"):
        return oauth_result_page("Outlook connection failed", params["error"][0]), 400
    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if not code or not state:
        return oauth_result_page("Outlook connection failed", "Missing code or state."), 400
    with db() as conn:
        state_row = conn.execute("SELECT * FROM oauth_states WHERE state = ? AND provider = 'outlook'", (state,)).fetchone()
        if not state_row:
            return oauth_result_page("Outlook connection failed", "OAuth state was invalid or expired."), 400
        try:
            token = exchange_outlook_code(code)
            access_token = token.get("access_token")
            refresh_token = token.get("refresh_token")
            if not access_token:
                raise ValueError("Microsoft did not return an access token.")
            profile = outlook_api_get("/v1.0/me", access_token, {"$select": "displayName,mail,userPrincipalName"})
            email = profile.get("mail") or profile.get("userPrincipalName") or ""
            display_name = profile.get("displayName") or email
            expires_at = token_expiry_iso(token.get("expires_in", 3600))
            stored_access_token = encrypt_secret(access_token)
            stored_refresh_token = encrypt_secret(refresh_token) if refresh_token else None
            existing = conn.execute("SELECT id, refresh_token FROM inbox_accounts WHERE provider = 'outlook' AND connected_email = ?", (email,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE inbox_accounts
                    SET display_name = COALESCE(NULLIF(display_name, ''), ?), access_token = ?,
                        refresh_token = COALESCE(?, refresh_token), token_expires_at = ?, granted_scopes = ?,
                        monitored_email = COALESCE(NULLIF(monitored_email, ''), ?), folder = COALESCE(NULLIF(folder, ''), 'Inbox'),
                        sync_status = 'connected', is_enabled = 1, next_sync_at = COALESCE(next_sync_at, ?),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (f"Outlook - {display_name}", stored_access_token, stored_refresh_token, expires_at, token.get("scope") or "", email, calculate_next_sync_at(24, "02:00"), existing["id"]),
                )
                account_id = existing["id"]
            else:
                cur = conn.execute(
                    """
                    INSERT INTO inbox_accounts (
                        provider, display_name, connected_email, monitored_email, folder, sync_status,
                        access_token, refresh_token, token_expires_at, granted_scopes, is_enabled,
                        evaluate_without_attachments, sync_interval_hours, sync_start_time, next_sync_at,
                        created_by_user_id
                    )
                    VALUES ('outlook', ?, ?, ?, 'Inbox', 'connected', ?, ?, ?, ?, 1, 0, 24, '02:00', ?, ?)
                    """,
                    (f"Outlook - {display_name}", email, email, stored_access_token, stored_refresh_token, expires_at, token.get("scope") or "", calculate_next_sync_at(24, "02:00"), state_row["user_id"]),
                )
                account_id = int(cur.lastrowid)
            refresh_outlook_folders(conn, account_id)
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
            return oauth_result_page("Outlook connected", f"{email} is connected. You can close this tab and return to POInbox."), 200
        except Exception as exc:
            conn.execute(
                "INSERT INTO processing_logs (level, message, metadata_json) VALUES ('error', ?, ?)",
                ("Outlook OAuth callback failed.", json.dumps({"error": str(exc)})),
            )
            conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
            conn.commit()
            return oauth_result_page("Outlook connection failed", "The token exchange failed. Check the Outlook OAuth configuration and server logs."), 500


def oauth_result_page(title: str, message: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{html.escape(title)}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:40px;color:#17202a}}.box{{max-width:680px;border:1px solid #d8dee9;border-radius:8px;padding:20px}}</style></head>
<body><section class="box"><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></section></body></html>"""


def exchange_gmail_code(code: str) -> dict:
    config = gmail_oauth_values()
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return urlopen_json(request)


def exchange_outlook_code(code: str) -> dict:
    config = outlook_oauth_values()
    tenant = config["tenant"] or "common"
    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
            "scope": config["scopes"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return urlopen_json(request)


def token_expiry_iso(expires_in: object) -> str:
    seconds = int(expires_in or 3600)
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def update_inbox_account(account_id: int, payload: dict) -> dict:
    interval = clean_sync_interval(payload.get("sync_interval_hours", 24))
    start_time = clean_sync_start_time(payload.get("sync_start_time") or "02:00")
    with db() as conn:
        conn.execute(
            """
            UPDATE inbox_accounts
            SET display_name = ?, monitored_email = ?, folder = ?, is_enabled = ?,
                evaluate_without_attachments = COALESCE(?, evaluate_without_attachments),
                sync_interval_hours = COALESCE(?, sync_interval_hours),
                sync_start_time = COALESCE(?, sync_start_time),
                next_sync_at = COALESCE(?, next_sync_at),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                (payload.get("display_name") or "").strip(),
                (payload.get("monitored_email") or "").strip(),
                (payload.get("folder") or "INBOX").strip(),
                bool_int(payload.get("is_enabled", True)),
                bool_int(payload.get("evaluate_without_attachments")) if "evaluate_without_attachments" in payload else None,
                interval if "sync_interval_hours" in payload else None,
                start_time if "sync_start_time" in payload else None,
                calculate_next_sync_at(interval, start_time) if "sync_interval_hours" in payload or "sync_start_time" in payload else None,
                account_id,
            ),
        )
        conn.commit()
    return list_inbox_accounts()


def get_inbox_config(account_id: int) -> dict:
    with db() as conn:
        account = row_to_dict(
            conn.execute(
                """
                SELECT id, provider, display_name, connected_email, monitored_email, folder, sync_status,
                    last_sync_at, is_enabled, evaluate_without_attachments, sync_interval_hours,
                    sync_start_time, next_sync_at, created_at, updated_at
                FROM inbox_accounts WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        )
        if not account:
            return {"error": "not_found"}
        labels = list_inbox_labels(conn, account_id)
    return {"account": account, "labels": labels}


def save_inbox_config(account_id: int, payload: dict) -> dict:
    interval = clean_sync_interval(payload.get("sync_interval_hours", 24))
    start_time = clean_sync_start_time(payload.get("sync_start_time") or "02:00")
    label_ids = set(str(value) for value in payload.get("selected_label_ids", []))
    with db() as conn:
        account = conn.execute("SELECT id FROM inbox_accounts WHERE id = ?", (account_id,)).fetchone()
        if not account:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE inbox_accounts
            SET display_name = ?, monitored_email = ?, folder = ?, is_enabled = ?,
                evaluate_without_attachments = ?, sync_interval_hours = ?, sync_start_time = ?,
                next_sync_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                (payload.get("display_name") or "").strip(),
                (payload.get("monitored_email") or "").strip(),
                (payload.get("folder") or "INBOX").strip(),
                bool_int(payload.get("is_enabled", True)),
                bool_int(payload.get("evaluate_without_attachments")),
                interval,
                start_time,
                calculate_next_sync_at(interval, start_time),
                account_id,
            ),
        )
        if "selected_label_ids" in payload:
            rows = conn.execute("SELECT label_id FROM inbox_labels WHERE inbox_account_id = ?", (account_id,)).fetchall()
            for row in rows:
                conn.execute(
                    "UPDATE inbox_labels SET is_selected = ?, updated_at = CURRENT_TIMESTAMP WHERE inbox_account_id = ? AND label_id = ?",
                    (1 if row["label_id"] in label_ids else 0, account_id, row["label_id"]),
                )
        conn.commit()
    return get_inbox_config(account_id)


def refresh_inbox_labels_response(account_id: int) -> dict:
    with db() as conn:
        account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (account_id,)).fetchone())
        if not account:
            return {"error": "not_found"}
        try:
            if account["provider"] == "gmail":
                labels = refresh_inbox_labels(conn, account_id)
            elif account["provider"] == "outlook":
                labels = refresh_outlook_folders(conn, account_id)
            else:
                return {"error": "Unknown inbox provider.", **get_inbox_config(account_id)}
            conn.commit()
            return {"labels": labels, **get_inbox_config(account_id)}
        except Exception as exc:
            return {"error": str(exc), **get_inbox_config(account_id)}


def list_inbox_labels(conn, account_id: int) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM inbox_labels
            WHERE inbox_account_id = ?
            ORDER BY label_type = 'system' DESC, label_name COLLATE NOCASE
            """,
            (account_id,),
        ).fetchall()
    )


def refresh_inbox_labels(conn, inbox_account_id: int) -> list[dict]:
    access_token = get_gmail_access_token(conn, inbox_account_id)
    payload = gmail_api_get("/gmail/v1/users/me/labels", access_token)
    labels = payload.get("labels") or []
    existing = {
        row["label_id"]: row
        for row in conn.execute("SELECT label_id, is_selected FROM inbox_labels WHERE inbox_account_id = ?", (inbox_account_id,)).fetchall()
    }
    seen = set()
    for label in labels:
        label_id = label.get("id") or ""
        if not label_id:
            continue
        seen.add(label_id)
        default_selected = 0 if label_id.upper() in {"TRASH", "SPAM"} else 1
        selected = existing[label_id]["is_selected"] if label_id in existing else default_selected
        conn.execute(
            """
            INSERT INTO inbox_labels (inbox_account_id, provider, label_id, label_name, label_type, is_selected)
            VALUES (?, 'gmail', ?, ?, ?, ?)
            ON CONFLICT(inbox_account_id, label_id) DO UPDATE SET
                label_name = excluded.label_name,
                label_type = excluded.label_type,
                updated_at = CURRENT_TIMESTAMP
            """,
            (inbox_account_id, label_id, label.get("name") or label_id, label.get("type") or "", selected),
        )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(
            f"DELETE FROM inbox_labels WHERE inbox_account_id = ? AND label_id NOT IN ({placeholders})",
            (inbox_account_id, *seen),
        )
    return list_inbox_labels(conn, inbox_account_id)


def refresh_outlook_folders(conn, inbox_account_id: int) -> list[dict]:
    access_token = get_outlook_access_token(conn, inbox_account_id)
    account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (inbox_account_id,)).fetchone()) or {}
    payload = outlook_api_get(f"{outlook_mailbox_base_path(account)}/mailFolders", access_token, {"$top": "100"})
    folders = payload.get("value") or []
    existing = {
        row["label_id"]: row
        for row in conn.execute("SELECT label_id, is_selected FROM inbox_labels WHERE inbox_account_id = ?", (inbox_account_id,)).fetchall()
    }
    any_existing_selected = any(row["is_selected"] for row in existing.values())
    seen = set()
    for folder in folders:
        folder_id = folder.get("id") or ""
        if not folder_id:
            continue
        seen.add(folder_id)
        name = folder.get("displayName") or folder_id
        is_inbox = normalize_label_name(name) == "inbox" or normalize_label_name(folder.get("wellKnownName")) == "inbox"
        default_selected = 1 if is_inbox and not any_existing_selected else 0
        selected = existing[folder_id]["is_selected"] if folder_id in existing else default_selected
        conn.execute(
            """
            INSERT INTO inbox_labels (inbox_account_id, provider, label_id, label_name, label_type, is_selected)
            VALUES (?, 'outlook', ?, ?, 'folder', ?)
            ON CONFLICT(inbox_account_id, label_id) DO UPDATE SET
                label_name = excluded.label_name,
                label_type = excluded.label_type,
                updated_at = CURRENT_TIMESTAMP
            """,
            (inbox_account_id, folder_id, name, selected),
        )
    if seen:
        placeholders = ",".join("?" for _ in seen)
        conn.execute(
            f"DELETE FROM inbox_labels WHERE inbox_account_id = ? AND label_id NOT IN ({placeholders})",
            (inbox_account_id, *seen),
        )
    return list_inbox_labels(conn, inbox_account_id)


def normalize_label_name(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def clean_sync_interval(value: object) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return 24


def clean_sync_start_time(value: object) -> str:
    text = str(value or "02:00").strip()
    if not re.match(r"^\d{2}:\d{2}$", text):
        return "02:00"
    hour, minute = [int(part) for part in text.split(":", 1)]
    if hour > 23 or minute > 59:
        return "02:00"
    return f"{hour:02d}:{minute:02d}"


def calculate_next_sync_at(interval_hours: int, start_time: str) -> str:
    now = datetime.now(timezone.utc)
    hour, minute = [int(part) for part in clean_sync_start_time(start_time).split(":", 1)]
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    interval = timedelta(hours=clean_sync_interval(interval_hours))
    while candidate <= now:
        candidate += interval
    return candidate.isoformat()


def delete_inbox_account(account_id: int) -> dict:
    with db() as conn:
        conn.execute("DELETE FROM inbox_accounts WHERE id = ?", (account_id,))
        conn.commit()
    return list_inbox_accounts()


def sync_inbox_account(account_id: int, payload: dict | None = None) -> dict:
    if account_id in SYNC_LOCKS:
        return {"error": "Sync is already running for this inbox.", **list_inbox_accounts()}
    SYNC_LOCKS.add(account_id)
    try:
        return sync_inbox_account_unlocked(account_id, payload)
    finally:
        SYNC_LOCKS.discard(account_id)


def sync_inbox_account_unlocked(account_id: int, payload: dict | None = None) -> dict:
    started = now_iso()
    started_perf = time.perf_counter()
    payload = payload or {}
    sync_mode = payload.get("sync_mode") or "manual"
    start_at = parse_local_datetime(payload.get("start_at"))
    end_at = parse_local_datetime(payload.get("end_at"))
    if payload.get("start_at") and not start_at:
        return {"error": "Invalid sync start date/time.", **list_inbox_accounts()}
    if payload.get("end_at") and not end_at:
        return {"error": "Invalid sync end date/time.", **list_inbox_accounts()}
    if start_at and end_at and end_at < start_at:
        return {"error": "End date/time must be after start date/time.", **list_inbox_accounts()}
    errors: list[str] = []
    messages_seen = 0
    messages_imported = 0
    messages_skipped = 0
    purchase_orders_created = 0
    with db() as conn:
        account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (account_id,)).fetchone())
        if not account:
            return {"error": "not_found", **list_inbox_accounts()}
        if not account.get("is_enabled"):
            return {"error": "Inbox connection is deactivated. Reactivate it before syncing.", **list_inbox_accounts()}
        cur = conn.execute(
            """
            INSERT INTO inbox_sync_runs (inbox_account_id, sync_mode, started_at, start_at, end_at, status, errors_json)
            VALUES (?, ?, ?, ?, ?, 'failed', '[]')
            """,
            (account_id, sync_mode, started, start_at.isoformat() if start_at else None, end_at.isoformat() if end_at else None),
        )
        run_id = int(cur.lastrowid)
        if account["provider"] == "gmail":
            try:
                sync_result = sync_gmail_messages(conn, account_id, run_id, start_at, end_at)
                messages_seen = sync_result["messages_seen"]
                messages_imported = sync_result["messages_imported"]
                messages_skipped = sync_result["messages_skipped"]
                purchase_orders_created = sync_result["purchase_orders_created"]
                errors.extend(sync_result["errors"])
            except Exception as exc:
                errors.append(str(exc))
        elif account["provider"] == "outlook":
            try:
                sync_result = sync_outlook_messages(conn, account_id, run_id, start_at, end_at)
                messages_seen = sync_result["messages_seen"]
                messages_imported = sync_result["messages_imported"]
                messages_skipped = sync_result["messages_skipped"]
                purchase_orders_created = sync_result["purchase_orders_created"]
                errors.extend(sync_result["errors"])
            except Exception as exc:
                errors.append(str(exc))
        else:
            errors.append("Unknown inbox provider.")
        conn.execute(
            """
            UPDATE inbox_sync_runs
            SET finished_at = ?, status = ?, messages_seen = ?, messages_imported = ?,
                messages_skipped = ?, purchase_orders_created = ?, error_count = ?, warning_count = ?,
                duration_ms = ?, status_detail = ?, errors_json = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                "failed" if errors else "completed",
                messages_seen,
                messages_imported,
                messages_skipped,
                purchase_orders_created,
                len(errors),
                0,
                elapsed_ms(started_perf),
                "; ".join(errors[:3]) if errors else "Sync completed.",
                json.dumps(errors),
                run_id,
            ),
        )
        conn.execute(
            """
            UPDATE inbox_accounts
            SET sync_status = ?, last_sync_at = ?, next_sync_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                "failed" if errors else "completed",
                now_iso(),
                calculate_next_sync_at(account.get("sync_interval_hours") or 24, account.get("sync_start_time") or "02:00"),
                account_id,
            ),
        )
        conn.commit()
    return {"sync_run": get_inbox_sync_run(run_id), **list_inbox_accounts()}


def parse_local_datetime(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def get_inbox_sync_run(run_id: int) -> dict | None:
    with db() as conn:
        return row_to_dict(conn.execute("SELECT * FROM inbox_sync_runs WHERE id = ?", (run_id,)).fetchone())


def sync_gmail_messages(conn, account_id: int, run_id: int, start_at: datetime | None = None, end_at: datetime | None = None) -> dict:
    account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (account_id,)).fetchone())
    if not account:
        raise ValueError("Inbox account not found.")
    access_token = get_gmail_access_token(conn, account_id)
    refresh_inbox_labels(conn, account_id)
    selected_labels = [
        row["label_id"]
        for row in conn.execute(
            "SELECT label_id FROM inbox_labels WHERE inbox_account_id = ? AND is_selected = 1 ORDER BY label_name",
            (account_id,),
        ).fetchall()
    ]
    if not selected_labels:
        raise ValueError("Select at least one label to sync.")
    messages_by_id: dict[str, dict] = {}
    errors: list[str] = []
    for label_id in selected_labels:
        try:
            params = {"maxResults": "100", "labelIds": label_id}
            query = gmail_query_for_date_range(start_at, end_at)
            if query:
                params["q"] = query
            messages_payload = gmail_api_get("/gmail/v1/users/me/messages", access_token, params)
            for item in messages_payload.get("messages") or []:
                if item.get("id"):
                    messages_by_id[item["id"]] = item
        except Exception as exc:
            errors.append(f"Label {label_id}: {exc}")
    result = {"messages_seen": len(messages_by_id), "messages_imported": 0, "messages_skipped": 0, "purchase_orders_created": 0, "errors": errors}
    for item in messages_by_id.values():
        started = time.perf_counter()
        message_id = item.get("id")
        if not message_id:
            continue
        provider_message_id = f"gmail:{message_id}"
        try:
            message = gmail_api_get(f"/gmail/v1/users/me/messages/{message_id}", access_token, {"format": "full"})
            headers = extract_gmail_headers(message.get("payload") or {})
            received_at = parse_gmail_received_datetime(headers.get("date"), message.get("internalDate"))
            if not message_received_in_range(received_at, start_at, end_at):
                result["messages_skipped"] += 1
                write_detection_result(conn, run_id, None, provider_message_id, "skipped_outside_sync_range", None, 0, 0, None, elapsed_ms(started), False, "Skipped because message was outside selected sync range.")
                continue
            body_text = extract_gmail_body(message.get("payload") or {})
            existing = row_to_dict(conn.execute("SELECT * FROM emails WHERE provider = 'gmail' AND provider_message_id = ?", (provider_message_id,)).fetchone())
            existing_attachment_rows: list[dict] = []
            if existing:
                existing_attachment_rows = rows_to_dicts(
                    conn.execute(
                        """
                        SELECT id, filename, extracted_text, extraction_method
                        FROM attachments
                        WHERE email_id = ?
                        ORDER BY id
                        """,
                        (existing["id"],),
                    ).fetchall()
                )
                existing_attachment_count = len(existing_attachment_rows)
                po_row = conn.execute("SELECT id FROM purchase_orders WHERE email_id = ? ORDER BY id DESC LIMIT 1", (existing["id"],)).fetchone()
                if po_row:
                    result["messages_skipped"] += 1
                    write_detection_result(
                        conn,
                        run_id,
                        existing["id"],
                        provider_message_id,
                        existing.get("classification"),
                        existing.get("classification_confidence"),
                        1,
                        existing_attachment_count,
                        po_row["id"],
                        elapsed_ms(started),
                        True,
                        "Skipped duplicate Gmail message that already has a purchase order.",
                    )
                    continue
            attachments: list[IncomingAttachment] = []
            attachment_errors: list[str] = []
            if not existing_attachment_rows:
                attachments, attachment_errors = download_gmail_attachments(message, access_token, STORAGE_DIR / "gmail" / message_id)
            if not attachments and not existing_attachment_rows and not account.get("evaluate_without_attachments"):
                result["messages_skipped"] += 1
                write_detection_result(
                    conn,
                    run_id,
                    existing["id"] if existing else None,
                    provider_message_id,
                    "skipped_no_supported_attachment",
                    None,
                    0,
                    0,
                    None,
                    elapsed_ms(started),
                    False,
                    "Skipped because the email had no supported attachments and body-only evaluation is disabled.",
                )
                continue
            incoming = IncomingEmail(
                provider="gmail",
                provider_message_id=provider_message_id,
                sender=headers.get("from", ""),
                recipients=headers.get("to", ""),
                subject=headers.get("subject", ""),
                received_at=received_at.isoformat() if received_at else normalize_date(headers.get("date")) or headers.get("date", ""),
                body_text=body_text,
                attachments=attachments,
            )
            attachment_text = ""
            attachment_rows = list(existing_attachment_rows)
            if existing:
                email_id = existing["id"]
                conn.execute(
                    """
                    UPDATE emails
                    SET sender = ?, recipients = ?, subject = ?, received_at = ?, body_text = ?
                    WHERE id = ?
                    """,
                    (incoming.sender, incoming.recipients, incoming.subject, incoming.received_at, incoming.body_text, email_id),
                )
                conn.commit()
            else:
                email_id = insert_email(conn, incoming)
            for attachment in incoming.attachments:
                row = insert_attachment(conn, email_id, attachment)
                attachment_rows.append(row)
            created = process_email(conn, email_id, attachment_rows)
            email_row = conn.execute("SELECT classification, classification_confidence FROM emails WHERE id = ?", (email_id,)).fetchone()
            po_row = conn.execute("SELECT id FROM purchase_orders WHERE email_id = ? ORDER BY id DESC LIMIT 1", (email_id,)).fetchone()
            po_duplicate_skipped = bool(created == 0 and not po_row and email_row and email_row["classification"] in {"possible_po", "purchase_order"})
            result["messages_imported"] += 1
            if po_duplicate_skipped:
                result["messages_skipped"] += 1
            result["purchase_orders_created"] += created
            if attachment_errors:
                result["errors"].extend(attachment_errors)
            write_detection_result(
                conn,
                run_id,
                email_id,
                provider_message_id,
                email_row["classification"] if email_row else None,
                email_row["classification_confidence"] if email_row else None,
                1 if attachment_rows else 0,
                len(attachment_rows),
                po_row["id"] if po_row else None,
                elapsed_ms(started),
                po_duplicate_skipped,
                "Duplicate PO number/revision skipped." if po_duplicate_skipped else "; ".join(attachment_errors),
            )
        except Exception as exc:
            result["errors"].append(f"{message_id}: {exc}")
            write_detection_result(conn, run_id, None, provider_message_id, None, None, 0, 0, None, elapsed_ms(started), False, str(exc))
    conn.commit()
    return result


def sync_outlook_messages(conn, account_id: int, run_id: int, start_at: datetime | None = None, end_at: datetime | None = None) -> dict:
    account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (account_id,)).fetchone())
    if not account:
        raise ValueError("Inbox account not found.")
    access_token = get_outlook_access_token(conn, account_id)
    refresh_outlook_folders(conn, account_id)
    selected_folders = [
        row["label_id"]
        for row in conn.execute(
            "SELECT label_id FROM inbox_labels WHERE inbox_account_id = ? AND is_selected = 1 ORDER BY label_name",
            (account_id,),
        ).fetchall()
    ]
    if not selected_folders:
        raise ValueError("Select at least one Outlook folder to sync.")
    messages_by_id: dict[str, dict] = {}
    errors: list[str] = []
    for folder_id in selected_folders:
        try:
            folder_messages = list_outlook_folder_messages(access_token, folder_id, start_at, end_at, account)
            for message in folder_messages:
                if message.get("id"):
                    messages_by_id[message["id"]] = message
        except Exception as exc:
            errors.append(f"Folder {folder_id}: {exc}")
    result = {"messages_seen": len(messages_by_id), "messages_imported": 0, "messages_skipped": 0, "purchase_orders_created": 0, "errors": errors}
    for message in messages_by_id.values():
        started = time.perf_counter()
        message_id = message.get("id")
        if not message_id:
            continue
        provider_message_id = f"outlook:{message_id}"
        try:
            received_at = parse_iso_datetime(message.get("receivedDateTime"))
            if not message_received_in_range(received_at, start_at, end_at):
                result["messages_skipped"] += 1
                write_detection_result(conn, run_id, None, provider_message_id, "skipped_outside_sync_range", None, 0, 0, None, elapsed_ms(started), False, "Skipped because message was outside selected sync range.")
                continue
            existing = row_to_dict(conn.execute("SELECT * FROM emails WHERE provider = 'outlook' AND provider_message_id = ?", (provider_message_id,)).fetchone())
            existing_attachment_rows: list[dict] = []
            if existing:
                existing_attachment_rows = rows_to_dicts(
                    conn.execute(
                        """
                        SELECT id, filename, extracted_text, extraction_method
                        FROM attachments
                        WHERE email_id = ?
                        ORDER BY id
                        """,
                        (existing["id"],),
                    ).fetchall()
                )
                po_row = conn.execute("SELECT id FROM purchase_orders WHERE email_id = ? ORDER BY id DESC LIMIT 1", (existing["id"],)).fetchone()
                if po_row:
                    result["messages_skipped"] += 1
                    write_detection_result(
                        conn,
                        run_id,
                        existing["id"],
                        provider_message_id,
                        existing.get("classification"),
                        existing.get("classification_confidence"),
                        1 if existing_attachment_rows else 0,
                        len(existing_attachment_rows),
                        po_row["id"],
                        elapsed_ms(started),
                        True,
                        "Skipped duplicate Outlook message that already has a purchase order.",
                    )
                    continue
            attachments: list[IncomingAttachment] = []
            attachment_errors: list[str] = []
            had_any_attachment = bool(message.get("hasAttachments"))
            if not existing_attachment_rows:
                attachments, attachment_errors, had_any_attachment = download_outlook_attachments(message_id, access_token, STORAGE_DIR / "outlook" / safe_storage_segment(message_id), had_any_attachment, account)
            if not attachments and not existing_attachment_rows and not account.get("evaluate_without_attachments"):
                result["messages_skipped"] += 1
                write_detection_result(
                    conn,
                    run_id,
                    existing["id"] if existing else None,
                    provider_message_id,
                    "skipped_no_supported_attachment",
                    None,
                    1 if had_any_attachment else 0,
                    0,
                    None,
                    elapsed_ms(started),
                    False,
                    "Skipped because the email had no supported attachments and body-only evaluation is disabled.",
                )
                continue
            incoming = IncomingEmail(
                provider="outlook",
                provider_message_id=provider_message_id,
                sender=extract_outlook_sender(message),
                recipients=extract_outlook_recipients(message),
                subject=message.get("subject") or "",
                received_at=received_at.isoformat() if received_at else message.get("receivedDateTime") or "",
                body_text=extract_outlook_body_text(message),
                attachments=attachments,
            )
            attachment_rows = list(existing_attachment_rows)
            if existing:
                email_id = existing["id"]
                conn.execute(
                    """
                    UPDATE emails
                    SET sender = ?, recipients = ?, subject = ?, received_at = ?, body_text = ?
                    WHERE id = ?
                    """,
                    (incoming.sender, incoming.recipients, incoming.subject, incoming.received_at, incoming.body_text, email_id),
                )
                conn.commit()
            else:
                email_id = insert_email(conn, incoming)
            for attachment in incoming.attachments:
                attachment_rows.append(insert_attachment(conn, email_id, attachment))
            created = process_email(conn, email_id, attachment_rows)
            email_row = conn.execute("SELECT classification, classification_confidence FROM emails WHERE id = ?", (email_id,)).fetchone()
            po_row = conn.execute("SELECT id FROM purchase_orders WHERE email_id = ? ORDER BY id DESC LIMIT 1", (email_id,)).fetchone()
            po_duplicate_skipped = bool(created == 0 and not po_row and email_row and email_row["classification"] in {"possible_po", "purchase_order"})
            result["messages_imported"] += 1
            if po_duplicate_skipped:
                result["messages_skipped"] += 1
            result["purchase_orders_created"] += created
            if attachment_errors:
                result["errors"].extend(attachment_errors)
            write_detection_result(
                conn,
                run_id,
                email_id,
                provider_message_id,
                email_row["classification"] if email_row else None,
                email_row["classification_confidence"] if email_row else None,
                1 if attachment_rows or had_any_attachment else 0,
                len(attachment_rows),
                po_row["id"] if po_row else None,
                elapsed_ms(started),
                po_duplicate_skipped,
                "Duplicate PO number/revision skipped." if po_duplicate_skipped else "; ".join(attachment_errors),
            )
        except Exception as exc:
            result["errors"].append(f"{message_id}: {exc}")
            write_detection_result(conn, run_id, None, provider_message_id, None, None, 0, 0, None, elapsed_ms(started), False, str(exc))
    conn.commit()
    return result


def list_outlook_folder_messages(access_token: str, folder_id: str, start_at: datetime | None, end_at: datetime | None, account: dict | None = None) -> list[dict]:
    params = {
        "$top": "50",
        "$orderby": "receivedDateTime desc",
        "$select": "id,subject,from,toRecipients,receivedDateTime,body,hasAttachments,internetMessageId",
    }
    filters = []
    if start_at:
        filters.append(f"receivedDateTime ge {graph_datetime(start_at)}")
    if end_at:
        filters.append(f"receivedDateTime le {graph_datetime(end_at)}")
    if filters:
        params["$filter"] = " and ".join(filters)
    path = f"{outlook_mailbox_base_path(account or {})}/mailFolders/{urllib.parse.quote(folder_id, safe='')}/messages"
    messages: list[dict] = []
    next_url: str | None = None
    while len(messages) < 250:
        payload = outlook_api_get_url(next_url, access_token) if next_url else outlook_api_get(path, access_token, params)
        for message in payload.get("value") or []:
            received_at = parse_iso_datetime(message.get("receivedDateTime"))
            if message_received_in_range(received_at, start_at, end_at):
                messages.append(message)
                if len(messages) >= 250:
                    break
        next_url = payload.get("@odata.nextLink")
        if not next_url:
            break
    return messages


def graph_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def gmail_query_for_date_range(start_at: datetime | None, end_at: datetime | None) -> str:
    parts = []
    if start_at:
        parts.append(f"after:{start_at.date().isoformat()}")
    if end_at:
        parts.append(f"before:{(end_at.date() + timedelta(days=1)).isoformat()}")
    return " ".join(parts)


def parse_gmail_received_datetime(date_header: str | None, internal_date: object = None) -> datetime | None:
    if internal_date:
        try:
            return datetime.fromtimestamp(int(internal_date) / 1000, tz=timezone.utc)
        except (TypeError, ValueError):
            pass
    if date_header:
        try:
            from email.utils import parsedate_to_datetime

            parsed = parsedate_to_datetime(date_header)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    return None


def message_received_in_range(received_at: datetime | None, start_at: datetime | None, end_at: datetime | None) -> bool:
    if not received_at:
        return True
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    if start_at and received_at < start_at:
        return False
    if end_at and received_at > end_at:
        return False
    return True


def get_gmail_access_token(conn, inbox_account_id: int) -> str:
    account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (inbox_account_id,)).fetchone())
    if not account:
        raise ValueError("Inbox account not found.")
    token = decrypt_secret(account.get("access_token"))
    expires_at = parse_iso_datetime(account.get("token_expires_at"))
    if token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return token
    return refresh_gmail_token(conn, account)


def refresh_gmail_token(conn, account: dict) -> str:
    refresh_token = decrypt_secret(account.get("refresh_token"))
    if not refresh_token:
        raise ValueError("Gmail account has no refresh token. Reconnect Gmail.")
    config = gmail_oauth_values()
    payload = urllib.parse.urlencode(
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        data = urlopen_json(request)
    except Exception:
        conn.execute("UPDATE inbox_accounts SET sync_status = 'auth_failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (account["id"],))
        conn.commit()
        raise
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Google refresh response did not include access token.")
    conn.execute(
        """
        UPDATE inbox_accounts
        SET access_token = ?, token_expires_at = ?, granted_scopes = COALESCE(?, granted_scopes),
            sync_status = 'connected', updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (encrypt_secret(access_token), token_expiry_iso(data.get("expires_in", 3600)), data.get("scope"), account["id"]),
    )
    conn.commit()
    return access_token


def get_outlook_access_token(conn, inbox_account_id: int) -> str:
    account = row_to_dict(conn.execute("SELECT * FROM inbox_accounts WHERE id = ?", (inbox_account_id,)).fetchone())
    if not account:
        raise ValueError("Inbox account not found.")
    token = decrypt_secret(account.get("access_token"))
    expires_at = parse_iso_datetime(account.get("token_expires_at"))
    if token and expires_at and expires_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return token
    return refresh_outlook_token(conn, account)


def refresh_outlook_token(conn, account: dict) -> str:
    refresh_token = decrypt_secret(account.get("refresh_token"))
    if not refresh_token:
        raise ValueError("Outlook account has no refresh token. Reconnect Outlook.")
    config = outlook_oauth_values()
    tenant = config["tenant"] or "common"
    payload = urllib.parse.urlencode(
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": config["scopes"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        data = urlopen_json(request)
    except Exception:
        conn.execute("UPDATE inbox_accounts SET sync_status = 'auth_failed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (account["id"],))
        conn.commit()
        raise
    access_token = data.get("access_token")
    if not access_token:
        raise ValueError("Microsoft refresh response did not include access token.")
    conn.execute(
        """
        UPDATE inbox_accounts
        SET access_token = ?, refresh_token = COALESCE(?, refresh_token), token_expires_at = ?,
            granted_scopes = COALESCE(?, granted_scopes), sync_status = 'connected',
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            encrypt_secret(access_token),
            encrypt_secret(data.get("refresh_token")) if data.get("refresh_token") else None,
            token_expiry_iso(data.get("expires_in", 3600)),
            data.get("scope"),
            account["id"],
        ),
    )
    conn.commit()
    return access_token


def gmail_api_get(path: str, access_token: str, params: dict | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"https://gmail.googleapis.com{path}{query}",
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    return urlopen_json(request)


def outlook_api_get(path: str, access_token: str, params: dict | None = None) -> dict:
    url = f"https://graph.microsoft.com{path}"
    if params:
        url += f"?{urllib.parse.urlencode(params)}"
    return outlook_api_get_url(url, access_token)


def outlook_api_get_url(url: str, access_token: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    return urlopen_json(request)


def urlopen_json(request: urllib.request.Request) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"HTTP {exc.code}: {body[:500]}") from exc


def extract_gmail_headers(payload: dict) -> dict[str, str]:
    headers = {}
    for item in payload.get("headers") or []:
        name = (item.get("name") or "").lower()
        if name in {"from", "to", "subject", "date"}:
            headers[name] = item.get("value") or ""
    return headers


def extract_gmail_body(payload: dict) -> str:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in walk_gmail_parts(payload):
        mime_type = part.get("mimeType") or ""
        data = (part.get("body") or {}).get("data")
        if not data:
            continue
        text = decode_gmail_base64url(data).decode("utf-8", errors="replace")
        if mime_type == "text/plain":
            plain_parts.append(text)
        elif mime_type == "text/html":
            html_parts.append(strip_html(text))
    return "\n\n".join(plain_parts).strip() or "\n\n".join(html_parts).strip()


def download_gmail_attachments(message: dict, access_token: str, target_dir: Path) -> tuple[list[IncomingAttachment], list[str]]:
    target_dir.mkdir(parents=True, exist_ok=True)
    attachments: list[IncomingAttachment] = []
    errors: list[str] = []
    message_id = message.get("id")
    for part in walk_gmail_parts(message.get("payload") or {}):
        filename = part.get("filename") or ""
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        if not filename or not attachment_id:
            continue
        safe_name = safe_upload_filename(filename)
        extension = Path(safe_name).suffix.lower()
        if extension not in {".pdf", ".txt", ".eml", ".xlsx", ".docx"}:
            errors.append(f"Skipped unsupported attachment {filename}")
            continue
        payload = gmail_api_get(f"/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}", access_token)
        data = payload.get("data")
        if not data:
            errors.append(f"Attachment {filename} had no data")
            continue
        path = unique_upload_path(target_dir, safe_name)
        path.write_bytes(decode_gmail_base64url(data))
        attachments.append(IncomingAttachment(path.name, part.get("mimeType") or mimetypes.guess_type(path.name)[0] or "application/octet-stream", path))
    return attachments, errors


def extract_outlook_sender(message: dict) -> str:
    email = ((message.get("from") or {}).get("emailAddress") or {})
    name = email.get("name") or ""
    address = email.get("address") or ""
    return f"{name} <{address}>".strip() if name and address else address or name


def extract_outlook_recipients(message: dict) -> str:
    values = []
    for recipient in message.get("toRecipients") or []:
        email = recipient.get("emailAddress") or {}
        name = email.get("name") or ""
        address = email.get("address") or ""
        values.append(f"{name} <{address}>".strip() if name and address else address or name)
    return ", ".join(value for value in values if value)


def extract_outlook_body_text(message: dict) -> str:
    body = message.get("body") or {}
    content = body.get("content") or ""
    if (body.get("contentType") or "").lower() == "html":
        return strip_html(content)
    return content


def outlook_mailbox_base_path(account: dict) -> str:
    connected = (account.get("connected_email") or "").strip().lower()
    monitored = (account.get("monitored_email") or "").strip()
    if monitored and monitored.lower() != connected:
        return f"/v1.0/users/{urllib.parse.quote(monitored, safe='')}"
    return "/v1.0/me"


def download_outlook_attachments(message_id: str, access_token: str, target_dir: Path, had_any_attachment: bool = False, account: dict | None = None) -> tuple[list[IncomingAttachment], list[str], bool]:
    target_dir.mkdir(parents=True, exist_ok=True)
    attachments: list[IncomingAttachment] = []
    errors: list[str] = []
    payload = outlook_api_get(f"{outlook_mailbox_base_path(account or {})}/messages/{urllib.parse.quote(message_id, safe='')}/attachments", access_token)
    for item in payload.get("value") or []:
        had_any_attachment = True
        odata_type = item.get("@odata.type") or ""
        if odata_type != "#microsoft.graph.fileAttachment":
            errors.append(f"Skipped unsupported Outlook attachment type {odata_type or 'unknown'}")
            continue
        filename = item.get("name") or ""
        safe_name = safe_upload_filename(filename)
        extension = Path(safe_name).suffix.lower()
        if extension not in {".pdf", ".txt", ".eml", ".xlsx", ".docx"}:
            errors.append(f"Skipped unsupported attachment {filename or 'unnamed'}")
            continue
        data = item.get("contentBytes")
        if not data:
            errors.append(f"Attachment {filename} had no content bytes")
            continue
        path = unique_upload_path(target_dir, safe_name)
        try:
            path.write_bytes(base64.b64decode(data))
        except Exception as exc:
            errors.append(f"Attachment {filename} could not be decoded: {exc}")
            continue
        attachments.append(IncomingAttachment(path.name, item.get("contentType") or mimetypes.guess_type(path.name)[0] or "application/octet-stream", path))
    return attachments, errors, had_any_attachment


def safe_storage_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-") or uuid.uuid4().hex


def walk_gmail_parts(part: dict):
    yield part
    for child in part.get("parts") or []:
        yield from walk_gmail_parts(child)


def decode_gmail_base64url(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+", " ", text)).strip()


def write_detection_result(
    conn,
    run_id: int,
    email_id: int | None,
    provider_message_id: str,
    classification: str | None,
    confidence: float | None,
    had_attachments: int,
    attachment_count: int,
    po_id: int | None,
    latency_ms: int,
    duplicate_skipped: bool,
    error_message: str,
) -> None:
    conn.execute(
        """
        INSERT INTO inbox_detection_results (
            inbox_sync_run_id, email_id, provider_message_id, detected_classification, detection_confidence,
            had_attachments, attachment_count, purchase_order_id, processing_latency_ms, duplicate_skipped,
            error_message
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (run_id, email_id, provider_message_id, classification, confidence, had_attachments, attachment_count, po_id, latency_ms, bool_int(duplicate_skipped), error_message),
    )
    upsert_inbox_message_record_from_detection(
        conn,
        run_id,
        provider_message_id,
        classification,
        attachment_count,
        po_id,
        error_message,
        duplicate_skipped,
    )


def upsert_inbox_message_record_from_detection(
    conn,
    run_id: int,
    provider_message_id: str,
    classification: str | None,
    attachment_count: int,
    po_id: int | None,
    error_message: str | None,
    duplicate_skipped: bool,
) -> None:
    run = conn.execute("SELECT inbox_account_id FROM inbox_sync_runs WHERE id = ?", (run_id,)).fetchone()
    provider = (provider_message_id or "").split(":", 1)[0] or "unknown"
    status = "failed" if error_message and classification not in {"skipped_no_supported_attachment", "skipped_outside_sync_range"} else "processed"
    if classification == "skipped_no_supported_attachment":
        status = "skipped_no_supported_attachment"
    elif duplicate_skipped:
        status = "skipped_duplicate"
    elif po_id:
        status = "po_created"
    conn.execute(
        """
        INSERT INTO inbox_message_records (
            inbox_account_id, provider, provider_message_id, attachment_count,
            supported_attachment_count, processing_status, last_processed_at,
            error_message, purchase_order_id
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
        ON CONFLICT(provider, provider_message_id)
        DO UPDATE SET inbox_account_id = excluded.inbox_account_id,
            attachment_count = excluded.attachment_count,
            supported_attachment_count = excluded.supported_attachment_count,
            processing_status = excluded.processing_status,
            last_processed_at = CURRENT_TIMESTAMP,
            error_message = excluded.error_message,
            purchase_order_id = excluded.purchase_order_id,
            updated_at = CURRENT_TIMESTAMP
        """,
        (run["inbox_account_id"] if run else None, provider, provider_message_id, attachment_count, attachment_count, status, error_message, po_id),
    )


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def list_inbox_detection_results() -> dict:
    with db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT dr.*, sr.inbox_account_id, imr.id AS inbox_message_record_id, imr.processing_status
                FROM inbox_detection_results dr
                LEFT JOIN inbox_sync_runs sr ON sr.id = dr.inbox_sync_run_id
                LEFT JOIN inbox_message_records imr ON imr.provider_message_id = dr.provider_message_id
                ORDER BY dr.created_at DESC LIMIT 100
                """
            ).fetchall()
        )
        messages = rows_to_dicts(
            conn.execute(
                """
                SELECT imr.*, ia.display_name AS inbox_display_name
                FROM inbox_message_records imr
                LEFT JOIN inbox_accounts ia ON ia.id = imr.inbox_account_id
                ORDER BY COALESCE(imr.last_processed_at, imr.created_at) DESC LIMIT 100
                """
            ).fetchall()
        )
    return {"results": rows, "messages": messages}


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_purchase_order_master_data_reviews(po_id: int) -> dict:
    with db() as conn:
        reviews = run_master_data_reviews(conn, po_id)
    return {"master_data_reviews": reviews}


def resolve_master_data_review(review_id: int, payload: dict) -> dict:
    with db() as conn:
        review = conn.execute("SELECT purchase_order_id, review_type FROM po_master_data_reviews WHERE id = ?", (review_id,)).fetchone()
        if not review:
            return {"error": "not_found"}
        resolve_review(conn, review_id, payload.get("matched_customer_id"), payload.get("matched_record_id"))
        po_id = review["purchase_order_id"]
        if review["review_type"] == "customer" and payload.get("matched_customer_id"):
            conn.execute(
                """
                UPDATE po_master_data_reviews
                SET matched_customer_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE purchase_order_id = ? AND status = 'open' AND matched_customer_id IS NULL
                """,
                (payload.get("matched_customer_id"), po_id),
            )
            conn.commit()
    return get_purchase_order(po_id)


def list_customer_part_xrefs() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM customer_part_xrefs ORDER BY customer_name, customer_part_number").fetchall())


def customer_part_xrefs_csv() -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["customer", "customer_part_number", "customer_part_revision", "internal_part_number", "internal_part_revision"],
        lineterminator="\n",
    )
    writer.writeheader()
    for row in list_customer_part_xrefs():
        writer.writerow(
            {
                "customer": row["customer_name"],
                "customer_part_number": row["customer_part_number"],
                "customer_part_revision": row.get("customer_part_revision"),
                "internal_part_number": row["internal_part_number"],
                "internal_part_revision": row.get("internal_part_revision"),
            }
        )
    return output.getvalue()


HEADER_EXPORT_FIELDS = [
    "id",
    "status",
    "order_type",
    "customer_company_name",
    "customer_contact_name",
    "po_number",
    "po_revision",
    "quote_number",
    "date_received",
    "payment_terms",
    "freight_terms",
    "bill_to_address",
    "ship_to_address",
    "total_value",
    "currency",
    "source",
    "source_type",
    "source_sender",
    "source_subject",
    "source_attachment_filename",
    "extraction_confidence",
    "extraction_notes",
    "created_at",
    "updated_at",
]

LINE_EXPORT_FIELDS = [
    "line_id",
    "line_number",
    "customer_part_number",
    "customer_part_revision",
    "internal_part_number",
    "internal_part_revision",
    "description",
    "quantity",
    "unit_of_measure",
    "unit_price",
    "line_total",
    "requested_date",
    "line_extraction_confidence",
    "line_extraction_notes",
]


def purchase_orders_csv(params: dict[str, list[str]], mode: str) -> str:
    output = io.StringIO()
    fields = HEADER_EXPORT_FIELDS + (LINE_EXPORT_FIELDS if mode == "lines" else [])
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    query, args = purchase_order_query(params)
    query += " GROUP BY po.id ORDER BY po.updated_at DESC"
    with db() as conn:
        pos = rows_to_dicts(conn.execute(query, args).fetchall())
        for po in pos:
            header = export_header_row(po)
            if mode != "lines":
                writer.writerow(header)
                continue
            lines = rows_to_dicts(
                conn.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id = ? ORDER BY id", (po["id"],)).fetchall()
            )
            if not lines:
                writer.writerow({**header, **{field: "" for field in LINE_EXPORT_FIELDS}})
                continue
            for line in lines:
                writer.writerow({**header, **export_line_row(line)})
    return output.getvalue()


def export_header_row(po: dict) -> dict:
    return {
        "id": po.get("id"),
        "status": po.get("status"),
        "order_type": po.get("order_type_name"),
        "customer_company_name": po.get("customer_company_name"),
        "customer_contact_name": po.get("customer_contact_name"),
        "po_number": po.get("po_number"),
        "po_revision": po.get("po_revision"),
        "quote_number": po.get("quote_number"),
        "date_received": po.get("date_received"),
        "payment_terms": po.get("payment_terms"),
        "freight_terms": po.get("freight_terms"),
        "bill_to_address": po.get("bill_to_address"),
        "ship_to_address": po.get("ship_to_address"),
        "total_value": po.get("total_value"),
        "currency": po.get("currency"),
        "source": po.get("source_display") or source_display(po),
        "source_type": po.get("source_type"),
        "source_sender": po.get("source_sender"),
        "source_subject": po.get("source_subject"),
        "source_attachment_filename": po.get("source_attachment_filename"),
        "extraction_confidence": po.get("extraction_confidence"),
        "extraction_notes": po.get("extraction_notes"),
        "created_at": po.get("created_at"),
        "updated_at": po.get("updated_at"),
    }


def export_line_row(line: dict) -> dict:
    return {
        "line_id": line.get("id"),
        "line_number": line.get("line_number"),
        "customer_part_number": line.get("customer_part_number"),
        "customer_part_revision": line.get("customer_part_revision"),
        "internal_part_number": line.get("internal_part_number"),
        "internal_part_revision": line.get("internal_part_revision"),
        "description": line.get("description"),
        "quantity": line.get("quantity"),
        "unit_of_measure": line.get("unit_of_measure"),
        "unit_price": line.get("unit_price"),
        "line_total": line.get("line_total"),
        "requested_date": line.get("requested_date"),
        "line_extraction_confidence": line.get("extraction_confidence"),
        "line_extraction_notes": line.get("extraction_notes"),
    }


def list_products() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM products ORDER BY is_active DESC, internal_part_number").fetchall())


def create_product(payload: dict) -> dict:
    internal_part_number = (payload.get("internal_part_number") or "").strip()
    if not internal_part_number:
        return {"error": "internal_part_number_required", "products": list_products()}
    with db() as conn:
        conn.execute(
            """
            INSERT INTO products (internal_part_number, internal_part_revision, description, unit_of_measure, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(internal_part_number) DO UPDATE SET
                internal_part_revision = excluded.internal_part_revision,
                description = excluded.description,
                unit_of_measure = excluded.unit_of_measure,
                is_active = excluded.is_active,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                internal_part_number,
                (payload.get("internal_part_revision") or "").strip(),
                (payload.get("description") or "").strip(),
                (payload.get("unit_of_measure") or "").strip(),
                1 if payload.get("is_active", True) else 0,
            ),
        )
        conn.commit()
    return {"products": list_products()}


def update_product(product_id: int, payload: dict) -> dict:
    allowed = ["internal_part_number", "internal_part_revision", "description", "unit_of_measure", "is_active"]
    if "is_active" in payload:
        payload["is_active"] = 1 if payload.get("is_active") else 0
    update_fields("products", product_id, payload, allowed)
    return {"products": list_products()}


def delete_product(product_id: int) -> dict:
    with db() as conn:
        used = conn.execute("SELECT COUNT(*) AS count FROM purchase_order_lines WHERE matched_product_id = ?", (product_id,)).fetchone()["count"]
        if used:
            conn.execute("UPDATE products SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (product_id,))
        else:
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
        conn.commit()
    return {"products": list_products()}


def products_csv() -> str:
    output = io.StringIO()
    fields = ["internal_part_number", "internal_part_revision", "description", "unit_of_measure", "is_active"]
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in list_products():
        writer.writerow({field: row.get(field) for field in fields})
    return output.getvalue()


def upload_products_csv(handler: AppHandler) -> dict:
    imported = 0
    skipped = 0
    errors: list[str] = []
    for filename, text in uploaded_csv_texts(handler, errors):
        reader = csv.DictReader(text.splitlines())
        if not reader.fieldnames:
            errors.append(f"{filename}: CSV has no header row.")
            continue
        field_map = {normalize_header(name): name for name in reader.fieldnames}
        aliases = {
            "internal_part_number": ["internal_part_number", "internalpartnumber", "part_number", "partnumber", "sku"],
            "internal_part_revision": ["internal_part_revision", "internalpartrevision", "revision", "rev"],
            "description": ["description", "item_description", "itemdescription"],
            "unit_of_measure": ["unit_of_measure", "uom", "unit"],
            "is_active": ["is_active", "active"],
        }
        resolved = {target: next((field_map[item] for item in options if item in field_map), None) for target, options in aliases.items()}
        if not resolved.get("internal_part_number"):
            errors.append(f"{filename}: Missing internal_part_number.")
            continue
        for index, row in enumerate(reader, start=2):
            part = (row.get(resolved["internal_part_number"]) or "").strip()
            if not part:
                skipped += 1
                errors.append(f"{filename} row {index}: missing internal_part_number.")
                continue
            create_product(
                {
                    "internal_part_number": part,
                    "internal_part_revision": row.get(resolved.get("internal_part_revision") or "", ""),
                    "description": row.get(resolved.get("description") or "", ""),
                    "unit_of_measure": row.get(resolved.get("unit_of_measure") or "", ""),
                    "is_active": parse_bool(row.get(resolved.get("is_active") or "", "1")),
                }
            )
            imported += 1
    return {"imported": imported, "skipped": skipped, "errors": errors, "products": list_products()}


def parse_bool(value: object) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "inactive"}


def list_review_tasks(params: dict[str, list[str]]) -> dict:
    status = params.get("status", ["open"])[0] or "open"
    severity = params.get("severity", [""])[0]
    reason = params.get("reason", [""])[0]
    owner = params.get("owner", [""])[0]
    customer = params.get("customer", [""])[0].lower()
    sort = params.get("sort", ["severity"])[0]
    query = """
        SELECT rt.*, po.po_number, po.customer_company_name, po.status AS po_status,
               CAST((julianday('now') - julianday(rt.created_at)) * 24 AS INTEGER) AS age_hours,
               COALESCE(NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''), u.name, u.email) AS assigned_to_display
        FROM review_tasks rt
        LEFT JOIN purchase_orders po ON po.id = rt.purchase_order_id
        LEFT JOIN users u ON u.id = rt.assigned_to_user_id
    """
    args: list[object] = []
    clauses = []
    if status != "all":
        clauses.append("rt.status = ?")
        args.append(status)
    if severity:
        clauses.append("rt.severity = ?")
        args.append(severity)
    if reason:
        clauses.append("rt.reason_code = ?")
        args.append(reason)
    if owner:
        clauses.append("COALESCE(rt.assigned_to_user_id, 0) = ?")
        args.append(int(owner))
    if customer:
        clauses.append("LOWER(COALESCE(po.customer_company_name, '')) LIKE ?")
        args.append(f"%{customer}%")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    order = {
        "oldest": "rt.created_at ASC, rt.id ASC",
        "newest": "rt.created_at DESC, rt.id DESC",
        "priority": "COALESCE(rt.priority, 2) ASC, rt.created_at ASC",
        "severity": "CASE rt.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, COALESCE(rt.priority, 2) ASC, rt.created_at ASC",
    }.get(sort, "CASE rt.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, COALESCE(rt.priority, 2) ASC, rt.created_at ASC")
    query += f" ORDER BY {order} LIMIT 300"
    with db() as conn:
        users = rows_to_dicts(
            conn.execute(
                """
                SELECT id, email, COALESCE(NULLIF(TRIM(first_name || ' ' || last_name), ''), name, email) AS display_name
                FROM users WHERE is_active = 1 ORDER BY display_name
                """
            ).fetchall()
        )
        return {"tasks": rows_to_dicts(conn.execute(query, args).fetchall()), "users": users}


def list_review_tasks_for_po(conn, po_id: int) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT * FROM review_tasks
            WHERE purchase_order_id = ?
            ORDER BY CASE status WHEN 'open' THEN 0 WHEN 'resolved' THEN 1 ELSE 2 END,
                     CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END,
                     created_at DESC
            """,
            (po_id,),
        ).fetchall()
    )


def list_extraction_evidence_for_po(conn, po_id: int) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT *
            FROM extraction_field_evidence
            WHERE purchase_order_id = ?
            ORDER BY purchase_order_line_id IS NOT NULL, field_name, id
            """,
            (po_id,),
        ).fetchall()
    )


def list_duplicate_candidates_for_po(conn, po_id: int) -> list[dict]:
    return rows_to_dicts(
        conn.execute(
            """
            SELECT dc.*, po.po_number AS candidate_po_number, po.po_revision AS candidate_po_revision,
                   po.customer_company_name AS candidate_customer, po.total_value AS candidate_total,
                   po.source_sender AS candidate_source_sender, po.date_received AS candidate_date_received,
                   po.source_attachment_filename AS candidate_attachment_filename,
                   (SELECT COUNT(*) FROM purchase_order_lines pol WHERE pol.purchase_order_id = po.id) AS candidate_line_count
            FROM po_duplicate_candidates dc
            LEFT JOIN purchase_orders po ON po.id = dc.candidate_purchase_order_id
            WHERE dc.purchase_order_id = ? OR dc.candidate_purchase_order_id = ?
            ORDER BY CASE dc.status WHEN 'open' THEN 0 ELSE 1 END, dc.created_at DESC
            """,
            (po_id, po_id),
        ).fetchall()
    )


def resolve_review_task_action(task_id: int, actor: dict, payload: dict | None = None) -> dict:
    payload = payload or {}
    with db() as conn:
        task = conn.execute("SELECT purchase_order_id, message, entity_type, entity_id FROM review_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE review_tasks
            SET status = 'resolved', resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP,
                resolved_reason = ?, resolution_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (actor.get("id"), payload.get("resolved_reason") or "manual", payload.get("resolution_note") or "", task_id),
        )
        if task["entity_type"] == "duplicate" and task["entity_id"]:
            conn.execute(
                "UPDATE po_duplicate_candidates SET status = 'resolved', resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP, resolution_note = ? WHERE id = ?",
                (actor.get("id"), payload.get("resolution_note") or "", task["entity_id"]),
            )
        record_audit_event(conn, task["purchase_order_id"], "review_task_resolved", "Review task resolved.", actor, {"task_id": task_id, "message": task["message"]})
        conn.commit()
    return get_purchase_order(task["purchase_order_id"])


def ignore_review_task_action(task_id: int, actor: dict, payload: dict | None = None) -> dict:
    payload = payload or {}
    with db() as conn:
        task = conn.execute("SELECT purchase_order_id, message, entity_type, entity_id FROM review_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "not_found"}
        conn.execute(
            """
            UPDATE review_tasks
            SET status = 'ignored', ignored_by_user_id = ?, ignored_at = CURRENT_TIMESTAMP,
                resolution_note = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (actor.get("id"), payload.get("resolution_note") or "", task_id),
        )
        if task["entity_type"] == "duplicate" and task["entity_id"]:
            conn.execute(
                "UPDATE po_duplicate_candidates SET status = 'ignored', resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP, resolution_note = ? WHERE id = ?",
                (actor.get("id"), payload.get("resolution_note") or "", task["entity_id"]),
            )
        record_audit_event(conn, task["purchase_order_id"], "review_task_ignored", "Review task ignored.", actor, {"task_id": task_id, "message": task["message"]})
        conn.commit()
    return get_purchase_order(task["purchase_order_id"])


def assign_review_task_action(task_id: int, payload: dict, actor: dict) -> dict:
    assigned_to = payload.get("assigned_to_user_id")
    with db() as conn:
        task = conn.execute("SELECT purchase_order_id FROM review_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            return {"error": "not_found"}
        conn.execute(
            "UPDATE review_tasks SET assigned_to_user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (assigned_to or None, task_id),
        )
        record_audit_event(conn, task["purchase_order_id"], "review_task_assigned", "Review task assigned.", actor, {"task_id": task_id, "assigned_to_user_id": assigned_to})
        conn.commit()
    return {"ok": True, **list_review_tasks({})}


def bulk_review_tasks_action(payload: dict, actor: dict) -> dict:
    task_ids = [int(item) for item in payload.get("task_ids") or []]
    action = payload.get("action")
    assigned_to = payload.get("assigned_to_user_id")
    if not task_ids:
        return {"error": "Select at least one exception.", **list_review_tasks({})}
    placeholders = ",".join("?" for _ in task_ids)
    with db() as conn:
        if action == "assign":
            conn.execute(f"UPDATE review_tasks SET assigned_to_user_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})", [assigned_to or None, *task_ids])
        elif action == "resolve":
            conn.execute(
                f"UPDATE review_tasks SET status = 'resolved', resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP, resolved_reason = 'bulk', updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [actor.get("id"), *task_ids],
            )
        elif action == "ignore":
            conn.execute(
                f"UPDATE review_tasks SET status = 'ignored', ignored_by_user_id = ?, ignored_at = CURRENT_TIMESTAMP, resolution_note = 'Bulk ignored', updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
                [actor.get("id"), *task_ids],
            )
        else:
            return {"error": "Unknown bulk action.", **list_review_tasks({})}
        conn.commit()
    return list_review_tasks({})


def duplicate_candidate_action(candidate_id: int, payload: dict, actor: dict) -> dict:
    action = payload.get("action")
    status = {
        "mark_duplicate": "confirmed_duplicate",
        "keep_both": "keep_both",
        "link_revision": "linked_revision",
        "ignore": "ignored",
    }.get(action)
    if not status:
        return {"error": "Unknown duplicate action."}
    with db() as conn:
        candidate = conn.execute("SELECT * FROM po_duplicate_candidates WHERE id = ?", (candidate_id,)).fetchone()
        if not candidate:
            return {"error": "not_found"}
        conn.execute(
            "UPDATE po_duplicate_candidates SET status = ?, resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP, resolution_note = ? WHERE id = ?",
            (status, actor.get("id"), payload.get("resolution_note") or "", candidate_id),
        )
        conn.execute(
            """
            UPDATE review_tasks
            SET status = CASE WHEN ? = 'ignored' THEN 'ignored' ELSE 'resolved' END,
                resolved_by_user_id = ?, resolved_at = CURRENT_TIMESTAMP,
                ignored_by_user_id = CASE WHEN ? = 'ignored' THEN ? ELSE ignored_by_user_id END,
                ignored_at = CASE WHEN ? = 'ignored' THEN CURRENT_TIMESTAMP ELSE ignored_at END,
                resolved_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE entity_type = 'duplicate' AND entity_id = ? AND status = 'open'
            """,
            (status, actor.get("id"), status, actor.get("id"), status, status, candidate_id),
        )
        record_audit_event(conn, candidate["purchase_order_id"], "duplicate_candidate_resolved", f"Duplicate candidate marked {status}.", actor, {"candidate_id": candidate_id, "status": status})
        conn.commit()
    return get_purchase_order(candidate["purchase_order_id"])


def record_audit_event(conn, po_id: int | None, event_type: str, message: str, actor: dict | None = None, metadata: dict | None = None) -> None:
    if not po_id:
        return
    conn.execute(
        """
        INSERT INTO po_audit_events (purchase_order_id, event_type, message, metadata_json, created_by_user_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (po_id, event_type, message, json.dumps(metadata or {}), actor.get("id") if actor else None),
    )


def resolve_review_tasks_for_fields(conn, po_id: int, line_id: int | None, field_names, actor: dict | None = None) -> None:
    fields = [field for field in field_names if field not in {"extraction_notes"}]
    if not fields:
        return
    placeholders = ",".join("?" for _ in fields)
    args: list[object] = [actor.get("id") if actor else None, po_id, *fields]
    line_clause = ""
    if line_id is not None:
        line_clause = " AND purchase_order_line_id = ?"
        args.append(line_id)
    else:
        line_clause = " AND purchase_order_line_id IS NULL"
    conn.execute(
        f"""
        UPDATE review_tasks
        SET status = 'resolved', resolved_by_user_id = COALESCE(?, resolved_by_user_id),
            resolved_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE purchase_order_id = ? AND status = 'open' AND field_name IN ({placeholders}){line_clause}
        """,
        args,
    )


def list_audit_events_for_po(conn, po_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT ae.*, u.email AS user_email,
               COALESCE(NULLIF(TRIM(u.first_name || ' ' || u.last_name), ''), u.name, u.email) AS user_display
        FROM po_audit_events ae
        LEFT JOIN users u ON u.id = ae.created_by_user_id
        WHERE ae.purchase_order_id = ?
        ORDER BY ae.created_at DESC, ae.id DESC
        LIMIT 100
        """,
        (po_id,),
    ).fetchall()
    events = rows_to_dicts(rows)
    feedback = rows_to_dicts(
        conn.execute(
            """
            SELECT ef.created_at, ef.field_name, ef.extracted_value, ef.corrected_value, u.email AS user_email
            FROM extraction_feedback ef
            LEFT JOIN users u ON u.id = ef.created_by_user_id
            WHERE ef.purchase_order_id = ?
            ORDER BY ef.created_at DESC, ef.id DESC
            LIMIT 100
            """,
            (po_id,),
        ).fetchall()
    )
    for row in feedback:
        events.append(
            {
                "event_type": "field_correction",
                "message": f"{row['field_name']} corrected from '{row['extracted_value']}' to '{row['corrected_value']}'.",
                "created_at": row["created_at"],
                "user_display": row.get("user_email") or "",
            }
        )
    return sorted(events, key=lambda item: item.get("created_at") or "", reverse=True)[:100]


def confirmed_order_view(po_id: int) -> dict:
    detail = get_purchase_order(po_id)
    if detail.get("error"):
        return detail
    return {
        "purchase_order": detail["purchase_order"],
        "lines": detail["lines"],
        "summary": build_confirmed_order_text(detail),
    }


def acknowledgment_draft(po_id: int) -> dict:
    detail = get_purchase_order(po_id)
    if detail.get("error"):
        return detail
    po = detail["purchase_order"]
    email = detail.get("email") or {}
    subject = f"Purchase Order {po.get('po_number') or ''} Received".strip()
    body = build_confirmed_order_text(detail)
    body = f"Hello,\n\nWe have received purchase order {po.get('po_number') or ''}{(' revision ' + po.get('po_revision')) if po.get('po_revision') else ''}.\n\n{body}\n\nThank you."
    return {"to": email.get("sender") or po.get("source_sender") or "", "subject": subject, "body": body}


def build_confirmed_order_text(detail: dict) -> str:
    po = detail["purchase_order"]
    lines = detail.get("lines") or []
    line_text = "\n".join(
        f"- {line.get('line_number') or ''} {line.get('customer_part_number') or line.get('internal_part_number') or ''} {line.get('description') or ''}: {line.get('quantity') or ''} {line.get('unit_of_measure') or ''} @ {line.get('unit_price') or ''}"
        for line in lines
    )
    return "\n".join(
        [
            f"Customer: {po.get('customer_company_name') or ''}",
            f"PO: {po.get('po_number') or ''}",
            f"Status: {po.get('status') or ''}",
            f"Received: {po.get('date_received') or ''}",
            f"Ship To: {po.get('ship_to_address') or ''}",
            f"Bill To: {po.get('bill_to_address') or ''}",
            f"Total: {po.get('total_value') or ''} {po.get('currency') or ''}",
            "Lines:",
            line_text or "(no lines)",
        ]
    )


def operations_reporting() -> dict:
    params = {}
    with db() as conn:
        status_counts = {row["status"]: row["count"] for row in conn.execute("SELECT status, COUNT(*) AS count FROM purchase_orders GROUP BY status")}
        total = sum(status_counts.values())
        open_exceptions = conn.execute("SELECT COUNT(*) AS count FROM review_tasks WHERE status = 'open'").fetchone()["count"]
        pos_with_exceptions = conn.execute("SELECT COUNT(DISTINCT purchase_order_id) AS count FROM review_tasks WHERE status = 'open' AND purchase_order_id IS NOT NULL").fetchone()["count"]
        feedback_count = conn.execute("SELECT COUNT(*) AS count FROM extraction_feedback").fetchone()["count"]
        avg_conf = conn.execute("SELECT AVG(extraction_confidence) AS value FROM purchase_orders").fetchone()["value"] or 0
        received_by_day = rows_to_dicts(conn.execute("SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS count FROM purchase_orders GROUP BY day ORDER BY day DESC LIMIT 14").fetchall())
        booked_by_day = rows_to_dicts(conn.execute("SELECT substr(updated_at, 1, 10) AS day, COUNT(*) AS count FROM purchase_orders WHERE status = 'Booked' GROUP BY day ORDER BY day DESC LIMIT 14").fetchall())
        top_customers = rows_to_dicts(conn.execute("SELECT COALESCE(customer_company_name, 'Unknown') AS customer, COUNT(*) AS count FROM purchase_orders GROUP BY customer ORDER BY count DESC LIMIT 10").fetchall())
        pos_by_source = rows_to_dicts(conn.execute("SELECT COALESCE(source_type, 'unknown') AS source, COUNT(*) AS count FROM purchase_orders GROUP BY source ORDER BY count DESC").fetchall())
        top_exception_reasons = rows_to_dicts(conn.execute("SELECT reason_code, COUNT(*) AS count FROM review_tasks WHERE status = 'open' GROUP BY reason_code ORDER BY count DESC LIMIT 10").fetchall())
        oldest_exceptions = rows_to_dicts(
            conn.execute(
                """
                SELECT rt.id, rt.reason_code, rt.message, rt.created_at, po.po_number, po.customer_company_name,
                       CAST((julianday('now') - julianday(rt.created_at)) * 24 AS INTEGER) AS age_hours
                FROM review_tasks rt
                LEFT JOIN purchase_orders po ON po.id = rt.purchase_order_id
                WHERE rt.status = 'open'
                ORDER BY rt.created_at ASC LIMIT 10
                """
            ).fetchall()
        )
        correction_fields = rows_to_dicts(conn.execute("SELECT field_name, COUNT(*) AS count FROM extraction_feedback GROUP BY field_name ORDER BY count DESC LIMIT 10").fetchall())
        inbox_by_account = rows_to_dicts(
            conn.execute(
                """
                SELECT ia.display_name, ia.provider, COALESCE(SUM(sr.messages_seen), 0) AS messages_seen,
                       COALESCE(SUM(sr.messages_imported), 0) AS messages_imported,
                       COALESCE(SUM(sr.messages_skipped), 0) AS messages_skipped,
                       COALESCE(SUM(sr.purchase_orders_created), 0) AS purchase_orders_created,
                       COALESCE(SUM(sr.error_count), 0) AS error_count
                FROM inbox_accounts ia
                LEFT JOIN inbox_sync_runs sr ON sr.inbox_account_id = ia.id
                GROUP BY ia.id
                ORDER BY ia.provider, ia.display_name
                """
            ).fetchall()
        )
        duplicate_summary = row_to_dict(
            conn.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'confirmed_duplicate' THEN 1 ELSE 0 END) AS confirmed_duplicates,
                    SUM(CASE WHEN status = 'keep_both' THEN 1 ELSE 0 END) AS keep_both,
                    SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END) AS open_candidates,
                    COUNT(*) AS total_candidates
                FROM po_duplicate_candidates
                """
            ).fetchone()
        )
        inbox = row_to_dict(
            conn.execute(
                """
                SELECT COALESCE(SUM(messages_seen), 0) AS messages_seen,
                       COALESCE(SUM(messages_imported), 0) AS messages_imported,
                       COALESCE(SUM(messages_skipped), 0) AS messages_skipped,
                       COALESCE(SUM(purchase_orders_created), 0) AS purchase_orders_created
                FROM inbox_sync_runs
                """
            ).fetchone()
        )
        return {
            "status_counts": status_counts,
            "total_purchase_orders": total,
            "open_exceptions": open_exceptions,
            "exception_rate": (pos_with_exceptions / total) if total else 0,
            "average_extraction_confidence": avg_conf,
            "manual_correction_count": feedback_count,
            "received_by_day": received_by_day,
            "booked_by_day": booked_by_day,
            "top_customers": top_customers,
            "pos_by_source": pos_by_source,
            "top_exception_reasons": top_exception_reasons,
            "oldest_exceptions": oldest_exceptions,
            "correction_fields": correction_fields,
            "inbox_by_account": inbox_by_account,
            "duplicate_summary": duplicate_summary,
            "inbox": inbox,
        }


def retry_inbox_message(record_id: int) -> dict:
    with db() as conn:
        record = row_to_dict(conn.execute("SELECT * FROM inbox_message_records WHERE id = ?", (record_id,)).fetchone())
        if not record:
            return {"error": "not_found", **list_inbox_accounts()}
        conn.execute("UPDATE inbox_message_records SET retry_count = retry_count + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (record_id,))
        conn.commit()
    received = parse_iso_datetime(record.get("received_at"))
    payload = {"sync_mode": "retry"}
    if received:
        payload["start_at"] = (received - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        payload["end_at"] = (received + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    return sync_inbox_account(record["inbox_account_id"], payload)


def reporting_summary_csv(params: dict[str, list[str]]) -> str:
    metrics = operations_reporting()
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["metric", "value"])
    for key in ("total_purchase_orders", "open_exceptions", "exception_rate", "average_extraction_confidence", "manual_correction_count"):
        writer.writerow([key, metrics.get(key)])
    inbox = metrics.get("inbox") or {}
    for key, value in inbox.items():
        writer.writerow([f"inbox_{key}", value])
    return output.getvalue()


def reporting_exceptions_csv(params: dict[str, list[str]]) -> str:
    rows = list_review_tasks({"status": ["all"]})["tasks"]
    output = io.StringIO()
    fields = ["id", "status", "severity", "priority", "po_number", "customer_company_name", "reason_code", "message", "field_name", "current_value", "confidence", "assigned_to_display", "created_at", "resolved_at", "ignored_at"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def reporting_corrections_csv(params: dict[str, list[str]]) -> str:
    with db() as conn:
        rows = rows_to_dicts(
            conn.execute(
                """
                SELECT ef.*, po.po_number, po.customer_company_name AS po_customer, u.email AS user_email
                FROM extraction_feedback ef
                LEFT JOIN purchase_orders po ON po.id = ef.purchase_order_id
                LEFT JOIN users u ON u.id = ef.created_by_user_id
                ORDER BY ef.created_at DESC
                """
            ).fetchall()
        )
    output = io.StringIO()
    fields = ["created_at", "po_number", "po_customer", "entity_type", "field_name", "extracted_value", "corrected_value", "confidence", "user_email", "source_attachment_filename"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def create_customer_part_xref(payload: dict) -> dict:
    try:
        save_customer_part_xref(payload)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"xrefs": list_customer_part_xrefs()}


def update_customer_part_xref(xref_id: int, payload: dict) -> dict:
    allowed = ["customer_name", "customer_part_number", "customer_part_revision", "internal_part_number", "internal_part_revision"]
    update_fields("customer_part_xrefs", xref_id, payload, allowed)
    return {"xrefs": list_customer_part_xrefs()}


def delete_customer_part_xref(xref_id: int) -> dict:
    with db() as conn:
        conn.execute("DELETE FROM customer_part_xrefs WHERE id = ?", (xref_id,))
        conn.commit()
    return {"xrefs": list_customer_part_xrefs()}


def save_customer_part_xref(payload: dict) -> None:
    customer_name = (payload.get("customer_name") or payload.get("customer") or "").strip()
    customer_part = (payload.get("customer_part_number") or "").strip()
    customer_part_revision = (payload.get("customer_part_revision") or "").strip()
    internal_part = (payload.get("internal_part_number") or "").strip()
    has_internal_part_revision = "internal_part_revision" in payload
    internal_part_revision = (payload.get("internal_part_revision") or "").strip()
    if not customer_name or not customer_part or not internal_part:
        raise ValueError("customer_name, customer_part_number, and internal_part_number are required")
    with db() as conn:
        existing = conn.execute(
            """
            SELECT id FROM customer_part_xrefs
            WHERE LOWER(TRIM(customer_name)) = LOWER(TRIM(?))
              AND LOWER(TRIM(customer_part_number)) = LOWER(TRIM(?))
              AND LOWER(TRIM(COALESCE(customer_part_revision, ''))) = LOWER(TRIM(?))
            """,
            (customer_name, customer_part, customer_part_revision),
        ).fetchone()
        if existing:
            if has_internal_part_revision:
                conn.execute(
                    """
                    UPDATE customer_part_xrefs
                    SET internal_part_number = ?, internal_part_revision = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (internal_part, internal_part_revision, existing["id"]),
                )
            else:
                conn.execute(
                    """
                    UPDATE customer_part_xrefs
                    SET internal_part_number = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (internal_part, existing["id"]),
                )
        else:
            conn.execute(
                """
                INSERT INTO customer_part_xrefs (
                    customer_name, customer_part_number, customer_part_revision,
                    internal_part_number, internal_part_revision
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (customer_name, customer_part, customer_part_revision, internal_part, internal_part_revision),
            )
        conn.commit()


def upload_customer_part_xrefs(handler: AppHandler) -> dict:
    imported = 0
    skipped = 0
    errors: list[str] = []
    for filename, text in uploaded_csv_texts(handler, errors):
        result = import_xref_csv(text)
        imported += result["imported"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"imported": imported, "skipped": skipped, "errors": errors, "xrefs": list_customer_part_xrefs()}


def uploaded_csv_texts(handler: AppHandler, errors: list[str]) -> list[tuple[str, str]]:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        errors.append("Expected multipart/form-data upload.")
        return []
    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
        },
    )
    fields = form["files"] if "files" in form else form["file"] if "file" in form else []
    if not isinstance(fields, list):
        fields = [fields]
    files: list[tuple[str, str]] = []
    for field in fields:
        raw_name = getattr(field, "filename", "") or ""
        filename = safe_upload_filename(raw_name)
        if Path(filename).suffix.lower() != ".csv":
            errors.append(f"{raw_name or '(missing)'}: only .csv files are allowed")
            continue
        files.append((filename, field.file.read().decode("utf-8-sig", errors="replace")))
    return files


def import_xref_csv(text: str) -> dict:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return {"imported": 0, "skipped": 0, "errors": ["CSV has no header row"]}
    field_map = {normalize_header(name): name for name in reader.fieldnames}
    aliases = {
        "customer_name": ["customer", "customer_name", "customercompany", "customer_company", "customername"],
        "customer_part_number": ["customer_part_number", "customerpartnumber", "customer_sku", "customersku", "customerpart"],
        "customer_part_revision": ["customer_part_revision", "customerpartrevision", "customer_rev", "customerrev", "part_rev", "partrevision"],
        "internal_part_number": ["internal_part_number", "internalpartnumber", "internal_sku", "internalsku", "internalpart"],
        "internal_part_revision": ["internal_part_revision", "internalpartrevision", "internal_rev", "internalrev"],
    }
    resolved = {}
    for target, options in aliases.items():
        for option in options:
            if option in field_map:
                resolved[target] = field_map[option]
                break
    missing = [target for target in ("customer_name", "customer_part_number", "internal_part_number") if target not in resolved]
    if missing:
        return {"imported": 0, "skipped": 0, "errors": [f"Missing required columns: {', '.join(missing)}"]}
    imported = 0
    skipped = 0
    errors: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        payload = {
            "customer_name": row.get(resolved["customer_name"], ""),
                "customer_part_number": row.get(resolved["customer_part_number"], ""),
                "customer_part_revision": row.get(resolved.get("customer_part_revision", ""), ""),
                "internal_part_number": row.get(resolved["internal_part_number"], ""),
                "internal_part_revision": row.get(resolved.get("internal_part_revision", ""), ""),
            }
        try:
            save_customer_part_xref(payload)
            imported += 1
        except ValueError as exc:
            skipped += 1
            errors.append(f"Row {row_number}: {exc}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


def upload_customers_csv(handler: AppHandler) -> dict:
    imported = 0
    skipped = 0
    errors: list[str] = []
    for _filename, text in uploaded_csv_texts(handler, errors):
        result = import_customers_csv(text)
        imported += result["imported"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"imported": imported, "skipped": skipped, "errors": errors, "customers": list_customers()}


def upload_customer_contacts_csv(handler: AppHandler) -> dict:
    imported = 0
    skipped = 0
    errors: list[str] = []
    for _filename, text in uploaded_csv_texts(handler, errors):
        result = import_customer_contacts_csv(text)
        imported += result["imported"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"imported": imported, "skipped": skipped, "errors": errors, "customers": list_customers()}


def import_customers_csv(text: str) -> dict:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return {"imported": 0, "skipped": 0, "errors": ["CSV has no header row"]}
    field_map = {normalize_header(name): name for name in reader.fieldnames}
    aliases = {
        "customer_name": ["customer_name", "customer", "customername"],
        "customer_number": ["customer_number", "customernumber", "customer_no", "customerno", "customer #", "customer#"],
        "payment_terms": ["payment_terms", "paymentterms", "terms"],
        "address_type": ["address_type", "addresstype"],
        "label": ["label", "address_label", "addresslabel"],
        "address_line_1": ["address_line_1", "addressline1", "address 1", "address1"],
        "address_line_2": ["address_line_2", "addressline2", "address 2", "address2"],
        "address_line_3": ["address_line_3", "addressline3", "address 3", "address3"],
        "city": ["city"],
        "state": ["state", "province"],
        "country": ["country"],
        "zip_code": ["zip_code", "zipcode", "zip", "postal_code", "postalcode"],
        "is_default": ["is_default", "isdefault", "default"],
    }
    resolved = resolve_csv_aliases(field_map, aliases)
    if "customer_name" not in resolved and "customer_number" not in resolved:
        return {"imported": 0, "skipped": 0, "errors": ["Missing required customer_name or customer_number column"]}
    imported = 0
    skipped = 0
    errors: list[str] = []
    with db() as conn:
        for row_number, row in enumerate(reader, start=2):
            try:
                customer_id = upsert_customer_from_csv(conn, csv_value(row, resolved, "customer_name"), csv_value(row, resolved, "customer_number"), csv_value(row, resolved, "payment_terms"))
                if not customer_id:
                    raise ValueError("customer_name or customer_number is required")
                if any(csv_value(row, resolved, key) for key in ["address_type", "address_line_1", "address_line_2", "address_line_3", "city", "state", "country", "zip_code"]):
                    address_type = csv_value(row, resolved, "address_type") or "bill_to"
                    address_payload = {
                        "address_type": address_type if address_type in {"bill_to", "ship_to"} else "bill_to",
                        "label": csv_value(row, resolved, "label"),
                        "address_line_1": csv_value(row, resolved, "address_line_1"),
                        "address_line_2": csv_value(row, resolved, "address_line_2"),
                        "address_line_3": csv_value(row, resolved, "address_line_3"),
                        "city": csv_value(row, resolved, "city"),
                        "state": csv_value(row, resolved, "state"),
                        "country": csv_value(row, resolved, "country"),
                        "zip_code": csv_value(row, resolved, "zip_code"),
                        "is_default": csv_value(row, resolved, "is_default").lower() in {"1", "true", "yes", "y"},
                    }
                    upsert_customer_address_from_csv(conn, customer_id, address_payload)
                imported += 1
            except ValueError as exc:
                skipped += 1
                errors.append(f"Row {row_number}: {exc}")
        conn.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}


def import_customer_contacts_csv(text: str) -> dict:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return {"imported": 0, "skipped": 0, "errors": ["CSV has no header row"]}
    field_map = {normalize_header(name): name for name in reader.fieldnames}
    aliases = {
        "customer_name": ["customer_name", "customer", "customername"],
        "customer_number": ["customer_number", "customernumber", "customer_no", "customerno"],
        "first_name": ["first_name", "firstname", "first"],
        "last_name": ["last_name", "lastname", "last"],
        "job_title": ["job_title", "jobtitle", "title"],
        "phone_number": ["phone_number", "phonenumber", "phone"],
        "email": ["email", "email_address", "emailaddress"],
    }
    resolved = resolve_csv_aliases(field_map, aliases)
    imported = 0
    skipped = 0
    errors: list[str] = []
    with db() as conn:
        for row_number, row in enumerate(reader, start=2):
            customer = find_customer_for_csv(conn, csv_value(row, resolved, "customer_name"), csv_value(row, resolved, "customer_number"))
            if not customer:
                skipped += 1
                errors.append(f"Row {row_number}: matching customer was not found")
                continue
            first_name = csv_value(row, resolved, "first_name")
            last_name = csv_value(row, resolved, "last_name")
            email = csv_value(row, resolved, "email")
            if not any([first_name, last_name, email]):
                skipped += 1
                errors.append(f"Row {row_number}: contact name or email is required")
                continue
            conn.execute(
                """
                INSERT INTO customer_contacts (customer_id, first_name, last_name, job_title, phone_number, email)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (customer["id"], first_name, last_name, csv_value(row, resolved, "job_title"), csv_value(row, resolved, "phone_number"), email),
            )
            imported += 1
        conn.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors}


def resolve_csv_aliases(field_map: dict[str, str], aliases: dict[str, list[str]]) -> dict[str, str]:
    resolved = {}
    for target, options in aliases.items():
        for option in options:
            normalized = normalize_header(option)
            if normalized in field_map:
                resolved[target] = field_map[normalized]
                break
    return resolved


def csv_value(row: dict, resolved: dict[str, str], key: str) -> str:
    return (row.get(resolved.get(key, ""), "") or "").strip()


def upsert_customer_from_csv(conn, customer_name: str, customer_number: str, payment_terms: str) -> int | None:
    if not customer_name and not customer_number:
        return None
    payment_terms_id = None
    if payment_terms:
        term = conn.execute("SELECT id, name FROM payment_terms WHERE LOWER(TRIM(name)) = LOWER(TRIM(?))", (payment_terms,)).fetchone()
        if term:
            payment_terms_id = term["id"]
            payment_terms = term["name"]
    existing = find_customer_for_csv(conn, customer_name, customer_number)
    if existing:
        conn.execute(
            """
            UPDATE customers
            SET customer_name = COALESCE(NULLIF(?, ''), customer_name),
                customer_number = COALESCE(NULLIF(?, ''), customer_number),
                payment_terms = COALESCE(NULLIF(?, ''), payment_terms),
                payment_terms_id = COALESCE(?, payment_terms_id),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (customer_name, customer_number, payment_terms, payment_terms_id, existing["id"]),
        )
        return existing["id"]
    cur = conn.execute(
        "INSERT INTO customers (customer_name, customer_number, payment_terms, payment_terms_id) VALUES (?, ?, ?, ?)",
        (customer_name or customer_number, customer_number, payment_terms, payment_terms_id),
    )
    return int(cur.lastrowid)


def find_customer_for_csv(conn, customer_name: str, customer_number: str):
    if customer_number:
        row = conn.execute("SELECT * FROM customers WHERE LOWER(TRIM(customer_number)) = LOWER(TRIM(?))", (customer_number,)).fetchone()
        if row:
            return row
    if customer_name:
        return conn.execute("SELECT * FROM customers WHERE LOWER(TRIM(customer_name)) = LOWER(TRIM(?))", (customer_name,)).fetchone()
    return None


def upsert_customer_address_from_csv(conn, customer_id: int, payload: dict) -> None:
    address_text = format_structured_address(payload)
    existing = conn.execute(
        """
        SELECT id FROM customer_addresses
        WHERE customer_id = ? AND address_type = ? AND LOWER(TRIM(COALESCE(label, ''))) = LOWER(TRIM(?))
          AND LOWER(TRIM(COALESCE(address_line_1, ''))) = LOWER(TRIM(?))
        """,
        (customer_id, payload["address_type"], payload.get("label") or "", payload.get("address_line_1") or ""),
    ).fetchone()
    values = (
        payload["address_type"],
        payload.get("label"),
        address_text,
        payload.get("address_line_1"),
        payload.get("address_line_2"),
        payload.get("address_line_3"),
        payload.get("city"),
        payload.get("state"),
        payload.get("country"),
        payload.get("zip_code"),
        bool_int(payload.get("is_default")),
    )
    if existing:
        conn.execute(
            """
            UPDATE customer_addresses
            SET address_type = ?, label = ?, address_text = ?, address_line_1 = ?, address_line_2 = ?,
                address_line_3 = ?, city = ?, state = ?, country = ?, zip_code = ?, is_default = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (*values, existing["id"]),
        )
    else:
        conn.execute(
            """
            INSERT INTO customer_addresses (
                customer_id, address_type, label, address_text, address_line_1, address_line_2,
                address_line_3, city, state, country, zip_code, is_default
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (customer_id, *values),
        )


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def line_total_from_payload(payload: dict) -> float | None:
    if payload.get("quantity") not in (None, "") and payload.get("unit_price") not in (None, ""):
        return round(float(payload["quantity"]) * float(payload["unit_price"]), 2)
    return None


def mark_fields_reviewed(table: str, row_id: int, fields: object) -> None:
    json_column = "field_confidence_json"
    field_names = [field for field in fields if field not in {"id", "total_value"}]
    if not field_names:
        return
    with db() as conn:
        row = conn.execute(f"SELECT {json_column} FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return
        try:
            confidence = json.loads(row[json_column] or "{}")
        except json.JSONDecodeError:
            confidence = {}
        for field in field_names:
            confidence[field] = 1.0
        conn.execute(f"UPDATE {table} SET {json_column} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (json.dumps(confidence), row_id))
        conn.commit()


ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".eml", ".xlsx", ".docx"}


def upload_samples(handler: AppHandler) -> dict:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        return {"error": "expected_multipart"}

    upload_dir = SAMPLES_DIR / "uploaded"
    upload_dir.mkdir(parents=True, exist_ok=True)
    rejected: list[dict[str, str]] = []
    saved: list[str] = []

    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
        },
    )
    fields = form["files"] if "files" in form else []
    if not isinstance(fields, list):
        fields = [fields]

    for field in fields:
        raw_name = getattr(field, "filename", "") or ""
        filename = safe_upload_filename(raw_name)
        extension = Path(filename).suffix.lower()
        if not filename or extension not in ALLOWED_UPLOAD_EXTENSIONS:
            rejected.append({"filename": raw_name or "(missing)", "reason": "Only .pdf, .txt, .eml, .xlsx, and .docx files are allowed."})
            continue
        target = unique_upload_path(upload_dir, filename)
        with target.open("wb") as output:
            output.write(field.file.read())
        saved.append(str(target.relative_to(SAMPLES_DIR)))

    with db() as conn:
        result = import_samples(conn, SAMPLES_DIR, STORAGE_DIR)
    return {**result, "saved_files": saved, "rejected_files": rejected}


def safe_upload_filename(filename: str) -> str:
    name = Path(filename).name
    stem = Path(name).stem
    suffix = Path(name).suffix.lower()
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-")
    if not cleaned:
        return ""
    return f"{cleaned}{suffix}"


def unique_upload_path(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    return directory / f"{Path(filename).stem}-{uuid.uuid4().hex[:8]}{Path(filename).suffix}"


def start_background_sync_runner() -> None:
    if not ENABLE_BACKGROUND_SYNC:
        return
    thread = threading.Thread(target=background_sync_loop, name="poinbox-background-sync", daemon=True)
    thread.start()


def background_sync_loop() -> None:
    while True:
        try:
            run_due_background_syncs()
        except Exception as exc:
            with db() as conn:
                conn.execute(
                    "INSERT INTO processing_logs (level, message, metadata_json) VALUES ('error', ?, ?)",
                    ("Background sync runner failed.", json.dumps({"error": str(exc)})),
                )
                conn.commit()
        time.sleep(60)


def run_due_background_syncs() -> None:
    now = datetime.utcnow()
    with db() as conn:
        accounts = rows_to_dicts(
            conn.execute(
                """
                SELECT id, last_sync_at, next_sync_at
                FROM inbox_accounts
                WHERE is_enabled = 1 AND sync_status IN ('connected', 'synced', 'sync_failed')
                  AND next_sync_at IS NOT NULL AND next_sync_at <= ?
                ORDER BY next_sync_at
                LIMIT 5
                """,
                (now.isoformat(),),
            ).fetchall()
        )
    for account in accounts:
        if account["id"] in SYNC_LOCKS:
            continue
        start_at = account.get("last_sync_at") or (now - timedelta(hours=24)).isoformat()
        sync_inbox_account(account["id"], {"start_at": start_at, "end_at": now.isoformat()})


def main() -> None:
    validate_production_config()
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    with db():
        pass
    start_background_sync_runner()
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), AppHandler)
    print(f"POInbox PO Intake MVP running at http://{APP_HOST}:{APP_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

from __future__ import annotations

import json
import re
import sys
import uuid
import cgi
import csv
import io
import mimetypes
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.config import APP_HOST, APP_PORT, DATABASE_PATH, PUBLIC_DIR, SAMPLES_DIR, STORAGE_DIR
from server.db import connect, initialize, row_to_dict, rows_to_dicts
from server.processing import import_samples, recalculate_po_total
from server.extraction import normalize_date


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/summary":
            return self.respond_json(get_summary())
        if parsed.path == "/api/purchase-orders":
            params = parse_qs(parsed.query)
            return self.respond_json(list_purchase_orders(params))
        if parsed.path == "/api/order-types":
            return self.respond_json(list_order_types())
        if parsed.path == "/api/customer-part-xrefs":
            return self.respond_json(list_customer_part_xrefs())
        if parsed.path == "/api/customer-part-xrefs.csv":
            return self.respond_csv(customer_part_xrefs_csv(), "customer-part-cross-reference.csv")
        if parsed.path == "/api/export/purchase-orders.csv":
            params = parse_qs(parsed.query)
            mode = params.get("mode", ["header"])[0]
            filename = "purchase-orders-with-lines.csv" if mode == "lines" else "purchase-orders-header.csv"
            return self.respond_csv(purchase_orders_csv(params, mode), filename)
        if parsed.path.startswith("/api/attachments/") and parsed.path.endswith("/view"):
            attachment_id = int(parsed.path.split("/")[-2])
            return self.serve_attachment(attachment_id)
        if parsed.path.startswith("/api/purchase-orders/"):
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(get_purchase_order(po_id))
        if parsed.path == "/api/logs":
            return self.respond_json(get_logs())
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/upload-samples":
            return self.respond_json(upload_samples(self))
        if parsed.path == "/api/customer-part-xrefs/upload":
            return self.respond_json(upload_customer_part_xrefs(self))
        if parsed.path == "/api/customer-part-xrefs":
            return self.respond_json(create_customer_part_xref(self.read_json()))
        if parsed.path == "/api/order-types":
            return self.respond_json(create_order_type(self.read_json()))
        if parsed.path == "/api/import-samples":
            with db() as conn:
                result = import_samples(conn, SAMPLES_DIR, STORAGE_DIR)
            return self.respond_json(result)
        if parsed.path.startswith("/api/purchase-orders/") and parsed.path.endswith("/lines"):
            po_id = int(parsed.path.split("/")[-2])
            payload = self.read_json()
            return self.respond_json(add_line(po_id, payload))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/customer-part-xrefs/"):
            xref_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_customer_part_xref(xref_id, self.read_json()))
        if parsed.path.startswith("/api/order-types/"):
            order_type_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_order_type(order_type_id, self.read_json()))
        if parsed.path.startswith("/api/purchase-orders/") and "/lines/" in parsed.path:
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_line(line_id, self.read_json()))
        if parsed.path.startswith("/api/purchase-orders/"):
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(update_purchase_order(po_id, self.read_json()))
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/customer-part-xrefs/"):
            xref_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_customer_part_xref(xref_id))
        if parsed.path.startswith("/api/order-types/"):
            order_type_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_order_type(order_type_id))
        if parsed.path.startswith("/api/purchase-orders/") and "/lines/" in parsed.path:
            line_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_line(line_id))
        if parsed.path.startswith("/api/purchase-orders/"):
            po_id = int(parsed.path.rsplit("/", 1)[-1])
            return self.respond_json(delete_purchase_order(po_id))
        self.send_error(HTTPStatus.NOT_FOUND)

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
        SELECT po.*, ot.name AS order_type_name, COUNT(pol.id) AS line_count
        FROM purchase_orders po
        LEFT JOIN purchase_order_lines pol ON pol.purchase_order_id = po.id
        LEFT JOIN order_types ot ON ot.id = po.order_type_id
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
        lines = rows_to_dicts(conn.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id = ? ORDER BY id", (po_id,)).fetchall())
        email = row_to_dict(conn.execute("SELECT * FROM emails WHERE id = ?", (po["email_id"],)).fetchone())
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
        return {"purchase_order": po, "lines": lines, "email": email, "attachment": attachment, "order_types": order_types}


def update_purchase_order(po_id: int, payload: dict) -> dict:
    allowed = [
        "status",
        "customer_company_name",
        "customer_contact_name",
        "bill_to_address",
        "ship_to_address",
        "po_number",
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
    update_fields("purchase_orders", po_id, payload, allowed)
    mark_fields_reviewed("purchase_orders", po_id, payload.keys())
    return get_purchase_order(po_id)


def add_line(po_id: int, payload: dict) -> dict:
    with db() as conn:
        po_number = conn.execute("SELECT po_number FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()["po_number"]
        line_total = line_total_from_payload(payload)
        conn.execute(
            """
            INSERT INTO purchase_order_lines (
                purchase_order_id, po_number, line_number, customer_part_number, internal_part_number, description,
                quantity, unit_of_measure, unit_price, line_total, requested_date, extraction_confidence, extraction_notes,
                field_confidence_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.5, 'Manually added', ?)
            """,
            (
                po_id,
                po_number,
                payload.get("line_number"),
                payload.get("customer_part_number"),
                payload.get("internal_part_number"),
                payload.get("description"),
                payload.get("quantity"),
                payload.get("unit_of_measure"),
                payload.get("unit_price"),
                line_total,
                payload.get("requested_date"),
                json.dumps({key: 1.0 for key in payload.keys()}),
            ),
        )
        conn.execute("UPDATE purchase_orders SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (po_id,))
        conn.commit()
        recalculate_po_total(conn, po_id)
    return get_purchase_order(po_id)


def update_line(line_id: int, payload: dict) -> dict:
    allowed = [
        "line_number",
        "customer_part_number",
        "internal_part_number",
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
    update_fields("purchase_order_lines", line_id, payload, allowed)
    mark_fields_reviewed("purchase_order_lines", line_id, payload.keys())
    with db() as conn:
        po_id = conn.execute("SELECT purchase_order_id FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()["purchase_order_id"]
        row = conn.execute("SELECT quantity, unit_price FROM purchase_order_lines WHERE id = ?", (line_id,)).fetchone()
        calculated = line_total_from_payload(dict(row))
        conn.execute("UPDATE purchase_order_lines SET line_total = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (calculated, line_id))
        recalculate_po_total(conn, po_id)
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


def list_customer_part_xrefs() -> list[dict]:
    with db() as conn:
        return rows_to_dicts(conn.execute("SELECT * FROM customer_part_xrefs ORDER BY customer_name, customer_part_number").fetchall())


def customer_part_xrefs_csv() -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["customer", "customer_part_number", "internal_part_number"], lineterminator="\n")
    writer.writeheader()
    for row in list_customer_part_xrefs():
        writer.writerow(
            {
                "customer": row["customer_name"],
                "customer_part_number": row["customer_part_number"],
                "internal_part_number": row["internal_part_number"],
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
    "quote_number",
    "date_received",
    "payment_terms",
    "freight_terms",
    "bill_to_address",
    "ship_to_address",
    "total_value",
    "currency",
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
    "internal_part_number",
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
        "quote_number": po.get("quote_number"),
        "date_received": po.get("date_received"),
        "payment_terms": po.get("payment_terms"),
        "freight_terms": po.get("freight_terms"),
        "bill_to_address": po.get("bill_to_address"),
        "ship_to_address": po.get("ship_to_address"),
        "total_value": po.get("total_value"),
        "currency": po.get("currency"),
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
        "internal_part_number": line.get("internal_part_number"),
        "description": line.get("description"),
        "quantity": line.get("quantity"),
        "unit_of_measure": line.get("unit_of_measure"),
        "unit_price": line.get("unit_price"),
        "line_total": line.get("line_total"),
        "requested_date": line.get("requested_date"),
        "line_extraction_confidence": line.get("extraction_confidence"),
        "line_extraction_notes": line.get("extraction_notes"),
    }


def create_customer_part_xref(payload: dict) -> dict:
    try:
        save_customer_part_xref(payload)
    except ValueError as exc:
        return {"error": str(exc)}
    return {"xrefs": list_customer_part_xrefs()}


def update_customer_part_xref(xref_id: int, payload: dict) -> dict:
    allowed = ["customer_name", "customer_part_number", "internal_part_number"]
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
    internal_part = (payload.get("internal_part_number") or "").strip()
    if not customer_name or not customer_part or not internal_part:
        raise ValueError("customer_name, customer_part_number, and internal_part_number are required")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO customer_part_xrefs (customer_name, customer_part_number, internal_part_number)
            VALUES (?, ?, ?)
            ON CONFLICT(customer_name, customer_part_number)
            DO UPDATE SET internal_part_number = excluded.internal_part_number, updated_at = CURRENT_TIMESTAMP
            """,
            (customer_name, customer_part, internal_part),
        )
        conn.commit()


def upload_customer_part_xrefs(handler: AppHandler) -> dict:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        return {"error": "expected_multipart"}
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
    skipped = 0
    errors: list[str] = []
    for field in fields:
        raw_name = getattr(field, "filename", "") or ""
        filename = safe_upload_filename(raw_name)
        if Path(filename).suffix.lower() != ".csv":
            errors.append(f"{raw_name or '(missing)'}: only .csv files are allowed")
            skipped += 1
            continue
        text = field.file.read().decode("utf-8-sig", errors="replace")
        result = import_xref_csv(text)
        imported += result["imported"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"imported": imported, "skipped": skipped, "errors": errors, "xrefs": list_customer_part_xrefs()}


def import_xref_csv(text: str) -> dict:
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        return {"imported": 0, "skipped": 0, "errors": ["CSV has no header row"]}
    field_map = {normalize_header(name): name for name in reader.fieldnames}
    aliases = {
        "customer_name": ["customer", "customer_name", "customercompany", "customer_company", "customername"],
        "customer_part_number": ["customer_part_number", "customerpartnumber", "customer_sku", "customersku", "customerpart"],
        "internal_part_number": ["internal_part_number", "internalpartnumber", "internal_sku", "internalsku", "internalpart"],
    }
    resolved = {}
    for target, options in aliases.items():
        for option in options:
            if option in field_map:
                resolved[target] = field_map[option]
                break
    missing = [target for target in aliases if target not in resolved]
    if missing:
        return {"imported": 0, "skipped": 0, "errors": [f"Missing required columns: {', '.join(missing)}"]}
    imported = 0
    skipped = 0
    errors: list[str] = []
    for row_number, row in enumerate(reader, start=2):
        payload = {
            "customer_name": row.get(resolved["customer_name"], ""),
            "customer_part_number": row.get(resolved["customer_part_number"], ""),
            "internal_part_number": row.get(resolved["internal_part_number"], ""),
        }
        try:
            save_customer_part_xref(payload)
            imported += 1
        except ValueError as exc:
            skipped += 1
            errors.append(f"Row {row_number}: {exc}")
    return {"imported": imported, "skipped": skipped, "errors": errors}


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


ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".txt", ".eml"}


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
            rejected.append({"filename": raw_name or "(missing)", "reason": "Only .pdf, .txt, and .eml files are allowed."})
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


def main() -> None:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    with db():
        pass
    server = ThreadingHTTPServer((APP_HOST, APP_PORT), AppHandler)
    print(f"POInbox PO Intake MVP running at http://{APP_HOST}:{APP_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()

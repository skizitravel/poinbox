from __future__ import annotations

import json
import sqlite3
from typing import Any


ORACLE_EBS_ORDER_ENTRY_MANIFEST = {
    "adapter_code": "oracle_ebs_order_entry",
    "erp_family": "oracle_ebs",
    "supported_transaction": "entered_sales_order",
    "required_context_fields": [
        "user_id",
        "responsibility_id",
        "resp_application_id",
        "security_group_id",
        "org_id",
        "nls_language",
    ],
    "activated_entities": [
        "oracle_operating_unit",
        "oracle_order_source",
        "oracle_order_type",
        "oracle_line_type",
        "oracle_price_list",
        "oracle_inventory_org",
        "oracle_hz_customer_account",
        "oracle_hz_site_use",
        "oracle_inventory_item",
    ],
    "canonical_mappings": {
        "customer_account": "sold_to_org_id",
        "ship_to_site": "ship_to_org_id",
        "bill_to_site": "invoice_to_org_id",
        "product": "inventory_item_id",
        "fulfillment_location": "ship_from_org_id",
        "order_document_type": "order_type_id",
        "line_document_type": "line_type_id",
        "price_reference": "price_list_id",
    },
    "credential_fields": ["endpoint_url", "api_username", "api_password", "credential_reference"],
    "capabilities": [
        "profile_setup",
        "external_id_mapping",
        "canonical_draft_validation",
        "oracle_payload_preview",
        "no_live_booking_by_default",
    ],
}


ADAPTER_MANIFESTS = {
    ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"]: ORACLE_EBS_ORDER_ENTRY_MANIFEST,
}


def adapter_manifest(adapter_code: str) -> dict[str, Any]:
    return ADAPTER_MANIFESTS.get(adapter_code, {})


def adapter_manifests() -> list[dict[str, Any]]:
    return list(ADAPTER_MANIFESTS.values())


def parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def oracle_profile_response(conn: sqlite3.Connection) -> dict[str, Any]:
    profile = conn.execute(
        """
        SELECT ep.*, es.system_name, es.erp_family, es.erp_version, es.environment,
               es.connection_mode, es.active_flag AS system_active_flag, es.config_json AS system_config_json
        FROM erp_profile ep
        LEFT JOIN erp_system es ON es.id = ep.erp_system_id
        WHERE ep.adapter_code = ?
        ORDER BY ep.active_flag DESC, ep.updated_at DESC, ep.id DESC
        LIMIT 1
        """,
        (ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"],),
    ).fetchone()
    return {
        "manifest": ORACLE_EBS_ORDER_ENTRY_MANIFEST,
        "profile": sanitize_profile(profile),
        "mapping_summary": oracle_mapping_summary(conn, profile["erp_system_id"] if profile else None),
    }


def sanitize_profile(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    settings = parse_json_object(row["settings_json"])
    secrets = parse_json_object(row["secret_json"])
    return {
        "id": row["id"],
        "profile_name": row["profile_name"],
        "transaction_type": row["transaction_type"],
        "adapter_code": row["adapter_code"],
        "profile_version": row["profile_version"],
        "write_mode": row["write_mode"],
        "defaulting_strategy": row["defaulting_strategy"],
        "validation_strategy": row["validation_strategy"],
        "active_flag": bool(row["active_flag"]),
        "settings": settings,
        "secret_configured": bool(secrets.get("api_password")),
        "system": {
            "id": row["erp_system_id"],
            "system_name": row["system_name"],
            "erp_family": row["erp_family"],
            "erp_version": row["erp_version"],
            "environment": row["environment"],
            "connection_mode": row["connection_mode"],
            "active_flag": bool(row["system_active_flag"]),
            "config": parse_json_object(row["system_config_json"]),
        },
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def oracle_mapping_summary(conn: sqlite3.Connection, erp_system_id: int | None) -> dict[str, int]:
    if not erp_system_id:
        return {}
    rows = conn.execute(
        """
        SELECT external_entity_type, COUNT(*) AS count
        FROM external_id_map
        WHERE erp_system_id = ? AND active_flag = 1
        GROUP BY external_entity_type
        ORDER BY external_entity_type
        """,
        (erp_system_id,),
    ).fetchall()
    return {row["external_entity_type"]: row["count"] for row in rows}


def profile_for_adapter(conn: sqlite3.Connection, adapter_code: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT ep.*, es.system_name, es.erp_family, es.erp_version, es.environment,
               es.connection_mode, es.active_flag AS system_active_flag, es.config_json AS system_config_json
        FROM erp_profile ep
        LEFT JOIN erp_system es ON es.id = ep.erp_system_id
        WHERE ep.adapter_code = ? AND ep.active_flag = 1
        ORDER BY ep.updated_at DESC, ep.id DESC
        LIMIT 1
        """,
        (adapter_code,),
    ).fetchone()
    return sanitize_profile(row)


def discover_setup(profile: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "enabled": bool(profile),
        "message": "Oracle EBS profile is configured for preview." if profile else "Oracle EBS profile is not configured.",
        "manifest": ORACLE_EBS_ORDER_ENTRY_MANIFEST,
    }


def sync_master_data(profile: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "enabled": False,
        "message": "Oracle EBS master-data sync is not enabled in this MVP pass.",
        "profile_id": profile.get("id") if profile else None,
    }


def create_entered_order(profile: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": False,
        "message": "Oracle EBS order creation is disabled. This pass only supports validation and payload preview.",
        "profile_id": profile.get("id") if profile else None,
    }


def translate_errors(profile: dict[str, Any] | None, erp_error: Any) -> dict[str, Any]:
    return {
        "message": str(erp_error or "Oracle EBS error translation is not configured yet."),
        "profile_id": profile.get("id") if profile else None,
    }


def build_canonical_order_draft(conn: sqlite3.Connection, po_id: int) -> dict[str, Any]:
    po = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
    if not po:
        return {"error": "not_found", "messages": [{"severity": "error", "message": "Purchase order was not found."}]}
    account = resolve_account(conn, po)
    roles = {role: resolve_partner_role(conn, po, account, role) for role in ("SOLD_TO", "SHIP_TO", "BILL_TO", "PAYER")}
    document_type = resolve_order_document_type(conn, po)
    lines = []
    for line in conn.execute("SELECT * FROM purchase_order_lines WHERE purchase_order_id = ? ORDER BY id", (po_id,)).fetchall():
        lines.append(build_canonical_line(conn, line, account))
    return {
        "order": {
            "source_document_ref": po["po_number"],
            "customer_po_number": po["po_number"],
            "purchase_order_id": po["id"],
            "customer_name": po["customer_company_name"],
            "customer_account": account,
            "partner_roles": roles,
            "document_type": document_type,
            "currency_code": po["currency"] or "USD",
            "payment_terms": po["payment_terms"],
            "freight_terms": po["freight_terms"],
            "requested_delivery_date": po["request_date"],
            "date_received": po["date_received"],
            "custom_fields": {},
        },
        "lines": lines,
    }


def resolve_account(conn: sqlite3.Connection, po: sqlite3.Row) -> dict[str, Any] | None:
    if "trading_partner_account_id" in po.keys() and po["trading_partner_account_id"]:
        row = conn.execute("SELECT * FROM trading_partner_account WHERE id = ?", (po["trading_partner_account_id"],)).fetchone()
        if row:
            return row_to_dict(row)
    if po["customer_company_name"]:
        row = conn.execute(
            "SELECT * FROM trading_partner_account WHERE LOWER(TRIM(account_name)) = LOWER(TRIM(?)) LIMIT 1",
            (po["customer_company_name"],),
        ).fetchone()
        if row:
            return row_to_dict(row)
    return None


def resolve_partner_role(conn: sqlite3.Connection, po: sqlite3.Row, account: dict[str, Any] | None, role_code: str) -> dict[str, Any] | None:
    column_by_role = {
        "SOLD_TO": "sold_to_partner_role_id",
        "SHIP_TO": "ship_to_partner_role_id",
        "BILL_TO": "bill_to_partner_role_id",
        "PAYER": "payer_partner_role_id",
    }
    role_id = po[column_by_role[role_code]] if column_by_role[role_code] in po.keys() else None
    row = None
    if role_id:
        row = partner_role_row(conn, role_id)
    if not row and account:
        row = conn.execute(
            """
            SELECT pra.*, tps.site_code, tps.site_name, tps.address_line_1, tps.city, tps.state_region,
                   tps.postal_code, tps.country
            FROM partner_role_assignment pra
            LEFT JOIN trading_partner_site tps ON tps.id = pra.trading_partner_site_id
            WHERE pra.trading_partner_account_id = ? AND pra.role_code = ? AND pra.active_flag = 1
            ORDER BY pra.primary_flag DESC, pra.id
            LIMIT 1
            """,
            (account["id"], role_code),
        ).fetchone()
    return row_to_dict(row)


def partner_role_row(conn: sqlite3.Connection, role_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT pra.*, tps.site_code, tps.site_name, tps.address_line_1, tps.city, tps.state_region,
               tps.postal_code, tps.country
        FROM partner_role_assignment pra
        LEFT JOIN trading_partner_site tps ON tps.id = pra.trading_partner_site_id
        WHERE pra.id = ?
        """,
        (role_id,),
    ).fetchone()


def resolve_order_document_type(conn: sqlite3.Connection, po: sqlite3.Row) -> dict[str, Any] | None:
    if "order_type_id" not in po.keys() or not po["order_type_id"]:
        return None
    row = conn.execute(
        "SELECT * FROM order_document_type WHERE legacy_source_table = 'order_types' AND legacy_source_id = ? LIMIT 1",
        (str(po["order_type_id"]),),
    ).fetchone()
    return row_to_dict(row)


def build_canonical_line(conn: sqlite3.Connection, line: sqlite3.Row, account: dict[str, Any] | None) -> dict[str, Any]:
    alias = None
    if "customer_product_alias_id" in line.keys() and line["customer_product_alias_id"]:
        alias = alias_row(conn, line["customer_product_alias_id"])
    if not alias and account and line["customer_part_number"]:
        alias = conn.execute(
            """
            SELECT cpa.*, p.product_number, p.description AS product_description
            FROM customer_product_alias cpa
            LEFT JOIN product p ON p.id = cpa.product_id
            WHERE cpa.trading_partner_account_id = ?
              AND cpa.normalized_customer_product_number = LOWER(TRIM(?))
              AND (
                LOWER(TRIM(COALESCE(cpa.customer_product_revision, ''))) = LOWER(TRIM(?))
                OR COALESCE(NULLIF(TRIM(cpa.customer_product_revision), ''), '') = ''
              )
              AND cpa.active_flag = 1
            ORDER BY CASE WHEN LOWER(TRIM(COALESCE(cpa.customer_product_revision, ''))) = LOWER(TRIM(?)) THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (account["id"], line["customer_part_number"], line["customer_part_revision"] or "", line["customer_part_revision"] or ""),
        ).fetchone()
    product = None
    if alias and alias["product_id"]:
        product = product_row(conn, alias["product_id"])
    if not product and "canonical_product_id" in line.keys() and line["canonical_product_id"]:
        product = product_row(conn, line["canonical_product_id"])
    return {
        "purchase_order_line_id": line["id"],
        "source_line_ref": line["line_number"],
        "customer_product_number": line["customer_part_number"],
        "customer_product_alias": row_to_dict(alias),
        "product": row_to_dict(product),
        "quantity": line["quantity"],
        "uom_code": line["unit_of_measure"],
        "unit_price": line["unit_price"],
        "fulfillment_location": None,
        "line_document_type": None,
        "requested_date": line["requested_date"],
        "custom_fields": {},
    }


def alias_row(conn: sqlite3.Connection, alias_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT cpa.*, p.product_number, p.description AS product_description
        FROM customer_product_alias cpa
        LEFT JOIN product p ON p.id = cpa.product_id
        WHERE cpa.id = ?
        """,
        (alias_id,),
    ).fetchone()


def product_row(conn: sqlite3.Connection, product_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM product WHERE id = ?", (product_id,)).fetchone()


def validate_draft_order(conn: sqlite3.Connection, profile: dict[str, Any] | None, draft: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    if not profile:
        messages.append({"severity": "error", "field": "profile", "message": "No active Oracle EBS profile is configured."})
        return {"ok": False, "messages": messages}
    settings = profile.get("settings") or {}
    for field in ORACLE_EBS_ORDER_ENTRY_MANIFEST["required_context_fields"]:
        if not str(settings.get(field) or "").strip():
            messages.append({"severity": "error", "field": field, "message": f"Oracle EBS context field {field} is required."})
    if not str(settings.get("order_source_id") or "").strip():
        messages.append({"severity": "error", "field": "order_source_id", "message": "Order source is required for Oracle payload preview."})
    order = draft.get("order") or {}
    account = order.get("customer_account")
    erp_system_id = profile.get("system", {}).get("id")
    if not account:
        messages.append({"severity": "error", "field": "customer_account", "message": "Could not resolve a canonical customer account for this PO."})
    elif not external_mapping_value(conn, erp_system_id, ["customer_account", "trading_partner_account"], account["id"], ["HZ_CUST_ACCOUNT"]):
        messages.append({"severity": "error", "field": "customer_account", "message": "Missing Oracle HZ_CUST_ACCOUNT external ID mapping for customer account."})
    for role, field_name, entity_types in [
        ("SHIP_TO", "ship_to_org_id", ["ship_to_site", "trading_partner_site"]),
        ("BILL_TO", "invoice_to_org_id", ["bill_to_site", "trading_partner_site"]),
    ]:
        role_value = (order.get("partner_roles") or {}).get(role)
        site_id = role_value.get("trading_partner_site_id") if role_value else None
        if not site_id:
            messages.append({"severity": "error", "field": field_name, "message": f"Could not resolve a canonical {role} site for this PO."})
        elif not external_mapping_value(conn, erp_system_id, entity_types, site_id, ["HZ_SITE_USE"]):
            messages.append({"severity": "error", "field": field_name, "message": f"Missing Oracle HZ_SITE_USE external ID mapping for {role} site."})
    document_type = order.get("document_type")
    if document_type and external_mapping_value(conn, erp_system_id, ["order_document_type"], document_type["id"], ["OM_ORDER_TYPE"]):
        pass
    elif not str(settings.get("order_type_id") or "").strip():
        messages.append({"severity": "error", "field": "order_type_id", "message": "Order type mapping or Oracle default order type is required."})
    if not str(settings.get("line_type_id") or "").strip():
        messages.append({"severity": "warning", "field": "line_type_id", "message": "Oracle line type default is not set; line_type_id will be blank."})
    if not str(settings.get("fulfillment_org_id") or "").strip():
        messages.append({"severity": "warning", "field": "fulfillment_org_id", "message": "Fulfillment org default is not set; ship_from_org_id will be blank unless line mappings are added later."})
    for index, line in enumerate(draft.get("lines") or [], start=1):
        product = line.get("product")
        if not product:
            messages.append({"severity": "error", "field": f"lines[{index}].product", "message": f"Line {index} could not resolve a canonical product."})
        elif not external_mapping_value(conn, erp_system_id, ["product"], product["id"], ["INVENTORY_ITEM"]):
            messages.append({"severity": "error", "field": f"lines[{index}].inventory_item_id", "message": f"Line {index} is missing Oracle INVENTORY_ITEM external ID mapping."})
    return {"ok": not any(item["severity"] == "error" for item in messages), "messages": messages}


def generate_payload(conn: sqlite3.Connection, profile: dict[str, Any] | None, draft: dict[str, Any]) -> dict[str, Any]:
    if not profile:
        return {"error": "profile_not_configured", "payload": None}
    settings = profile.get("settings") or {}
    erp_system_id = profile.get("system", {}).get("id")
    order = draft.get("order") or {}
    account = order.get("customer_account") or {}
    roles = order.get("partner_roles") or {}
    document_type = order.get("document_type")
    payload = {
        "org_id": blank_to_none(settings.get("org_id")),
        "order_source_id": blank_to_none(settings.get("order_source_id")),
        "orig_sys_document_ref": order.get("customer_po_number"),
        "sold_to_org_id": external_mapping_value(conn, erp_system_id, ["customer_account", "trading_partner_account"], account.get("id"), ["HZ_CUST_ACCOUNT"]),
        "ship_to_org_id": site_external_value(conn, erp_system_id, roles.get("SHIP_TO"), ["ship_to_site", "trading_partner_site"]),
        "invoice_to_org_id": site_external_value(conn, erp_system_id, roles.get("BILL_TO"), ["bill_to_site", "trading_partner_site"]),
        "order_type_id": external_mapping_value(conn, erp_system_id, ["order_document_type"], document_type.get("id") if document_type else None, ["OM_ORDER_TYPE"]) or blank_to_none(settings.get("order_type_id")),
        "price_list_id": blank_to_none(settings.get("price_reference_id")),
        "transaction_currency": order.get("currency_code"),
        "payment_terms": order.get("payment_terms"),
        "lines": [],
    }
    for line in draft.get("lines") or []:
        product = line.get("product") or {}
        payload["lines"].append(
            {
                "orig_sys_line_ref": line.get("source_line_ref"),
                "inventory_item_id": external_mapping_value(conn, erp_system_id, ["product"], product.get("id"), ["INVENTORY_ITEM"]),
                "ordered_quantity": line.get("quantity"),
                "order_quantity_uom": line.get("uom_code"),
                "ship_from_org_id": blank_to_none(settings.get("fulfillment_org_id")),
                "line_type_id": blank_to_none(settings.get("line_type_id")),
                "unit_selling_price": line.get("unit_price"),
                "request_date": line.get("requested_date"),
            }
        )
    return {"payload": payload, "mode": "preview_only", "writeback_enabled": False}


def site_external_value(
    conn: sqlite3.Connection, erp_system_id: int | None, role: dict[str, Any] | None, entity_types: list[str]
) -> str | None:
    if not role:
        return None
    return external_mapping_value(conn, erp_system_id, entity_types, role.get("trading_partner_site_id"), ["HZ_SITE_USE"])


def external_mapping_value(
    conn: sqlite3.Connection,
    erp_system_id: int | None,
    canonical_entity_types: list[str],
    canonical_entity_id: int | None,
    external_entity_types: list[str],
) -> str | None:
    if not erp_system_id or not canonical_entity_id:
        return None
    placeholders = ",".join("?" for _ in canonical_entity_types)
    external_placeholders = ",".join("?" for _ in external_entity_types)
    row = conn.execute(
        f"""
        SELECT external_id, external_code
        FROM external_id_map
        WHERE erp_system_id = ?
          AND canonical_entity_id = ?
          AND canonical_entity_type IN ({placeholders})
          AND external_entity_type IN ({external_placeholders})
          AND active_flag = 1
        ORDER BY id DESC
        LIMIT 1
        """,
        (erp_system_id, canonical_entity_id, *canonical_entity_types, *external_entity_types),
    ).fetchone()
    if not row:
        return None
    return row["external_id"] or row["external_code"]


def blank_to_none(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def oracle_payload_preview(conn: sqlite3.Connection, po_id: int) -> dict[str, Any]:
    profile = profile_for_adapter(conn, ORACLE_EBS_ORDER_ENTRY_MANIFEST["adapter_code"])
    draft = build_canonical_order_draft(conn, po_id)
    validation = validate_draft_order(conn, profile, draft)
    preview = generate_payload(conn, profile, draft)
    return {
        "manifest": ORACLE_EBS_ORDER_ENTRY_MANIFEST,
        "profile": profile,
        "setup": discover_setup(profile),
        "draft": draft,
        "validation": validation,
        "payload": preview.get("payload"),
        "mode": "preview_only",
        "writeback_enabled": False,
        "create_result": create_entered_order(profile, preview.get("payload") or {}),
    }

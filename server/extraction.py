from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from server.openai_settings import get_openai_runtime_config


PO_EXTRACTION_PROMPT_VERSION = "po-extraction-v2-feedback"


PO_KEYWORDS = [
    "purchase order",
    "po number",
    "p.o.",
    "bill to",
    "ship to",
    "unit price",
    "qty",
    "quantity",
    "requested date",
    "line total",
]


@dataclass
class Classification:
    label: str
    confidence: float
    explanation: str


def classify_purchase_order(subject: str, body: str, attachment_text: str, filenames: list[str]) -> Classification:
    haystack = " ".join([subject, body, attachment_text, " ".join(filenames)]).lower()
    hits = [kw for kw in PO_KEYWORDS if kw in haystack]
    score = min(0.98, 0.18 + len(hits) * 0.11)
    if "purchase order" in haystack or "po number" in haystack:
        score += 0.16
    if re.search(r"\bpo[-\s#:]*[a-z0-9-]{4,}\b", haystack):
        score += 0.12
    score = min(score, 0.99)
    if score >= 0.72:
        label = "purchase_order"
    elif score >= 0.42:
        label = "possible_po"
    else:
        label = "not_po"
    explanation = f"Matched PO indicators: {', '.join(hits) if hits else 'none'}."
    return Classification(label, round(score, 2), explanation)


def extract_purchase_order(
    text: str,
    email: dict[str, Any],
    attachment_filename: str | None,
    mode: str | None = None,
    prior_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    config = get_openai_runtime_config()
    requested_mode = mode or ("ai_with_examples" if config.use_ai_extraction and prior_examples else "ai_text" if config.use_ai_extraction else "rule_based")
    use_ai = requested_mode in {"ai_text", "ai_with_examples"}
    if use_ai and config.api_key_configured:
        try:
            return extract_with_openai(text, email, attachment_filename, prior_examples if requested_mode == "ai_with_examples" else None, config.api_key, config.model)
        except Exception as exc:
            fallback = extract_with_rules(text, email, attachment_filename)
            fallback["extraction_notes"] = f"OpenAI extraction failed; used rule fallback. {exc}"
            fallback["extraction_confidence"] = min(fallback["extraction_confidence"], 0.55)
            fallback["_extraction_method"] = "fallback_rule_based"
            fallback["_error_message"] = str(exc)
            return fallback
    extraction = extract_with_rules(text, email, attachment_filename)
    extraction["_extraction_method"] = "rule_based"
    extraction["_prompt_version"] = PO_EXTRACTION_PROMPT_VERSION
    if use_ai and not config.api_key_configured:
        extraction["extraction_notes"] = "AI extraction was requested but no OpenAI API key is configured; used rule-based extraction."
        extraction["_error_message"] = "AI extraction requested without configured OpenAI API key."
    return extraction


def extract_with_rules(text: str, email: dict[str, Any], attachment_filename: str | None) -> dict[str, Any]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)
    po_number = first_match(
        joined,
        [
            r"Purchase Order\s+((?:PO-)?[A-Z0-9][A-Z0-9-]{3,})",
            r"\bP\.?O\.?\s*(?:Number|No\.?|#|:|-)?\s*([A-Z0-9][A-Z0-9-]{3,})",
        ],
    )
    company = first_match(joined, [r"Customer(?: Company)?:\s*(.+)", r"Vendor:\s*(.+)"])
    bill_to = block_after(lines, "Bill To")
    ship_to = block_after(lines, "Ship To")
    request_date = first_match(joined, [r"Requested Date:\s*([0-9A-Za-z, /\-]+)", r"Request Date:\s*([0-9A-Za-z, /\-]+)"])
    quote_number = first_match(
        joined,
        [
            r"Quote\s*(?:Number|No\.?|#)\s*:\s*([A-Z0-9][A-Z0-9-]{2,})",
            r"Quote\s*:\s*([A-Z0-9][A-Z0-9-]{2,})",
            r"Quotation\s*(?:Number|No\.?|#)?\s*:\s*([A-Z0-9][A-Z0-9-]{2,})",
        ],
    )
    po_revision = first_match(
        joined,
        [
            r"\bPO\s*Rev(?:ision)?\.?\s*:\s*([A-Z0-9.-]+)",
            r"\bRev(?:ision)?\.?\s*:\s*([A-Z0-9.-]+)",
            r"\bChange Order\s*:\s*([A-Z0-9.-]+)",
            r"\bAmendment\s*:\s*([A-Z0-9.-]+)",
        ],
    )
    payment_terms = first_match(joined, [r"Payment Terms:\s*([A-Za-z0-9 /.-]+)", r"\bTerms:\s*((?:Net\s*)?\d{1,3}|Net\s*\d{1,3}|Due on receipt)"])
    freight_terms = first_match(joined, [r"Freight Terms:\s*([A-Za-z0-9 /.-]+)", r"Shipping Terms:\s*([A-Za-z0-9 /.-]+)", r"\bFOB:\s*([A-Za-z0-9 /.-]+)"])
    total_value = money(first_match(joined, [r"Total(?: Value)?:\s*\$?([0-9,]+\.\d{2})", r"Grand Total:\s*\$?([0-9,]+\.\d{2})"]))
    currency = "USD" if "$" in joined or total_value is not None else None
    parsed_lines = parse_line_items(lines, po_number)
    confidence = 0.58
    if po_number:
        confidence += 0.12
    if parsed_lines:
        confidence += 0.16
    if company:
        confidence += 0.08
    notes = "Rule-based extraction. Review before booking."
    field_confidence = {
        "customer_company_name": 0.86 if company else 0.25,
        "customer_contact_name": 0.78 if first_match(joined, [r"Contact:\s*(.+)"]) else 0.35,
        "bill_to_address": 0.82 if bill_to else 0.25,
        "ship_to_address": 0.82 if ship_to else 0.25,
        "po_number": 0.9 if po_number else 0.2,
        "po_revision": 0.82 if po_revision else 0.45,
        "date_received": 0.9 if email.get("received_at") else 0.3,
        "request_date": 0.82 if request_date else 0.3,
        "quote_number": 0.82 if quote_number else 0.35,
        "payment_terms": 0.82 if payment_terms else 0.35,
        "freight_terms": 0.82 if freight_terms else 0.35,
        "currency": 0.85 if currency else 0.4,
        "order_type_id": 0.3,
    }
    return {
        "customer_company_name": company,
        "customer_contact_name": first_match(joined, [r"Contact:\s*(.+)"]),
        "bill_to_address": bill_to,
        "ship_to_address": ship_to,
        "po_number": po_number,
        "po_revision": po_revision,
        "quote_number": quote_number,
        "payment_terms": payment_terms,
        "freight_terms": freight_terms,
        "date_received": normalize_date(email.get("received_at")),
        "request_date": normalize_date(request_date),
        "total_value": total_value,
        "currency": currency,
        "source_sender": email.get("sender"),
        "source_subject": email.get("subject"),
        "source_attachment_filename": attachment_filename,
        "extraction_confidence": round(min(confidence, 0.9), 2),
        "extraction_notes": notes,
        "field_confidence": field_confidence,
        "lines": parsed_lines,
    }


def parse_line_items(lines: list[str], po_number: str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    pattern = re.compile(
        r"^(?P<line>\d+)[\s|,]+(?P<customer>[A-Z0-9-]{3,})[\s|,]+(?P<internal>(?=[A-Z0-9-]*[\d-])[A-Z0-9-]{2,}|-)[\s|,]+(?P<desc>.+?)[\s|,]+(?P<qty>\d+(?:\.\d+)?)\s*(?P<uom>EA|PCS|PC|LB|KG|FT|M)?[\s|,]+\$?(?P<unit>[0-9,]+\.\d{2})[\s|,]+\$?(?P<total>[0-9,]+\.\d{2})(?:[\s|,]+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}))?$",
        re.IGNORECASE,
    )
    no_internal_pattern = re.compile(
        r"^(?P<line>\d+)[\s|,]+(?P<customer>[A-Z0-9-]{3,})[\s|,]+(?P<desc>.+?)[\s|,]+(?P<qty>\d+(?:\.\d+)?)\s*(?P<uom>EA|PCS|PC|LB|KG|FT|M)?[\s|,]+\$?(?P<unit>[0-9,]+\.\d{2})[\s|,]+\$?(?P<total>[0-9,]+\.\d{2})(?:[\s|,]+(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}|[0-9]{1,2}/[0-9]{1,2}/[0-9]{2,4}))?$",
        re.IGNORECASE,
    )
    for raw in lines:
        match = pattern.search(raw)
        inferred_internal = False
        if not match:
            match = no_internal_pattern.search(raw)
            inferred_internal = True
        if not match:
            continue
        data = match.groupdict()
        internal = None if inferred_internal or data.get("internal") == "-" else data.get("internal")
        items.append(
            {
                "po_number": po_number,
                "line_number": data["line"],
                "customer_part_number": data["customer"],
                "internal_part_number": internal,
                "description": data["desc"].strip(),
                "quantity": float(data["qty"]),
                "unit_of_measure": data.get("uom") or "EA",
                "unit_price": money(data["unit"]),
                "line_total": money(data["total"]),
                "requested_date": data.get("date"),
                "extraction_confidence": 0.72,
                "extraction_notes": "Parsed from tabular text.",
                "field_confidence": {
                    "line_number": 0.85,
                    "customer_part_number": 0.86,
                    "internal_part_number": 0.82 if internal else 0.25,
                    "description": 0.75,
                    "quantity": 0.86,
                    "unit_of_measure": 0.72 if data.get("uom") else 0.45,
                    "unit_price": 0.84,
                    "line_total": 0.84,
                    "requested_date": 0.78 if data.get("date") else 0.35,
                },
            }
        )
    return items


def extract_with_openai(
    text: str,
    email: dict[str, Any],
    attachment_filename: str | None,
    prior_examples: list[dict[str, Any]] | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    prompt = {
        "task": (
            "Extract customer purchase order data. Return only JSON. Use null for missing values. Do not invent data. "
            "A quote, quotation, proposal, estimate, invoice, or order confirmation number is not a purchase order number. "
            "If the document is not actually a customer purchase order, return null for po_number and explain the uncertainty in extraction_notes."
        ),
        "prompt_version": PO_EXTRACTION_PROMPT_VERSION,
        "prior_corrected_examples_instruction": (
            "Use prior examples only as layout and labeling guidance. Do not copy PO numbers, quantities, prices, dates, "
            "or customer-specific values unless they are present in the current document. Prefer current document evidence."
        ),
        "source_evidence_instruction": (
            "For important fields, you may return either a simple value or an object like "
            "{\"value\":\"PO-10491\",\"confidence\":0.94,\"source_snippet\":\"Purchase Order #: PO-10491\"}. "
            "The source_snippet should be a short exact excerpt from the current document that supports the value."
        ),
        "system_date_instruction": (
            "Do not extract, infer, or return date_received. Date received is controlled by the app from email/upload/import metadata. "
            "Requested delivery dates may still be extracted into line requested_date values."
        ),
        "prior_corrected_examples": prior_examples or [],
        "schema": {
            "customer_company_name": None,
            "customer_contact_name": None,
            "bill_to_address": None,
            "ship_to_address": None,
            "bill_to_address_structured": {
                "address_line_1": None,
                "address_line_2": None,
                "address_line_3": None,
                "city": None,
                "state": None,
                "country": None,
                "zip_code": None,
            },
            "ship_to_address_structured": {
                "address_line_1": None,
                "address_line_2": None,
                "address_line_3": None,
                "city": None,
                "state": None,
                "country": None,
                "zip_code": None,
            },
            "po_number": None,
            "po_revision": None,
            "quote_number": None,
            "request_date": None,
            "payment_terms": None,
            "freight_terms": None,
            "total_value": None,
            "currency": None,
            "source_sender": None,
            "source_subject": None,
            "source_attachment_filename": None,
            "extraction_confidence": 0,
            "extraction_notes": "",
            "lines": [
                {
                    "po_number": None,
                    "line_number": None,
                    "customer_part_number": None,
                    "customer_part_revision": None,
                    "internal_part_number": None,
                    "internal_part_revision": None,
                    "description": None,
                    "quantity": None,
                    "unit_of_measure": None,
                    "unit_price": None,
                    "line_total": None,
                    "requested_date": None,
                    "extraction_confidence": 0,
                    "extraction_notes": "",
                }
            ],
        },
        "field_guidance": {
            "bill_to_address_structured": "Use address_line_1, address_line_2, address_line_3, city, state, country, zip_code. Leave uncertain fields null.",
            "ship_to_address_structured": "Use address_line_1, address_line_2, address_line_3, city, state, country, zip_code. Leave uncertain fields null.",
            "part_revisions": "Extract customer/internal part revisions separately from part numbers. Common labels include Rev, Revision, Part Rev, Customer Rev, Drawing Rev, Internal Rev. Do not invent revisions.",
            "po_number": "Only extract a true customer purchase order number. Do not use quote/proposal/quotation numbers as the PO number.",
        },
        "email": email,
        "attachment_filename": attachment_filename,
        "document_text": text[:45000],
    }
    payload = {
        "model": model or "gpt-4.1-mini",
        "input": [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": json.dumps(prompt)}],
            }
        ],
        "text": {"format": {"type": "json_object"}},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key or os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        data = json.loads(response.read().decode("utf-8"))
    content = data["output"][0]["content"][0]["text"]
    parsed = json.loads(content)
    parsed = normalize_ai_evidence_objects(parsed)
    parsed.pop("date_received", None)
    validate_extraction(parsed)
    parsed["_extraction_method"] = "ai_with_examples" if prior_examples else "ai_text"
    parsed["_model_name"] = model or "gpt-4.1-mini"
    parsed["_prompt_version"] = PO_EXTRACTION_PROMPT_VERSION
    parsed["_raw_output_json"] = content
    parsed["_prior_examples_used"] = bool(prior_examples)
    return parsed


def normalize_ai_evidence_objects(parsed: dict[str, Any]) -> dict[str, Any]:
    field_confidence = parsed.setdefault("field_confidence", {})
    for field in list(parsed.keys()):
        value = parsed[field]
        if isinstance(value, dict) and "value" in value:
            if value.get("confidence") is not None:
                field_confidence[field] = value.get("confidence")
            parsed[field] = value.get("value")
    for line in parsed.get("lines") or []:
        if not isinstance(line, dict):
            continue
        line_confidence = line.setdefault("field_confidence", {})
        for field in list(line.keys()):
            value = line[field]
            if isinstance(value, dict) and "value" in value:
                if value.get("confidence") is not None:
                    line_confidence[field] = value.get("confidence")
                line[field] = value.get("value")
    return parsed


def validate_extraction(data: dict[str, Any]) -> None:
    required = ["po_number", "lines", "extraction_confidence", "extraction_notes"]
    for key in required:
        if key not in data:
            raise ValueError(f"Extraction missing {key}")
    if not isinstance(data["lines"], list):
        raise ValueError("Extraction lines must be an array")


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    iso_match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    if iso_match:
        return iso_match.group(1)
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%B %d, %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return text


def first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def block_after(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if line.lower().startswith(label.lower()):
            inline = line.split(":", 1)[1].strip() if ":" in line else ""
            collected = [inline] if inline else []
            for follow in lines[index + 1 : index + 4]:
                if re.match(r"^[A-Za-z ]+:", follow):
                    break
                collected.append(follow)
            return "\n".join(collected).strip() or None
    return None


def money(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.replace(",", ""))
    except ValueError:
        return None

"""Tests for the PO classifier."""

import pytest
from app.services.po_classifier import is_likely_po


# --- Likely PO cases ---

def test_po_keyword_in_subject_pdf():
    assert is_likely_po("PO #1234 Office Supplies", "attachment.pdf") is True


def test_purchase_order_in_subject():
    assert is_likely_po("Purchase Order REV2 - Equipment", "doc.xlsx") is True


def test_rev_keyword_in_filename():
    assert is_likely_po("Shipment Update", "PO_REV1_Parts.pdf") is True


def test_order_keyword_in_subject():
    assert is_likely_po("Order Confirmation #5501", "order_5501.xls") is True


def test_po_keyword_in_filename_only():
    assert is_likely_po("Monthly Report", "PO_99012_Urgent.pdf") is True


def test_case_insensitive_subject():
    assert is_likely_po("purchase order for widgets", "doc.pdf") is True


def test_case_insensitive_filename():
    assert is_likely_po("Fwd: see attached", "Purchase_Order_Q1.xlsx") is True


# --- Non-PO cases ---

def test_invoice_not_po():
    assert is_likely_po("Invoice INV-8821 for Shipping", "Invoice_8821.pdf") is False


def test_wrong_extension():
    assert is_likely_po("PO #1234 Office Supplies", "purchase_order.docx") is False


def test_newsletter_not_po():
    assert is_likely_po("January Newsletter", "January_Newsletter.pdf") is False


def test_support_ticket_not_po():
    assert is_likely_po("Support Ticket #4430", "Ticket_4430_Notes.pdf") is False


def test_empty_subject_no_keyword_in_filename():
    assert is_likely_po("", "report.xlsx") is False


def test_txt_extension_not_po():
    assert is_likely_po("PO #999", "po_999.txt") is False

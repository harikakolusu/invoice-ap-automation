"""Unit tests for the business rules: extraction, duplicate normalisation, tolerances, allocation."""
from datetime import date
from decimal import Decimal as D

from ap_automation.common import alloc, norm_invoice_number
from ap_automation.generator.documents import render
from ap_automation.pipeline.extraction import extract
from ap_automation.pipeline.matching import DuplicateDetector, ThreeWayMatcher

INV = {"vendor_invoice_number": "APEX-1042", "invoice_date": date(2026, 3, 5), "po_id": "PO-2026-000001",
       "currency": "USD", "payment_terms": "NET30", "subtotal": D("2520.00"), "tax_amount": D("453.60"),
       "stated_total": D("2973.60")}
LINES = [{"line_number": 1, "sku": "SKU-ITH-0001", "description": "Ball Bearing 6204", "quantity": 2,
          "unit_price": D("1250.00"), "tax_code": "TX18", "line_amount": D("2500.00")},
         {"line_number": 2, "sku": "SKU-MRO-0003", "description": "Hex Bolts M10 100pk", "quantity": 4,
          "unit_price": D("5.00"), "tax_code": "TX18", "line_amount": D("20.00")}]
VENDOR = {"vendor_name": "Apex Metals Inc.", "tax_id": "12-3456789"}


def test_extraction_round_trip_every_layout():
    for channel, style in (("PDF_UPLOAD", "LONG"), ("PDF_UPLOAD", "ISO"), ("EMAIL", "ISO"), ("EDI", "ISO")):
        ex = extract(render({**INV, "channel": channel}, LINES, VENDOR, style, "Buyer"))
        assert ex["confidence"] == 1, channel
        assert ex["vendor_tax_id"] == "12-3456789" and ex["vendor_invoice_number"] == "APEX-1042"
        assert ex["invoice_date"] == date(2026, 3, 5) and ex["po_number"] == "PO-2026-000001"
        assert ex["stated_total"] == D("2973.60") and ex["tax_amount"] == D("453.60")
        # description ending in digits must not be confused with the quantity column
        assert [(l["description"], l["quantity"], l["unit_price"]) for l in ex["lines"]] == \
               [("Ball Bearing 6204", 2, D("1250.00")), ("Hex Bolts M10 100pk", 4, D("5.00"))]


def test_non_po_invoice_has_no_po_reference():
    for channel in ("PDF_UPLOAD", "EMAIL", "EDI"):
        ex = extract(render({**INV, "po_id": None, "channel": channel}, LINES, VENDOR, "ISO", "Buyer"))
        assert ex["po_number"] is None


def test_duplicate_number_normalisation():
    assert norm_invoice_number("apex-1042") == norm_invoice_number("APEX1042")
    assert norm_invoice_number("INV/2026/00012") == norm_invoice_number("INV-2026-00012")
    det = DuplicateDetector()
    assert det.check("VND-00001", "APEX-1042", "INV-A") is None
    assert det.check("VND-00002", "APEX-1042", "INV-B") is None   # same number, other vendor: not a duplicate
    assert det.check("VND-00001", "apex1042", "INV-C") == "INV-A"


def _matcher(received=100, ordered=100):
    pol = [{"po_line_id": "POL-1", "po_id": "PO-1", "sku": "S", "unit_price": "10.00", "tax_code": "TX18",
            "quantity": str(ordered)}]
    grns = [{"grn_id": "G1", "po_id": "PO-1", "receipt_date": "2026-01-02"},
            {"grn_id": "G2", "po_id": "PO-1", "receipt_date": "2026-01-09"}]
    half = received // 2
    gl = [{"grn_line_id": "GL1", "grn_id": "G1", "po_line_id": "POL-1", "quantity_received": str(half)},
          {"grn_line_id": "GL2", "grn_id": "G2", "po_line_id": "POL-1", "quantity_received": str(received - half)}]
    return ThreeWayMatcher(pol, grns, gl, D("2.0"), D("5.0"))


def _line(qty=100, price="10.00", tax="TX18"):
    return [{"invoice_line_id": "L1", "sku": "S", "quantity": qty, "unit_price": D(price), "tax_code": tax}]


def codes(res):
    return res[0], sorted(e["code"] for e in res[1])


def test_price_tolerance_boundary():
    assert codes(_matcher().match("PO-1", _line(price="10.20"))) == ("MATCHED_WITHIN_TOLERANCE", [])  # exactly +2%
    assert codes(_matcher().match("PO-1", _line(price="10.21"))) == ("PRICE_VARIANCE", ["PRICE_VARIANCE"])
    assert codes(_matcher().match("PO-1", _line(price="9.00"))) == ("MATCHED_WITHIN_TOLERANCE", [])  # favourable
    assert codes(_matcher().match("PO-1", _line(tax="TX05"))) == ("TAX_VARIANCE", ["TAX_MISMATCH"])


def test_quantity_rules_and_fifo_allocation():
    status, exc, alloc_rows = _matcher().match("PO-1", _line(qty=100))
    assert status == "MATCHED" and not exc
    assert [(a["grn_line_id"], a["matched_qty"]) for a in alloc_rows] == [("GL1", 50), ("GL2", 50)]
    assert codes(_matcher(received=60).match("PO-1", _line(qty=100))) == ("QTY_VARIANCE", ["QTY_EXCEEDS_RECEIPT"])
    assert codes(_matcher(received=105).match("PO-1", _line(qty=105))) == ("MATCHED_WITHIN_TOLERANCE", [])
    assert codes(_matcher(received=106).match("PO-1", _line(qty=106))) == ("QTY_VARIANCE", ["QTY_EXCEEDS_PO"])


def test_quantity_is_consumed_across_invoices():
    m = _matcher()
    assert codes(m.match("PO-1", _line(qty=60)))[1] == []
    assert codes(m.match("PO-1", _line(qty=40)))[1] == []
    assert codes(m.match("PO-1", _line(qty=1)))[1] == ["QTY_EXCEEDS_RECEIPT"]   # third invoice over-bills


def test_missing_receipt():
    m = ThreeWayMatcher([{"po_line_id": "POL-1", "po_id": "PO-1", "sku": "S", "unit_price": "10.00",
                          "tax_code": "TX18", "quantity": "5"}], [], [], D("2"), D("5"))
    assert codes(m.match("PO-1", _line(qty=5))) == ("NO_RECEIPT", ["MISSING_RECEIPT"])


def test_alloc_sums_exactly():
    assert alloc(2000, {"a": 0.7, "b": 0.1, "c": 0.08, "d": 0.05, "e": 0.04, "f": 0.03}) == \
           {"a": 1400, "b": 200, "c": 160, "d": 100, "e": 80, "f": 60}
    assert sum(alloc(7, {"x": 1, "y": 1, "z": 1}).values()) == 7

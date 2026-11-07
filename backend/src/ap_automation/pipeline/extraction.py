"""Field extraction from raw invoice documents (layout detection + rule-based parsers).

Deterministic and explainable by design: every extracted value can be traced to a line in the document.
An LLM extractor can be dropped in behind the same `extract()` contract (see README, "Extending").
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

REQUIRED = ("vendor_tax_id", "vendor_invoice_number", "invoice_date", "stated_total")


def _money(s: str | None):
    if not s:
        return None
    try:
        return Decimal(s.replace("$", "").replace(",", "").strip())
    except InvalidOperation:
        return None


def _find(pattern: str, text: str):
    m = re.search(pattern, text, re.M)
    return m.group(1).strip() if m else None


def _parse_date(s: str | None):
    if not s:
        return None
    for f in ("%Y-%m-%d", "%B %d, %Y", "%d/%m/%Y", "%Y%m%d"):
        try:
            return datetime.strptime(s.strip(), f).date()
        except ValueError:
            pass
    return None


def _line(n, sku, desc, qty, price, tax, amt) -> dict:
    return {"line_number": int(n), "sku": sku.strip(), "description": desc.strip(), "quantity": int(qty),
            "unit_price": _money(price), "tax_code": tax.strip(), "line_amount": _money(amt)}


def _classic(text: str) -> dict:
    lines = []
    for row in text.splitlines():
        if re.match(r"^\s*\d+\s{2,}SKU-", row):
            parts = re.split(r"\s{2,}", row.strip())
            if len(parts) == 7:
                lines.append(_line(*parts))
    po = _find(r"^PO Number:\s*(.+)$", text)
    return {"vendor_name": text.splitlines()[0].strip(), "vendor_tax_id": _find(r"^Tax ID:\s*(\S+)$", text),
            "vendor_invoice_number": _find(r"^Invoice No:\s*(.+)$", text),
            "invoice_date": _parse_date(_find(r"^Invoice Date:\s*(.+)$", text)),
            "po_number": None if po in (None, "N/A") else po,
            "currency": _find(r"^Currency:\s*(\S+)$", text), "payment_terms": _find(r"^Payment Terms:\s*(\S+)$", text),
            "subtotal": _money(_find(r"^\s*Subtotal:\s*([\d,]+\.\d{2})\s*$", text)),
            "tax_amount": _money(_find(r"^\s*Tax:\s*([\d,]+\.\d{2})\s*$", text)),
            "stated_total": _money(_find(r"^\s*TOTAL DUE:\s*([\d,]+\.\d{2})\s*$", text)), "lines": lines}


def _email(text: str) -> dict:
    lines = [_line(i, *m) for i, m in enumerate(re.findall(
        r"^- (SKU-\S+) \| (.+?) \| qty (\d+) \| @ \$([\d,]+\.\d{2}) \| (TX\d{2}) \| \$([\d,]+\.\d{2})\s*$",
        text, re.M), 1)]
    po = _find(r"^Purchase Order:\s*(\S+)$", text)
    return {"vendor_name": _find(r"^Vendor:\s*(.+)$", text), "vendor_tax_id": _find(r"^Vendor Tax ID:\s*(\S+)$", text),
            "vendor_invoice_number": _find(r"^Invoice #:\s*(.+)$", text),
            "invoice_date": _parse_date(_find(r"^Invoice Date \(DD/MM/YYYY\):\s*(\S+)$", text)),
            "po_number": None if po in (None, "none") else po,
            "currency": _find(r"^Currency:\s*(\S+)$", text), "payment_terms": _find(r"^Terms:\s*(\S+)$", text),
            "subtotal": _money(_find(r"^Subtotal:\s*\$([\d,]+\.\d{2})$", text)),
            "tax_amount": _money(_find(r"^Tax:\s*\$([\d,]+\.\d{2})$", text)),
            "stated_total": _money(_find(r"^Amount Due:\s*\$([\d,]+\.\d{2})$", text)), "lines": lines}


def _edi(text: str) -> dict:
    out = {"lines": []}
    for row in text.splitlines():
        f = row.split("|")
        if f[0] == "HDR" and len(f) == 7:
            out |= {"vendor_invoice_number": f[2], "invoice_date": _parse_date(f[3]), "po_number": f[4] or None,
                    "currency": f[5], "payment_terms": f[6]}
        elif f[0] == "VND" and len(f) == 3:
            out |= {"vendor_tax_id": f[1], "vendor_name": f[2]}
        elif f[0] == "LIN" and len(f) == 8:
            out["lines"].append(_line(*f[1:]))
        elif f[0] == "TOT" and len(f) == 4:
            out |= {"subtotal": _money(f[1]), "tax_amount": _money(f[2]), "stated_total": _money(f[3])}
    return out


def detect_layout(text: str) -> str:
    if text.startswith("HDR|"):
        return "EDI"
    if text.startswith("From:") and "\nSubject:" in text:
        return "EMAIL"
    return "CLASSIC"


def extract(text: str) -> dict:
    layout = detect_layout(text)
    ex = {"CLASSIC": _classic, "EMAIL": _email, "EDI": _edi}[layout](text)
    found = sum(ex.get(k) is not None for k in REQUIRED) + bool(ex["lines"])
    ex["layout"] = layout
    ex["confidence"] = Decimal(found) / (len(REQUIRED) + 1)
    return ex


if __name__ == "__main__":   # smoke check: python -m ap_automation.pipeline.extraction
    doc = "HDR|INVOICE|AB-1|20260315|PO-2026-000001|USD|NET30\nVND|12-3456789|X Co\n" \
          "LIN|1|SKU-ITH-0001|Laptop|2|10.00|TX18|20.00\nTOT|20.00|3.60|23.60\n"
    r = extract(doc)
    assert r["layout"] == "EDI" and r["invoice_date"] == date(2026, 3, 15) and r["confidence"] == 1
    assert r["lines"][0]["unit_price"] == Decimal("10.00")
    print("ok")

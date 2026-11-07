"""Render an invoice as the raw text document a vendor would send.

Three layouts mimic real intake channels:
  PDF_UPLOAD -> CLASSIC (text layer of a PDF, fixed-width table)
  EMAIL      -> EMAIL   (invoice details in an email body)
  EDI        -> EDI     (pipe-delimited electronic invoice)
"""
from __future__ import annotations

LAYOUT_BY_CHANNEL = {"PDF_UPLOAD": "CLASSIC", "EMAIL": "EMAIL", "EDI": "EDI"}


def _amt(x) -> str:
    return f"{x:,.2f}"


def _date(d, style: str) -> str:
    if style == "LONG":
        return f"{d:%B} {d.day}, {d.year}"
    return d.isoformat()


def _ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def render_unstructured(inv: dict, lines: list[dict], vendor: dict) -> str:
    """A free-form letter, like a scanned or hand-typed invoice. The rule parser cannot read it; used to
    benchmark the LLM extraction fallback. Same facts as the structured document, different wording."""
    d = inv["invoice_date"]
    po = f"This is billed against your purchase order {inv['po_id']}." if inv["po_id"] else \
        "No purchase order was raised for this work."
    items = "\n".join(
        f"  * {l['quantity']} x {l['description']} (our item code {l['sku']}) at USD {_amt(l['unit_price'])} each, "
        f"tax class {l['tax_code']}, line value USD {_amt(l['line_amount'])}" for l in lines)
    return (f"{vendor['vendor_name'].upper()}\nregistered under tax number {vendor['tax_id']}\n\n"
            f"Dear Accounts Payable team,\n\n"
            f"Please find below our bill reference {inv['vendor_invoice_number']}, dated the {_ordinal(d.day)} of "
            f"{d:%B %Y}. {po} Payment is due on {inv['payment_terms']} terms, in {inv['currency']}.\n\n"
            f"We supplied the following:\n{items}\n\n"
            f"Goods value comes to USD {_amt(inv['subtotal'])}, with USD {_amt(inv['tax_amount'])} of tax on top, "
            f"so the amount we are asking you to remit is USD {_amt(inv['stated_total'])}.\n\n"
            f"Kind regards,\nCredit Control\n")


def render(inv: dict, lines: list[dict], vendor: dict, date_style: str, buyer: str) -> str:
    layout = LAYOUT_BY_CHANNEL[inv["channel"]]
    po = inv["po_id"] or ""
    if layout == "EDI":
        out = [f"HDR|INVOICE|{inv['vendor_invoice_number']}|{inv['invoice_date']:%Y%m%d}|{po}|"
               f"{inv['currency']}|{inv['payment_terms']}",
               f"VND|{vendor['tax_id']}|{vendor['vendor_name']}"]
        out += [f"LIN|{l['line_number']}|{l['sku']}|{l['description']}|{l['quantity']}|{l['unit_price']}|"
                f"{l['tax_code']}|{l['line_amount']}" for l in lines]
        out.append(f"TOT|{inv['subtotal']}|{inv['tax_amount']}|{inv['stated_total']}")
        return "\n".join(out) + "\n"

    if layout == "EMAIL":
        slug = vendor["vendor_name"].split()[0].lower()
        out = [f"From: billing@{slug}.example",
               "To: ap-inbox@buyer.example",
               f"Subject: Invoice {inv['vendor_invoice_number']} from {vendor['vendor_name']}",
               "",
               "Hello AP team, please find our invoice details below.",
               "",
               f"Vendor: {vendor['vendor_name']}",
               f"Vendor Tax ID: {vendor['tax_id']}",
               f"Invoice #: {inv['vendor_invoice_number']}",
               f"Invoice Date (DD/MM/YYYY): {inv['invoice_date']:%d/%m/%Y}",
               f"Purchase Order: {po or 'none'}",
               f"Terms: {inv['payment_terms']}",
               f"Currency: {inv['currency']}",
               "",
               "Items:"]
        out += [f"- {l['sku']} | {l['description']} | qty {l['quantity']} | @ ${_amt(l['unit_price'])} | "
                f"{l['tax_code']} | ${_amt(l['line_amount'])}" for l in lines]
        out += ["", f"Subtotal: ${_amt(inv['subtotal'])}", f"Tax: ${_amt(inv['tax_amount'])}",
                f"Amount Due: ${_amt(inv['stated_total'])}", "", "Regards,", "Billing Team"]
        return "\n".join(out) + "\n"

    out = [vendor["vendor_name"],
           f"Tax ID: {vendor['tax_id']}",
           f"Remit to: Accounts Receivable, {vendor['vendor_name']}",
           "",
           " " * 32 + "INVOICE",
           f"Invoice No:      {inv['vendor_invoice_number']}",
           f"Invoice Date:    {_date(inv['invoice_date'], date_style)}",
           f"PO Number:       {po or 'N/A'}",
           f"Payment Terms:   {inv['payment_terms']}",
           f"Currency:        {inv['currency']}",
           f"Bill To:         {buyer}",
           "",
           f"{'Ln':>2}  {'SKU':<13}  {'Description':<30}  {'Qty':>6}  {'Unit Price':>10}  {'Tax':<4}  {'Amount':>11}",
           f"{'--':>2}  {'-' * 13}  {'-' * 30}  {'-' * 6}  {'-' * 10}  {'-' * 4}  {'-' * 11}"]
    out += [f"{l['line_number']:>2}  {l['sku']:<13}  {l['description']:<30}  {l['quantity']:>6}  "
            f"{_amt(l['unit_price']):>10}  {l['tax_code']:<4}  {_amt(l['line_amount']):>11}" for l in lines]
    pad = " " * 50
    out += ["", f"{pad}Subtotal:   {_amt(inv['subtotal']):>14}", f"{pad}Tax:        {_amt(inv['tax_amount']):>14}",
            f"{pad}TOTAL DUE:  {_amt(inv['stated_total']):>14}"]
    return "\n".join(out) + "\n"

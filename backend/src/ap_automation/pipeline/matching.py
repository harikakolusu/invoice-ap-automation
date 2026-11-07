"""Duplicate detection and three-way match (PO <-> goods receipt <-> invoice)."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from ..common import norm_invoice_number


class DuplicateDetector:
    """Flags an invoice whose (vendor, normalised number) was already seen; returns the original invoice_id."""

    def __init__(self):
        self.seen: dict[tuple, str] = {}

    def check(self, vendor_id: str, number: str, invoice_id: str) -> str | None:
        key = (vendor_id, norm_invoice_number(number))
        if key in self.seen:
            return self.seen[key]
        self.seen[key] = invoice_id
        return None


def _exc(code, line_id, detail, expected=None, actual=None) -> dict:
    return {"code": code, "invoice_line_id": line_id, "detail": detail,
            "expected": None if expected is None else str(expected),
            "actual": None if actual is None else str(actual)}


class ThreeWayMatcher:
    """Stateful across a batch: quantity already billed against each PO line is remembered (no double billing)."""

    def __init__(self, po_lines: list[dict], grns: list[dict], grn_lines: list[dict], price_pct: Decimal,
                 qty_pct: Decimal):
        self.price_pct, self.qty_pct = price_pct, qty_pct
        self.pol = {(l["po_id"], l["sku"]): l for l in po_lines}
        grn_date = {g["grn_id"]: g["receipt_date"] for g in grns}
        grn_po = {g["grn_id"]: g["po_id"] for g in grns}
        self.po_has_receipt = set(grn_po.values())
        self.capacity = defaultdict(list)     # po_line_id -> [[grn_line_id, remaining_qty], ...] FIFO
        self.received = defaultdict(int)
        for gl in sorted(grn_lines, key=lambda g: (grn_date[g["grn_id"]], g["grn_line_id"])):
            self.capacity[gl["po_line_id"]].append([gl["grn_line_id"], int(gl["quantity_received"])])
            self.received[gl["po_line_id"]] += int(gl["quantity_received"])
        self.billed = defaultdict(int)

    def match(self, po_id: str, lines: list[dict]) -> tuple[str, list[dict], list[dict]]:
        exceptions, allocations, flags, within = [], [], set(), False
        has_receipt = po_id in self.po_has_receipt
        if not has_receipt:
            exceptions.append(_exc("MISSING_RECEIPT", None, f"no goods receipt posted for {po_id}"))
        for l in lines:
            lid = l["invoice_line_id"]
            pol = self.pol.get((po_id, l["sku"]))
            if pol is None:
                exceptions.append(_exc("PO_NOT_FOUND", lid, f"{l['sku']} is not on {po_id}"))
                flags.add("PO")
                continue
            po_price = Decimal(pol["unit_price"])
            if l["unit_price"] != po_price:
                if (l["unit_price"] - po_price) * 100 > po_price * self.price_pct:
                    pct = (l["unit_price"] - po_price) / po_price * 100
                    exceptions.append(_exc("PRICE_VARIANCE", lid, f"{l['sku']} unit price {pct:+.2f}% vs PO "
                                           f"(tolerance {self.price_pct}%)", po_price, l["unit_price"]))
                    flags.add("PRICE")
                else:
                    within = True
            if l["tax_code"] != pol["tax_code"]:
                exceptions.append(_exc("TAX_MISMATCH", lid, f"{l['sku']} billed {l['tax_code']}, PO says "
                                       f"{pol['tax_code']}", pol["tax_code"], l["tax_code"]))
                flags.add("TAX")
            if not has_receipt:
                continue
            pid, ordered, qty = pol["po_line_id"], int(pol["quantity"]), l["quantity"]
            cum = self.billed[pid] + qty
            if cum * 100 > ordered * (100 + self.qty_pct):
                exceptions.append(_exc("QTY_EXCEEDS_PO", lid, f"{l['sku']} cumulative billed {cum} > ordered "
                                       f"{ordered} + {self.qty_pct}%", ordered, cum))
                flags.add("QTY")
            if cum > self.received[pid]:
                exceptions.append(_exc("QTY_EXCEEDS_RECEIPT", lid, f"{l['sku']} cumulative billed {cum} > "
                                       f"received {self.received[pid]}", self.received[pid], cum))
                flags.add("QTY")
            if cum > ordered and "QTY" not in flags:
                within = True
            self.billed[pid] = cum
            remaining = qty
            for slot in self.capacity[pid]:          # FIFO allocation -> invoice_match bridge rows
                take = min(remaining, slot[1])
                if take > 0:
                    allocations.append({"invoice_line_id": lid, "grn_line_id": slot[0], "matched_qty": take})
                    slot[1] -= take
                    remaining -= take

        if not has_receipt:
            status = "NO_RECEIPT"
        elif "PO" in flags:
            status = "NOT_EVALUATED"
        elif "TAX" in flags:
            status = "TAX_VARIANCE"
        elif "QTY" in flags:
            status = "QTY_VARIANCE"
        elif "PRICE" in flags:
            status = "PRICE_VARIANCE"
        else:
            status = "MATCHED_WITHIN_TOLERANCE" if within else "MATCHED"
        return status, exceptions, allocations

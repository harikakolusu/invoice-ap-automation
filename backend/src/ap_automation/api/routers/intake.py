"""Intake preview: paste a raw invoice document, get extracted fields + pre-checks against master data.

Rules first; with use_llm, Claude reads documents the rules cannot (free-form, unseen layouts).
Read-only: nothing is persisted (the batch pipeline is the system of record).
"""
import random
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...common import load_config, money
from ...generator.documents import render_unstructured
from ...llm.extractor import hybrid_extract
from ...pipeline.extraction import extract
from .. import store
from .ai import get_llm

router = APIRouter(prefix="/datasets/{name}/intake", tags=["intake"])


class Document(BaseModel):
    text: str = Field(..., min_length=10, max_length=100_000)
    use_llm: bool = False


@router.post("/extract")
def extract_preview(name: str, doc: Document):
    ds = store.get(name)
    tax = {k: Decimal(v) for k, v in load_config()["tax_codes"].items()}
    if doc.use_llm:
        try:
            llm = get_llm()
        except HTTPException as e:   # not configured: rules result + a note instead of an error
            llm, note = None, e.detail
        ex = hybrid_extract(doc.text, llm)
        if llm is None and ex["confidence"] < 1:
            ex["llm_error"] = note
    else:
        ex = extract(doc.text) | {"extraction_method": "RULES"}
    vendor = next((v for v in ds.vendors.values() if v["tax_id"] == ex.get("vendor_tax_id")), None)
    po = ds.pos.get(ex.get("po_number") or "")
    sub = sum((money(l["quantity"] * l["unit_price"]) for l in ex["lines"]), Decimal(0))
    tx = sum((money(money(l["quantity"] * l["unit_price"]) * tax.get(l["tax_code"], Decimal(0))) for l in ex["lines"]),
             Decimal(0))
    checks = [
        {"check": "All required fields found", "ok": ex["confidence"] == 1},
        {"check": "Vendor found in master", "ok": vendor is not None},
        {"check": "Vendor active", "ok": bool(vendor) and vendor["status"] == "ACTIVE"},
        {"check": "PO reference valid (or non-PO)", "ok": not ex.get("po_number") or po is not None},
        {"check": "PO belongs to vendor", "ok": not po or bool(vendor) and po["vendor_id"] == vendor["vendor_id"]},
        {"check": "Stated total = lines + tax", "ok": ex.get("stated_total") is not None
         and abs(ex["stated_total"] - (sub + tx)) <= Decimal("0.05")},
    ]
    return {"extracted": {k: v for k, v in ex.items() if k != "lines"}, "lines": ex["lines"],
            "computed": {"subtotal": sub, "tax_amount": tx, "total": sub + tx},
            "vendor": vendor, "purchase_order": po, "checks": checks}


@router.get("/sample")
def sample(name: str, style: str = Query("structured", pattern="^(structured|unstructured)$"),
           status: str | None = None):
    """A real document from the inbox, or the same invoice re-written as a free-form letter."""
    ds = store.get(name)
    rows = [d for d in ds.decisions if not status or d["final_status"] == status]
    if not rows:
        raise HTTPException(404, "no invoices")
    d = random.choice(rows)
    if style == "structured":
        return {"invoice_id": d["invoice_id"], "text": ds.document_text(d["document_id"])}
    inv, lines = ds.source_invoice(d["document_id"])
    return {"invoice_id": d["invoice_id"], "text": render_unstructured(inv, lines, ds.vendors[inv["vendor_id"]])}

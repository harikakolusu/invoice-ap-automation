"""Invoice list (filter, search, paginate) and full invoice detail with audit trail."""
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query

from .. import store

router = APIRouter(prefix="/datasets/{name}/invoices", tags=["invoices"])


@router.get("")
def list_invoices(name: str, status: str | None = None, exception: str | None = None, queue: str | None = None,
                  q: str | None = None, limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    ds = store.get(name)
    rows = ds.decisions
    if status:
        rows = [d for d in rows if d["final_status"] == status]
    if exception:
        rows = [d for d in rows if d["primary_exception"] == exception]
    if queue:
        rows = [d for d in rows if d["route_queue"] == queue]
    if q:
        needle = q.lower()
        rows = [d for d in rows if needle in d["invoice_id"].lower() or needle in (d["po_id"] or "").lower()
                or needle in (d["vendor_invoice_number"] or "").lower()
                or needle in ds.vendors.get(d["vendor_id"] or "", {}).get("vendor_name", "").lower()]
    return {"total": len(rows), "value_usd": float(sum((Decimal(d["computed_total"]) for d in rows), Decimal(0))),
            "items": [ds.summary_row(d) for d in rows[offset:offset + limit]]}


@router.get("/{invoice_id}")
def invoice_detail(name: str, invoice_id: str):
    ds = store.get(name)
    d = ds.decision_by_id.get(invoice_id)
    if not d:
        raise HTTPException(404, f"invoice {invoice_id} not found")
    doc = d["document_id"]
    lines = ds.extracted_lines[doc]
    po = ds.pos.get(d["po_id"] or "")
    return {
        "decision": {**ds.summary_row(d), "exception_codes": d["exception_codes"],
                     "duplicate_of_invoice_id": d["duplicate_of_invoice_id"],
                     "extraction_confidence": d["extraction_confidence"], "processed_at": d["processed_at"]},
        "vendor": ds.vendors.get(d["vendor_id"] or ""),
        "extracted": ds.extracted[doc],
        "lines": [{**l, "matches": ds.matches.get(f"INVL-{invoice_id}-{int(l['line_number']):02d}", [])}
                  for l in lines],
        "purchase_order": po and {**po, "requester": ds.person(po["requester_id"]), "lines": ds.po_lines[po["po_id"]],
                                  "receipts": ds.grns.get(po["po_id"], [])},
        "exceptions": [{**e, "assigned_to": ds.person(e["assigned_to"])} for e in ds.exc_by_inv.get(invoice_id, [])],
        "approvals": [{**a, "approver": ds.person(a["approver_id"])} for a in ds.approvals.get(invoice_id, [])],
        "payment": ds.payments.get(invoice_id),
        "events": ds.events[invoice_id],
        "document": {"text": ds.document_text(doc), **ds.channel[doc]},
        # shown in the UI for review only; the pipeline never reads ground truth
        "ground_truth": ds.ground_truth.get(doc),
    }

"""Read-side data access for the API: loads a dataset folder once, indexes it, reloads when a run rewrites it."""
from __future__ import annotations

import json
import re
import threading
from collections import defaultdict
from pathlib import Path

from fastapi import HTTPException

from ..common import DATA_ROOT, read_csv
from ..schema import TABLES

_NAME = re.compile(r"^[a-z0-9_.]+$")
_cache: dict[str, tuple[float, "Dataset"]] = {}
_lock = threading.Lock()
run_lock = threading.Lock()          # one pipeline run at a time


def list_datasets() -> list[str]:
    if not DATA_ROOT.exists():
        return []
    return sorted(p.name for p in DATA_ROOT.iterdir()
                  if p.is_dir() and (p / "reports" / "evaluation_metrics.json").exists())


def get(name: str) -> "Dataset":
    if not _NAME.match(name) or name not in list_datasets():
        raise HTTPException(404, f"dataset '{name}' not found; run: python -m ap_automation run-all")
    stamp = (DATA_ROOT / name / "reports" / "evaluation_metrics.json").stat().st_mtime
    with _lock:
        hit = _cache.get(name)
        if not hit or hit[0] != stamp:
            _cache[name] = (stamp, Dataset(DATA_ROOT / name))
        return _cache[name][1]


def _group(rows, key):
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


class Dataset:
    def __init__(self, path: Path):
        self.path = path
        t = {n: read_csv(path / s["zone"] / f"{n}.csv") for n, s in TABLES.items()
             if (path / s["zone"] / f"{n}.csv").exists()}
        rep = lambda f: json.loads((path / "reports" / f).read_text(encoding="utf-8"))
        self.metrics, self.validation, self.plan = rep("evaluation_metrics.json"), rep("validation_summary.json"), \
            rep("generation_plan.json")
        self.decisions = t["invoice_decision"]
        self.decision_by_id = {d["invoice_id"]: d for d in self.decisions}
        self.vendors = {v["vendor_id"]: v for v in t["vendor"]}
        self.employees = {e["employee_id"]: e for e in t["employee"]}
        self.pos = {p["po_id"]: p for p in t["purchase_order"]}
        self.po_lines = _group(t["purchase_order_line"], "po_id")
        self.grns = _group(t["goods_receipt"], "po_id")
        self.exceptions = t["invoice_exception"]
        self.exc_by_inv = _group(self.exceptions, "invoice_id")
        self.events = _group(t["invoice_event"], "invoice_id")
        self.approvals = _group(t["approval"], "invoice_id")
        self.payments = {p["invoice_id"]: p for p in t["payment"]}
        self.matches = _group(t["invoice_match"], "invoice_line_id")
        self.extracted = {e["document_id"]: e for e in t["extracted_invoice"]}
        self.extracted_lines = _group(t["extracted_invoice_line"], "document_id")
        self.channel = {m["document_id"]: m for m in read_csv(path / "inbox" / "intake_manifest.csv")}
        self.ground_truth = {g["document_id"]: g for g in read_csv(path / "ground_truth" / "ground_truth.csv")}

    def person(self, emp_id):
        e = self.employees.get(emp_id or "")
        return {"employee_id": emp_id, "name": e["full_name"], "role": e["role"]} if e else None

    def summary_row(self, d: dict) -> dict:
        v = self.vendors.get(d["vendor_id"] or "", {})
        return {**{k: d[k] for k in ("invoice_id", "document_id", "po_id", "vendor_invoice_number", "invoice_date",
                                     "computed_total", "match_status", "primary_exception", "final_status",
                                     "approval_path", "route_queue", "exception_count")},
                "vendor_id": d["vendor_id"], "vendor_name": v.get("vendor_name"),
                "channel": self.channel[d["document_id"]]["channel"],
                "received_at": self.channel[d["document_id"]]["received_at"],
                "assigned_to": self.person(d["assigned_to"])}

    def source_invoice(self, doc_id: str):
        """Typed source-truth invoice + lines, only to render a demo free-form document."""
        from datetime import date
        from decimal import Decimal
        inv = next(r for r in read_csv(self.path / "source_truth" / "invoice.csv") if r["document_id"] == doc_id)
        lines = [l for l in read_csv(self.path / "source_truth" / "invoice_line.csv") if l["invoice_id"] == inv["invoice_id"]]
        inv = {**inv, "invoice_date": date.fromisoformat(inv["invoice_date"]), "po_id": inv["po_id"] or None,
               **{k: Decimal(inv[k]) for k in ("subtotal", "tax_amount", "stated_total")}}
        lines = [{**l, "quantity": int(l["quantity"]), "unit_price": Decimal(l["unit_price"]),
                  "line_amount": Decimal(l["line_amount"])} for l in lines]
        return inv, lines

    def document_text(self, doc_id: str) -> str:
        return (self.path / "inbox" / "documents" / self.channel[doc_id]["file_name"]).read_text(encoding="utf-8")

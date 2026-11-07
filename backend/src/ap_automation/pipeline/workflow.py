"""End-to-end AP workflow: intake -> extraction -> validation -> 3-way match -> exception routing
-> approval -> payment readiness. Every state change is written as an invoice_event (append-only).

Information barrier: reads only master/ and inbox/. Never reads source_truth/ or ground_truth/.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import cycle
from pathlib import Path

from ..common import money, read_csv, sha256_file, write_csv
from ..schema import cols
from .extraction import extract
from .matching import DuplicateDetector, ThreeWayMatcher

PRE_MATCH = {"EXTRACTION_INCOMPLETE", "VENDOR_UNKNOWN", "DUPLICATE_INVOICE", "VENDOR_CLOSED", "VENDOR_MISMATCH",
             "PO_NOT_FOUND", "TOTAL_MISMATCH", "DATE_BEFORE_PO"}


class APWorkflow:
    def __init__(self, data_dir: Path, cfg: dict, llm=None):
        self.dir, self.cfg, self.llm = Path(data_dir), cfg, llm
        self.fy = cfg["fiscal_year"]
        m = self.dir / "master"
        self.vendors = read_csv(m / "vendor.csv")
        self.v_by_tax = {v["tax_id"]: v for v in self.vendors}
        self.v_by_name = {v["vendor_name"].lower(): v for v in self.vendors}
        self.pos = {p["po_id"]: p for p in read_csv(m / "purchase_order.csv")}
        self.employees = read_csv(m / "employee.csv")
        tol = cfg["tolerances"]
        self.amount_abs, self.line_abs = Decimal(tol["amount_abs"]), Decimal(tol["line_amount_abs"])
        self.matcher = ThreeWayMatcher(read_csv(m / "purchase_order_line.csv"), read_csv(m / "goods_receipt.csv"),
                                       read_csv(m / "goods_receipt_line.csv"), Decimal(tol["price_pct"]),
                                       Decimal(tol["qty_pct"]))
        self.dups = DuplicateDetector()
        self.tax = {k: Decimal(v) for k, v in cfg["tax_codes"].items()}
        self.precedence = cfg["exception_precedence"]
        self.routing = cfg["routing"]
        ap = cfg["approval_policy"]
        self.auto_max, self.l1_max = Decimal(ap["auto_approve_max"]), Decimal(ap["l1_max"])
        self.l1_by_dept = {e["department"]: e["employee_id"] for e in self.employees if e["role"] == "APPROVER_L1"}
        self.rr = {r: cycle([e["employee_id"] for e in self.employees if e["role"] == r])
                   for r in ("AP_ANALYST", "PROCESS_OWNER", "SYSTEM_ADMIN", "APPROVER_L2", "REQUESTER")}
        self.out = defaultdict(list)
        self.counters = defaultdict(int)

    # ------------------------------------------------------------------ helpers
    def _id(self, prefix: str, width: int = 6, year: bool = True) -> str:
        self.counters[prefix] += 1
        n = self.counters[prefix]
        return f"{prefix}-{self.fy}-{n:0{width}d}" if year else f"{prefix}-{n:0{width}d}"

    def _event(self, inv_id, frm, to, ts, actor="SYSTEM", detail=None):
        self.counters[inv_id] += 1
        self.out["invoice_event"].append({"event_id": self._id("IEV", 7, year=False), "invoice_id": inv_id,
                                          "seq": self.counters[inv_id], "from_state": frm, "to_state": to, "event_ts": ts,
                                          "actor": actor, "detail": detail})
        return to

    def _resolve_vendor(self, ex):
        return self.v_by_tax.get(ex.get("vendor_tax_id") or "") or \
            self.v_by_name.get((ex.get("vendor_name") or "").lower())

    def _assignee(self, role, po):
        if role == "REQUESTER" and po:
            return po["requester_id"]
        return next(self.rr[role])

    # ------------------------------------------------------------------ main
    def run(self) -> dict:
        manifest = read_csv(self.dir / "inbox" / "intake_manifest.csv")
        for m in sorted(manifest, key=lambda r: (r["received_at"], r["document_id"])):
            self.process(m)
        self.write()
        return {k: len(v) for k, v in self.out.items()}

    def process(self, m: dict):
        path = self.dir / "inbox" / "documents" / m["file_name"]
        if sha256_file(path) != m["sha256"]:
            raise ValueError(f"{m['document_id']}: document checksum does not match intake manifest")
        received = datetime.fromisoformat(m["received_at"])
        text = path.read_text(encoding="utf-8")
        if self.llm:      # rules first, Claude only for documents the rules cannot read
            from ..llm.extractor import hybrid_extract
            ex = hybrid_extract(text, self.llm)
        else:
            ex = extract(text)

        vendor = self._resolve_vendor(ex)
        self.counters["INV"] += 1
        inv_id = f"INV-{vendor['vendor_code'] if vendor else 'UNKN000'}-{self.fy}-{self.counters['INV']:06d}"
        state = self._event(inv_id, None, "RECEIVED", received, detail=f"{m['document_id']} via {m['channel']}")
        state = self._event(inv_id, state, "EXTRACTED", received + timedelta(minutes=1),
                            detail=f"layout={ex['layout']} method={ex.get('extraction_method', 'RULES')} "
                                   f"confidence={ex['confidence']:.2f}")

        lines = []
        for l in ex["lines"]:
            amt = money(l["quantity"] * l["unit_price"])
            lines.append({**l, "invoice_line_id": f"INVL-{inv_id}-{l['line_number']:02d}", "calc_amount": amt,
                          "calc_tax": money(amt * self.tax.get(l["tax_code"], Decimal(0)))})
        subtotal = sum((l["calc_amount"] for l in lines), Decimal(0))
        tax = sum((l["calc_tax"] for l in lines), Decimal(0))
        total = subtotal + tax
        self._record_extraction(m["document_id"], ex)

        exc, allocations, dup_of, match_status = [], [], None, "NOT_EVALUATED"
        po_num = ex.get("po_number")
        po = self.pos.get(po_num) if po_num else None
        if ex["confidence"] < 1:
            exc.append(self._x("EXTRACTION_INCOMPLETE", None, f"confidence {ex['confidence']:.2f}"))
        if not vendor:
            exc.append(self._x("VENDOR_UNKNOWN", None, f"tax id {ex.get('vendor_tax_id')} not in vendor master"))
        if vendor and ex.get("vendor_invoice_number"):
            dup_of = self.dups.check(vendor["vendor_id"], ex["vendor_invoice_number"], inv_id)
            if dup_of:
                exc.append(self._x("DUPLICATE_INVOICE", None, f"same vendor + invoice number as {dup_of}",
                                   dup_of, ex["vendor_invoice_number"]))

        if not exc:      # duplicates / unreadable docs short-circuit: no matching, no quantity consumed
            inv_date = ex["invoice_date"]
            if vendor["status"] == "CLOSED" and vendor["effective_to"] and \
                    inv_date > date.fromisoformat(vendor["effective_to"]):
                exc.append(self._x("VENDOR_CLOSED", None, f"vendor closed on {vendor['effective_to']}",
                                   vendor["effective_to"], inv_date))
            if po_num and not po:
                exc.append(self._x("PO_NOT_FOUND", None, f"{po_num} not in PO master", None, po_num))
            if po and po["vendor_id"] != vendor["vendor_id"]:
                exc.append(self._x("VENDOR_MISMATCH", None, f"{po_num} belongs to {po['vendor_id']}",
                                   po["vendor_id"], vendor["vendor_id"]))
            for l in lines:
                if abs(l["line_amount"] - l["calc_amount"]) > self.line_abs:
                    exc.append(self._x("TOTAL_MISMATCH", l["invoice_line_id"], "line amount != qty x price",
                                       l["calc_amount"], l["line_amount"]))
            for field, calc in (("subtotal", subtotal), ("tax_amount", tax), ("stated_total", total)):
                if ex.get(field) is None or abs(ex[field] - calc) > self.amount_abs:
                    exc.append(self._x("TOTAL_MISMATCH", None, f"{field} on document does not reconcile with lines",
                                       calc, ex.get(field)))
            if po and inv_date < date.fromisoformat(po["po_date"]):
                exc.append(self._x("DATE_BEFORE_PO", None, f"invoice dated before PO ({po['po_date']})",
                                   po["po_date"], inv_date))
            if po:
                match_status, mexc, allocations = self.matcher.match(po["po_id"], lines)
                exc += [self._x(e["code"], e["invoice_line_id"], e["detail"], e["expected"], e["actual"]) for e in mexc]
            elif not po_num:
                match_status = "NON_PO"

        codes = sorted({e["code"] for e in exc}, key=self.precedence.index)
        primary = codes[0] if codes else None
        decision = {"invoice_id": inv_id, "document_id": m["document_id"],
                    "vendor_id": vendor["vendor_id"] if vendor else None, "po_id": po["po_id"] if po else None,
                    "vendor_invoice_number": ex.get("vendor_invoice_number"), "invoice_date": ex.get("invoice_date"),
                    "computed_total": total, "match_status": match_status, "primary_exception": primary,
                    "exception_codes": ";".join(codes) or None, "exception_count": len(exc),
                    "duplicate_of_invoice_id": dup_of, "extraction_confidence": ex["confidence"],
                    "approval_path": None, "route_queue": None, "assigned_to": None}
        ts = received + timedelta(minutes=2)
        for a in allocations:
            self.out["invoice_match"].append({"match_id": self._id("MAT"), **a})

        if exc:
            if primary not in PRE_MATCH:
                state = self._event(inv_id, state, "VALIDATED", ts)
            for e in sorted(exc, key=lambda e: self.precedence.index(e["code"])):
                r = self.routing[e["code"]]
                owner = self._assignee(r["role"], po)
                is_primary = e["code"] == primary and decision["assigned_to"] is None
                if is_primary:
                    decision |= {"route_queue": r["queue"], "assigned_to": owner}
                self.out["invoice_exception"].append({
                    "exception_id": self._id("EXC"), "invoice_id": inv_id, "invoice_line_id": e["invoice_line_id"],
                    "exception_code": e["code"], "severity": r["severity"], "is_primary": is_primary,
                    "queue": r["queue"], "assigned_to": owner, "detail": e["detail"],
                    "expected_value": e["expected"], "actual_value": e["actual"], "status": "OPEN",
                    "created_at": ts, "sla_due_at": ts + timedelta(hours=r["sla_hours"])})
            state = self._event(inv_id, state, "ON_HOLD", ts + timedelta(minutes=1), detail=f"{primary} -> "
                                f"{decision['route_queue']} ({decision['assigned_to']})")
            decision |= {"final_status": "ON_HOLD", "payment_ready": False, "processed_at": ts + timedelta(minutes=1)}
        else:
            state = self._event(inv_id, state, "VALIDATED", ts)
            if po:
                state = self._event(inv_id, state, "MATCHED", ts + timedelta(minutes=1), detail=match_status)
            state = self._event(inv_id, state, "PENDING_APPROVAL", ts + timedelta(minutes=2))
            decided, path = self._approve(inv_id, total, po, ts + timedelta(minutes=2))
            state = self._event(inv_id, state, "APPROVED", decided, detail=path)
            pay_at = decided + timedelta(minutes=1)
            due = ex["invoice_date"] + timedelta(days=self.cfg["payment_terms_days"].get(
                ex.get("payment_terms"), self.cfg["payment_terms_days"][vendor["payment_terms"]]))
            self.out["payment"].append({
                "payment_id": self._id("PAY"), "invoice_id": inv_id, "vendor_id": vendor["vendor_id"],
                "amount": total, "currency": "USD", "method": vendor["payment_method"],
                "scheduled_date": max(due, decided.date() + timedelta(days=1)), "status": "SCHEDULED",
                "created_at": pay_at})
            self._event(inv_id, state, "PAYMENT_READY", pay_at, detail=f"scheduled {total} USD")
            decision |= {"final_status": "PAYMENT_READY", "payment_ready": True, "approval_path": path,
                         "processed_at": pay_at}
        self.out["invoice_decision"].append(decision)

    def _x(self, code, line_id, detail, expected=None, actual=None) -> dict:
        return {"code": code, "invoice_line_id": line_id, "detail": detail,
                "expected": None if expected is None else str(expected),
                "actual": None if actual is None else str(actual)}

    def _approve(self, inv_id, total, po, ts):
        """Policy: <= auto max and PO-backed -> system; <= L1 max -> dept manager; above -> manager + director."""
        if po and total <= self.auto_max:
            levels = [(0, None, f"PO-backed and total <= {self.auto_max}: auto-approve")]
        else:
            dept = po["department"] if po else "FINANCE"
            reason = "non-PO invoice requires manager approval" if not po else f"total > {self.auto_max}"
            levels = [(1, self.l1_by_dept[dept], reason)]
            if total > self.l1_max:
                levels.append((2, next(self.rr["APPROVER_L2"]), f"total > {self.l1_max}: finance director"))
        for level, approver, rule in levels:
            ts = ts + timedelta(hours={0: 0, 1: 6, 2: 18}[level], minutes=1)
            self.out["approval"].append({"approval_id": self._id("APR"), "invoice_id": inv_id, "level": level,
                                         "approver_type": "SYSTEM" if approver is None else "HUMAN",
                                         "approver_id": approver, "decision": "APPROVED", "policy_rule": rule,
                                         "decided_at": ts})
        return ts, "AUTO" if levels[0][0] == 0 else "L1" if len(levels) == 1 else "L1>L2"

    def _record_extraction(self, doc_id, ex):
        self.out["extracted_invoice"].append({"document_id": doc_id, "line_count": len(ex["lines"]),
                                              **{k: ex.get(k) for k in cols("extracted_invoice")
                                                 if k not in ("document_id", "line_count")}})
        for l in ex["lines"]:
            self.out["extracted_invoice_line"].append({"extracted_line_id": f"{doc_id}-{l['line_number']:02d}",
                                                       "document_id": doc_id, **l})

    def write(self):
        for t in ("extracted_invoice", "extracted_invoice_line", "invoice_decision", "invoice_match",
                  "invoice_exception", "approval", "payment", "invoice_event"):
            write_csv(self.dir / "pipeline_output" / f"{t}.csv", self.out[t], cols(t))


def run_pipeline(data_dir: Path, cfg: dict, llm=None) -> dict:
    return APWorkflow(data_dir, cfg, llm).run()

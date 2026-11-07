"""Dataset + pipeline validation (Step 8).

PK uniqueness, FK integrity, enums/patterns/types, join validity, date ordering, arithmetic reconciliation,
lifecycle transitions, duplicate checks, volumes/mix, leakage and payment-safety.
A rule broken only by rows labelled as deliberate anomalies counts as PASS (reported as `labelled`).
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .common import alloc, money, norm_invoice_number, read_csv, write_json, write_text
from .schema import INVOICE_TRANSITIONS, PO_TRANSITIONS, TABLES, VENDOR_TRANSITIONS


def _parse(typ, v):
    if typ == "int":
        return int(v)
    if typ == "money":
        d = Decimal(v)
        if d != d.quantize(Decimal("0.01")):
            raise ValueError("more than 2 decimals")
        return d
    if typ == "rate":
        return Decimal(v)
    if typ == "date":
        return date.fromisoformat(v)
    if typ == "datetime":
        return datetime.fromisoformat(v)
    if typ == "bool":
        if v not in ("true", "false"):
            raise ValueError("bad bool")
        return v == "true"
    return v


class Validator:
    def __init__(self, data_dir: Path, cfg: dict):
        self.dir, self.cfg = Path(data_dir), cfg
        self.t = {}
        for name, spec in TABLES.items():
            p = self.dir / spec["zone"] / f"{name}.csv"
            if p.exists():
                self.t[name] = read_csv(p)
        self.gt = {r["invoice_id"]: r for r in read_csv(self.dir / "ground_truth" / "ground_truth.csv")}
        self.checks = []

    def add(self, name, category, violations, labelled=0, note=""):
        self.checks.append({"check": name, "category": category, "status": "FAIL" if violations else "PASS",
                            "violations": len(violations), "labelled_anomalies_allowed": labelled,
                            "sample": [str(v) for v in violations[:5]], "note": note})

    def labelled(self, invoice_id, *scenarios):
        return self.gt.get(invoice_id, {}).get("scenario") in scenarios

    # ---------------------------------------------------------------- generic schema rules
    def schema_checks(self):
        for name, rows in self.t.items():
            spec = TABLES[name]
            pk = spec["pk"]
            dup = [k for k, c in Counter(r[pk] for r in rows).items() if c > 1]
            self.add(f"{name}: primary key {pk} unique", "primary_key", dup)
            bad = []
            for c in spec["cols"]:
                rx = re.compile(c.pattern) if c.pattern else None
                for r in rows:
                    v = r[c.name]
                    if v == "":
                        if c.required:
                            bad.append(f"{r[pk]}.{c.name} missing")
                        continue
                    try:
                        _parse(c.type, v)
                    except (ValueError, InvalidOperation):
                        bad.append(f"{r[pk]}.{c.name}={v!r} not {c.type}")
                    if c.enum and v not in c.enum:
                        bad.append(f"{r[pk]}.{c.name}={v!r} not in enum")
                    if rx and not rx.match(v):
                        bad.append(f"{r[pk]}.{c.name}={v!r} bad format")
                if c.unique and c.name != pk:
                    vals = [r[c.name] for r in rows if r[c.name]]
                    bad += [f"{c.name}={k} duplicated" for k, n in Counter(vals).items() if n > 1]
            self.add(f"{name}: required / type / enum / format / unique", "schema", bad)

    def fk_checks(self):
        for name, rows in self.t.items():
            for c in TABLES[name]["cols"]:
                if not c.fk:
                    continue
                pt, pc = c.fk.split(".")
                if pt not in self.t:
                    continue
                keys = {r[pc] for r in self.t[pt]}
                bad = [f"{name}.{c.name}={r[c.name]}" for r in rows if r[c.name] and r[c.name] not in keys]
                self.add(f"FK {name}.{c.name} -> {c.fk}", "foreign_key", bad)
        # polymorphic lifecycle FK
        keys = {"VENDOR": {r["vendor_id"] for r in self.t["vendor"]},
                "PURCHASE_ORDER": {r["po_id"] for r in self.t["purchase_order"]}}
        bad = [r["event_id"] for r in self.t["lifecycle_event"] if r["entity_id"] not in keys[r["entity_type"]]]
        self.add("FK lifecycle_event.entity_id -> vendor / purchase_order", "foreign_key", bad)

    # ---------------------------------------------------------------- domain rules
    def join_checks(self):
        pol = {r["po_line_id"]: r for r in self.t["purchase_order_line"]}
        grn = {r["grn_id"]: r for r in self.t["goods_receipt"]}
        bad = [r["grn_line_id"] for r in self.t["goods_receipt_line"] if pol[r["po_line_id"]]["po_id"] != grn[r["grn_id"]]["po_id"]]
        self.add("GRN line's PO line belongs to the GRN's PO", "join", bad)
        inv = {r["invoice_id"]: r for r in self.t["invoice"]}
        bad = [r["invoice_line_id"] for r in self.t["invoice_line"]
               if r["po_line_id"] and pol[r["po_line_id"]]["po_id"] != inv[r["invoice_id"]]["po_id"]]
        bad += [r["invoice_line_id"] for r in self.t["invoice_line"] if bool(r["po_line_id"]) != bool(inv[r["invoice_id"]]["po_id"])]
        self.add("Invoice line's PO line belongs to the invoice's PO", "join", bad)
        po ={r["po_id"]: r for r in self.t["purchase_order"]}
        bad = [r["invoice_id"] for r in self.t["invoice"] if r["po_id"] and po[r["po_id"]]["vendor_id"] != r["vendor_id"]]
        self.add("Invoice vendor = PO vendor", "join", bad)
        if "invoice_match" in self.t:
            grnl = {r["grn_line_id"]: r for r in self.t["goods_receipt_line"]}
            invl = {r["invoice_line_id"]: r for r in self.t["invoice_line"]}
            bad = [r["match_id"] for r in self.t["invoice_match"]
                   if invl[r["invoice_line_id"]]["po_line_id"] != grnl[r["grn_line_id"]]["po_line_id"]]
            used = defaultdict(int)
            for r in self.t["invoice_match"]:
                used[r["grn_line_id"]] += int(r["matched_qty"])
            bad += [k for k, q in used.items() if q > int(grnl[k]["quantity_received"])]
            self.add("Bridge invoice_match: same PO line, allocation <= received", "join", bad)

    def date_checks(self):
        run = date.fromisoformat(self.cfg["dates"]["run_date"])
        V = {r["vendor_id"]: r for r in self.t["vendor"]}
        po = {r["po_id"]: r for r in self.t["purchase_order"]}
        d = date.fromisoformat
        bad = [v["vendor_id"] for v in V.values() if (v["status"] == "CLOSED") != bool(v["effective_to"])
               or (v["effective_to"] and d(v["effective_to"]) < d(v["effective_from"]))]
        self.add("Vendor effective_to set iff CLOSED and >= effective_from", "date_order", bad)
        bad = [p["po_id"] for p in po.values() if d(p["po_date"]) < d(V[p["vendor_id"]]["effective_from"])
               or (V[p["vendor_id"]]["effective_to"] and d(p["po_date"]) > d(V[p["vendor_id"]]["effective_to"]))]
        self.add("PO date within vendor effective dates", "date_order", bad)
        bad = [g["grn_id"] for g in self.t["goods_receipt"] if d(g["receipt_date"]) < d(po[g["po_id"]]["po_date"])]
        self.add("Receipt date >= PO date", "date_order", bad)
        before, closed, other = [], [], []
        terms = self.cfg["payment_terms_days"]
        for i in self.t["invoice"]:
            idate = d(i["invoice_date"])
            if i["po_id"] and idate < d(po[i["po_id"]]["po_date"]):
                before.append(i["invoice_id"])
            v = V[i["vendor_id"]]
            if v["effective_to"] and idate > d(v["effective_to"]):
                closed.append(i["invoice_id"])
            if datetime.fromisoformat(i["received_at"]).date() < idate or \
                    d(i["due_date"]) != idate + timedelta(days=terms[i["payment_terms"]]) or \
                    datetime.fromisoformat(i["received_at"]).date() > run:
                other.append(i["invoice_id"])
        self._labelled_rule("Invoice date >= PO date", "date_order", before, "DATE_BEFORE_PO")
        self._labelled_rule("Invoice date <= vendor closure date", "date_order", closed, "CLOSED_VENDOR")
        self.add("received_at >= invoice_date, <= run date; due_date = invoice_date + terms", "date_order", other)

    def _labelled_rule(self, name, cat, offenders, *scenarios):
        unlabelled = [x for x in offenders if not self.labelled(x, *scenarios)]
        self.add(name, cat, unlabelled, labelled=len(offenders) - len(unlabelled),
                 note=f"allowed only for labelled {', '.join(scenarios)}")

    def arithmetic_checks(self):
        tax = {k: Decimal(v) for k, v in self.cfg["tax_codes"].items()}
        for lt, ht, hk in (("purchase_order_line", "purchase_order", "po_id"), ("invoice_line", "invoice", "invoice_id")):
            bad, sums = [], defaultdict(lambda: [Decimal(0), Decimal(0), 0])
            pk = TABLES[lt]["pk"]
            for l in self.t[lt]:
                amt, rate = Decimal(l["line_amount"]), Decimal(l["tax_rate"])
                if amt != money(int(l["quantity"]) * Decimal(l["unit_price"])) or rate != tax[l["tax_code"]] \
                        or Decimal(l["tax_amount"]) != money(amt * rate) or int(l["quantity"]) <= 0 \
                        or Decimal(l["unit_price"]) <= 0:
                    bad.append(l[pk])
                s = sums[l[hk]]
                s[0] += amt
                s[1] += Decimal(l["tax_amount"])
                s[2] += 1
            self.add(f"{lt}: amount = qty x price, tax = amount x rate(tax_code)", "arithmetic", bad)
            total_col = "total_amount" if ht == "purchase_order" else "grand_total"
            bad = [h[hk] for h in self.t[ht] if Decimal(h["subtotal"]) != sums[h[hk]][0]
                   or Decimal(h["tax_amount"]) != sums[h[hk]][1] or int(h["line_count"]) != sums[h[hk]][2]
                   or Decimal(h[total_col]) != Decimal(h["subtotal"]) + Decimal(h["tax_amount"])]
            self.add(f"{ht}: subtotal / tax / total / line_count reconcile with lines", "arithmetic", bad)
        bad = [p["po_id"] for p in self.t["purchase_order"] if not 1 <= int(p["line_count"]) <= 8]
        self.add("PO has 1..8 lines", "arithmetic", bad)
        off = [i["invoice_id"] for i in self.t["invoice"] if i["stated_total"] != i["grand_total"]]
        self._labelled_rule("Stated total = line-derived grand total", "arithmetic", off, "TOTAL_MISMATCH")
        pol = {r["po_line_id"]: int(r["quantity"]) for r in self.t["purchase_order_line"]}
        grn_date = {g["grn_id"]: g["receipt_date"] for g in self.t["goods_receipt"]}
        cum, bad = defaultdict(int), []
        for gl in sorted(self.t["goods_receipt_line"], key=lambda g: (grn_date[g["grn_id"]], g["grn_line_id"])):
            cum[gl["po_line_id"]] += int(gl["quantity_received"])
            c, o = cum[gl["po_line_id"]], pol[gl["po_line_id"]]
            if gl["receipt_type"] != ("PARTIAL" if c < o else "FULL" if c == o else "OVER"):
                bad.append(gl["grn_line_id"])
        self.add("GRN receipt_type consistent with cumulative received vs ordered", "arithmetic", bad)

    def lifecycle_checks(self):
        status = {("VENDOR", v["vendor_id"]): v["status"] for v in self.t["vendor"]}
        status |= {("PURCHASE_ORDER", p["po_id"]): p["status"] for p in self.t["purchase_order"]}
        allowed = {"VENDOR": VENDOR_TRANSITIONS, "PURCHASE_ORDER": PO_TRANSITIONS}
        last, bad = {}, []
        for e in sorted(self.t["lifecycle_event"], key=lambda e: e["event_id"]):
            k, frm = (e["entity_type"], e["entity_id"]), e["from_state"] or None
            if (frm, e["to_state"]) not in allowed[e["entity_type"]] or last.get(k) != frm:
                bad.append(e["event_id"])
            last[k] = e["to_state"]
        bad += [f"{k} final {last.get(k)} != {s}" for k, s in status.items() if last.get(k) != s]
        self.add("Vendor / PO lifecycle transitions valid and final state = entity status", "lifecycle", bad)
        if "invoice_event" not in self.t:
            return
        final = {d["invoice_id"]: d["final_status"] for d in self.t["invoice_decision"]}
        last, prev_ts, prev_seq, bad = {}, {}, {}, []
        for e in self.t["invoice_event"]:
            k, frm = e["invoice_id"], e["from_state"] or None
            ts, seq = datetime.fromisoformat(e["event_ts"]), int(e["seq"])
            if (frm, e["to_state"]) not in INVOICE_TRANSITIONS or last.get(k) != frm \
                    or (k in prev_ts and ts < prev_ts[k]) or seq != prev_seq.get(k, 0) + 1:
                bad.append(e["event_id"])
            last[k], prev_ts[k], prev_seq[k] = e["to_state"], ts, seq
        bad += [k for k, s in final.items() if last.get(k) != s]
        self.add("Invoice event transitions valid, ordered, final state = decision", "lifecycle", bad)

    def duplicate_checks(self):
        groups = defaultdict(list)
        for i in sorted(self.t["invoice"], key=lambda r: r["received_at"]):
            groups[(i["vendor_id"], norm_invoice_number(i["vendor_invoice_number"]))].append(i["invoice_id"])
        bad, n = [], 0
        for ids in groups.values():
            for later in ids[1:]:
                n += 1
                g = self.gt[later]
                if g["issue_type"] != "DUPLICATE" or g["duplicate_of_invoice_id"] != ids[0]:
                    bad.append(later)
        labelled = [k for k, g in self.gt.items() if g["issue_type"] == "DUPLICATE"]
        bad += [k for k in labelled if k not in {x for ids in groups.values() for x in ids[1:]}]
        self.add("Repeated (vendor, invoice number) only where labelled DUPLICATE, pair recorded", "duplicates",
                 bad, labelled=n)

    def volume_checks(self, scale):
        base = self.cfg["base_volumes"]
        tgt = {"vendor": "vendors", "purchase_order": "purchase_orders", "purchase_order_line": "po_lines",
               "goods_receipt": "goods_receipts", "invoice": "invoices"}
        bad = [f"{t}: {len(self.t[t])} != {round(base[k] * scale)}" for t, k in tgt.items()
               if len(self.t[t]) != round(base[k] * scale)]
        self.add("Row volumes hit targets exactly", "volume", bad)
        n = len(self.gt)
        want = alloc(n, self.cfg["issue_mix"])
        got = Counter(g["issue_type"] for g in self.gt.values())
        bad = [f"{k}: {got[k]} != {v}" for k, v in want.items() if got[k] != v]
        self.add("Issue mix matches configured shares", "volume", bad,
                 note="; ".join(f"{k} {got[k] / n:.1%}" for k in want))

    def leakage_checks(self):
        manifest = read_csv(self.dir / "inbox" / "intake_manifest.csv")
        bad = [c for c in manifest[0] if c not in ("document_id", "file_name", "channel", "received_at", "sha256", "bytes")]
        words = re.compile(r"CLEAN_|DUPLICATE_|_VARIANCE|_MISMATCH|EXCEEDS|ground.truth|scenario", re.I)
        for p in sorted((self.dir / "inbox" / "documents").glob("*.txt")):
            if words.search(p.read_text(encoding="utf-8")):
                bad.append(p.name)
        label_cols = {"scenario", "issue_type", "edge_case"}
        for t in ("invoice", "invoice_line"):
            bad += [f"{t}.{c}" for c in self.t[t][0] if c in label_cols]
        self.add("No ground-truth labels in pipeline inputs (manifest, documents, source tables)", "leakage", bad)

    def payment_safety_checks(self):
        if "invoice_decision" not in self.t:
            return
        dec = {d["invoice_id"]: d for d in self.t["invoice_decision"]}
        pays = Counter(p["invoice_id"] for p in self.t["payment"])
        appr = Counter(a["invoice_id"] for a in self.t["approval"])
        inv = {i["invoice_id"]: i for i in self.t["invoice"]}
        bad = [k for k, d in dec.items() if d["final_status"] == "ON_HOLD" and (pays[k] or appr[k] or d["payment_ready"] == "true")]
        self.add("No blocked (ON_HOLD) invoice is payment-ready, approved or paid", "payment_safety", bad)
        bad = [k for k, d in dec.items() if d["final_status"] == "PAYMENT_READY" and (pays[k] != 1 or not appr[k])]
        bad += [p["payment_id"] for p in self.t["payment"] if Decimal(p["amount"]) != Decimal(dec[p["invoice_id"]]["computed_total"])
                or Decimal(p["amount"]) != Decimal(inv[p["invoice_id"]]["grand_total"])]
        self.add("Each payment-ready invoice has 1 payment (= line-derived total) and approvals", "payment_safety", bad)
        exc_inv = {e["invoice_id"] for e in self.t["invoice_exception"]}
        bad = [k for k in exc_inv if dec[k]["final_status"] != "ON_HOLD"]
        bad += [k for k, d in dec.items() if d["final_status"] == "ON_HOLD" and k not in exc_inv]
        self.add("Exceptions <-> ON_HOLD one-to-one at invoice level", "payment_safety", bad)

    def sqlite_checks(self):
        db = self.dir / "exports" / "ap_automation.db"
        if not db.exists():
            return
        con = sqlite3.connect(db)
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        con.close()
        self.add("SQLite seed loads; PRAGMA foreign_key_check / integrity_check clean", "foreign_key",
                 [str(r) for r in fk] + ([] if ok == "ok" else [ok]))

    def run(self, scale: float) -> dict:
        self.schema_checks()
        self.fk_checks()
        self.join_checks()
        self.date_checks()
        self.arithmetic_checks()
        self.lifecycle_checks()
        self.duplicate_checks()
        self.volume_checks(scale)
        self.leakage_checks()
        self.payment_safety_checks()
        self.sqlite_checks()
        failed = [c for c in self.checks if c["status"] == "FAIL"]
        return {"status": "FAIL" if failed else "PASS", "checks_run": len(self.checks), "checks_failed": len(failed),
                "row_counts": {k: len(v) for k, v in self.t.items()}, "checks": self.checks}


def validate(data_dir: Path, cfg: dict, scale: float) -> dict:
    res = Validator(data_dir, cfg).run(scale)
    out = Path(data_dir) / "reports"
    write_json(out / "validation_summary.json", res)
    md = [f"# Validation summary: **{res['status']}**", "",
          f"{res['checks_run']} checks, {res['checks_failed']} failed.", "",
          "| Category | Check | Status | Violations | Labelled anomalies (allowed) |", "|---|---|---|---|---|"]
    md += [f"| {c['category']} | {c['check']} | {c['status']} | {c['violations']} | {c['labelled_anomalies_allowed']} |"
           for c in res["checks"]]
    write_text(out / "validation_summary.md", "\n".join(md) + "\n")
    return res

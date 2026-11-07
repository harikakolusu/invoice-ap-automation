"""Deterministic synthetic data generator (fixed seed, parameterised scale).

Order of generation (parents before children):
  employees -> vendors -> purchase orders -> PO lines -> goods receipts -> receipt lines
  -> invoice drafts (baseline) -> labelled scenario injection -> duplicates
  -> IDs in intake order -> derived totals -> ground truth -> raw documents
"""
from __future__ import annotations

import copy
import math
import random
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from ..common import alloc, money, sha256_text
from ..schema import DEPARTMENTS, TAX_CODES
from . import catalog
from .documents import LAYOUT_BY_CHANNEL, render
from .scenarios import SCENARIOS

POOL_SCENARIOS = ("PRICE_VARIANCE", "TAX_MISMATCH", "TOTAL_MISMATCH", "DATE_BEFORE_PO", "CLEAN_PRICE_WITHIN_TOL")


class InfeasibleVolumes(ValueError):
    pass


def plan_counts(cfg: dict, n: dict) -> tuple[dict, dict]:
    """Scenario counts per invoice and PO fulfilment plan, solved so every volume target is hit exactly."""
    N, P, G = n["invoices"], n["purchase_orders"], n["goods_receipts"]
    issues = alloc(N, cfg["issue_mix"])
    sc = {"PRICE_VARIANCE": issues["PRICE_VARIANCE"], "MISSING_RECEIPT": issues["MISSING_RECEIPT"]}
    sc |= alloc(issues["TAX_VENDOR_ERROR"], dict.fromkeys(("TAX_MISMATCH", "CLOSED_VENDOR", "TOTAL_MISMATCH",
                                                            "DATE_BEFORE_PO"), 1))
    sc |= alloc(issues["QTY_MISMATCH"], {"QTY_EXCEEDS_RECEIPT": 1, "QTY_EXCEEDS_PO": 1})
    sc |= alloc(issues["DUPLICATE"], {"DUPLICATE_RESUBMISSION": 3, "DUPLICATE_NUMBER": 2})
    sc |= {k: round(N * v) for k, v in cfg["clean_subtypes_share_of_all_invoices"].items()}

    po = {"MISSING": sc["MISSING_RECEIPT"], "CLOSED": sc["CLOSED_VENDOR"],
          "PARTIAL_CLEAN": sc["CLEAN_PARTIAL_DELIVERY"], "PARTIAL_EXCEED": sc["QTY_EXCEEDS_RECEIPT"],
          "OVER_CLEAN": sc["CLEAN_OVER_RECEIPT_WITHIN_TOL"], "OVER_EXCEED": sc["QTY_EXCEEDS_PO"]}
    fixed_grn_pos = sum(po.values()) - po["MISSING"]          # POs with exactly one GRN and one invoice
    dups = sc["DUPLICATE_RESUBMISSION"] + sc["DUPLICATE_NUMBER"]
    pool = N - dups - sc["CLEAN_NON_PO"] - po["MISSING"] - fixed_grn_pos   # invoices from FULL + SPLIT POs
    uninvoiced = G - fixed_grn_pos - pool                      # received, invoice not yet arrived
    open_pos = round(P * cfg["open_po_share"])
    full_plus_split = P - po["MISSING"] - fixed_grn_pos - uninvoiced - open_pos
    split = pool - full_plus_split                             # split POs: 2 GRNs, 2 invoices
    full = full_plus_split - split
    clean_rest = pool - sum(sc[k] for k in POOL_SCENARIOS)
    if min(pool, uninvoiced, split, full, clean_rest - dups) < 0:
        raise InfeasibleVolumes(f"volumes {n} cannot satisfy the issue mix (pool={pool}, uninvoiced={uninvoiced}, "
                                f"split={split}, full={full})")
    po |= {"FULL": full, "SPLIT": split, "UNINVOICED": uninvoiced, "OPEN": open_pos}
    return sc, po


class Generator:
    def __init__(self, cfg: dict, scale: float, seed: int):
        self.cfg, self.scale, self.seed = cfg, scale, seed
        self.rng = random.Random(seed)
        self.fy = cfg["fiscal_year"]
        self.tax = {k: Decimal(v) for k, v in cfg["tax_codes"].items()}
        self.terms = cfg["payment_terms_days"]
        self.n = {k: round(v * scale) for k, v in cfg["base_volumes"].items()}
        self.d0 = date.fromisoformat(cfg["dates"]["po_start"])
        self.d1 = date.fromisoformat(cfg["dates"]["po_end"])
        self.sc, self.po_plan = plan_counts(cfg, self.n)

    # ------------------------------------------------------------------ helpers
    def _logu(self, lo, hi) -> float:
        return math.exp(self.rng.uniform(math.log(lo), math.log(hi)))

    def _rand_date(self, a: date, b: date) -> date:
        return a + timedelta(days=self.rng.randint(0, (b - a).days))

    def _received_at(self, d: date) -> datetime:
        return datetime.combine(d + timedelta(days=self.rng.randint(0, 5)),
                                time(self.rng.randint(7, 19), self.rng.randint(0, 59)))

    def _line(self, sku: dict, qty: int, price: Decimal, tax_code: str) -> dict:
        amt = money(qty * price)
        return {"sku": sku["sku"], "description": sku["description"], "uom": sku["uom"], "quantity": qty,
                "unit_price": price, "tax_code": tax_code, "tax_rate": self.tax[tax_code], "line_amount": amt,
                "tax_amount": money(amt * self.tax[tax_code])}

    # ------------------------------------------------------------------ master data
    def employees(self):
        rng = self.rng
        names = [f"{f} {l}" for f in catalog.FIRST for l in catalog.LAST]
        rng.shuffle(names)
        spec = ([(d, "REQUESTER", None) for d in DEPARTMENTS for _ in range(3)]
                + [(d, "APPROVER_L1", self.cfg["approval_policy"]["l1_max"]) for d in DEPARTMENTS]
                + [("FINANCE", "APPROVER_L2", "1000000.00")] * 2
                + [("FINANCE", "AP_ANALYST", None)] * 4
                + [("FINANCE", "PROCESS_OWNER", None), ("OPERATIONS", "PROCESS_OWNER", None)]
                + [("IT", "SYSTEM_ADMIN", None)] * 2)
        self.employees_rows = [
            {"employee_id": f"EMP-{i:04d}", "full_name": names[i - 1], "department": d, "role": r,
             "approval_limit": money(lim) if lim else None, "status": "ACTIVE"}
            for i, (d, r, lim) in enumerate(spec, 1)]
        self.requesters = [e for e in self.employees_rows if e["role"] == "REQUESTER"]

    def skus(self):
        self.sku_by_cat = defaultdict(list)
        for cat, (pfx, uom, tax, (plo, phi), (qlo, qhi), items) in catalog.CATALOG.items():
            for j, desc in enumerate(items, 1):
                self.sku_by_cat[cat].append({"sku": f"SKU-{pfx}-{j:04d}", "description": desc, "uom": uom,
                                             "tax_code": tax, "base_price": money(self._logu(plo, phi)),
                                             "qty": (qlo, qhi), "category": cat})

    def vendors(self):
        rng, V = self.rng, self.n["vendors"]
        goods_cats = [c for c in catalog.CATALOG if c != "SERVICES"]
        combos = [(p, c, l) for p in catalog.VENDOR_PREFIX for c in catalog.VENDOR_CORE for l in catalog.VENDOR_LEGAL]
        names = rng.sample(combos, V)
        tax_ids = rng.sample(range(10 ** 8, 10 ** 9), V)
        idx = list(range(V))
        closing = rng.sample(idx, self.po_plan["CLOSED"])
        rest = [i for i in idx if i not in set(closing)]
        inactive = set(rng.sample(rest, round(V * self.cfg["inactive_closed_vendor_share"])))
        self.vendor_rows, self.vstyle = [], {}
        for i, (p, c, l) in enumerate(names):
            vid = f"VND-{i + 1:05d}"
            country = rng.choices(["US", "IN", "GB", "DE", "SG"], [60, 15, 10, 10, 5])[0]
            cat = catalog.CORE_CATEGORY.get(c) or rng.choice(goods_cats)
            v = {"vendor_id": vid, "vendor_code": f"{p[:4].upper()}{i + 1:03d}", "vendor_name": f"{p} {c} {l}",
                 "tax_id": f"{str(tax_ids[i])[:2]}-{str(tax_ids[i])[2:]}", "country": country,
                 "primary_category": cat, "payment_terms": rng.choices(list(self.terms), [10, 50, 25, 15])[0],
                 "payment_method": "ACH" if country == "US" else "WIRE", "currency": "USD",
                 "preferred_channel": rng.choices(["EMAIL", "PDF_UPLOAD", "EDI"], [45, 35, 20])[0],
                 "status": "ACTIVE", "effective_from": self._rand_date(date(2015, 1, 1), date(2025, 12, 31)),
                 "effective_to": None}
            if i in inactive:   # closed early in the year, no activity afterwards
                v["status"], v["effective_to"] = "CLOSED", self._rand_date(date(self.fy, 1, 2), date(self.fy, 3, 31))
            self.vendor_rows.append(v)
            self.vstyle[vid] = {"secondary": rng.choice([g for g in goods_cats if g != cat]),
                                "num_style": rng.choice(["DASH", "PLAIN", "SLASH"]),
                                "num_next": rng.randint(1000, 60000), "date_style": rng.choice(["ISO", "LONG"]),
                                "weight": rng.paretovariate(1.3)}
        self.vendor_by_id = {v["vendor_id"]: v for v in self.vendor_rows}
        self.closing_vendors = [self.vendor_rows[i] for i in closing]
        self.active_vendors = [v for k, v in enumerate(self.vendor_rows) if k not in set(closing) | inactive]

    # ------------------------------------------------------------------ purchase orders and receipts
    def purchase_orders(self):
        rng, P, L = self.rng, self.n["purchase_orders"], self.n["po_lines"]
        plan = self.po_plan
        early = [t for t in ("MISSING", "CLOSED", "PARTIAL_CLEAN", "PARTIAL_EXCEED", "OVER_CLEAN", "OVER_EXCEED",
                             "FULL", "SPLIT") for _ in range(plan[t])]
        rng.shuffle(early)
        types = early + ["UNINVOICED"] * plan["UNINVOICED"] + ["OPEN"] * plan["OPEN"]  # latest POs still pending
        dates = sorted(self._rand_date(self.d0, self.d1) for _ in range(P))

        counts = rng.choices(range(1, 9), [72, 15, 6, 3, 2, 1, 0.5, 0.5], k=P)
        while sum(counts) != L:      # nudge to the exact line volume, keeping 1..8 lines per PO
            k = rng.randrange(P)
            if sum(counts) < L and counts[k] < 8:
                counts[k] += 1
            elif sum(counts) > L and counts[k] > 1:
                counts[k] -= 1

        weights = [self.vstyle[v["vendor_id"]]["weight"] for v in self.active_vendors]
        closing = iter(self.closing_vendors)
        self.pos, self.po_lines = [], []
        for i, (t, d, k) in enumerate(zip(types, dates, counts), 1):
            vendor = next(closing) if t == "CLOSED" else rng.choices(self.active_vendors, weights)[0]
            req = rng.choice(self.requesters)
            po_id = f"PO-{self.fy}-{i:06d}"
            st = self.vstyle[vendor["vendor_id"]]
            pool = self.sku_by_cat[vendor["primary_category"]] + self.sku_by_cat[st["secondary"]]
            lines = []
            for ln, sku in enumerate(rng.sample(pool, k), 1):
                qty = int(self._logu(*sku["qty"]))
                if ln == 1 and t in ("PARTIAL_CLEAN", "PARTIAL_EXCEED", "SPLIT") and qty < 4:
                    qty = rng.randint(4, 24)
                if ln == 1 and t in ("OVER_CLEAN", "OVER_EXCEED") and qty < 20:
                    qty = rng.randint(20, 240)
                price = money(sku["base_price"] * Decimal(str(round(rng.uniform(0.92, 1.08), 4))))
                line = self._line(sku, qty, price, sku["tax_code"])
                line |= {"po_line_id": f"POL-{po_id}-{ln:02d}", "po_id": po_id, "line_number": ln}
                lines.append(line)
            self.po_lines += lines
            self.pos.append({"po_id": po_id, "vendor_id": vendor["vendor_id"], "po_date": d,
                             "requester_id": req["employee_id"], "department": req["department"], "currency": "USD",
                             "line_count": k, "subtotal": sum((l["line_amount"] for l in lines), Decimal(0)),
                             "tax_amount": sum((l["tax_amount"] for l in lines), Decimal(0)),
                             "_type": t, "_lines": lines})
        for po in self.pos:
            po["total_amount"] = po["subtotal"] + po["tax_amount"]

    def receipts(self):
        rng = self.rng
        raw = []   # (date, po, {po_line_id: qty})
        for po in self.pos:
            t, lines = po["_type"], po["_lines"]
            if t in ("MISSING", "OPEN"):
                po["_grns"] = []
                continue
            d1 = po["po_date"] + timedelta(days=rng.randint(3, 30))
            full = {l["po_line_id"]: l["quantity"] for l in lines}
            l1, q1 = lines[0]["po_line_id"], lines[0]["quantity"]
            if t in ("PARTIAL_CLEAN", "PARTIAL_EXCEED"):
                full[l1] = min(q1 - 1, max(1, int(q1 * rng.uniform(0.3, 0.9))))
                gs = [(d1, full)]
            elif t == "OVER_CLEAN":
                full[l1] = q1 + rng.randint(1, max(1, q1 * 5 // 100))
                gs = [(d1, full)]
            elif t == "OVER_EXCEED":
                full[l1] = q1 + rng.randint(math.ceil(q1 * 0.10), math.ceil(q1 * 0.30))
                gs = [(d1, full)]
            elif t == "SPLIT":
                g1, g2 = {}, {}
                a = min(q1 - 1, max(1, int(q1 * rng.uniform(0.3, 0.8))))
                g1[l1], g2[l1] = a, q1 - a
                for l in lines[1:]:
                    r, q = rng.random(), l["quantity"]
                    if r < 0.5 or (r < 0.8 and q < 2):
                        g1[l["po_line_id"]] = q
                    elif r < 0.8:
                        h = rng.randint(1, q - 1)
                        g1[l["po_line_id"]], g2[l["po_line_id"]] = h, q - h
                    else:
                        g2[l["po_line_id"]] = q
                gs = [(d1, g1), (d1 + timedelta(days=rng.randint(5, 25)), g2)]
            else:   # FULL, CLOSED, UNINVOICED
                gs = [(d1, full)]
            po["_grns"] = []
            for d, q in gs:
                g = {"po": po, "receipt_date": d, "qty": q}
                po["_grns"].append(g)
                raw.append(g)

        raw.sort(key=lambda g: (g["receipt_date"], g["po"]["po_id"]))
        self.grns, self.grn_lines = [], []
        pol_by_id = {l["po_line_id"]: l for l in self.po_lines}
        cum = defaultdict(int)
        for i, g in enumerate(raw, 1):
            g["grn_id"] = f"GRN-{self.fy}-{i:06d}"
            self.grns.append({"grn_id": g["grn_id"], "po_id": g["po"]["po_id"], "receipt_date": g["receipt_date"],
                              "warehouse": rng.choice(catalog.WAREHOUSES), "status": "POSTED"})
            ln = 0
            for pol_id, q in g["qty"].items():
                if q <= 0:
                    continue
                ln += 1
                cum[pol_id] += q
                ordered = pol_by_id[pol_id]["quantity"]
                rtype = "PARTIAL" if cum[pol_id] < ordered else "FULL" if cum[pol_id] == ordered else "OVER"
                self.grn_lines.append({"grn_line_id": f"GRNL-{g['grn_id']}-{ln:02d}", "grn_id": g["grn_id"],
                                       "po_line_id": pol_id, "line_number": ln, "quantity_received": q,
                                       "receipt_type": rtype})

        # PO status + append-only lifecycle history derived from receipts.
        events = []
        for v in self.vendor_rows:
            events.append(("VENDOR", v["vendor_id"], None, "ACTIVE", v["effective_from"], "onboarded"))
        for po in self.pos:
            events.append(("PURCHASE_ORDER", po["po_id"], None, "OPEN", po["po_date"], "po issued"))
            state, got = "OPEN", defaultdict(int)
            for g in po["_grns"]:
                for pol_id, q in g["qty"].items():
                    got[pol_id] += q
                new = ("FULLY_RECEIVED" if all(got[l["po_line_id"]] >= l["quantity"] for l in po["_lines"])
                       else "PARTIALLY_RECEIVED")
                if new != state:
                    events.append(("PURCHASE_ORDER", po["po_id"], state, new, g["receipt_date"], g["grn_id"]))
                    state = new
            po["status"] = state
        self._events = events

    # ------------------------------------------------------------------ invoices
    def _draft(self, po, vendor, lines_src, inv_date, scenario, split=False):
        lines = [{"po_line": pol, **{k: pol[k] for k in ("sku", "description", "uom", "unit_price", "tax_code")},
                  "quantity": q} for pol, q in lines_src]
        return {"po": po, "vendor": vendor, "lines": lines, "invoice_date": inv_date,
                "received_at": self._received_at(inv_date), "channel": vendor["preferred_channel"], "scenario": scenario, "split": split, "detail": "", "dup_of": None,
                "stated_delta": Decimal(0)}

    def invoices(self):
        rng = self.rng
        drafts, pool = [], []
        pol_by_id = {l["po_line_id"]: l for l in self.po_lines}
        for po in self.pos:
            t, vendor = po["_type"], self.vendor_by_id[po["vendor_id"]]
            ordered = [(l, l["quantity"]) for l in po["_lines"]]
            if t == "MISSING":
                drafts.append(self._draft(po, vendor, ordered, po["po_date"] + timedelta(days=rng.randint(7, 40)),
                                          "MISSING_RECEIPT"))
                continue
            if t in ("OPEN", "UNINVOICED"):
                continue
            for g in po["_grns"]:
                billed = [(pol_by_id[k], q) for k, q in g["qty"].items() if q > 0]
                inv_date = g["receipt_date"] + timedelta(days=rng.randint(0, 7))
                if t == "CLOSED":
                    eff_to = g["receipt_date"] + timedelta(days=rng.randint(1, 3))
                    vendor["status"], vendor["effective_to"] = "CLOSED", eff_to
                    d = self._draft(po, vendor, billed, eff_to + timedelta(days=rng.randint(1, 10)), "CLOSED_VENDOR")
                    d["detail"] = f"vendor closed {eff_to}; invoice dated after closure"
                    drafts.append(d)
                elif t == "PARTIAL_CLEAN":
                    drafts.append(self._draft(po, vendor, billed, inv_date, "CLEAN_PARTIAL_DELIVERY"))
                elif t == "PARTIAL_EXCEED":
                    d = self._draft(po, vendor, ordered, inv_date, "QTY_EXCEEDS_RECEIPT")
                    d["detail"] = f"line 1 billed {ordered[0][1]}, received {g['qty'][ordered[0][0]['po_line_id']]}"
                    drafts.append(d)
                elif t == "OVER_CLEAN":
                    drafts.append(self._draft(po, vendor, billed, inv_date, "CLEAN_OVER_RECEIPT_WITHIN_TOL"))
                elif t == "OVER_EXCEED":
                    d = self._draft(po, vendor, billed, inv_date, "QTY_EXCEEDS_PO")
                    d["detail"] = f"line 1 billed {billed[0][1]} vs ordered {ordered[0][1]}"
                    drafts.append(d)
                else:   # FULL / SPLIT -> scenario assigned from the pool below
                    d = self._draft(po, vendor, billed, inv_date, None, split=(t == "SPLIT"))
                    drafts.append(d)
                    pool.append(d)

        rng.shuffle(pool)
        k = 0
        for scen in POOL_SCENARIOS:
            for d in pool[k:k + self.sc[scen]]:
                d["scenario"] = scen
                self._inject(d)
            k += self.sc[scen]
        clean_pool = pool[k:]
        for d in clean_pool:
            d["scenario"] = "CLEAN_SPLIT_DELIVERY" if d["split"] else "CLEAN_FULL"

        # Non-PO service invoices.
        services = self.sku_by_cat["SERVICES"]
        for _ in range(self.sc["CLEAN_NON_PO"]):
            vendor = rng.choice(self.active_vendors)
            src = []
            for sku in rng.sample(services, rng.choice([1, 1, 2, 3])):
                price = money(sku["base_price"] * Decimal(str(round(rng.uniform(0.9, 1.1), 4))))
                src.append(({**sku, "unit_price": price, "po_line_id": None}, int(self._logu(1, 12))))
            d = self._draft(None, vendor, src,
                            self._rand_date(date(self.fy, 2, 1), date(self.fy, 10, 15)), "CLEAN_NON_PO")
            for l in d["lines"]:
                l["po_line"] = None
            drafts.append(d)

        self._number(drafts)
        drafts += self._duplicates(clean_pool)
        self.drafts = drafts

    def _inject(self, d):
        rng, scen, lines = self.rng, d["scenario"], d["lines"]
        if scen == "PRICE_VARIANCE":
            for l in rng.sample(lines, 1 if len(lines) == 1 else rng.choice([1, 1, 2])):
                p = l["unit_price"]
                new = money(p * Decimal(str(round(1 + rng.uniform(0.03, 0.25), 4))))
                while (new - p) * 100 <= p * 2:
                    new += Decimal("0.01")
                l["unit_price"] = new
                d["detail"] += f"{l['sku']} price {p} -> {new} (+{(new - p) / p * 100:.1f}%); "
        elif scen == "CLEAN_PRICE_WITHIN_TOL":
            l = rng.choice(lines)
            p = l["unit_price"]
            f = rng.uniform(0.002, 0.019) if rng.random() < 0.7 else -rng.uniform(0.005, 0.06)
            new = money(p * Decimal(str(round(1 + f, 4))))
            if new == p or (new - p) * 100 > p * 2:
                new = p - Decimal("0.01")
            l["unit_price"] = new
            d["detail"] = f"{l['sku']} price {p} -> {new} ({(new - p) / p * 100:+.2f}%, within tolerance)"
        elif scen == "TAX_MISMATCH":
            l = rng.choice(lines)
            new = rng.choice([c for c in TAX_CODES if c != l["tax_code"]])
            d["detail"] = f"{l['sku']} tax {l['tax_code']} -> {new}"
            l["tax_code"] = new
        elif scen == "TOTAL_MISMATCH":
            d["stated_delta"] = Decimal(rng.choice([-1, 1])) * Decimal(str(round(rng.uniform(0.01, 0.08), 4)))
        elif scen == "DATE_BEFORE_PO":
            new = d["po"]["po_date"] - timedelta(days=rng.randint(2, 30))
            d["detail"] = f"invoice dated {new}, PO dated {d['po']['po_date']}"
            d["invoice_date"] = new

    def _number(self, drafts):
        """Vendor-issued invoice numbers: unique per vendor, increasing with invoice date."""
        by_vendor = defaultdict(list)
        for i, d in enumerate(drafts):
            by_vendor[d["vendor"]["vendor_id"]].append((d["invoice_date"], i, d))
        for vid, items in by_vendor.items():
            st = self.vstyle[vid]
            for _, _, d in sorted(items, key=lambda x: (x[0], x[1])):
                n = st["num_next"]
                st["num_next"] += self.rng.randint(1, 9)
                code4 = self.vendor_by_id[vid]["vendor_code"][:4]
                d["number"] = {"DASH": f"{code4}-{n}", "PLAIN": f"{n:06d}", "SLASH": f"INV/{self.fy}/{n:05d}"}[
                    st["num_style"]]

    def _duplicates(self, clean_pool):
        rng = self.rng
        n_resub, n_num = self.sc["DUPLICATE_RESUBMISSION"], self.sc["DUPLICATE_NUMBER"]
        originals = rng.sample(clean_pool, n_resub + n_num)
        out = []
        for j, o in enumerate(originals):
            d = {**o, "lines": copy.deepcopy([{k: v for k, v in l.items() if k != "po_line"} for l in o["lines"]]),
                 "dup_of": o, "split": False, "stated_delta": Decimal(0)}
            for l, ol in zip(d["lines"], o["lines"]):
                l["po_line"] = ol["po_line"]
            if j < n_resub:
                d["scenario"] = "DUPLICATE_RESUBMISSION"
                d["channel"] = rng.choice([c for c in LAYOUT_BY_CHANNEL if c != o["channel"]])
                d["received_at"] = o["received_at"] + timedelta(days=rng.randint(1, 14), minutes=rng.randint(0, 600))
                style = self.vstyle[o["vendor"]["vendor_id"]]["num_style"]
                if rng.random() < 0.5:   # same invoice, number keyed differently by the vendor's other system
                    d["number"] = {"DASH": o["number"].replace("-", ""), "PLAIN": f"#{o['number']}",
                                   "SLASH": o["number"].replace("/", "-")}[style]
                d["detail"] = f"resubmission of {o['number']} via {d['channel']} (number as '{d['number']}')"
            else:
                d["scenario"] = "DUPLICATE_NUMBER"
                d["invoice_date"] = o["invoice_date"] + timedelta(days=rng.randint(3, 12))
                d["received_at"] = max(self._received_at(d["invoice_date"]), o["received_at"] + timedelta(days=1))
                if len(d["lines"]) > 1 and rng.random() < 0.5:
                    d["lines"].pop()
                elif d["lines"][0]["quantity"] > 1:
                    d["lines"][0]["quantity"] -= rng.randint(1, max(1, d["lines"][0]["quantity"] // 3))
                else:
                    d["lines"][0]["unit_price"] = money(d["lines"][0]["unit_price"] * Decimal("0.9"))
                d["detail"] = f"number {o['number']} reused with different date/amount"
            out.append(d)
        return out

    # ------------------------------------------------------------------ finalise
    def finalise(self):
        """Assign IDs in intake order, derive totals, build ground truth and documents."""
        order = sorted(enumerate(self.drafts), key=lambda x: (x[1]["received_at"], x[0]))
        pol_id = lambda l: l["po_line"]["po_line_id"] if l["po_line"] else None
        self.invoice_rows, self.invoice_line_rows, self.ground_truth, self.documents = [], [], [], []
        ap = self.cfg["approval_policy"]
        routing = self.cfg["routing"]
        for seq, (_, d) in enumerate(order, 1):
            v, po = d["vendor"], d["po"]
            inv_id = f"INV-{v['vendor_code']}-{self.fy}-{seq:06d}"
            d["invoice_id"] = inv_id
            lines = []
            for ln, l in enumerate(d["lines"], 1):
                row = self._line(l, l["quantity"], l["unit_price"], l["tax_code"])
                row |= {"invoice_line_id": f"INVL-{inv_id}-{ln:02d}", "invoice_id": inv_id, "line_number": ln,
                        "po_line_id": pol_id(l)}
                lines.append(row)
            sub = sum((l["line_amount"] for l in lines), Decimal(0))
            tax = sum((l["tax_amount"] for l in lines), Decimal(0))
            grand = sub + tax
            stated = money(grand * (1 + d["stated_delta"])) if d["stated_delta"] else grand
            if d["scenario"] == "TOTAL_MISMATCH":
                if abs(stated - grand) < 1:
                    stated = grand + Decimal("1.00")
                d["detail"] = f"stated {stated} vs line sum {grand}"
            terms = v["payment_terms"]
            inv = {"invoice_id": inv_id, "document_id": f"DOC-{self.fy}-{seq:06d}", "vendor_id": v["vendor_id"],
                   "po_id": po["po_id"] if po else None, "vendor_invoice_number": d["number"],
                   "invoice_date": d["invoice_date"], "received_at": d["received_at"], "channel": d["channel"],
                   "currency": "USD", "payment_terms": terms,
                   "due_date": d["invoice_date"] + timedelta(days=self.terms[terms]), "line_count": len(lines),
                   "subtotal": sub, "tax_amount": tax, "grand_total": grand, "stated_total": stated}
            self.invoice_rows.append(inv)
            self.invoice_line_rows += lines

            issue, exc, match, edge = SCENARIOS[d["scenario"]]
            path = None
            if exc is None:
                if grand <= Decimal(ap["auto_approve_max"]) and po:
                    path = "AUTO"
                else:
                    path = "L1" if grand <= Decimal(ap["l1_max"]) else "L1>L2"
            self.ground_truth.append({
                "document_id": inv["document_id"], "invoice_id": inv_id, "scenario": d["scenario"],
                "issue_type": issue, "edge_case": edge, "expected_primary_exception": exc,
                "expected_match_status": match, "expected_final_status": "PAYMENT_READY" if exc is None else "ON_HOLD",
                "expected_payment_ready": exc is None, "expected_route_queue": routing[exc]["queue"] if exc else None,
                "expected_approval_path": path,
                "duplicate_of_invoice_id": d["dup_of"]["invoice_id"] if d["dup_of"] else None,
                "injected_detail": d["detail"].strip("; ") or None})
            text = render(inv, lines, v, self.vstyle[v["vendor_id"]]["date_style"], self.cfg["buyer_name"])
            self.documents.append({"document_id": inv["document_id"], "file_name": f"{inv['document_id']}.txt",
                                   "channel": d["channel"], "received_at": d["received_at"],
                                   "sha256": sha256_text(text), "bytes": len(text.encode()), "_text": text})

        self.lifecycle = []
        for v in self.vendor_rows:
            if v["status"] == "CLOSED":
                self._events.append(("VENDOR", v["vendor_id"], "ACTIVE", "CLOSED", v["effective_to"], "vendor closed"))
        for i, (et, eid, fs, ts, d, det) in enumerate(sorted(self._events, key=lambda e: (e[4], e[0], e[1])), 1):
            self.lifecycle.append({"event_id": f"LEV-{i:07d}", "entity_type": et, "entity_id": eid,
                                   "from_state": fs, "to_state": ts, "event_date": d, "detail": det})

    def run(self) -> dict:
        self.employees()
        self.skus()
        self.vendors()
        self.purchase_orders()
        self.receipts()
        self.invoices()
        self.finalise()
        strip = lambda rows: [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
        return {
            "tables": {
                "employee": self.employees_rows, "vendor": self.vendor_rows, "purchase_order": strip(self.pos),
                "purchase_order_line": self.po_lines, "goods_receipt": self.grns, "goods_receipt_line": self.grn_lines,
                "lifecycle_event": self.lifecycle, "invoice": self.invoice_rows, "invoice_line": self.invoice_line_rows,
            },
            "ground_truth": self.ground_truth,
            "documents": self.documents,
            "plan": {"volumes": self.n, "scenario_counts": self.sc, "po_fulfilment_plan": self.po_plan},
        }

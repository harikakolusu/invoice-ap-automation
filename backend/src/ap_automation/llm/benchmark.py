"""LLM extraction benchmark: rules vs Claude on documents the rule parser has never seen.

Takes N invoices from a dataset, re-renders each as a free-form letter (generator.documents.render_unstructured),
extracts with both methods and scores every field against source_truth. Writes reports/llm_benchmark.json.
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..common import read_csv, write_json
from ..generator.documents import render_unstructured
from ..pipeline.extraction import extract
from .client import Claude, LLMError
from .extractor import llm_extract

HEADER = ("vendor_tax_id", "vendor_invoice_number", "invoice_date", "po_number", "currency", "payment_terms",
          "subtotal", "tax_amount", "stated_total")
LINE = ("sku", "quantity", "unit_price", "tax_code", "line_amount")


def _typed(inv: dict, lines: list[dict]) -> tuple[dict, list[dict]]:
    i = {**inv, "invoice_date": date.fromisoformat(inv["invoice_date"]),
         **{k: Decimal(inv[k]) for k in ("subtotal", "tax_amount", "stated_total")}, "po_id": inv["po_id"] or None}
    ls = [{**l, "quantity": int(l["quantity"]), "unit_price": Decimal(l["unit_price"]),
           "line_amount": Decimal(l["line_amount"])} for l in lines]
    return i, ls


def score(ex: dict, inv: dict, lines: list[dict], vendor: dict) -> dict:
    truth = {"vendor_tax_id": vendor["tax_id"], "vendor_invoice_number": inv["vendor_invoice_number"],
             "invoice_date": inv["invoice_date"], "po_number": inv["po_id"], "currency": inv["currency"],
             "payment_terms": inv["payment_terms"], "subtotal": inv["subtotal"], "tax_amount": inv["tax_amount"],
             "stated_total": inv["stated_total"]}
    hits = {f: ex.get(f) == truth[f] for f in HEADER}
    got = {l["line_number"]: l for l in ex.get("lines", [])}
    for f in LINE:
        hits[f"line.{f}"] = all(got.get(int(l["line_number"]), {}).get(f) == l[f] for l in lines) and \
            len(got) == len(lines)
    return hits


def run_benchmark(data_dir: Path, n: int, llm: Claude, seed: int = 7) -> dict:
    d = Path(data_dir)
    invs = read_csv(d / "source_truth" / "invoice.csv")
    by_inv = defaultdict(list)
    for l in read_csv(d / "source_truth" / "invoice_line.csv"):
        by_inv[l["invoice_id"]].append(l)
    vendors = {v["vendor_id"]: v for v in read_csv(d / "master" / "vendor.csv")}
    sample = random.Random(seed).sample(invs, min(n, len(invs)))

    totals = {"rules": defaultdict(int), "llm": defaultdict(int)}
    exact = {"rules": 0, "llm": 0}
    docs, tokens, errors = [], {"input": 0, "output": 0}, []
    for raw in sample:
        inv, lines = _typed(raw, by_inv[raw["invoice_id"]])
        v = vendors[inv["vendor_id"]]
        text = render_unstructured(inv, lines, v)
        res = {"rules": score(extract(text), inv, lines, v)}
        try:
            ai = llm_extract(text, llm)
            res["llm"] = score(ai, inv, lines, v)
            tokens["input"] += ai["llm_usage"]["input_tokens"] or 0
            tokens["output"] += ai["llm_usage"]["output_tokens"] or 0
        except LLMError as e:
            errors.append({"invoice_id": inv["invoice_id"], "error": str(e)})
            res["llm"] = {f: False for f in res["rules"]}
        for m in ("rules", "llm"):
            for f, hit in res[m].items():
                totals[m][f] += hit
            exact[m] += all(res[m].values())
        docs.append({"invoice_id": inv["invoice_id"], "rules_exact": all(res["rules"].values()),
                     "llm_exact": all(res["llm"].values()),
                     "llm_missed": [f for f, h in res["llm"].items() if not h]})
    k = len(sample)
    out = {"documents": k, "model": llm.model, "document_style": "free-form letter (unseen by rule parser)",
           "document_exact_match": {m: round(exact[m] / k, 4) for m in exact},
           "field_accuracy": {m: {f: round(c / k, 4) for f, c in totals[m].items()} for m in totals},
           "tokens": tokens, "errors": errors, "per_document": docs}
    write_json(d / "reports" / "llm_benchmark.json", out)
    return out

"""Evaluation: pipeline outputs vs source truth and ground truth, plus operational KPIs.

Measures the acceptance criteria:
  1. extracted fields match source            -> field-level extraction accuracy
  2. line arithmetic and tax reconcile        -> validation arithmetic checks + TOTAL_MISMATCH recall
  3. duplicate detection flags correct pair   -> duplicate pair accuracy, precision, recall
  4. 3-way match + approval agree with policy -> match_status / primary exception / approval path accuracy
  5. no blocked invoice is payment-ready      -> unsafe releases == 0
"""
from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from .common import read_csv, write_json


def _prf(gold, pred, labels):
    out = {}
    for c in labels:
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        pr = tp / (tp + fp) if tp + fp else 1.0
        rc = tp / (tp + fn) if tp + fn else 1.0
        out[c] = {"precision": round(pr, 4), "recall": round(rc, 4),
                  "f1": round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0, "support": tp + fn}
    return out


def _acc(pairs):
    pairs = list(pairs)
    return round(sum(a == b for a, b in pairs) / len(pairs), 4) if pairs else 1.0


def evaluate(data_dir: Path, cfg: dict) -> dict:
    d = Path(data_dir)
    src = {r["document_id"]: r for r in read_csv(d / "source_truth" / "invoice.csv")}
    src_lines = defaultdict(list)
    for l in read_csv(d / "source_truth" / "invoice_line.csv"):
        src_lines[l["invoice_id"]].append(l)
    gt = {r["document_id"]: r for r in read_csv(d / "ground_truth" / "ground_truth.csv")}
    ext = {r["document_id"]: r for r in read_csv(d / "pipeline_output" / "extracted_invoice.csv")}
    ext_lines = defaultdict(list)
    for l in read_csv(d / "pipeline_output" / "extracted_invoice_line.csv"):
        ext_lines[l["document_id"]].append(l)
    dec = {r["document_id"]: r for r in read_csv(d / "pipeline_output" / "invoice_decision.csv")}
    exc = read_csv(d / "pipeline_output" / "invoice_exception.csv")
    events = read_csv(d / "pipeline_output" / "invoice_event.csv")
    docs = sorted(src)

    # 1. extraction accuracy (field level + document level)
    num = lambda v: Decimal(v) if v else None
    hdr = {"invoice_id": lambda s, e, k: dec[k]["invoice_id"] == s["invoice_id"],
           "vendor": lambda s, e, k: dec[k]["vendor_id"] == s["vendor_id"],
           "vendor_invoice_number": lambda s, e, k: e["vendor_invoice_number"] == s["vendor_invoice_number"],
           "invoice_date": lambda s, e, k: e["invoice_date"] == s["invoice_date"],
           "po_number": lambda s, e, k: e["po_number"] == s["po_id"],
           "currency": lambda s, e, k: e["currency"] == s["currency"],
           "payment_terms": lambda s, e, k: e["payment_terms"] == s["payment_terms"],
           "subtotal": lambda s, e, k: num(e["subtotal"]) == num(s["subtotal"]),
           "tax_amount": lambda s, e, k: num(e["tax_amount"]) == num(s["tax_amount"]),
           "stated_total": lambda s, e, k: num(e["stated_total"]) == num(s["stated_total"]),
           "line_count": lambda s, e, k: int(e["line_count"]) == int(s["line_count"])}
    field_hits = {f: 0 for f in hdr}
    line_fields = ("sku", "description", "quantity", "unit_price", "tax_code", "line_amount")
    line_hits, n_lines, exact_docs = Counter(), 0, 0
    by_layout = defaultdict(lambda: [0, 0])
    for k in docs:
        s, e = src[k], ext[k]
        ok = True
        for f, fn in hdr.items():
            hit = fn(s, e, k)
            field_hits[f] += hit
            ok &= hit
        sl, el = src_lines[s["invoice_id"]], {int(l["line_number"]): l for l in ext_lines[k]}
        for l in sl:
            n_lines += 1
            x = el.get(int(l["line_number"]), {})
            for f in line_fields:
                hit = f in x and (num(x[f]) == num(l[f]) if f in ("unit_price", "line_amount") else x[f] == l[f])
                line_hits[f] += hit
                ok &= hit
        exact_docs += ok
        by_layout[e["layout"]][0] += ok
        by_layout[e["layout"]][1] += 1
    n = len(docs)
    extraction = {
        "documents": n, "document_exact_match_rate": round(exact_docs / n, 4),
        "header_field_accuracy": {f: round(h / n, 4) for f, h in field_hits.items()},
        "line_field_accuracy": {f: round(line_hits[f] / n_lines, 4) for f in line_fields},
        "lines_evaluated": n_lines,
        "exact_match_by_layout": {k: {"documents": v[1], "exact_match_rate": round(v[0] / v[1], 4)}
                                  for k, v in sorted(by_layout.items())}}

    # 3/4. decisions vs ground truth
    gold_exc = [gt[k]["expected_primary_exception"] or "NONE" for k in docs]
    pred_exc = [dec[k]["primary_exception"] or "NONE" for k in docs]
    labels = sorted(set(gold_exc) | set(pred_exc))
    confusion = {g: dict(Counter(p for gg, p in zip(gold_exc, pred_exc) if gg == g)) for g in labels}
    per_class = _prf(gold_exc, pred_exc, labels)
    approval_pairs = [(gt[k]["expected_approval_path"], dec[k]["approval_path"]) for k in docs
                      if gt[k]["expected_approval_path"]]
    scenario_acc = defaultdict(lambda: [0, 0])
    for k in docs:
        s = scenario_acc[gt[k]["scenario"]]
        s[0] += (dec[k]["primary_exception"] == gt[k]["expected_primary_exception"]
                 and dec[k]["match_status"] == gt[k]["expected_match_status"]
                 and dec[k]["final_status"] == gt[k]["expected_final_status"])
        s[1] += 1
    decisions = {
        "primary_exception_accuracy": _acc(zip(gold_exc, pred_exc)),
        "macro_f1": round(statistics.mean(v["f1"] for v in per_class.values()), 4),
        "per_exception": per_class, "confusion_matrix_gold_to_pred": confusion,
        "match_status_accuracy": _acc((gt[k]["expected_match_status"], dec[k]["match_status"]) for k in docs),
        "final_status_accuracy": _acc((gt[k]["expected_final_status"], dec[k]["final_status"]) for k in docs),
        "route_queue_accuracy": _acc((gt[k]["expected_route_queue"], dec[k]["route_queue"]) for k in docs),
        "approval_path_accuracy": _acc(approval_pairs),
        "accuracy_by_scenario": {s: {"invoices": v[1], "fully_correct_rate": round(v[0] / v[1], 4)}
                                 for s, v in sorted(scenario_acc.items())}}

    gold_dup = {k for k in docs if gt[k]["issue_type"] == "DUPLICATE"}
    pred_dup = {k for k in docs if dec[k]["primary_exception"] == "DUPLICATE_INVOICE"}
    pair_ok = sum(dec[k]["duplicate_of_invoice_id"] == gt[k]["duplicate_of_invoice_id"] for k in gold_dup)
    duplicates = {"labelled_duplicates": len(gold_dup), "flagged": len(pred_dup),
                  "precision": round(len(gold_dup & pred_dup) / len(pred_dup), 4) if pred_dup else 1.0,
                  "recall": round(len(gold_dup & pred_dup) / len(gold_dup), 4) if gold_dup else 1.0,
                  "correct_pair_rate": round(pair_ok / len(gold_dup), 4) if gold_dup else 1.0,
                  "by_variant": {s: sum(gt[k]["scenario"] == s and k in pred_dup for k in gold_dup)
                                 for s in ("DUPLICATE_RESUBMISSION", "DUPLICATE_NUMBER")}}

    # 5. payment safety
    unsafe = [dec[k]["invoice_id"] for k in docs if dec[k]["payment_ready"] == "true"
              and gt[k]["expected_payment_ready"] != "true"]
    false_hold = [dec[k]["invoice_id"] for k in docs if dec[k]["payment_ready"] != "true"
                  and gt[k]["expected_payment_ready"] == "true"]
    safety = {"unsafe_releases_blocked_but_payment_ready": len(unsafe), "false_holds_clean_but_blocked": len(false_hold),
              "sample_unsafe": unsafe[:5], "sample_false_holds": false_hold[:5]}

    # operational KPIs
    total = lambda rows: float(sum(Decimal(r["computed_total"]) for r in rows))
    ready = [r for r in dec.values() if r["payment_ready"] == "true"]
    held = [r for r in dec.values() if r["payment_ready"] != "true"]
    first_ts, ready_ts = {}, {}
    for e in events:
        first_ts.setdefault(e["invoice_id"], datetime.fromisoformat(e["event_ts"]))
        if e["to_state"] == "PAYMENT_READY":
            ready_ts[e["invoice_id"]] = datetime.fromisoformat(e["event_ts"])
    cycle = [(ready_ts[i] - first_ts[i]).total_seconds() / 3600 for i in ready_ts]
    queue = defaultdict(lambda: {"invoices": 0, "value_usd": 0.0})
    for r in held:
        queue[r["route_queue"]]["invoices"] += 1
        queue[r["route_queue"]]["value_usd"] += float(r["computed_total"])
    amounts = sorted(float(s["grand_total"]) for s in src.values())
    q = statistics.quantiles(amounts, n=20)
    kpis = {
        "invoices_processed": n, "payment_ready": len(ready), "on_hold": len(held),
        "payment_ready_rate": round(len(ready) / n, 4),
        "touchless_rate_auto_approved": round(sum(r["approval_path"] == "AUTO" for r in ready) / n, 4),
        "exception_rate": round(len(held) / n, 4),
        "value_payment_ready_usd": round(total(ready), 2), "value_on_hold_usd": round(total(held), 2),
        "exceptions_raised_total": len(exc), "exceptions_by_code": dict(Counter(e["exception_code"] for e in exc)),
        "primary_exceptions_by_code": dict(Counter(r["primary_exception"] for r in held)),
        "queue_workload": {k: {"invoices": v["invoices"], "value_usd": round(v["value_usd"], 2)}
                           for k, v in sorted(queue.items())},
        "approval_path_mix": dict(Counter(r["approval_path"] for r in ready)),
        "cycle_time_hours_to_payment_ready": {"mean": round(statistics.mean(cycle), 2) if cycle else None,
                                              "median": round(statistics.median(cycle), 2) if cycle else None,
                                              "p95": round(statistics.quantiles(cycle, n=20)[-1], 2)
                                              if len(cycle) > 1 else None},
        "invoice_value_usd": {"min": amounts[0], "p05": round(q[0], 2), "median": round(statistics.median(amounts), 2),
                              "p95": round(q[-1], 2), "max": amounts[-1]},
        "channel_mix": dict(Counter(s["channel"] for s in src.values())),
        "issue_mix_actual": {k: round(v / n, 4) for k, v in Counter(g["issue_type"] for g in gt.values()).items()},
        "issue_mix_target": cfg["issue_mix"],
    }

    acceptance = [
        ("Extracted fields match source", extraction["document_exact_match_rate"] == 1.0,
         f"document exact match {extraction['document_exact_match_rate']:.2%}"),
        ("Line arithmetic and tax reconcile (mismatches caught)", per_class.get("TOTAL_MISMATCH", {}).get("recall", 1) == 1
         and per_class.get("TAX_MISMATCH", {}).get("recall", 1) == 1,
         f"TOTAL_MISMATCH recall {per_class.get('TOTAL_MISMATCH', {}).get('recall')}, "
         f"TAX_MISMATCH recall {per_class.get('TAX_MISMATCH', {}).get('recall')}"),
        ("Duplicate detection flags the correct pair", duplicates["correct_pair_rate"] == 1.0
         and duplicates["precision"] == 1.0, f"pair accuracy {duplicates['correct_pair_rate']:.2%}, "
         f"precision {duplicates['precision']:.2%}"),
        ("Three-way match and approval outcome agree with policy",
         decisions["match_status_accuracy"] == 1.0 and decisions["primary_exception_accuracy"] == 1.0
         and decisions["approval_path_accuracy"] == 1.0,
         f"match {decisions['match_status_accuracy']:.2%}, exception {decisions['primary_exception_accuracy']:.2%}, "
         f"approval {decisions['approval_path_accuracy']:.2%}"),
        ("No blocked invoice is marked payment-ready", len(unsafe) == 0, f"unsafe releases = {len(unsafe)}"),
    ]
    res = {"acceptance_criteria": [{"criterion": c, "status": "PASS" if ok else "FAIL", "evidence": ev}
                                   for c, ok, ev in acceptance],
           "extraction": extraction, "decisions": decisions, "duplicates": duplicates,
           "payment_safety": safety, "kpis": kpis}
    write_json(d / "reports" / "evaluation_metrics.json", res)
    return res

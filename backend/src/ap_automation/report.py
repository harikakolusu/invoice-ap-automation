"""Self-contained HTML run report (no external assets): KPIs, acceptance, exceptions, accuracy, validation."""
from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path

from .common import read_csv, write_text

CSS = """
:root{--bg:#f7f8fa;--card:#fff;--ink:#1c2430;--mute:#5f6b7a;--line:#e3e7ec;--ok:#1a7f4b;--bad:#b42318;--acc:#2f5bd3;--bar:#c9d6f5}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--card:#1b2129;--ink:#e6eaf0;--mute:#9aa6b5;--line:#2b333d;--ok:#4cc38a;--bad:#ff7b72;--acc:#7aa2ff;--bar:#2c3d66}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.sub{color:var(--mute)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}.k{color:var(--mute);font-size:12px}
.v{font-size:22px;font-weight:600;margin-top:2px}.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%}th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}
th{font-size:12px;color:var(--mute);font-weight:600}td.n{text-align:right;font-variant-numeric:tabular-nums}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}
.bar{height:10px;background:var(--bar);border-radius:3px}.bar>span{display:block;height:100%;background:var(--acc);border-radius:3px}
details summary{cursor:pointer;margin:8px 0;color:var(--acc)}code{font-size:12px}
"""


def _t(headers, rows, num=()):
    h = "".join(f"<th>{html.escape(x)}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td class='{'n' if i in num else ''}'>{c}</td>" for i, c in enumerate(r)) + "</tr>"
                for r in rows)
    return f"<div class='wrap'><table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table></div>"


def _st(s):
    return f"<span class='{'pass' if s == 'PASS' else 'fail'}'>{s}</span>"


def _bar(frac):
    return f"<div class='bar' style='width:160px'><span style='width:{min(frac, 1) * 100:.1f}%'></span></div>"


def build_report(data_dir: Path) -> Path:
    d = Path(data_dir)
    ev = json.loads((d / "reports" / "evaluation_metrics.json").read_text(encoding="utf-8"))
    va = json.loads((d / "reports" / "validation_summary.json").read_text(encoding="utf-8"))
    plan = json.loads((d / "reports" / "generation_plan.json").read_text(encoding="utf-8"))
    k, x, dc, du = ev["kpis"], ev["extraction"], ev["decisions"], ev["duplicates"]
    passed = sum(a["status"] == "PASS" for a in ev["acceptance_criteria"])

    cards = [("Invoices processed", f"{k['invoices_processed']:,}"),
             ("Payment-ready", f"{k['payment_ready']:,} ({k['payment_ready_rate']:.1%})"),
             ("Touchless (auto-approved)", f"{k['touchless_rate_auto_approved']:.1%}"),
             ("Value payment-ready", f"${k['value_payment_ready_usd']:,.0f}"),
             ("Value on hold", f"${k['value_on_hold_usd']:,.0f}"),
             ("Unsafe releases", f"{ev['payment_safety']['unsafe_releases_blocked_but_payment_ready']}"),
             ("Extraction exact-match", f"{x['document_exact_match_rate']:.1%}"),
             ("Primary exception accuracy", f"{dc['primary_exception_accuracy']:.1%}"),
             ("Median hours to payment-ready", f"{k['cycle_time_hours_to_payment_ready']['median']}")]
    s = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
         f"content='width=device-width,initial-scale=1'><title>AP Automation Run</title><style>{CSS}</style></head>"
         f"<body><main><h1>Invoice-to-Pay Automation: run report</h1>"
         f"<div class='sub'>seed {plan['seed']} · scale {plan['scale']} · validation {_st(va['status'])} "
         f"({va['checks_run']} checks) · acceptance {passed}/{len(ev['acceptance_criteria'])}</div>",
         "<div class='grid'>" + "".join(f"<div class='card'><div class='k'>{a}</div><div class='v'>{b}</div></div>"
                                       for a, b in cards) + "</div>"]

    s.append("<h2>Acceptance criteria</h2>")
    s.append(_t(["Criterion", "Status", "Evidence"],
                [(html.escape(a["criterion"]), _st(a["status"]), html.escape(a["evidence"]))
                 for a in ev["acceptance_criteria"]]))

    s.append("<h2>Issue mix: target vs generated</h2>")
    s.append(_t(["Issue type", "Target", "Actual", ""],
                [(i, f"{t:.0%}", f"{k['issue_mix_actual'].get(i, 0):.1%}", _bar(k["issue_mix_actual"].get(i, 0) / 0.7))
                 for i, t in k["issue_mix_target"].items()], num=(1, 2)))

    s.append("<h2>Exception routing: open work by queue</h2>")
    mx = max((v["invoices"] for v in k["queue_workload"].values()), default=1)
    s.append(_t(["Queue", "Invoices on hold", "Value (USD)", ""],
                [(q, v["invoices"], f"{v['value_usd']:,.2f}", _bar(v["invoices"] / mx))
                 for q, v in k["queue_workload"].items()], num=(1, 2)))

    s.append("<h2>Exception detection vs ground truth</h2>")
    s.append(_t(["Primary exception", "Precision", "Recall", "F1", "Support"],
                [(c, f"{m['precision']:.3f}", f"{m['recall']:.3f}", f"{m['f1']:.3f}", m["support"])
                 for c, m in dc["per_exception"].items()], num=(1, 2, 3, 4)))
    labels = list(dc["confusion_matrix_gold_to_pred"])
    s.append("<details><summary>Confusion matrix (rows = expected, columns = predicted)</summary>" +
             _t(["expected \\ predicted"] + labels,
                [[g] + [dc["confusion_matrix_gold_to_pred"][g].get(p, "") for p in labels] for g in labels],
                num=tuple(range(1, len(labels) + 1))) + "</details>")
    s.append(_t(["Decision metric", "Value"],
                [("Match status accuracy", f"{dc['match_status_accuracy']:.2%}"),
                 ("Final status accuracy", f"{dc['final_status_accuracy']:.2%}"),
                 ("Route queue accuracy", f"{dc['route_queue_accuracy']:.2%}"),
                 ("Approval path accuracy", f"{dc['approval_path_accuracy']:.2%}"),
                 ("Duplicate pair accuracy", f"{du['correct_pair_rate']:.2%} ({du['labelled_duplicates']} pairs)"),
                 ("Duplicate precision / recall", f"{du['precision']:.2%} / {du['recall']:.2%}")]))

    s.append("<h2>Accuracy by scenario</h2>")
    s.append(_t(["Scenario", "Invoices", "Fully correct"],
                [(sc, v["invoices"], f"{v['fully_correct_rate']:.1%}") for sc, v in dc["accuracy_by_scenario"].items()],
                num=(1, 2)))

    s.append("<h2>Extraction accuracy</h2>")
    s.append(_t(["Header field", "Accuracy"], [(f, f"{a:.2%}") for f, a in x["header_field_accuracy"].items()], num=(1,)))
    s.append("<br>" + _t(["Line field", "Accuracy"], [(f, f"{a:.2%}") for f, a in x["line_field_accuracy"].items()],
                         num=(1,)))
    s.append("<br>" + _t(["Layout", "Documents", "Exact match"],
                         [(l, v["documents"], f"{v['exact_match_rate']:.2%}") for l, v in x["exact_match_by_layout"].items()],
                         num=(1, 2)))

    # Traceability: one example per exception type, with its event trail.
    exc = read_csv(d / "pipeline_output" / "invoice_exception.csv")
    events = defaultdict(list)
    for e in read_csv(d / "pipeline_output" / "invoice_event.csv"):
        events[e["invoice_id"]].append(e)
    seen, rows = set(), []
    for e in exc:
        if e["is_primary"] == "true" and e["exception_code"] not in seen:
            seen.add(e["exception_code"])
            trail = " → ".join(ev_["to_state"] for ev_ in events[e["invoice_id"]])
            rows.append((e["exception_code"], f"<code>{e['invoice_id']}</code>", html.escape(e["detail"]),
                         e["queue"], e["assigned_to"], html.escape(trail)))
    s.append("<h2>Traceability: one example per exception</h2>")
    s.append(_t(["Exception", "Invoice", "Why", "Queue", "Owner", "State trail"], rows))

    s.append("<h2>Validation checks</h2>")
    s.append(f"<details><summary>{va['checks_run']} checks, {va['checks_failed']} failed. Expand</summary>" +
             _t(["Category", "Check", "Status", "Violations", "Labelled anomalies"],
                [(c["category"], html.escape(c["check"]), _st(c["status"]), c["violations"],
                  c["labelled_anomalies_allowed"]) for c in va["checks"]], num=(3, 4)) + "</details>")
    s.append("</main></body></html>")
    out = d / "reports" / "report.html"
    write_text(out, "\n".join(s))
    return out

# Invoice-to-Pay Automation

End-to-end accounts-payable automation: **invoice intake → field extraction → PO/receipt three-way match →
exception routing → approval → payment readiness**, built on a fully synthetic, reproducible procure-to-pay
dataset with separate ground truth and measurable evaluation.

| Layer | Stack | What it does |
|---|---|---|
| `backend/` engine | Python 3.10+ standard library only | data generator, AP pipeline, validation, evaluation, SQL/JSON export |
| `backend/` API | FastAPI | REST API over the processed data: dashboard, invoices, exception queues, intake preview, re-run |
| `backend/` AI | **Claude (`claude-opus-5-5`) via the Anthropic SDK** | LLM extraction fallback for unreadable documents, AI exception copilot, rules-vs-LLM benchmark |
| `frontend/` | React 18 + Vite 7 + React Router 7 | operations UI: dashboard, invoice list and audit trail, AI copilot, exception queues, AI intake, validation |

## AI / LLM: where Claude is used

**Rules-first, LLM-assisted.** Deterministic controls decide every hold, approval and payment. Claude does the
two jobs rules are bad at:

| | What Claude does | Guardrail |
|---|---|---|
| **1. Hybrid extraction** | Reads invoices the rule parser can't (free-form letters, new vendor layouts, OCR text) and returns fields as JSON-schema-validated output | Called only when rule confidence < 1; its output passes the same arithmetic, duplicate and three-way-match controls; told to copy, never "fix", values |
| **2. Exception copilot** | Explains why an invoice is on hold, the root cause and next action, and drafts the email to the vendor / requester / vendor-master admin | Advisory only, can't approve or pay; never sees ground truth; document text treated as untrusted data |
| **3. AI intake preview** | Paste any document in the UI; rules read known layouts, Claude reads the rest | Read-only |
| **4. LLM benchmark** | `llm-benchmark` scores rules vs Claude field by field on unseen free-form documents, with token cost | Uses `source_truth` as the answer key |

Built with the official `anthropic` SDK: structured outputs (`output_config.format: json_schema`), explicit effort,
server-side refusal fallbacks, typed error handling. Without an API key everything else still runs and the UI shows
"AI: not configured (rules only)". Details, prompts and guardrails: [docs/llm.md](docs/llm.md).

```bash
cd backend && cp .env.example .env     # set ANTHROPIC_API_KEY
python -m ap_automation llm-status
python -m ap_automation llm-benchmark --data data/starter --n 20
```

## Quick start

```bash
# 1. backend: build the data and start the API on http://127.0.0.1:8000  (Swagger docs at /docs)
cd backend
pip install -r requirements.txt
python -m pip install -e .
python -m ap_automation run-all --preset full
python -m ap_automation serve --reload
```

```bash
# 2. frontend (second terminal): dev server on http://localhost:5173, proxies /api to :8000
cd frontend
npm install
npm run dev
```

One-process option: `npm run build` in `frontend/`, then `python -m ap_automation serve` serves the built UI
at http://127.0.0.1:8000 as well. The engine alone needs nothing installed:
`cd backend && PYTHONPATH=src python -m ap_automation run-all --preset full`, then open
`backend/data/full/reports/report.html`.

---

## Results (full dataset, seed 20261022)

| | |
|---|---|
| Volumes | 300 vendors · 1,500 POs · 2,200 PO lines · 1,800 receipts · 2,000 invoices (exact) |
| Issue mix | 70 % clean · 10 % price variance · 8 % qty mismatch · 5 % duplicates · 4 % missing receipt · 3 % tax/vendor (exact) |
| Validation | **87 / 87 checks PASS** (PK, FK, enums, formats, joins, dates, arithmetic, lifecycle, duplicates, leakage, payment safety, SQLite FK check) |
| Extraction | 100 % document exact match across 3 layouts (CLASSIC 622, EMAIL 1,079, EDI 299 docs) |
| Decisions | primary exception, match status, routing queue and approval path all 100 % vs ground truth |
| Duplicates | 100 / 100 flagged, 100 % correct pair, 0 false positives |
| Payment safety | **0 blocked invoices released**, 0 clean invoices wrongly held |
| Business outcome | 1,400 invoices ($9.27 M) payment-ready · 600 ($5.58 M) on hold in 5 queues · 51.6 % touchless |
| Reproducibility | Two regenerations with the same seed are byte-identical (every CSV/JSON/SQL/report file + all 2,000 documents) |
| Runtime | ~20 s for the full run on a laptop |

### Acceptance criteria

| Criterion (from the brief) | How it is proven | Result |
|---|---|---|
| Extracted fields match source | `evaluation.extraction`: 11 header + 6 line fields vs `source_truth/` | PASS |
| Line arithmetic and tax reconcile | validation arithmetic checks + TOTAL_MISMATCH / TAX_MISMATCH recall = 1.0 | PASS |
| Duplicate detection flags the correct pair | `duplicate_of_invoice_id` vs ground truth, precision and pair accuracy | PASS |
| Three-way match and approval agree with policy | match status, primary exception, approval path accuracy | PASS |
| No blocked invoice is payment-ready | validation `payment_safety` + evaluation `unsafe_releases` = 0 | PASS |

> Why 100 %? The extractor parses the same synthetic templates the generator writes, so perfect scores are the
> expected baseline. The value is the harness: the same metrics will show exactly where an OCR/LLM extractor or a
> policy change loses accuracy. Tests prove the checks bite: corrupting a foreign key, a line amount, a payment
> flag or adding an unlabelled duplicate each makes validation FAIL (`tests/test_end_to_end.py`).

---

## Project structure

```
invoice-ap-automation/
├── README.md
├── docs/
│   ├── architecture.md                 # workflow diagram, information barrier, API, code map, design choices
│   ├── llm.md                          # where and how Claude is used, guardrails, benchmark
│   ├── business_rules.md               # every rule, threshold, precedence, routing, approval, generation logic
│   └── data_dictionary.md              # generated: every field's type, required, allowed values, unit, rule + ERD
│
├── backend/                            # Python: engine + REST API
│   ├── pyproject.toml                  # package, CLI entry point, optional [api] / [dev] extras, pytest config
│   ├── requirements.txt                # fastapi, uvicorn, anthropic, pytest, httpx (engine itself needs none)
│   ├── .env.example                    # ANTHROPIC_API_KEY + optional LLM overrides (copy to .env)
│   ├── configs/
│   │   └── default.json                # seed, volumes, issue mix, tolerances, approval limits, routing, SLAs
│   ├── src/ap_automation/
│   │   ├── __main__.py                 # CLI: run-all | generate | process | export | validate | evaluate | report | reproduce | docs | serve
│   │   ├── common.py                   # money math, IO, checksums, paths
│   │   ├── schema.py                   # single source of truth for all 17 tables (types, PK/FK, enums, rules)
│   │   ├── generator/                  # synthetic data
│   │   │   ├── core.py                 #   volume solver, master data, receipts, invoices, anomaly injection, IDs
│   │   │   ├── scenarios.py            #   rule table: scenario -> expected exception / match / edge case
│   │   │   ├── documents.py            #   renders invoices as CLASSIC (PDF text), EMAIL, EDI documents
│   │   │   └── catalog.py              #   hand-authored synthetic names, SKUs, price ranges
│   │   ├── pipeline/                   # the AP workflow
│   │   │   ├── extraction.py           #   layout detection + field parsing + confidence
│   │   │   ├── matching.py             #   duplicate detector + stateful three-way matcher (FIFO allocation)
│   │   │   └── workflow.py             #   orchestration, routing, approval, payment, event log
│   │   ├── llm/                        # ★ Claude integration (Anthropic SDK)
│   │   │   ├── client.py               #   structured-output call, refusal fallbacks, typed errors, .env loading
│   │   │   ├── extractor.py            #   JSON-schema extraction + rules-first hybrid strategy
│   │   │   ├── copilot.py              #   exception explanation + drafted follow-up (advisory)
│   │   │   └── benchmark.py            #   rules vs Claude on unseen free-form documents
│   │   ├── api/                        # REST API (FastAPI)
│   │   │   ├── main.py                 #   app, CORS, routers, serves frontend/dist in production
│   │   │   ├── store.py                #   loads + indexes a dataset, reloads after a run
│   │   │   └── routers/
│   │   │       ├── datasets.py         #   GET list / summary / validation, POST run
│   │   │       ├── invoices.py         #   GET list (filter, search, paginate), GET detail with audit trail
│   │   │       ├── exceptions.py       #   GET exception queues with owners and SLAs
│   │   │       ├── intake.py           #   POST raw document -> extracted fields (rules or Claude) + pre-checks
│   │   │       └── ai.py               #   GET LLM status, POST invoice copilot
│   │   ├── validation.py               # 87 data-quality + safety checks
│   │   ├── evaluation.py               # accuracy, P/R/F1, confusion matrix, KPIs, acceptance criteria
│   │   ├── export.py                   # SQL seed, SQLite, JSON, manifest, reproducibility
│   │   ├── report.py                   # self-contained HTML report
│   │   └── docs.py                     # regenerates docs/data_dictionary.md from schema.py
│   ├── tests/
│   │   ├── test_rules.py               # extraction per layout, tolerance boundaries, FIFO, duplicates
│   │   ├── test_end_to_end.py          # full build validates; same seed identical; corrupted data fails
│   │   ├── test_api.py                 # REST contract: filters, detail, queues, intake, bad input
│   │   └── test_llm.py                 # Claude integration with a fake client (no network)
│   └── data/
│       ├── starter/                    # scale 0.1 (200 invoices), same generator, same seed
│       └── full/                       # scale 1.0 (2,000 invoices)
│           ├── master/                 #   ERP extracts the pipeline may read
│           ├── inbox/                  #   raw documents + intake_manifest.csv  (pipeline input)
│           ├── source_truth/           #   what vendors really billed            (evaluation only)
│           ├── ground_truth/           #   ground_truth.csv / .json              (evaluation only)
│           ├── pipeline_output/        #   extracted fields, decisions, exceptions, matches, approvals, payments, events
│           ├── exports/                #   seed.sql, ap_automation.db (SQLite), json/
│           └── reports/                #   validation, evaluation metrics, manifest, reproducibility, report.html
│
└── frontend/                           # React operations UI
    ├── package.json                    # react, react-dom, react-router-dom, vite (pinned, npm audit clean)
    ├── vite.config.js                  # dev server :5173, proxies /api -> :8000
    ├── index.html
    └── src/
        ├── main.jsx                    # entry: router + dataset context
        ├── App.jsx                     # routes
        ├── api/client.js               # fetch wrapper for every endpoint
        ├── context/DatasetContext.jsx  # selected dataset, re-run refresh
        ├── hooks/useApi.js             # fetch-on-change hook with stale-response guard
        ├── components/
        │   ├── Layout.jsx              # sidebar nav, dataset switcher, re-run button
        │   └── ui.jsx                  # Badge, Card, Kpi, Bar, Field, Loading
        ├── pages/
        │   ├── DashboardPage.jsx       # KPIs, acceptance criteria, queues, issue mix, P/R/F1
        │   ├── InvoicesPage.jsx        # filter / search / paginate all invoices
        │   ├── InvoiceDetailPage.jsx   # decision, exceptions, lines + receipt allocation, PO, audit trail, raw doc
        │   ├── ExceptionsPage.jsx      # work queues by owner with SLA
        │   ├── IntakePage.jsx          # paste a document, see extraction + pre-checks
        │   └── ValidationPage.jsx      # all 87 checks by category
        ├── utils/format.js             # money / % / label formatting
        └── styles/global.css           # design tokens, light + dark mode, responsive
```

The pipeline reads only `master/` and `inbox/`. It never sees `source_truth/` or `ground_truth/`, and a
validation check confirms no labels leak into its inputs. The UI shows ground truth on the invoice page
only as a reviewer's answer key.

---

## Commands

Run from `backend/` (after `pip install -e .`, or prefix with `PYTHONPATH=src` / `$env:PYTHONPATH="src";`):

```bash
python -m ap_automation run-all --preset starter     # 200 invoices, ~4 s
python -m ap_automation run-all --preset full        # 2,000 invoices, ~20 s
python -m ap_automation run-all --scale 0.5 --seed 7 # any scale / seed -> data/scale_0.5
python -m ap_automation reproduce --preset full      # regenerate twice, compare checksums
python -m ap_automation validate --data data/full    # single stages: generate, process, export, validate, evaluate, report
python -m ap_automation docs                         # rebuild docs/data_dictionary.md
python -m ap_automation serve --reload               # REST API on :8000, Swagger UI at /docs
python -m ap_automation llm-status                   # is Claude configured?
python -m ap_automation llm-benchmark --data data/starter --n 20   # rules vs Claude on free-form docs
python -m ap_automation run-all --preset full --llm  # pipeline with Claude extraction fallback
python -m pytest -q                                  # test suite
```

Exit code is non-zero if validation or any acceptance criterion fails, so `run-all` works as a CI gate.

### REST API

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | status, version, datasets |
| GET | `/api/datasets` | available datasets with validation status |
| GET | `/api/datasets/{ds}/summary` | KPIs, acceptance criteria, accuracy, duplicates, payment safety |
| GET | `/api/datasets/{ds}/invoices?status=&exception=&queue=&q=&limit=&offset=` | filtered invoice list + total value |
| GET | `/api/datasets/{ds}/invoices/{invoice_id}` | decision, extracted fields, lines + receipt allocation, PO, exceptions, approvals, payment, events, raw document |
| GET | `/api/datasets/{ds}/exceptions?queue=&code=` | open exceptions with owner and SLA, counts per queue |
| GET | `/api/datasets/{ds}/validation` | all validation checks |
| POST | `/api/datasets/{ds}/intake/extract` | `{text}` → extracted fields, recomputed totals, master-data pre-checks (read-only) |
| POST | `/api/datasets/{starter or full}/run` | regenerate + reprocess the preset, returns validation / acceptance |
| GET | `/api/llm/status` | Claude model, SDK installed, credentials configured |
| POST | `/api/datasets/{ds}/invoices/{invoice_id}/copilot` | Claude: summary, root cause, next action, drafted message (advisory) |
| GET | `/api/datasets/{ds}/intake/sample?style=structured\|unstructured` | a real inbox document, or the same invoice as a free-form letter |

---

## How it works

**1. Generate (parents first).** employees → vendors → POs → PO lines → receipts → receipt lines → invoices →
invoice lines. A small solver (`plan_counts`) decides how many POs are fully received, partially received,
over-received, split across two deliveries, still open or awaiting invoice, so every volume and mix target is hit
exactly. Labelled anomalies are injected into a random sample of otherwise valid invoices; totals, tax, due dates,
PO status and receipt types are always derived from the underlying lines and events.

**2. Render documents.** Each invoice becomes the raw text AP would receive: a PDF text layer (fixed-width table,
ISO or long dates), an email body (DD/MM/YYYY dates, `$1,234.50` amounts) or an EDI file. Duplicate resubmissions
arrive on a different channel, sometimes with the number re-keyed (`HELI-53432` → `HELI53432`).

**3. Process.** For each document in arrival order: verify checksum → extract → resolve vendor → assign
`INV-<vendor-code>-2026-NNNNNN` → duplicate check → header checks → three-way match with tolerances and
cumulative quantity → route the highest-precedence exception to its queue and owner with an SLA, **or** apply the
approval policy and schedule payment. Every state change is appended to `invoice_event`; nothing is overwritten.

**4. Validate, evaluate, report.** See results above; details in `data/full/reports/`.

Rules and thresholds: [docs/business_rules.md](docs/business_rules.md). Fields:
[docs/data_dictionary.md](docs/data_dictionary.md). Design: [docs/architecture.md](docs/architecture.md).

---

## Brief → implementation traceability

| Brief requirement | Where |
|---|---|
| Master data first, dependents with valid parent IDs | `generator/core.py` `Generator.run()` order; FK checks in `validation.py` |
| 1–8 PO lines with SKU, qty, unit price, tax code | `purchase_orders()`; check "PO has 1..8 lines" |
| Receipts with full / partial / over-receipt | `receipts()`; `goods_receipt_line.receipt_type` |
| Invoices referencing vendor and optionally PO | `invoice.po_id` nullable; 3 % non-PO service invoices |
| Totals, tax, grand total calculated from lines | `finalise()`; arithmetic checks |
| Match status derived from price / qty / tax tolerances | `pipeline/matching.py`; `configs/default.json` tolerances |
| Approval / payment only for eligible invoices | `workflow.py` `_approve()`; payment-safety checks |
| State changes as explicit events, no overwrite | `lifecycle_event` (vendor, PO), `invoice_event` (invoice) |
| Labels from documented rules, not random | `generator/scenarios.py` + approval policy |
| PK for every entity, FK for every relationship, cardinality, bridge for N:M | `schema.py`, `docs/data_dictionary.md`, `invoice_match` |
| ID conventions `VND-00001`, `PO-2026-000001`, `GRN-2026-000001`, `INV-<code>-2026-000001`, `INVL-<id>-01` | regex patterns in `schema.py`, enforced by validation |
| Data dictionary (type, required, allowed values, units, uniqueness, rule) | `docs/data_dictionary.md` (generated) |
| 300 / 1,500 / 2,200 / 1,800 / 2,000 and the issue mix | `configs/default.json`; check "Row volumes hit targets exactly" |
| Fixed seed, parameterised scale, starter + full from one generator | `--seed`, `--scale`, `--preset` |
| All 8 required edge cases | table in [business_rules.md §8](docs/business_rules.md) |
| Separate ground truth, never in features | `ground_truth/`; leakage check |
| Validation: PK, FK, enums, date order, arithmetic, lifecycle, duplicates | `validation.py` (87 checks) |
| CSV / JSON / SQL seed, README, dictionary, command, seed, manifest, validation summary | `data/*/exports`, `data/*/reports` |
| Regenerate twice, compare counts / checksums | `reproduce` command → `reports/reproducibility.json` |
| Lawful provenance | 100 % synthetic; recorded in `reports/manifest.json` |

---

## Data provenance

No external data. Vendor names, people, SKUs and price ranges are hand-authored word lists in
`backend/src/ap_automation/generator/catalog.py`, combined by a seeded RNG. Tax IDs and invoice numbers are random
digits. The buyer is a fictional "Orbit Manufacturing Inc."; email domains use the reserved `.example` TLD.
Generic procure-to-pay concepts (PO, GRN, three-way match) informed the schema; no dataset was copied.

## Limitations and next steps

- **LLM extraction** is wired in as a fallback and benchmarked on free-form text. Next: send scanned PDFs to Claude
  as `document` blocks (vision) and run the benchmark on them.
- **Exceptions stay OPEN.** Resolution workflow (approve variance, request credit note, re-match after a late
  receipt) would add `RESOLVED` transitions to `invoice_event`.
- **Single currency (USD)** and one fiscal year. Multi-currency needs FX rates on invoice date.
- **Batch, not streaming.** The workflow class processes one document at a time, so wrapping it in an API or
  queue consumer is straightforward.

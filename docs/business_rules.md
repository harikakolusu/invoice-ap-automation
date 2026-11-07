# Business rules

All thresholds live in `configs/default.json`, so a process owner can change policy without touching code.

## 1. Intake and extraction

| Rule | Behaviour |
|---|---|
| Integrity | Document sha256 must equal the intake manifest, otherwise the run stops (tampered input). |
| Layout | `HDR\|` prefix → EDI; `From:` + `Subject:` → EMAIL; otherwise CLASSIC (PDF text layer). |
| Required fields | vendor tax ID, invoice number, invoice date, total, at least one line. Confidence = share found. |
| Confidence < 1 | `EXTRACTION_INCOMPLETE` → AP_OPERATIONS. |
| Vendor resolution | Tax ID, then exact name. Not found → `VENDOR_UNKNOWN` → VENDOR_MASTER. |
| Invoice ID | `INV-<vendor_code>-2026-<6-digit intake sequence>`; lines `INVL-<invoice_id>-NN`. |

## 2. Duplicate detection (runs before matching, short-circuits)

Key = (vendor_id, normalised invoice number), where normalisation upper-cases and strips non-alphanumerics
(`HELI-53432` = `heli53432`, `INV/2026/00012` = `INV-2026-00012`, `#004821` = `004821`).
A repeat → `DUPLICATE_INVOICE`, `duplicate_of_invoice_id` = the first invoice. Duplicates consume no PO quantity.

Covers both required cases: **same invoice submitted twice** (identical content via a second channel, number
sometimes re-keyed) and **duplicate invoice number** (same number reused with a different date/amount).

## 3. Header validation

| Code | Rule |
|---|---|
| `VENDOR_CLOSED` | vendor status CLOSED and invoice_date > vendor.effective_to |
| `PO_NOT_FOUND` | PO number on document not in master, or a billed SKU is not on the PO |
| `VENDOR_MISMATCH` | invoice vendor ≠ PO vendor |
| `TOTAL_MISMATCH` | any of: line amount ≠ qty × price (±0.01); subtotal, tax or total on document ≠ values recomputed from lines (±0.05). Tax per line = round(amount × rate(tax_code), 2). |
| `DATE_BEFORE_PO` | invoice_date < po_date |

## 4. Three-way match (PO ↔ goods receipt ↔ invoice), per invoice line

| Code | Rule (defaults) |
|---|---|
| `MISSING_RECEIPT` | the PO has no goods receipt at all |
| `PRICE_VARIANCE` | (invoice price − PO price) / PO price > **2.0 %**. Favourable (lower) prices are accepted. |
| `TAX_MISMATCH` | invoice tax code ≠ PO line tax code |
| `QTY_EXCEEDS_PO` | cumulative billed on the PO line > ordered × (1 + **5 %**) |
| `QTY_EXCEEDS_RECEIPT` | cumulative billed on the PO line > cumulative received |

"Cumulative billed" includes earlier invoices in the batch (split deliveries are billed per delivery).
Matched quantity is allocated FIFO across receipt lines and written to the bridge table `invoice_match`.

**Match status** (first that applies): NON_PO (no PO reference) · NO_RECEIPT · NOT_EVALUATED (PO missing /
duplicate) · TAX_VARIANCE · QTY_VARIANCE · PRICE_VARIANCE · MATCHED_WITHIN_TOLERANCE (any accepted price
deviation or over-receipt inside tolerance) · MATCHED.

## 5. Exception precedence and routing

Every exception is recorded; the highest-precedence one is the **primary** and decides the queue.

| # | Code | Queue | Owner role (actor) | SLA |
|---|---|---|---|---|
| 1 | EXTRACTION_INCOMPLETE | AP_OPERATIONS | AP analyst (operations analyst) | 24 h |
| 2 | VENDOR_UNKNOWN | VENDOR_MASTER | System administrator | 48 h |
| 3 | DUPLICATE_INVOICE | AP_OPERATIONS | AP analyst | 24 h |
| 4 | VENDOR_CLOSED | VENDOR_MASTER | System administrator | 48 h |
| 5 | VENDOR_MISMATCH | VENDOR_MASTER | System administrator | 48 h |
| 6 | PO_NOT_FOUND | AP_OPERATIONS | AP analyst | 24 h |
| 7 | TOTAL_MISMATCH | AP_OPERATIONS | AP analyst | 24 h |
| 8 | DATE_BEFORE_PO | AP_OPERATIONS | AP analyst | 24 h |
| 9 | MISSING_RECEIPT | RECEIVING_CONFIRMATION | The PO's business requester | 72 h |
| 10 | TAX_MISMATCH | TAX_REVIEW | Process owner | 48 h |
| 11 | QTY_EXCEEDS_PO | PROCUREMENT_REVIEW | Process owner | 48 h |
| 12 | QTY_EXCEEDS_RECEIPT | RECEIVING_CONFIRMATION | The PO's business requester | 72 h |
| 13 | PRICE_VARIANCE | PROCUREMENT_REVIEW | Process owner | 48 h |

All exceptions are blocking: the invoice goes ON_HOLD, gets **no approval and no payment**.

## 6. Approval policy (only for exception-free invoices)

| Condition | Path | Approvers |
|---|---|---|
| PO-backed and total ≤ 5,000 | `AUTO` | system (level 0) |
| total ≤ 25,000, or non-PO ≤ 25,000 | `L1` | department manager of the PO requester (FINANCE for non-PO) |
| total > 25,000 | `L1>L2` | department manager, then finance director |

## 7. Payment readiness

Payment record created only after the last approval: amount = line-derived total, method from vendor (ACH for
US, WIRE otherwise), `scheduled_date = max(due_date, approval date + 1 day)`, status SCHEDULED.
Invariant checked by validation: **no ON_HOLD invoice has an approval or a payment**.

## 8. Synthetic data generation logic

1. Employees (actors) → vendors (300; 2 % closed early, plus dedicated vendors that close mid-flow).
2. POs (1,500) dated Jan–Jul 2026, vendor chosen with a Pareto weight (few large suppliers, long tail).
3. PO lines (2,200, 1–8 per PO, skewed to 1–2) from the vendor's primary + secondary category; price = catalog
   base ± 8 %; tax code from the SKU category.
4. Receipts (1,800) per PO fulfilment plan: FULL, PARTIAL, OVER (within / beyond tolerance), SPLIT (2 deliveries),
   UNINVOICED (received, invoice pending), OPEN or MISSING (no receipt).
5. Invoices (2,000) bill what was received (one per delivery), then labelled scenarios are injected into a
   random sample. Totals, tax, due dates are always **derived** from lines; only `stated_total` on a
   TOTAL_MISMATCH document deviates, and it is labelled.
6. Duplicates are copies of clean invoices received 1–14 days later.
7. Ground truth comes from `generator/scenarios.py` (rule table) + the approval policy, never from random draws.

| Scenario | Share | Required edge case covered |
|---|---|---|
| CLEAN_FULL / CLEAN_SPLIT_DELIVERY / CLEAN_PARTIAL_DELIVERY | 57 % / 4 % partial | **partial delivery** |
| CLEAN_PRICE_WITHIN_TOL, CLEAN_OVER_RECEIPT_WITHIN_TOL | 4 % / 2 % | tolerance boundaries |
| CLEAN_NON_PO | 3 % | invoice without PO ("optionally PO") |
| PRICE_VARIANCE | 10 % | price variance |
| QTY_EXCEEDS_RECEIPT / QTY_EXCEEDS_PO | 4 % / 4 % | **invoice exceeds PO quantity** |
| DUPLICATE_RESUBMISSION / DUPLICATE_NUMBER | 3 % / 2 % | **same invoice submitted twice**, **duplicate invoice number** |
| MISSING_RECEIPT | 4 % | missing receipt |
| TAX_MISMATCH / CLOSED_VENDOR / TOTAL_MISMATCH / DATE_BEFORE_PO | 0.75 % each | **tax mismatch**, **closed vendor**, **invoice total differs from line sum**, **invoice date before PO date** |

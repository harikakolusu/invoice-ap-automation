# Validation summary: **PASS**

87 checks, 0 failed.

| Category | Check | Status | Violations | Labelled anomalies (allowed) |
|---|---|---|---|---|
| primary_key | employee: primary key employee_id unique | PASS | 0 | 0 |
| schema | employee: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | vendor: primary key vendor_id unique | PASS | 0 | 0 |
| schema | vendor: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | purchase_order: primary key po_id unique | PASS | 0 | 0 |
| schema | purchase_order: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | purchase_order_line: primary key po_line_id unique | PASS | 0 | 0 |
| schema | purchase_order_line: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | goods_receipt: primary key grn_id unique | PASS | 0 | 0 |
| schema | goods_receipt: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | goods_receipt_line: primary key grn_line_id unique | PASS | 0 | 0 |
| schema | goods_receipt_line: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | lifecycle_event: primary key event_id unique | PASS | 0 | 0 |
| schema | lifecycle_event: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice: primary key invoice_id unique | PASS | 0 | 0 |
| schema | invoice: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice_line: primary key invoice_line_id unique | PASS | 0 | 0 |
| schema | invoice_line: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | extracted_invoice: primary key document_id unique | PASS | 0 | 0 |
| schema | extracted_invoice: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | extracted_invoice_line: primary key extracted_line_id unique | PASS | 0 | 0 |
| schema | extracted_invoice_line: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice_decision: primary key invoice_id unique | PASS | 0 | 0 |
| schema | invoice_decision: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice_match: primary key match_id unique | PASS | 0 | 0 |
| schema | invoice_match: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice_exception: primary key exception_id unique | PASS | 0 | 0 |
| schema | invoice_exception: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | approval: primary key approval_id unique | PASS | 0 | 0 |
| schema | approval: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | payment: primary key payment_id unique | PASS | 0 | 0 |
| schema | payment: required / type / enum / format / unique | PASS | 0 | 0 |
| primary_key | invoice_event: primary key event_id unique | PASS | 0 | 0 |
| schema | invoice_event: required / type / enum / format / unique | PASS | 0 | 0 |
| foreign_key | FK purchase_order.vendor_id -> vendor.vendor_id | PASS | 0 | 0 |
| foreign_key | FK purchase_order.requester_id -> employee.employee_id | PASS | 0 | 0 |
| foreign_key | FK purchase_order_line.po_id -> purchase_order.po_id | PASS | 0 | 0 |
| foreign_key | FK goods_receipt.po_id -> purchase_order.po_id | PASS | 0 | 0 |
| foreign_key | FK goods_receipt_line.grn_id -> goods_receipt.grn_id | PASS | 0 | 0 |
| foreign_key | FK goods_receipt_line.po_line_id -> purchase_order_line.po_line_id | PASS | 0 | 0 |
| foreign_key | FK invoice.vendor_id -> vendor.vendor_id | PASS | 0 | 0 |
| foreign_key | FK invoice.po_id -> purchase_order.po_id | PASS | 0 | 0 |
| foreign_key | FK invoice_line.invoice_id -> invoice.invoice_id | PASS | 0 | 0 |
| foreign_key | FK invoice_line.po_line_id -> purchase_order_line.po_line_id | PASS | 0 | 0 |
| foreign_key | FK extracted_invoice_line.document_id -> extracted_invoice.document_id | PASS | 0 | 0 |
| foreign_key | FK invoice_decision.invoice_id -> invoice.invoice_id | PASS | 0 | 0 |
| foreign_key | FK invoice_decision.vendor_id -> vendor.vendor_id | PASS | 0 | 0 |
| foreign_key | FK invoice_decision.po_id -> purchase_order.po_id | PASS | 0 | 0 |
| foreign_key | FK invoice_decision.duplicate_of_invoice_id -> invoice_decision.invoice_id | PASS | 0 | 0 |
| foreign_key | FK invoice_decision.assigned_to -> employee.employee_id | PASS | 0 | 0 |
| foreign_key | FK invoice_match.invoice_line_id -> invoice_line.invoice_line_id | PASS | 0 | 0 |
| foreign_key | FK invoice_match.grn_line_id -> goods_receipt_line.grn_line_id | PASS | 0 | 0 |
| foreign_key | FK invoice_exception.invoice_id -> invoice_decision.invoice_id | PASS | 0 | 0 |
| foreign_key | FK invoice_exception.assigned_to -> employee.employee_id | PASS | 0 | 0 |
| foreign_key | FK approval.invoice_id -> invoice_decision.invoice_id | PASS | 0 | 0 |
| foreign_key | FK approval.approver_id -> employee.employee_id | PASS | 0 | 0 |
| foreign_key | FK payment.invoice_id -> invoice_decision.invoice_id | PASS | 0 | 0 |
| foreign_key | FK payment.vendor_id -> vendor.vendor_id | PASS | 0 | 0 |
| foreign_key | FK invoice_event.invoice_id -> invoice_decision.invoice_id | PASS | 0 | 0 |
| foreign_key | FK lifecycle_event.entity_id -> vendor / purchase_order | PASS | 0 | 0 |
| join | GRN line's PO line belongs to the GRN's PO | PASS | 0 | 0 |
| join | Invoice line's PO line belongs to the invoice's PO | PASS | 0 | 0 |
| join | Invoice vendor = PO vendor | PASS | 0 | 0 |
| join | Bridge invoice_match: same PO line, allocation <= received | PASS | 0 | 0 |
| date_order | Vendor effective_to set iff CLOSED and >= effective_from | PASS | 0 | 0 |
| date_order | PO date within vendor effective dates | PASS | 0 | 0 |
| date_order | Receipt date >= PO date | PASS | 0 | 0 |
| date_order | Invoice date >= PO date | PASS | 0 | 15 |
| date_order | Invoice date <= vendor closure date | PASS | 0 | 15 |
| date_order | received_at >= invoice_date, <= run date; due_date = invoice_date + terms | PASS | 0 | 0 |
| arithmetic | purchase_order_line: amount = qty x price, tax = amount x rate(tax_code) | PASS | 0 | 0 |
| arithmetic | purchase_order: subtotal / tax / total / line_count reconcile with lines | PASS | 0 | 0 |
| arithmetic | invoice_line: amount = qty x price, tax = amount x rate(tax_code) | PASS | 0 | 0 |
| arithmetic | invoice: subtotal / tax / total / line_count reconcile with lines | PASS | 0 | 0 |
| arithmetic | PO has 1..8 lines | PASS | 0 | 0 |
| arithmetic | Stated total = line-derived grand total | PASS | 0 | 15 |
| arithmetic | GRN receipt_type consistent with cumulative received vs ordered | PASS | 0 | 0 |
| lifecycle | Vendor / PO lifecycle transitions valid and final state = entity status | PASS | 0 | 0 |
| lifecycle | Invoice event transitions valid, ordered, final state = decision | PASS | 0 | 0 |
| duplicates | Repeated (vendor, invoice number) only where labelled DUPLICATE, pair recorded | PASS | 0 | 100 |
| volume | Row volumes hit targets exactly | PASS | 0 | 0 |
| volume | Issue mix matches configured shares | PASS | 0 | 0 |
| leakage | No ground-truth labels in pipeline inputs (manifest, documents, source tables) | PASS | 0 | 0 |
| payment_safety | No blocked (ON_HOLD) invoice is payment-ready, approved or paid | PASS | 0 | 0 |
| payment_safety | Each payment-ready invoice has 1 payment (= line-derived total) and approvals | PASS | 0 | 0 |
| payment_safety | Exceptions <-> ON_HOLD one-to-one at invoice level | PASS | 0 | 0 |
| foreign_key | SQLite seed loads; PRAGMA foreign_key_check / integrity_check clean | PASS | 0 | 0 |

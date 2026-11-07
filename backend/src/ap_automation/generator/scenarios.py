"""Documented rule table: scenario -> label + expected outcome.

Ground truth is derived from this table plus the approval policy, never assigned at random.
Each row: (issue_type, expected_primary_exception, expected_match_status, edge_case)
"""

SCENARIOS = {
    # --- clean (~70%) ---
    "CLEAN_FULL":                    ("CLEAN", None, "MATCHED", "full_receipt"),
    "CLEAN_SPLIT_DELIVERY":          ("CLEAN", None, "MATCHED", "partial_delivery"),
    "CLEAN_PARTIAL_DELIVERY":        ("CLEAN", None, "MATCHED", "partial_delivery"),
    "CLEAN_OVER_RECEIPT_WITHIN_TOL": ("CLEAN", None, "MATCHED_WITHIN_TOLERANCE", "over_receipt_within_tolerance"),
    "CLEAN_PRICE_WITHIN_TOL":        ("CLEAN", None, "MATCHED_WITHIN_TOLERANCE", "price_variance_within_tolerance"),
    "CLEAN_NON_PO":                  ("CLEAN", None, "NON_PO", "non_po_invoice"),
    # --- price variance (10%) ---
    "PRICE_VARIANCE":       ("PRICE_VARIANCE", "PRICE_VARIANCE", "PRICE_VARIANCE", "price_over_tolerance"),
    # --- quantity mismatch (8%) ---
    "QTY_EXCEEDS_RECEIPT":  ("QTY_MISMATCH", "QTY_EXCEEDS_RECEIPT", "QTY_VARIANCE", "billed_more_than_received"),
    "QTY_EXCEEDS_PO":       ("QTY_MISMATCH", "QTY_EXCEEDS_PO", "QTY_VARIANCE", "invoice_exceeds_po_quantity"),
    # --- duplicates (5%) ---
    "DUPLICATE_RESUBMISSION": ("DUPLICATE", "DUPLICATE_INVOICE", "NOT_EVALUATED", "same_invoice_submitted_twice"),
    "DUPLICATE_NUMBER":       ("DUPLICATE", "DUPLICATE_INVOICE", "NOT_EVALUATED", "duplicate_invoice_number"),
    # --- missing receipt (4%) ---
    "MISSING_RECEIPT":      ("MISSING_RECEIPT", "MISSING_RECEIPT", "NO_RECEIPT", "missing_receipt"),
    # --- tax / vendor / header errors (3%) ---
    "TAX_MISMATCH":         ("TAX_VENDOR_ERROR", "TAX_MISMATCH", "TAX_VARIANCE", "tax_mismatch"),
    "CLOSED_VENDOR":        ("TAX_VENDOR_ERROR", "VENDOR_CLOSED", "MATCHED", "closed_vendor"),
    "TOTAL_MISMATCH":       ("TAX_VENDOR_ERROR", "TOTAL_MISMATCH", "MATCHED", "invoice_total_differs_from_line_sum"),
    "DATE_BEFORE_PO":       ("TAX_VENDOR_ERROR", "DATE_BEFORE_PO", "MATCHED", "invoice_date_before_po_date"),
}

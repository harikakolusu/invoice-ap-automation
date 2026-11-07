"""Single source of truth for every table: columns, types, keys, enums, rules.

Drives: SQL DDL, the data dictionary (docs), CSV column order, and validation.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Col:
    name: str
    type: str          # str | int | money | rate | date | datetime | bool
    desc: str
    required: bool = True
    enum: tuple = ()
    pattern: str = ""
    unique: bool = False
    fk: str = ""       # "table.column"
    card: str = ""     # cardinality of the FK relationship, child:parent view, e.g. "N:1"
    unit: str = ""
    rule: str = ""


DEPARTMENTS = ("OPERATIONS", "IT", "FACILITIES", "MANUFACTURING", "MARKETING", "FINANCE")
ROLES = ("REQUESTER", "APPROVER_L1", "APPROVER_L2", "AP_ANALYST", "PROCESS_OWNER", "SYSTEM_ADMIN")
CATEGORIES = ("IT_HARDWARE", "OFFICE_SUPPLIES", "MRO", "PACKAGING", "RAW_MATERIALS", "FACILITIES_SUPPLIES", "SERVICES")
TAX_CODES = ("TX00", "TX05", "TX12", "TX18")
TERMS = ("NET15", "NET30", "NET45", "NET60")
CHANNELS = ("EMAIL", "PDF_UPLOAD", "EDI")
UOMS = ("EA", "BOX", "ROLL", "KG", "L", "HR", "MO", "PAIR", "SET")
MATCH_STATUS = ("MATCHED", "MATCHED_WITHIN_TOLERANCE", "NON_PO", "PRICE_VARIANCE", "QTY_VARIANCE",
                "TAX_VARIANCE", "NO_RECEIPT", "NOT_EVALUATED")
EXCEPTION_CODES = ("EXTRACTION_INCOMPLETE", "VENDOR_UNKNOWN", "DUPLICATE_INVOICE", "VENDOR_CLOSED",
                   "VENDOR_MISMATCH", "PO_NOT_FOUND", "TOTAL_MISMATCH", "DATE_BEFORE_PO", "MISSING_RECEIPT",
                   "TAX_MISMATCH", "QTY_EXCEEDS_PO", "QTY_EXCEEDS_RECEIPT", "PRICE_VARIANCE")
QUEUES = ("AP_OPERATIONS", "VENDOR_MASTER", "RECEIVING_CONFIRMATION", "TAX_REVIEW", "PROCUREMENT_REVIEW")
INVOICE_STATES = ("RECEIVED", "EXTRACTED", "VALIDATED", "MATCHED", "PENDING_APPROVAL", "APPROVED",
                  "PAYMENT_READY", "ON_HOLD")
PO_STATES = ("OPEN", "PARTIALLY_RECEIVED", "FULLY_RECEIVED")
VENDOR_STATES = ("ACTIVE", "CLOSED")

# Allowed lifecycle transitions (None = creation). Validation checks every event against these.
INVOICE_TRANSITIONS = {
    (None, "RECEIVED"), ("RECEIVED", "EXTRACTED"), ("EXTRACTED", "VALIDATED"), ("EXTRACTED", "ON_HOLD"),
    ("VALIDATED", "MATCHED"), ("VALIDATED", "PENDING_APPROVAL"), ("VALIDATED", "ON_HOLD"),
    ("MATCHED", "PENDING_APPROVAL"), ("PENDING_APPROVAL", "APPROVED"), ("APPROVED", "PAYMENT_READY"),
}
PO_TRANSITIONS = {(None, "OPEN"), ("OPEN", "PARTIALLY_RECEIVED"), ("OPEN", "FULLY_RECEIVED"),
                  ("PARTIALLY_RECEIVED", "FULLY_RECEIVED")}
VENDOR_TRANSITIONS = {(None, "ACTIVE"), ("ACTIVE", "CLOSED")}

Y = r"\d{4}"
P_VENDOR = r"^VND-\d{5}$"
P_VCODE = r"^[A-Z]{4}\d{3,}$"
P_PO = rf"^PO-{Y}-\d{{6}}$"
P_POL = rf"^POL-PO-{Y}-\d{{6}}-\d{{2}}$"
P_GRN = rf"^GRN-{Y}-\d{{6}}$"
P_GRNL = rf"^GRNL-GRN-{Y}-\d{{6}}-\d{{2}}$"
P_INV = rf"^INV-[A-Z]{{4}}\d{{3,}}-{Y}-\d{{6}}$"
P_INVL = rf"^INVL-INV-[A-Z]{{4}}\d{{3,}}-{Y}-\d{{6}}-\d{{2}}$"
P_DOC = rf"^DOC-{Y}-\d{{6}}$"
P_EMP = r"^EMP-\d{4}$"
P_SKU = r"^SKU-[A-Z]{3}-\d{4}$"

MONEY_POS = "> 0, 2 decimals"


def _t(zone, desc, pk, cols, grain=""):
    return {"zone": zone, "desc": desc, "pk": pk, "cols": cols, "grain": grain}


TABLES: dict[str, dict] = {
    # ---------------- master / ERP extracts ----------------
    "employee": _t("master", "Primary actors: requesters, approvers, AP analysts, process owners, system admins.",
                   "employee_id", [
        Col("employee_id", "str", "Employee / actor ID", pattern=P_EMP, unique=True),
        Col("full_name", "str", "Synthetic full name"),
        Col("department", "str", "Owning department", enum=DEPARTMENTS),
        Col("role", "str", "Workflow role", enum=ROLES),
        Col("approval_limit", "money", "Max invoice value this approver may approve", required=False,
            unit="USD", rule="set only for APPROVER_L1 / APPROVER_L2"),
        Col("status", "str", "Employment status", enum=("ACTIVE",)),
    ]),
    "vendor": _t("master", "Supplier master. Created first; every PO and invoice references it.", "vendor_id", [
        Col("vendor_id", "str", "Vendor ID", pattern=P_VENDOR, unique=True),
        Col("vendor_code", "str", "Short code used inside invoice IDs", pattern=P_VCODE, unique=True),
        Col("vendor_name", "str", "Legal name (synthetic)", unique=True),
        Col("tax_id", "str", "Synthetic tax registration number", pattern=r"^\d{2}-\d{7}$", unique=True),
        Col("country", "str", "ISO country", enum=("US", "IN", "GB", "DE", "SG")),
        Col("primary_category", "str", "Main spend category supplied", enum=CATEGORIES[:-1]),
        Col("payment_terms", "str", "Default payment terms", enum=TERMS),
        Col("payment_method", "str", "Remittance method", enum=("ACH", "WIRE")),
        Col("currency", "str", "Billing currency", enum=("USD",)),
        Col("preferred_channel", "str", "Usual invoice submission channel", enum=CHANNELS),
        Col("status", "str", "Lifecycle state", enum=VENDOR_STATES),
        Col("effective_from", "date", "Onboarding date"),
        Col("effective_to", "date", "Closure date", required=False,
            rule="required iff status=CLOSED; >= effective_from"),
    ]),
    "purchase_order": _t("master", "Purchase order header.", "po_id", [
        Col("po_id", "str", "PO number", pattern=P_PO, unique=True),
        Col("vendor_id", "str", "Ordering vendor", fk="vendor.vendor_id", card="N:1"),
        Col("po_date", "date", "PO issue date", rule="within vendor effective dates"),
        Col("requester_id", "str", "Business requester", fk="employee.employee_id", card="N:1"),
        Col("department", "str", "Requesting department", enum=DEPARTMENTS),
        Col("currency", "str", "PO currency", enum=("USD",)),
        Col("status", "str", "Derived from receipts", enum=PO_STATES),
        Col("line_count", "int", "Number of PO lines", rule="1..8, = count(purchase_order_line)"),
        Col("subtotal", "money", "Sum of line_amount", unit="USD"),
        Col("tax_amount", "money", "Sum of line tax_amount", unit="USD"),
        Col("total_amount", "money", "subtotal + tax_amount", unit="USD"),
    ]),
    "purchase_order_line": _t("master", "PO line: what was ordered, at what price and tax code.", "po_line_id", [
        Col("po_line_id", "str", "PO line ID", pattern=P_POL, unique=True),
        Col("po_id", "str", "Parent PO", fk="purchase_order.po_id", card="N:1"),
        Col("line_number", "int", "1-based line number", rule="unique within PO"),
        Col("sku", "str", "Item SKU", pattern=P_SKU, rule="unique within PO"),
        Col("description", "str", "Item description"),
        Col("uom", "str", "Unit of measure", enum=UOMS),
        Col("quantity", "int", "Ordered quantity", unit="uom", rule="> 0"),
        Col("unit_price", "money", "Agreed unit price", unit="USD", rule=MONEY_POS),
        Col("tax_code", "str", "Tax code", enum=TAX_CODES),
        Col("tax_rate", "rate", "Rate implied by tax_code", rule="= tax_codes[tax_code]"),
        Col("line_amount", "money", "quantity * unit_price", unit="USD"),
        Col("tax_amount", "money", "round(line_amount * tax_rate, 2)", unit="USD"),
    ]),
    "goods_receipt": _t("master", "Goods receipt note (GRN) header: one delivery against a PO.", "grn_id", [
        Col("grn_id", "str", "GRN number", pattern=P_GRN, unique=True),
        Col("po_id", "str", "PO received against", fk="purchase_order.po_id", card="N:1"),
        Col("receipt_date", "date", "Date goods were received", rule=">= po_date"),
        Col("warehouse", "str", "Receiving site", enum=("WH-NORTH", "WH-SOUTH", "WH-EAST", "WH-WEST")),
        Col("status", "str", "Posting state", enum=("POSTED",)),
    ]),
    "goods_receipt_line": _t("master", "Quantity received per PO line in one delivery.", "grn_line_id", [
        Col("grn_line_id", "str", "GRN line ID", pattern=P_GRNL, unique=True),
        Col("grn_id", "str", "Parent GRN", fk="goods_receipt.grn_id", card="N:1"),
        Col("po_line_id", "str", "PO line received", fk="purchase_order_line.po_line_id", card="N:1",
            rule="po_line.po_id = grn.po_id"),
        Col("line_number", "int", "1-based line number"),
        Col("quantity_received", "int", "Units received", unit="uom", rule="> 0"),
        Col("receipt_type", "str", "Cumulative received vs ordered after this line", enum=("FULL", "PARTIAL", "OVER")),
    ]),
    "lifecycle_event": _t("master", "Append-only state history for vendors and POs (never overwritten).", "event_id", [
        Col("event_id", "str", "Event ID", pattern=r"^LEV-\d{7}$", unique=True),
        Col("entity_type", "str", "Entity", enum=("VENDOR", "PURCHASE_ORDER")),
        Col("entity_id", "str", "vendor_id or po_id", rule="polymorphic FK, validated per entity_type"),
        Col("from_state", "str", "Previous state (empty on creation)", required=False, enum=VENDOR_STATES + PO_STATES),
        Col("to_state", "str", "New state", enum=VENDOR_STATES + PO_STATES),
        Col("event_date", "date", "When the state changed"),
        Col("detail", "str", "Trigger, e.g. GRN ID", required=False),
    ]),
    # ---------------- what vendors actually sent (evaluation only) ----------------
    "invoice": _t("source_truth", "Invoice as issued by the vendor (truth). The pipeline never reads this table; it "
                  "re-derives these fields from the raw document.", "invoice_id", [
        Col("invoice_id", "str", "Internal invoice ID", pattern=P_INV, unique=True),
        Col("document_id", "str", "Raw document in the inbox", pattern=P_DOC, unique=True),
        Col("vendor_id", "str", "Issuing vendor", fk="vendor.vendor_id", card="N:1"),
        Col("po_id", "str", "Referenced PO (empty for non-PO invoices)", required=False,
            fk="purchase_order.po_id", card="N:0..1"),
        Col("vendor_invoice_number", "str", "Number printed by vendor",
            rule="(vendor, normalised number) unique except labelled duplicates"),
        Col("invoice_date", "date", "Invoice date", rule=">= po_date unless labelled DATE_BEFORE_PO"),
        Col("received_at", "datetime", "Intake timestamp", rule=">= invoice_date"),
        Col("channel", "str", "Submission channel", enum=CHANNELS),
        Col("currency", "str", "Currency", enum=("USD",)),
        Col("payment_terms", "str", "Terms on invoice", enum=TERMS),
        Col("due_date", "date", "invoice_date + terms days"),
        Col("line_count", "int", "Number of invoice lines", rule="= count(invoice_line)"),
        Col("subtotal", "money", "Sum of line_amount", unit="USD"),
        Col("tax_amount", "money", "Sum of line tax_amount", unit="USD"),
        Col("grand_total", "money", "subtotal + tax_amount (derived)", unit="USD"),
        Col("stated_total", "money", "Total printed on the document", unit="USD",
            rule="= grand_total unless labelled TOTAL_MISMATCH"),
    ]),
    "invoice_line": _t("source_truth", "Invoice line as issued by the vendor.", "invoice_line_id", [
        Col("invoice_line_id", "str", "Invoice line ID", pattern=P_INVL, unique=True),
        Col("invoice_id", "str", "Parent invoice", fk="invoice.invoice_id", card="N:1"),
        Col("line_number", "int", "1-based line number"),
        Col("po_line_id", "str", "PO line billed (empty for non-PO)", required=False,
            fk="purchase_order_line.po_line_id", card="N:0..1"),
        Col("sku", "str", "Item SKU", pattern=P_SKU),
        Col("description", "str", "Item description"),
        Col("uom", "str", "Unit of measure", enum=UOMS),
        Col("quantity", "int", "Billed quantity", rule="> 0"),
        Col("unit_price", "money", "Billed unit price", unit="USD", rule=MONEY_POS),
        Col("tax_code", "str", "Billed tax code", enum=TAX_CODES),
        Col("tax_rate", "rate", "Rate implied by tax_code"),
        Col("line_amount", "money", "quantity * unit_price", unit="USD"),
        Col("tax_amount", "money", "round(line_amount * tax_rate, 2)", unit="USD"),
    ]),
    # ---------------- pipeline outputs ----------------
    "extracted_invoice": _t("pipeline_output", "Header fields extracted from the raw document.", "document_id", [
        Col("document_id", "str", "Source document", pattern=P_DOC, unique=True),
        Col("layout", "str", "Detected layout; LLM = extracted by Claude fallback", enum=("CLASSIC", "EMAIL", "EDI", "LLM")),
        Col("vendor_name", "str", "Extracted vendor name", required=False),
        Col("vendor_tax_id", "str", "Extracted vendor tax ID", required=False),
        Col("vendor_invoice_number", "str", "Extracted invoice number", required=False),
        Col("invoice_date", "date", "Extracted invoice date", required=False),
        Col("po_number", "str", "Extracted PO reference", required=False),
        Col("currency", "str", "Extracted currency", required=False),
        Col("payment_terms", "str", "Extracted terms", required=False),
        Col("subtotal", "money", "Extracted subtotal", required=False),
        Col("tax_amount", "money", "Extracted tax", required=False),
        Col("stated_total", "money", "Extracted total", required=False),
        Col("line_count", "int", "Lines extracted"),
        Col("confidence", "rate", "Share of required fields found (0..1)"),
    ]),
    "extracted_invoice_line": _t("pipeline_output", "Lines extracted from the raw document.", "extracted_line_id", [
        Col("extracted_line_id", "str", "<document_id>-<nn>", unique=True),
        Col("document_id", "str", "Source document", fk="extracted_invoice.document_id", card="N:1"),
        Col("line_number", "int", "Line number"),
        Col("sku", "str", "SKU"),
        Col("description", "str", "Description"),
        Col("quantity", "int", "Quantity"),
        Col("unit_price", "money", "Unit price"),
        Col("tax_code", "str", "Tax code"),
        Col("line_amount", "money", "Line amount"),
    ]),
    "invoice_decision": _t("pipeline_output", "One row per processed invoice: match result, exceptions, decision.",
                           "invoice_id", [
        Col("invoice_id", "str", "Assigned invoice ID", pattern=P_INV, unique=True, fk="invoice.invoice_id", card="1:1"),
        Col("document_id", "str", "Source document", pattern=P_DOC, unique=True),
        Col("vendor_id", "str", "Resolved vendor", required=False, fk="vendor.vendor_id", card="N:1"),
        Col("po_id", "str", "Resolved PO", required=False, fk="purchase_order.po_id", card="N:0..1"),
        Col("vendor_invoice_number", "str", "Extracted invoice number", required=False),
        Col("invoice_date", "date", "Extracted invoice date", required=False),
        Col("computed_total", "money", "Total recomputed from extracted lines", unit="USD"),
        Col("match_status", "str", "Three-way match result", enum=MATCH_STATUS),
        Col("primary_exception", "str", "Highest-precedence exception", required=False, enum=EXCEPTION_CODES),
        Col("exception_codes", "str", "All exception codes, ';'-separated", required=False),
        Col("exception_count", "int", "Number of exceptions raised"),
        Col("final_status", "str", "Decision", enum=("PAYMENT_READY", "ON_HOLD")),
        Col("payment_ready", "bool", "True only when no blocking exception and fully approved"),
        Col("approval_path", "str", "Approval levels applied", required=False, enum=("AUTO", "L1", "L1>L2")),
        Col("duplicate_of_invoice_id", "str", "Earlier invoice this duplicates", required=False,
            fk="invoice_decision.invoice_id", card="N:0..1"),
        Col("route_queue", "str", "Queue of primary exception", required=False, enum=QUEUES),
        Col("assigned_to", "str", "Owner of primary exception", required=False, fk="employee.employee_id", card="N:1"),
        Col("extraction_confidence", "rate", "From extraction"),
        Col("processed_at", "datetime", "Decision timestamp"),
    ]),
    "invoice_match": _t("pipeline_output", "Bridge (N:M) between invoice lines and goods receipt lines; quantity "
                        "allocated FIFO.", "match_id", [
        Col("match_id", "str", "Match ID", pattern=r"^MAT-\d{4}-\d{6}$", unique=True),
        Col("invoice_line_id", "str", "Invoice line", fk="invoice_line.invoice_line_id", card="N:1"),
        Col("grn_line_id", "str", "Receipt line", fk="goods_receipt_line.grn_line_id", card="N:1"),
        Col("matched_qty", "int", "Quantity allocated", rule="> 0; sum per grn_line <= quantity_received"),
    ]),
    "invoice_exception": _t("pipeline_output", "Every exception raised, routed to a queue and owner with an SLA.",
                            "exception_id", [
        Col("exception_id", "str", "Exception ID", pattern=r"^EXC-\d{4}-\d{6}$", unique=True),
        Col("invoice_id", "str", "Invoice", fk="invoice_decision.invoice_id", card="N:1"),
        Col("invoice_line_id", "str", "Line, when line-level", required=False),
        Col("exception_code", "str", "Exception type", enum=EXCEPTION_CODES),
        Col("severity", "str", "Severity", enum=("HIGH", "MEDIUM")),
        Col("is_primary", "bool", "Highest precedence for this invoice"),
        Col("queue", "str", "Work queue", enum=QUEUES),
        Col("assigned_to", "str", "Owner", fk="employee.employee_id", card="N:1"),
        Col("detail", "str", "Human-readable explanation"),
        Col("expected_value", "str", "Policy / PO value", required=False),
        Col("actual_value", "str", "Invoice value", required=False),
        Col("status", "str", "Exception state", enum=("OPEN",)),
        Col("created_at", "datetime", "Raised at"),
        Col("sla_due_at", "datetime", "created_at + queue SLA"),
    ]),
    "approval": _t("pipeline_output", "Approval records, created only for eligible (exception-free) invoices.",
                   "approval_id", [
        Col("approval_id", "str", "Approval ID", pattern=r"^APR-\d{4}-\d{6}$", unique=True),
        Col("invoice_id", "str", "Invoice", fk="invoice_decision.invoice_id", card="N:1"),
        Col("level", "int", "0 = auto, 1 = manager, 2 = finance director"),
        Col("approver_type", "str", "Who approved", enum=("SYSTEM", "HUMAN")),
        Col("approver_id", "str", "Approver (empty for SYSTEM)", required=False, fk="employee.employee_id", card="N:1"),
        Col("decision", "str", "Outcome", enum=("APPROVED",)),
        Col("policy_rule", "str", "Rule that required this approval"),
        Col("decided_at", "datetime", "Decision timestamp"),
    ]),
    "payment": _t("pipeline_output", "Payment scheduled for approved invoices only (1:1 with invoice).", "payment_id", [
        Col("payment_id", "str", "Payment ID", pattern=r"^PAY-\d{4}-\d{6}$", unique=True),
        Col("invoice_id", "str", "Invoice paid", unique=True, fk="invoice_decision.invoice_id", card="1:1"),
        Col("vendor_id", "str", "Payee", fk="vendor.vendor_id", card="N:1"),
        Col("amount", "money", "= invoice computed_total", unit="USD"),
        Col("currency", "str", "Currency", enum=("USD",)),
        Col("method", "str", "Remittance method", enum=("ACH", "WIRE")),
        Col("scheduled_date", "date", "max(due_date, approval date + 1)"),
        Col("status", "str", "Payment state", enum=("SCHEDULED",)),
        Col("created_at", "datetime", "When scheduled"),
    ]),
    "invoice_event": _t("pipeline_output", "Append-only invoice state history.", "event_id", [
        Col("event_id", "str", "Event ID", pattern=r"^IEV-\d{7}$", unique=True),
        Col("invoice_id", "str", "Invoice", fk="invoice_decision.invoice_id", card="N:1"),
        Col("seq", "int", "Order within invoice"),
        Col("from_state", "str", "Previous state", required=False, enum=INVOICE_STATES),
        Col("to_state", "str", "New state", enum=INVOICE_STATES),
        Col("event_ts", "datetime", "Timestamp"),
        Col("actor", "str", "SYSTEM or employee_id"),
        Col("detail", "str", "Reason", required=False),
    ]),
}


def cols(table: str) -> list[str]:
    return [c.name for c in TABLES[table]["cols"]]

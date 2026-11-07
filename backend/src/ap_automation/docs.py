"""Generate docs/data_dictionary.md (with ER diagram) from schema.py, so docs never drift from code."""
from __future__ import annotations

from .common import REPO_ROOT, write_text
from .schema import (INVOICE_TRANSITIONS, PO_TRANSITIONS, TABLES, VENDOR_TRANSITIONS)

CROW = {"N:1": "||--o{", "N:0..1": "|o--o{", "1:1": "||--o|"}   # parent <rel> child


def _trans(ts):
    return ", ".join(f"{a or '∅'} → {b}" for a, b in sorted(ts, key=lambda t: (t[0] or "", t[1])))


def write_data_dictionary() -> str:
    md = ["# Data dictionary", "",
          "Generated from `backend/src/ap_automation/schema.py` by `python -m ap_automation docs`. Do not edit by hand.", "",
          "## Entities", "", "| Table | Zone | Primary key | Rows describe |", "|---|---|---|---|"]
    md += [f"| `{n}` | {s['zone']} | `{s['pk']}` | {s['desc']} |" for n, s in TABLES.items()]

    md += ["", "## Entity-relationship diagram", "", "```mermaid", "erDiagram"]
    for n, s in TABLES.items():
        for c in s["cols"]:
            if c.fk:
                t = c.fk.split(".")[0]
                md.append(f"    {t} {CROW[c.card]} {n} : \"{c.name}\"")
    md += ["    vendor ||--o{ lifecycle_event : \"entity_id (VENDOR)\"",
           "    purchase_order ||--o{ lifecycle_event : \"entity_id (PURCHASE_ORDER)\"", "```", "",
           "## Relationships and cardinality", "",
           "| Child.column | → Parent | Cardinality (child:parent) | Optional |", "|---|---|---|---|"]
    for n, s in TABLES.items():
        for c in s["cols"]:
            if c.fk:
                md.append(f"| `{n}.{c.name}` | `{c.fk}` | {c.card} | {'yes' if not c.required else 'no'} |")
    md += ["", "Many-to-many: `invoice_line` ↔ `goods_receipt_line` is N:M (one invoice line can consume several "
           "deliveries, one delivery can be billed across several invoices). It is resolved by the bridge table "
           "`invoice_match` (quantity allocated FIFO by receipt date).", "",
           "## Lifecycle states (append-only history)", "",
           f"- **Vendor** (`lifecycle_event`): {_trans(VENDOR_TRANSITIONS)}. Effective dates: `effective_from`, "
           "`effective_to`.",
           f"- **Purchase order** (`lifecycle_event`): {_trans(PO_TRANSITIONS)}. Status derived from receipts.",
           f"- **Invoice** (`invoice_event`): {_trans(INVOICE_TRANSITIONS)}.", "",
           "Goods receipts are `POSTED`; payments are `SCHEDULED`; exceptions are `OPEN` (resolution is out of "
           "scope for a single batch run).", ""]

    for n, s in TABLES.items():
        md += [f"## `{n}`", "", s["desc"], "",
               "| Field | Type | Req. | Allowed values / format | Unit | Unique | Validation rule |",
               "|---|---|---|---|---|---|---|"]
        for c in s["cols"]:
            allowed = ", ".join(c.enum) if c.enum else (f"`{c.pattern}`" if c.pattern else "")
            rule = "; ".join(x for x in (c.desc, c.rule, f"FK → `{c.fk}`" if c.fk else "") if x)
            md.append(f"| `{c.name}` | {c.type} | {'Y' if c.required else 'N'} | {allowed} | {c.unit} | "
                      f"{'Y' if c.unique or c.name == s['pk'] else ''} | {rule} |")
        md.append("")
    md += ["## Type conventions", "",
           "- `money`: decimal, exactly 2 places, USD, rounded half-up. `rate`: decimal fraction (0.18 = 18%).",
           "- `date`: ISO `YYYY-MM-DD`. `datetime`: ISO `YYYY-MM-DDTHH:MM:SS` (local, no TZ).",
           "- `bool`: `true` / `false`. Empty cell = NULL.", ""]
    text = "\n".join(md)
    write_text(REPO_ROOT / "docs" / "data_dictionary.md", text)
    return text

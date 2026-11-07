"""Exception work queues: what each owner has to resolve, with SLA due times."""
from collections import Counter

from fastapi import APIRouter

from .. import store

router = APIRouter(prefix="/datasets/{name}/exceptions", tags=["exceptions"])


@router.get("")
def exception_queues(name: str, queue: str | None = None, code: str | None = None):
    ds = store.get(name)
    primary = [e for e in ds.exceptions if e["is_primary"] == "true"]
    queues = Counter(e["queue"] for e in primary)
    rows = [e for e in primary if (not queue or e["queue"] == queue) and (not code or e["exception_code"] == code)]
    items = []
    for e in rows:
        d = ds.decision_by_id[e["invoice_id"]]
        items.append({**e, "assigned_to": ds.person(e["assigned_to"]), "computed_total": d["computed_total"],
                      "vendor_name": ds.vendors.get(d["vendor_id"] or "", {}).get("vendor_name"),
                      "secondary_codes": [c for c in (d["exception_codes"] or "").split(";")
                                          if c and c != e["exception_code"]]})
    return {"queues": dict(sorted(queues.items())), "codes": dict(Counter(e["exception_code"] for e in primary)),
            "total": len(items), "items": items}

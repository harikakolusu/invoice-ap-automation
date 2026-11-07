"""Shared helpers: money math, config loading, CSV/JSON IO, checksums."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]      # backend/
REPO_ROOT = PROJECT_ROOT.parent                           # repo root (docs/, frontend/)
DATA_ROOT = PROJECT_ROOT / "data"
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "default.json"
CENT = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(CENT, ROUND_HALF_UP)


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def alloc(total: int, weights: dict) -> dict:
    """Split an integer total by weights using largest remainder (sums exactly to total)."""
    s = sum(weights.values())
    raw = {k: total * w / s for k, w in weights.items()}
    out = {k: int(v) for k, v in raw.items()}
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), list(weights).index(k)))[: total - sum(out.values())]:
        out[k] += 1
    return out


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime):
        return v.isoformat(timespec="seconds")
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def jsonable(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    return fmt(v)


def write_csv(path: Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([fmt(r.get(c)) for c in cols])


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, default=jsonable)
        f.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="\n", encoding="utf-8") as f:
        f.write(text)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def norm_invoice_number(s: str) -> str:
    """Normalise vendor invoice numbers for duplicate detection: 'abc-0012' == 'ABC0012'."""
    return "".join(ch for ch in s.upper() if ch.isalnum())


# Dataset folder layout (one place, used by every stage).
ZONES = {
    "master": "master",              # ERP master/transaction extracts the pipeline may read
    "inbox": "inbox",                # raw invoice documents + intake manifest (pipeline input)
    "source_truth": "source_truth",  # what vendors actually sent; evaluation only, never pipeline input
    "ground_truth": "ground_truth",  # labels + expected decisions; evaluation only
    "pipeline_output": "pipeline_output",
    "exports": "exports",
    "reports": "reports",
}

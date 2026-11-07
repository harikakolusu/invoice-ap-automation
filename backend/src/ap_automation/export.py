"""Exports (SQL seed, SQLite DB, JSON), source manifest with checksums, reproducibility check."""
from __future__ import annotations

import hashlib
import platform
import sqlite3
import tempfile
from pathlib import Path

from . import __version__
from .common import read_csv, sha256_file, write_json, write_text
from .schema import TABLES

SQLTYPE = {"str": "TEXT", "int": "INTEGER", "money": "NUMERIC(14,2)", "rate": "NUMERIC(8,4)", "date": "DATE",
           "datetime": "TIMESTAMP", "bool": "BOOLEAN"}


def ddl(name: str) -> str:
    spec, out, fks = TABLES[name], [], []
    for c in spec["cols"]:
        s = f"  {c.name} {SQLTYPE[c.type]}"
        s += " PRIMARY KEY" if c.name == spec["pk"] else (" NOT NULL" if c.required else "")
        if c.unique and c.name != spec["pk"]:
            s += " UNIQUE"
        if c.enum:
            s += f" CHECK ({c.name} IN ({', '.join(repr(e) for e in c.enum)}))"
        out.append(s)
        if c.fk:
            t, k = c.fk.split(".")
            fks.append(f"  FOREIGN KEY ({c.name}) REFERENCES {t}({k})")
    return f"-- {spec['desc']}\nCREATE TABLE {name} (\n" + ",\n".join(out + fks) + "\n);\n"


def _lit(typ: str, v: str) -> str:
    if v == "":
        return "NULL"
    if typ in ("int", "money", "rate"):
        return v
    if typ == "bool":
        return "TRUE" if v == "true" else "FALSE"
    return "'" + v.replace("'", "''") + "'"


def _typed(typ: str, v: str):
    if v == "":
        return None
    if typ == "int":
        return int(v)
    if typ in ("money", "rate"):
        return float(v)
    if typ == "bool":
        return v == "true"
    return v


def export(data_dir: Path) -> dict:
    d = Path(data_dir)
    sql = ["-- AP automation seed data (generated; do not edit). Load: sqlite3 ap.db < seed.sql", "BEGIN;"]
    counts = {}
    for name, spec in TABLES.items():
        p = d / spec["zone"] / f"{name}.csv"
        if not p.exists():
            continue
        rows = read_csv(p)
        counts[name] = len(rows)
        sql.append(ddl(name))
        types = [(c.name, c.type) for c in spec["cols"]]
        for i in range(0, len(rows), 500):
            vals = ",\n".join("(" + ", ".join(_lit(t, r[c]) for c, t in types) + ")" for r in rows[i:i + 500])
            sql.append(f"INSERT INTO {name} ({', '.join(c for c, _ in types)}) VALUES\n{vals};")
        write_json(d / "exports" / "json" / f"{name}.json", [{c: _typed(t, r[c]) for c, t in types} for r in rows])
    sql.append("COMMIT;")
    write_text(d / "exports" / "seed.sql", "\n".join(sql) + "\n")
    db = d / "exports" / "ap_automation.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript((d / "exports" / "seed.sql").read_text(encoding="utf-8"))
    con.close()
    return counts


# ---------------------------------------------------------------- manifest + reproducibility
SKIP = {"reports/manifest.json", "reports/reproducibility.json", "exports/ap_automation.db"}


def file_hashes(data_dir: Path) -> dict:
    d, out, docs = Path(data_dir), {}, hashlib.sha256()
    for p in sorted(d.rglob("*")):
        rel = p.relative_to(d).as_posix()
        if not p.is_file() or rel in SKIP:
            continue
        if rel.startswith("inbox/documents/"):
            docs.update(f"{p.name}:{sha256_file(p)}\n".encode())
            continue
        rows = sum(1 for _ in open(p, encoding="utf-8")) - 1 if p.suffix == ".csv" else None
        out[rel] = {"sha256": sha256_file(p), "bytes": p.stat().st_size, "rows": rows}
    n_docs = len(list((d / "inbox" / "documents").glob("*.txt")))
    out["inbox/documents/*.txt"] = {"sha256": docs.hexdigest(), "files": n_docs}
    return out


def write_manifest(data_dir: Path, seed: int, scale: float, command: str) -> dict:
    m = {"project": "invoice-ap-automation", "version": __version__, "seed": seed, "scale": scale,
         "generator_command": command, "python": platform.python_version(),
         "provenance": {
             "external_data_used": False,
             "sources": "100% synthetic. Vendor names, people, SKUs and prices come from hand-authored word lists in "
                        "src/ap_automation/generator/catalog.py combined by a seeded RNG. No public or personal data "
                        "was downloaded, scraped or redistributed.",
             "schema_inspiration": "Generic procure-to-pay concepts (PO, GRN, three-way match); no dataset copied.",
             "license": "Synthetic data and code authored for this project; no third-party terms apply.",
             "fields_discarded": "n/a (no external source)"},
         "files": file_hashes(data_dir)}
    write_json(Path(data_dir) / "reports" / "manifest.json", m)
    return m


def reproducibility(cfg: dict, scale: float, seed: int, compare_to: Path | None, build) -> dict:
    """Regenerate twice with the same seed (fresh temp dirs) and compare every file checksum + row count."""
    runs = []
    with tempfile.TemporaryDirectory() as t:
        for i in (1, 2):
            out = Path(t) / f"run{i}"
            build(out, cfg, scale, seed)
            runs.append(file_hashes(out))
    a, b = runs
    diff = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
    res = {"seed": seed, "scale": scale, "files_compared": len(a), "identical": not diff, "differences": diff,
           "row_counts": {k: v["rows"] for k, v in a.items() if v.get("rows") is not None},
           "combined_checksum": hashlib.sha256("".join(f"{k}{v['sha256']}" for k, v in sorted(a.items()))
                                               .encode()).hexdigest()}
    if compare_to and (compare_to / "reports" / "generation_plan.json").exists():
        c = file_hashes(compare_to)
        res["matches_committed_dataset"] = sorted(k for k in set(a) | set(c) if a.get(k) != c.get(k)) == []
    return res

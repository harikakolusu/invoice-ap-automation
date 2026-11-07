"""Synthetic data generation: writes master data, raw invoice documents, source truth and ground truth."""
from __future__ import annotations

import shutil
from pathlib import Path

from ..common import ZONES, write_csv, write_json, write_text
from ..schema import TABLES, cols
from .core import Generator

GT_COLS = ["document_id", "invoice_id", "scenario", "issue_type", "edge_case", "expected_primary_exception",
           "expected_match_status", "expected_final_status", "expected_payment_ready", "expected_route_queue",
           "expected_approval_path", "duplicate_of_invoice_id", "injected_detail"]
MANIFEST_COLS = ["document_id", "file_name", "channel", "received_at", "sha256", "bytes"]


def generate_dataset(out_dir: Path, cfg: dict, scale: float, seed: int) -> dict:
    data = Generator(cfg, scale, seed).run()
    for zone in ZONES.values():          # regenerate from scratch: no stale files from older runs
        shutil.rmtree(out_dir / zone, ignore_errors=True)
    for t, rows in data["tables"].items():
        write_csv(out_dir / TABLES[t]["zone"] / f"{t}.csv", rows, cols(t))
    write_csv(out_dir / "ground_truth" / "ground_truth.csv", data["ground_truth"], GT_COLS)
    write_json(out_dir / "ground_truth" / "ground_truth.json", data["ground_truth"])
    for doc in data["documents"]:
        write_text(out_dir / "inbox" / "documents" / doc["file_name"], doc["_text"])
    write_csv(out_dir / "inbox" / "intake_manifest.csv", data["documents"], MANIFEST_COLS)
    write_json(out_dir / "reports" / "generation_plan.json",
               {"seed": seed, "scale": scale, **data["plan"]})
    return data["plan"]

"""End-to-end: build a small dataset, everything must validate; corrupted data must FAIL validation."""
import csv
import shutil

import pytest

from ap_automation.__main__ import build_all
from ap_automation.common import load_config
from ap_automation.evaluation import evaluate
from ap_automation.export import file_hashes
from ap_automation.validation import validate

CFG = load_config()
SCALE = 0.1


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    out = tmp_path_factory.mktemp("ds") / "starter"
    build_all(out, CFG, SCALE, CFG["seed"])
    return out


def test_validation_and_acceptance_pass(dataset):
    v = validate(dataset, CFG, SCALE)
    assert v["status"] == "PASS", [c for c in v["checks"] if c["status"] == "FAIL"]
    e = evaluate(dataset, CFG)
    assert {a["status"] for a in e["acceptance_criteria"]} == {"PASS"}
    assert e["payment_safety"]["unsafe_releases_blocked_but_payment_ready"] == 0


def test_same_seed_is_byte_identical(dataset, tmp_path):
    build_all(tmp_path / "again", CFG, SCALE, CFG["seed"])
    assert file_hashes(tmp_path / "again") == file_hashes(dataset)


def test_different_seed_changes_data(dataset, tmp_path):
    build_all(tmp_path / "other", CFG, SCALE, CFG["seed"] + 1)
    assert file_hashes(tmp_path / "other")["master/vendor.csv"] != file_hashes(dataset)["master/vendor.csv"]


def _corrupt(src, tmp_path, rel, mutate):
    d = tmp_path / "bad"
    shutil.copytree(src, d)
    (d / "exports" / "ap_automation.db").unlink()        # check the CSVs, not the stale DB
    p = d / rel
    rows = list(csv.DictReader(open(p, newline="", encoding="utf-8")))
    mutate(rows)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return {c["check"] for c in validate(d, CFG, SCALE)["checks"] if c["status"] == "FAIL"}


def test_validation_catches_broken_foreign_key(dataset, tmp_path):
    failed = _corrupt(dataset, tmp_path, "master/purchase_order_line.csv",
                      lambda rows: rows[0].update(po_id="PO-2026-999999"))
    assert "FK purchase_order_line.po_id -> purchase_order.po_id" in failed


def test_validation_catches_bad_arithmetic(dataset, tmp_path):
    failed = _corrupt(dataset, tmp_path, "source_truth/invoice_line.csv",
                      lambda rows: rows[0].update(line_amount="1.23"))
    assert "invoice_line: amount = qty x price, tax = amount x rate(tax_code)" in failed


def test_validation_catches_payment_on_blocked_invoice(dataset, tmp_path):
    def release(rows):
        held = next(r for r in rows if r["final_status"] == "ON_HOLD")
        held["payment_ready"] = "true"
    failed = _corrupt(dataset, tmp_path, "pipeline_output/invoice_decision.csv", release)
    assert "No blocked (ON_HOLD) invoice is payment-ready, approved or paid" in failed


def test_validation_catches_unlabelled_duplicate(dataset, tmp_path):
    def dup(rows):
        rows[1].update(vendor_id=rows[0]["vendor_id"], vendor_invoice_number=rows[0]["vendor_invoice_number"])
    failed = _corrupt(dataset, tmp_path, "source_truth/invoice.csv", dup)
    assert "Repeated (vendor, invoice number) only where labelled DUPLICATE, pair recorded" in failed

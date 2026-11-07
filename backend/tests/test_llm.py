"""LLM integration tests with a fake Claude client (no network, no API key needed)."""
import csv
import json
from datetime import date
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

pytest.importorskip("anthropic")

from ap_automation.__main__ import build_all  # noqa: E402
from ap_automation.common import load_config, read_csv, sha256_text  # noqa: E402
from ap_automation.generator.documents import render, render_unstructured  # noqa: E402
from ap_automation.llm import Claude, LLMError  # noqa: E402
from ap_automation.llm.copilot import build_context, explain  # noqa: E402
from ap_automation.llm.extractor import hybrid_extract  # noqa: E402
from ap_automation.pipeline.workflow import run_pipeline  # noqa: E402

CFG = load_config()
INV = {"vendor_invoice_number": "APEX-1042", "invoice_date": date(2026, 3, 5), "po_id": "PO-2026-000001",
       "currency": "USD", "payment_terms": "NET30", "subtotal": D("2500.00"), "tax_amount": D("450.00"),
       "stated_total": D("2950.00"), "channel": "PDF_UPLOAD"}
LINES = [{"line_number": 1, "sku": "SKU-ITH-0001", "description": "Laptop 14in i7", "quantity": 2,
          "unit_price": D("1250.00"), "tax_code": "TX18", "line_amount": D("2500.00")}]
VENDOR = {"vendor_name": "Apex Metals Inc.", "tax_id": "12-3456789"}


def payload(inv=INV, lines=LINES, vendor=VENDOR):
    return {"vendor_name": vendor["vendor_name"], "vendor_tax_id": vendor["tax_id"],
            "vendor_invoice_number": inv["vendor_invoice_number"], "invoice_date": str(inv["invoice_date"]),
            "po_number": inv["po_id"] or "", "currency": inv["currency"], "payment_terms": inv["payment_terms"],
            "subtotal": str(inv["subtotal"]), "tax_amount": str(inv["tax_amount"]),
            "stated_total": str(inv["stated_total"]),
            "lines": [{"line_number": int(l["line_number"]), "sku": l["sku"], "description": l["description"],
                       "quantity": int(l["quantity"]), "unit_price": str(l["unit_price"]), "tax_code": l["tax_code"],
                       "line_amount": str(l["line_amount"])} for l in lines]}


class FakeAnthropic:
    """Mimics client.beta.messages.create; records every request."""

    def __init__(self, reply, stop_reason="end_turn"):
        self.reply, self.stop_reason, self.calls = reply, stop_reason, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        body = self.reply(kw) if callable(self.reply) else self.reply
        return SimpleNamespace(stop_reason=self.stop_reason, model=kw["model"],
                               content=[SimpleNamespace(type="text", text=json.dumps(body))],
                               usage=SimpleNamespace(input_tokens=900, output_tokens=200))


def test_rules_handle_known_layouts_without_calling_claude():
    fake = FakeAnthropic(payload())
    ex = hybrid_extract(render(INV, LINES, VENDOR, "ISO", "Buyer"), Claude(fake))
    assert ex["extraction_method"] == "RULES" and fake.calls == []


def test_claude_reads_free_form_document_the_rules_cannot():
    text = render_unstructured(INV, LINES, VENDOR)
    fake = FakeAnthropic(payload())
    ex = hybrid_extract(text, Claude(fake))
    assert ex["extraction_method"] == "LLM" and ex["confidence"] == 1
    assert ex["invoice_date"] == date(2026, 3, 5) and ex["stated_total"] == D("2950.00")
    assert ex["lines"][0]["unit_price"] == D("1250.00") and ex["lines"][0]["quantity"] == 2
    req = fake.calls[0]
    assert req["model"] == "claude-opus-5-5" and req["fallbacks"] == "default"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert text in req["messages"][0]["content"]          # document passed as delimited data


def test_claude_failure_falls_back_to_rules_result():
    fake = FakeAnthropic(payload(), stop_reason="refusal")
    ex = hybrid_extract(render_unstructured(INV, LINES, VENDOR), Claude(fake))
    assert ex["extraction_method"] == "RULES" and "declined" in ex["llm_error"]
    with pytest.raises(LLMError):
        Claude(FakeAnthropic(payload(), stop_reason="max_tokens"))("s", "u", {}, "low")


def test_copilot_never_sees_ground_truth_and_is_advisory():
    detail = {"decision": {"invoice_id": "INV-X", "primary_exception": "PRICE_VARIANCE"},
              "ground_truth": {"scenario": "PRICE_VARIANCE"}, "document": {"text": "..."}, "exceptions": []}
    reply = {"summary": "Price is 12% above PO.", "root_cause": "Vendor used list price.",
             "recommended_action": "Ask vendor for a credit note.", "confidence": "high",
             "draft_message": {"recipient": "vendor", "subject": "Price variance", "body": "Hello..."}}
    fake = FakeAnthropic(reply)
    out = explain(detail, Claude(fake))
    assert out["advisory_only"] and out["summary"].startswith("Price")
    assert "ground_truth" not in build_context(detail)
    assert "scenario" not in fake.calls[0]["messages"][0]["content"]


def test_pipeline_uses_claude_only_for_unreadable_document(tmp_path):
    out = tmp_path / "ds"
    build_all(out, CFG, 0.1, CFG["seed"])
    # Replace one inbox document with a free-form letter of the same invoice.
    src = read_csv(out / "source_truth" / "invoice.csv")[0]
    lines = [{**l, "quantity": int(l["quantity"]), "unit_price": D(l["unit_price"]), "line_amount": D(l["line_amount"])}
             for l in read_csv(out / "source_truth" / "invoice_line.csv") if l["invoice_id"] == src["invoice_id"]]
    vendor = next(v for v in read_csv(out / "master" / "vendor.csv") if v["vendor_id"] == src["vendor_id"])
    inv = {**src, "invoice_date": date.fromisoformat(src["invoice_date"]), "po_id": src["po_id"] or None,
           **{k: D(src[k]) for k in ("subtotal", "tax_amount", "stated_total")}}
    text = render_unstructured(inv, lines, vendor)
    (out / "inbox" / "documents" / f"{src['document_id']}.txt").write_text(text, encoding="utf-8", newline="\n")
    man = read_csv(out / "inbox" / "intake_manifest.csv")
    for m in man:
        if m["document_id"] == src["document_id"]:
            m["sha256"] = sha256_text(text)
    with open(out / "inbox" / "intake_manifest.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(man[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(man)

    def decision():
        return next(d for d in read_csv(out / "pipeline_output" / "invoice_decision.csv")
                    if d["document_id"] == src["document_id"])

    run_pipeline(out, CFG)                                  # rules only: cannot read it
    assert decision()["primary_exception"] == "EXTRACTION_INCOMPLETE"

    fake = FakeAnthropic(payload(inv, lines, vendor))
    run_pipeline(out, CFG, Claude(fake))                   # hybrid: Claude reads it, normal controls apply
    gt = next(g for g in read_csv(out / "ground_truth" / "ground_truth.csv") if g["document_id"] == src["document_id"])
    assert decision()["final_status"] == gt["expected_final_status"]
    assert decision()["primary_exception"] == gt["expected_primary_exception"]
    assert len(fake.calls) == 1                             # only the unreadable document went to Claude

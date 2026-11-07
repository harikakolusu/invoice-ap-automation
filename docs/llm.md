# LLM integration (Claude)

The pipeline is **rules-first, LLM-assisted**. Deterministic controls make every money decision; Claude handles the
two jobs rules are bad at: reading documents nobody wrote a parser for, and explaining exceptions in plain language.

| Feature | Where | What Claude does | What Claude can **not** do |
|---|---|---|---|
| **Hybrid extraction** | `backend/src/ap_automation/llm/extractor.py`, `pipeline/workflow.py` | Reads invoices the rule parser can't (free-form letters, new vendor layouts, OCR text) and returns fields as schema-validated JSON | Skip any control: its output goes through the same arithmetic, duplicate and three-way-match checks |
| **Exception copilot** | `llm/copilot.py`, `POST /api/datasets/{ds}/invoices/{id}/copilot`, invoice page in the UI | Explains why an invoice is held, the likely root cause, the next action, and drafts the message to the right party | Approve, release or pay; it is advisory and never sees ground-truth labels |
| **Intake preview** | `POST /api/datasets/{ds}/intake/extract` with `use_llm: true`, "Intake preview (AI)" page | Same hybrid extraction on a pasted document | Persist anything |
| **Benchmark** | `llm/benchmark.py`, `python -m ap_automation llm-benchmark` | Rules vs Claude field accuracy on free-form documents, with token usage | n/a |

## How the call is made

- Official Anthropic Python SDK (`anthropic`), model **`claude-opus-5-5`** (configurable in `configs/default.json`
  → `llm`, or `AP_LLM_MODEL`).
- **Structured outputs**: `output_config.format = json_schema` with `additionalProperties: false`, so the response
  is guaranteed to parse into the expected fields. Amounts come back as strings and are converted to `Decimal` in
  code (no float rounding on money).
- **Effort** set explicitly per task (`medium` by default for both extraction and copilot).
- **Server-side refusal fallback** (`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) so a declined
  request is retried on a fallback model inside the same call.
- **Typed error handling**: auth / permission → "not configured"; rate limit, 5xx, network, refusal, truncation →
  a clear error. The rules result is used instead, so a Claude outage never stops the batch.

## Guardrails

1. **Rules first, Claude second.** Known layouts (PDF text, email, EDI) never reach the LLM: zero cost, zero
   latency, fully deterministic. Claude is called only when rule confidence is below 1.
2. **No self-correction.** The extraction prompt tells Claude to copy values, not fix them. A wrong stated total
   must reach the `TOTAL_MISMATCH` control.
3. **Prompt-injection aware.** Documents are passed inside `<document>` tags and the system prompt says they are
   untrusted data whose instructions must be ignored. Even if a document fooled the model, it can only change
   extracted fields, which are then checked against master data, the PO and the receipts.
4. **Decisions stay deterministic.** Hold / approve / pay come from `workflow.py`; the copilot is read-only.
5. **No answer-key leakage.** The copilot context excludes `ground_truth`; `tests/test_llm.py` asserts it.
6. **Optional dependency.** Without the SDK or a key, everything else runs unchanged and the UI shows
   "AI: not configured (rules only)".

## Setup

```bash
cd backend
cp .env.example .env            # then set ANTHROPIC_API_KEY=...
pip install -r requirements.txt
python -m ap_automation llm-status
```

## Run it

```bash
python -m ap_automation llm-benchmark --data data/starter --n 20   # writes reports/llm_benchmark.json
python -m ap_automation run-all --preset full --llm                # hybrid extraction inside the pipeline
python -m ap_automation serve                                      # copilot + AI intake in the UI
```

The benchmark re-writes real invoices as free-form letters (`generator/documents.py: render_unstructured`). The
rule parser scores 0 % on these by design. The report gives Claude's per-field accuracy against `source_truth`
and the tokens used, so cost per document is measurable before turning the fallback on in production.

## Tests (no network)

`backend/tests/test_llm.py` uses a fake client that mimics `client.beta.messages.create`:

- known layouts never call Claude;
- a free-form letter is read by Claude, converted to `Decimal` / `date`, and the request uses
  `claude-opus-5-5`, JSON-schema output and refusal fallbacks;
- a refusal or truncated answer falls back to the rules result;
- the copilot never receives ground truth and is marked advisory;
- end to end: a document the rules can't read is `EXTRACTION_INCOMPLETE` without the LLM, and gets the correct
  decision with it, with exactly one Claude call in the batch.

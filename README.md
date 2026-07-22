# LedgerLens — InvoiceIQ

Photographed invoices in, clean ledger out. Upload a photo or scan of an
invoice; a vision LLM (Gemini) extracts vendor, invoice number, date, line
items and totals with a **self-reported confidence score per field**. Fields
scoring under **0.8** are routed to a **human review queue** where you correct
or confirm them before the invoice enters the ledger. The ledger exports to
CSV in one click.

**Stretch goals**
- **Duplicate-invoice detection (working)** — every upload is perceptually
  hashed (8×8 average hash, `dedupe.py`); re-uploads within Hamming distance 5
  of an existing invoice are parked as duplicates instead of double-counting.
- **Multi-currency totals (partial)** — the ledger converts every invoice
  total to INR and shows a grand total. Conversion works end-to-end, but rates
  are a static table (`currency.py`), not a live FX API.

## Run it locally

Tested on macOS and Linux with Python 3.11.

```bash
git clone https://github.com/preetkabhishek-cell/ledgerlens-invoiceiq.git
cd ledgerlens-invoiceiq
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: paste your Gemini API key (free at https://aistudio.google.com/apikey)

python sample_invoices/make_samples.py   # generates demo invoices
python app.py                            # http://localhost:5000
```

Log in with the seeded test account: **evaluator@demo.com / Demo@2026**.

No API key handy? Set `MOCK_EXTRACTION=1` in `.env` — the app runs with a
canned extraction result so the full flow is still clickable.

### Docker

```bash
docker build -t ledgerlens .
docker run -p 5000:5000 --env-file .env ledgerlens
```

## Architecture

```
Browser --> Flask (app.py)
              |  upload
              v
        dedupe.py -- perceptual hash vs. existing invoices --> parked as duplicate
              | (new)
              v
        extraction.py -- Gemini 2.0 Flash, JSON mode, temperature 0
              |            prompt: prompts/extraction_prompt.txt
              v
        database.py (SQLite)
          fields with confidence < 0.8 -> review queue (human corrects/confirms)
          all fields >= 0.8 or reviewed -> ledger
              |
              v
        ledger view -- currency.py converts totals to INR -- CSV export
```

**Key decisions**
- *Structured JSON output over function calling* — the prompt lives in a
  plain-text file anyone can read and version, and retry logic is a simple
  "parse failed -> try again" loop.
- *Self-reported per-field confidence* — vision APIs don't expose token-level
  confidence for extraction, so the prompt makes the model score its own
  certainty with explicit calibration rules, and the eval script
  (`eval/eval_extraction.py`) checks those scores are honest (wrong answers
  must not come with high confidence).
- *SQLite over Postgres/Sheets* — single-user evaluation app; zero-config
  matters more than row locking here. The queries in `database.py` are plain
  SQL and would port to Postgres unchanged.
- *Flask over FastAPI/React* — server-rendered pages keep the whole flow in
  ~6 small files an evaluator can read top to bottom.

## Evaluation

```bash
python eval/eval_extraction.py               # real API
MOCK_EXTRACTION=1 python eval/eval_extraction.py   # plumbing check
```

Prints per-field accuracy on the labelled sample invoices and flags
"overconfident misses" (wrong value with confidence >= 0.8) — the failure mode
that would silently corrupt the ledger.

## Known limitations

- Handwritten invoices score low confidence and always route to review (by
  design, but it means no straight-through processing for them).
- No batch upload — one invoice per request.
- FX rates are static (see stretch note above).
- Single review threshold (0.8) for all fields; per-field thresholds (e.g.
  stricter for `total`) would be the next improvement.

## Repo map

```
app.py                     Flask routes (auth, upload, review, ledger, CSV)
extraction.py              Gemini call + JSON validation + retries + mock mode
database.py                SQLite schema and all queries
dedupe.py                  perceptual hash duplicate detection (stretch 1)
currency.py                static-rate INR conversion (stretch 2, partial)
prompts/extraction_prompt.txt   the extraction prompt (versioned)
eval/eval_extraction.py    per-field accuracy + confidence honesty check
sample_invoices/make_samples.py generates demo invoices (incl. a near-duplicate)
templates/, static/        server-rendered UI
```

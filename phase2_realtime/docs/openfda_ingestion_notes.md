# openFDA Drug Shortage Ingestion — Implementation Notes

**Module:** `phase2_realtime/data_ingestion/openfda_shortages.py`
**DB:** `phase2_data/openfda.db`
**Date:** 2026-05-05

---

## What this module does

Daily pull of oncology shortage records from `api.fda.gov/drug/shortages.json`.
Deduplicates via `record_hash = MD5(generic_name | package_ndc | initial_posting_date)`.
Persists to SQLite. Exposes `get_active_shortages()` for downstream MAB labeling.

---

## API behaviour observed

- **Endpoint:** `https://api.fda.gov/drug/shortages.json`
- **Oncology filter:** `search=therapeutic_category:"Oncology"` — works reliably.
- **Pagination:** `skip` + `limit` params. Meta block returns `total`; paginate until `skip >= total`.
- **Rate limits:** 240 req/min unauthenticated. `OPENFDA_API_KEY` in `.env` raises daily quota to 120k/day.
- **Error responses:** API returns `{"error": {"code": "NOT_FOUND", "message": "No matches found."}}` when a paginated skip exceeds total. Module handles this cleanly — stops pagination without raising.
- **Date fields:** Dates are nested as `[{"type": "Initial Posting", "date": "YYYYMMDD"}, ...]`. The module flattens these to `initial_posting_date`, `update_date`, `change_date`.
- **Status values observed:** "Current shortage", "Resolved shortage", "Discontinued" — `get_active_shortages()` filters to "Current shortage" only.

---

## Schema decisions

- `record_hash` as PRIMARY KEY enables `INSERT OR IGNORE` deduplication without a SELECT-then-INSERT pattern.
- `raw_json` stores the full API record for downstream MAB labeling — avoids re-fetching.
- `ingested_at` is UTC ISO string, not a SQLite DATETIME, to avoid timezone ambiguity.
- Indexes on `(status, therapeutic_category)` and `(initial_posting_date, update_date)` support the two common query patterns.

---

## Integration with OncoSupply pipeline

1. `run_daily_cycle()` → MAB labeling layer reads `get_active_shortages()`.
2. US shortage onset is a 30–120 day leading indicator for LATAM (shared API manufacturers).
3. `raw_json` preserves `openfda{}` nested block (rxcui, pharm_class_epc, pharm_class_moa) for future molecule-level crosswalk with PAHO Strategic Fund denominator.

---

## Running

```bash
# Unit tests only (no network)
pytest phase2_realtime/tests/test_openfda_shortages.py -v

# Include live API test
pytest phase2_realtime/tests/test_openfda_shortages.py -v -m live

# Smoke test
python3 -c "from phase2_realtime.data_ingestion.openfda_shortages import fetch_oncology_shortages; print(len(fetch_oncology_shortages(limit=10)))"
```

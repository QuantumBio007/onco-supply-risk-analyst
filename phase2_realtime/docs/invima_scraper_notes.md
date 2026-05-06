# INVIMA Scraper — Implementation Notes

**Status:** v1, 2026-05-05. 36/40 tests pass (4 skipped = live tests gated on `INVIMA_LIVE_TEST`).

## Two streams ingested

1. **Desabastecimientos index** — `https://www.invima.gov.co/productos-vigilados/medicamentos-y-productos-biologicos/desabastecimientos`. UTF-8.
2. **Alertas sanitarias** — `https://app.invima.gov.co/alertas/medicamentos-productos-biologicos`. UTF-8.

## ⚠ Architectural finding: desabastecimientos returns PDF metadata, NOT products

The INVIMA shortage page does **not** publish structured per-product shortage data. It publishes monthly PDF reports (e.g., "Listado de abastecimiento y desabastecimiento de medicamentos en seguimiento — Marzo 2026"). The scraper extracts:
- `producto`: report title (NOT a drug name)
- `principio_activo`: empty (lives inside the PDF)
- `registro_sanitario`: empty
- `tipo`: report classification (`abastecimiento_y_desabastecimiento` / `desabastecimiento` / `disponibilidad`)
- PDF URL for downstream extraction

**To get drug-level shortage signals from Colombia, you must download and parse the monthly PDFs.** That is a separate next-sprint task — not blocked, just not done. Until then, INVIMA shortage signal is at the report-publication-event level (monthly cadence), not the per-drug level.

This contrasts with ANMAT, where `Listado_Faltantes.asp` returns a structured per-drug table inline.

## Storage

`phase2_data/invima.db` SQLite. Two tables (`invima_shortages`, `invima_alerts`), MD5-hashed natural-key dedup, `INSERT OR IGNORE`. `raw_html` column on shortages table for downstream re-parsing.

## Polite scraping

- 1 req/sec rate limit.
- User-Agent: `OncoSupply-research/0.1 (academic research; cmart156@jh.edu)`.
- 5-second timeout, single retry.

## Departures from spec / bugs found in v1

Two parser bugs caught during test debugging (post-Sonnet handoff):

1. **Alert tipo classifier consumed drug titles.** The `_parse_alertas_table()` function classified any cell containing `"retiro"` or `"comunicado"` as `tipo_alerta`. Drug titles like "BEVACIZUMAB ... Retiro voluntario lote BV2024-001" were consumed as tipo, leaving `titulo` empty. Fixed by requiring exact short-string match on canonical types (≤30 chars, lowercase equals one of the canonical strings).

2. **`_classify_report_tipo()` precedence bug.** "desabastecimiento" contains "abastecimiento" as substring, so `"abastecimiento" in lower` always matched both. Fixed with negative-lookbehind regex `(?<!des)abastecimiento` to detect standalone "abastecimiento".

## Known gaps for next implementer

- **PDF download + parsing** for monthly desabastecimiento reports — required for drug-level Colombia signal.
- **Schema drift monitoring.** INVIMA's site is a modern Drupal-style portal; HTML structure can change without notice. Add content-shape assertions before production.
- **Live-test gating** via `INVIMA_LIVE_TEST` env var; live tests don't run by default.

## Cross-LATAM portability

Same pattern as ANMAT (regulator scraper + alert scraper). Ports to ANVISA (Brazil) next. ANVISA is rumored to have actual structured shortage tables, which would put it ahead of INVIMA in data quality.

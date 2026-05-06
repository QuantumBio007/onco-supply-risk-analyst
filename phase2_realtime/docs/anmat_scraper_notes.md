# ANMAT Scraper — Implementation Notes

**Status:** v1, 2026-05-05. 23/25 tests pass (2 skipped = live tests gated on `ANMAT_LIVE_TEST` env var).

## Three streams ingested

1. **Shortage list** — `http://www.anmat.gob.ar/listados/Listado_Faltantes.asp` (Latin-1 ASP). Per-row: `producto, ifa, laboratorio, certificado, fecha_notificacion, estado, motivo, fecha_normalizacion`.
2. **Alerts archive** — `http://www.anmat.gob.ar/alertas_medicamentos.asp` (Latin-1 ASP). Per-row: `fecha, titulo, descripcion, pdf_url`. PDF download is out of scope; URL is stored.
3. **Boletín Oficial Disposiciones (Rubro 5006)** — `https://www.boletinoficial.gob.ar/seccion/primera/?rubro=5006` (UTF-8). Per-row: `numero_disposicion, fecha, sumario, detalle_url`.

## Storage

`phase2_data/anmat.db` SQLite. Three tables (`anmat_shortages`, `anmat_alerts`, `anmat_dispositions`), each keyed on a deterministic MD5 hash of natural-key fields. `INSERT OR IGNORE` makes re-ingestion idempotent. `raw_html` column on `anmat_shortages` for downstream re-parsing if schema drifts.

## Encoding

- Two `anmat.gob.ar` ASP pages: `response.encoding = 'latin-1'` is set explicitly. Mojibake (e.g., `Ã©` instead of `é`) on accented characters indicates encoding bug.
- Boletín Oficial: UTF-8 default works.

Fixtures under `phase2_realtime/tests/fixtures/anmat/` are saved as binary Latin-1 files for the ASP streams to validate end-to-end decoding.

## Polite scraping

- 1 req/sec rate limit (`time.sleep`).
- User-Agent: `OncoSupply-research/0.1 (academic research; cmart156@jh.edu)`.
- 5-second timeout, single retry on failure.

## Departures from spec

- `_extract_disposicion_number()` regex was case-sensitive in v1. Fixed to use `re.IGNORECASE` after a test caught all-caps "DISPOSICION" headers failing extraction. Patterns now match `Disposición`, `DISPOSICION`, `Disp.`, etc.

## Known gaps for next implementer

- PDF parsing of `/comunicados/` PDFs not implemented. Lot-level recall data lives there.
- Boletín Oficial detail pages (`detalleAviso/`) not recursively followed; we capture only the listing page summaries.
- No alerting on schema drift. If ANMAT changes the legacy ASP page layout, the parser will silently produce empty rows. Add a content-shape monitor before production.
- Live tests run only when `ANMAT_LIVE_TEST=1` to avoid hitting the site on every CI run.

## Cross-LATAM portability

This architecture (regulator scraper + gazette scraper) is designed to port to ANVISA (Brazil), INVIMA (Colombia), DIGEMID (Peru), ISP (Chile), COFEPRIS (Mexico). INVIMA is the next planned module.

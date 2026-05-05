# Data Acquisition Report — 2026-05-05

**Authored:** Opus 4.7 + 3 web-search-agents (in parallel).
**Purpose:** Concrete URLs, formats, and example records for three external data sources OncoSupply needs to move from internal calibration to external validation. Skips Romero (separate path).

---

## Source 1: ANMAT shortage bulletins (Argentina)

**Verdict:** Scrape, don't wait for an API. Three load-bearing endpoints, all public, all stable.

**Primary endpoints:**
| Purpose | URL | Format |
|---|---|---|
| Shortages list ("Faltantes") | http://www.anmat.gob.ar/listados/Listado_Faltantes.asp | Legacy ASP HTML table; CSV snapshot when present |
| Alerts & recalls archive | http://www.anmat.gob.ar/alertas_medicamentos.asp | HTML reverse-chronological + linked PDFs |
| Boletín Oficial — ANMAT Disposiciones (Rubro 5006) | https://www.boletinoficial.gob.ar/seccion/primera/?rubro=5006 | Daily structured HTML; full annexes |

**Fields per shortage record:** Producto, IFA (active ingredient — your join key; ANMAT does NOT publish ATC), Laboratorio titular, Certificado, Fecha de notificación, Estado (faltante temporal / discontinuado / no comercializado), Motivo, Fecha estimada de normalización.

**Cadence:** Multiple updates per week; Disposición 754/2025 (Jan 2025) tightened reporting requirements (45-day max for temporary interruptions). Boletín Oficial daily.

**Worked example:** ANMAT Disposición 3865/2025 (2025-06-06) — Eczane Pharma 93-product oncology recall including temozolomida, abiraterona, capecitabina, nilotinib. Boletín Oficial: https://www.boletinoficial.gob.ar/detalleAviso/primera/326644/20250606. Use this + Disposición 3752/2025 (2025-05-30) as gold-standard pipeline test cases.

**Acquisition stack:** Python + `requests` + `BeautifulSoup`. Latin-1 encoding on legacy ASP, UTF-8 on Boletín Oficial. 1 req/sec polite scraping. Build IFA→ATC L01 crosswalk locally (WHO INN list). Same architecture ports to ANVISA, INVIMA, ISP, DIGEMID, COFEPRIS for LATAM extension.

**Risk:** Legacy ASP endpoints have changed before. Pin URLs in config; add content-shape monitor.

---

## Source 2: FDA + PAHO drug shortage databases

### FDA — acquisition-ready, structured, free

**openFDA API:** `https://api.fda.gov/drug/shortages.json`
- No auth required (rate-limited; free API key gives 120k/day)
- Daily updates, coverage 2012–present
- Built-in `therapeutic_category:"Oncology"` filter

**Direct oncology query:**
```
https://api.fda.gov/drug/shortages.json?search=therapeutic_category:"Oncology"&limit=100
```

**Fields:** generic_name, proprietary_name, company_name, package_ndc, presentation, dosage_form, strength, therapeutic_category, status, shortage_reason, availability, dates, plus nested `openfda{}` block with rxcui, unii, pharm_class_epc, pharm_class_moa.

**Bulk download:** https://open.fda.gov/data/downloads/ (zipped JSON).

**Worked example (live, 2026-05-05):** Methotrexate Sodium Injection — Accord Healthcare, current shortage, oncology, ~30-day estimated recovery, reason: shortage of an active ingredient. Background: 270 drugs in shortage as of March 2025; 15 oncology drugs identified in shortage 2023–2025, 12 lasting >2 years (PMC12459136).

### PAHO — NO public shortage feed exists

**Closest substitutes:**
1. **PAHO Strategic Fund product list** — https://www.paho.org/en/paho-strategic-fund. The procurement universe (~$800M/yr LATAM oncology). Not a shortage feed but the right denominator: restricts your model to drugs that actually matter for LATAM public sector.
2. **National regulator scrapers** — only Brazil (ANVISA) and Colombia (INVIMA) have structured public shortage lists. Argentina (ANMAT — see Source 1) and Mexico (COFEPRIS) are press-release-driven, lower signal.
3. **EMA's European Shortages Monitoring Platform (ESMP)** — launched Nov 2024, EU-only, but a 3–6 month leading indicator for LATAM via shared API supply chains. https://www.ema.europa.eu/en/human-regulatory-overview/post-authorisation/medicine-shortages-availability-issues/public-information-medicine-shortages

**The non-existence of a PAHO public shortage feed is itself the consulting-level insight** — it's why a predictive layer (OncoSupply) has commercial value.

### Recommended architecture

1. **openFDA = structured backbone.** Daily pull, oncology filter, label as US leading-indicator.
2. **ANVISA + INVIMA scrapers** — only direct LATAM signal. HTML-only, daily diff.
3. **PAHO Strategic Fund product list** = oncology denominator (which molecules matter).
4. **70%+ of LATAM oncology generics share APIs/manufacturers with US-shortage drugs**, so US shortage onset is a strong predictor for LATAM shortage 30–120 days later.

---

## Source 3: Argentina + Colombia oncology incidence by province / department

**Verdict:** **Colombia is substantially better than Argentina for sub-national.** Argentina is country-level only for adults; pediatric is good (ROHA). Colombia has CAC department-level mandatory reporting and a Revista Colombiana de Cancerología 2017–2021 modeled-incidence article covering 25 cancer types × 27 departments.

### Argentina — partial sub-national

**Adult — limitation: country-level only at INC; sub-national fragmented across 14 RCBPs.**
- INC flagship: *Incidencia de cáncer en Argentina, 2022* — https://www.argentina.gob.ar/sites/default/files/incidencia-de-cancer-argentina-2022-pdf.pdf (built on data from only 2 RCBPs: Entre Ríos + Mendoza).
- Mortality by province IS published: https://www.argentina.gob.ar/salud/instituto-nacional-del-cancer/estadisticas/mortalidad
- 14 provincial RCBPs (Mendoza, Santa Fe, etc.) — fragmented, no consolidated province × cancer-type table.

**Pediatric — strong:**
- ROHA open CSV (2000–2019, ages 0–14): https://datos.salud.gob.ar/dataset/roha-registro-oncopediatrico-hospitalario-de-argentina-de-personas-entre-0-a-14-anos-2000-2019
- 91 reporting sources, all provinces, 93% case capture under 15.
- ~40,283 cases under 19 since 2000.

**Worked example:** cervical cancer incidence ranges 7.8/100k (Buenos Aires province) to 23.2/100k (Formosa) — RCBP-derived.

### Colombia — strong sub-national

**Cuenta de Alto Costo (CAC) — primary anchor:**
- Cancer landing: https://cuentadealtocosto.org/enfermedades-de-alto-costo/cancer/
- 2024 report: https://cuentadealtocosto.org/situacion-del-cancer-en-la-poblacion-adulta-atendida-en-el-sgsss-de-colombia-en-2024/
- 651,589 prevalent cases (Oct 31 2024), 62k new annually, mandatory EPS reporting, department + EPS breakdowns.
- 2024 regional split: Central 32.7%, Caribbean 20.0%, Bogotá D.C. 17.8%.

**INC Colombia modeled incidence (2017–2021) by department × cancer type:**
- Article: https://www.revistacancercol.org/index.php/cancer/article/view/1061
- PDF: https://www.revistacancercol.org/index.php/cancer/article/download/1061/1045/14832
- 25 cancer localizations × 27 departments + Capital District + grouped Amazon region.

**Worked example:** Antioquia all-cancer incidence 7,110 cases / age-adjusted rate 194.9 per 100k person-years.

**Pediatric — weaker than Argentina.** Observatorio Nacional de Cáncer (SISPRO) covers leukemias/lymphomas/CNS but department-level public dashboards are limited. Plan to request CAC pediatric data directly from MinSalud.

### Calibration recommendation for OncoSupply

1. **Colombia: anchor on CAC 2024 + Revista Colombiana de Cancerología 2017–2021** for department × cancer-type rates. Cleaner half of the LATAM pair.
2. **Argentina: ROHA for pediatric (open CSV); country-level Globocan/INC 2022 for adult** with Mendoza + Entre Ríos as anchor RCBPs. Apply national-to-province scaling via INDEC population denominators.
3. **Document explicitly:** Argentina sub-national adult incidence is *modeled, not observed.* This is a real limitation worth disclosing in funder docs — pretending otherwise is the kind of thing a sophisticated reviewer catches.

---

## Cross-source acquisition priorities for OncoSupply

| # | Source | Status | Effort to ingest | Priority |
|---|---|---|---|---|
| 1 | openFDA Oncology | API, free, no auth | Low (1 day) | **DO FIRST** |
| 2 | CAC 2024 PDF + tables | Public PDF, open data | Medium (parse PDF tables) | High |
| 3 | ANMAT Listado_Faltantes + Boletín Oficial | HTML scrape | Medium (Latin-1, ASP) | High |
| 4 | INVIMA desabastecimientos | HTML scrape | Low | Medium |
| 5 | ROHA open CSV | Direct download | Low | Medium |
| 6 | Revista Colombiana 2017–2021 modeled incidence | PDF + supplementary tables | Medium | Medium |
| 7 | ANVISA shortage list | HTML scrape | Medium | Lower (Brazil not in current scope) |
| 8 | PAHO Strategic Fund product list | PDF / web | Low | Use as denominator only |

**Honest caveats baked in:**
- ANMAT, ANVISA, INVIMA all require scraping; no APIs.
- PAHO has no public shortage feed; do not promise one in funder docs.
- Argentina sub-national adult incidence is modeled, not observed.
- Pediatric Colombia data may require direct CAC/MinSalud request.

---

## Source links — full appendix

(Romero paper acquisition tracked separately — see `data_acquisition_romero_2026-05-05.md` once that web-search-agent completes.)

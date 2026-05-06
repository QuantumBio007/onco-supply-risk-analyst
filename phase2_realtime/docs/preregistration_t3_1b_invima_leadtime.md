# T3.1b Pre-Registration — INVIMA Retrospective Lead-Time Signal Analysis

**Authored:** 2026-05-06 (before any analysis code is written or committed)
**Author:** Carlos Martino (with Opus 4.7 review)
**Purpose:** Lock down what we will and will NOT claim from a retrospective signal-precedence analysis on INVIMA's longitudinal drug shortage registry, BEFORE running the analysis. Any post-hoc threshold loosening is itself a finding, not a tuning move.

---

## Honest scope of this test

This is **NOT** the T3.1 predictive backtest specified in `preregistration_t3_1_amparo_backtest.md`. That test requires:
1. ANMAT historical bulletins ingested (currently 0 rows — scraper has known production bug)
2. Historical news archive aligned to event dates (we have no historical news ingestion)
3. Replay infrastructure to feed news through the live classifier in chronological order

This document pre-registers **Plan B**: a retrospective analysis testing whether INVIMA's intermediate `monitorizacion` status — which is publicly available in the same monthly PDFs as the final `desabastecido` flag — provides a leading signal that a careful registry monitor (such as OncoSupply) could exploit to give downstream consumers earlier warning.

**This test cannot prove the live OncoSupply news pipeline predicts shortages.** It can only prove (or refute) that INVIMA's own data has detectable lead-time structure, and that secondary signals from openFDA can corroborate INVIMA events. Any funder-facing communication MUST distinguish these claims from a true predictive backtest.

The full T3.1 predictive backtest remains DEFERRED pending (a) Marin reply on amparo dataset access, OR (b) ANMAT scraper fix + historical news ingestion sprint.

---

## Data sources

| Source | File | Span | Records | Granularity |
|---|---|---|---|---|
| INVIMA monthly PDFs | `phase2_data/invima.db` / `invima_drug_shortages` | 2023-06 → 2025-09 | 6,467 (283 oncology) | per (drug, formulation, snapshot) |
| openFDA shortage registry | `phase2_data/openfda.db` / `openfda_shortages` | live (snapshots from 2025) | 118 oncology | per drug record with `initial_posting_date` |

INVIMA snapshots available: **2023-06, 2023-12, 2024-01, 2024-04, 2024-08, 2024-12, 2025-01, 2025-06, 2025-09** (9 snapshots, uneven gaps of 1–5 months).

---

## Hypotheses

### H1 — INVIMA `monitorizacion` provides ≥1 snapshot of lead-time before `desabastecido*`

**Population (pre-registered filter, no exceptions):**
- `is_oncology = 1`
- Unit of analysis = (`inn_normalized`, `producto_canonical`) where `producto_canonical` is `producto_raw` lowercased and stripped of whitespace and trailing concentration tokens (the literal canonicalization rule is locked in the analysis script BEFORE the script runs).
- Include only formulations whose FIRST observed status in our window is benign (`monitorizacion`, `riesgo`, or `no_desabastecido`) and that subsequently transition to a shortage state (`desabastecido`, `desabastecido_lmvnd`, `desabastecido_lmvnd_pendiente`, `desabastecido_no_lmvnd`). Drugs already in `desabastecido*` at first observation are EXCLUDED from H1 (no observable lead-time) and reported in a separate "left-truncated" count.

**Lead-time metric:**
- For each qualifying formulation, count the number of INVIMA snapshots between the FIRST `monitorizacion`/`riesgo` snapshot and the FIRST `desabastecido*` snapshot. Snapshots are counted as ordinal positions in the 9-snapshot ordered list, NOT as calendar months (snapshot intervals are uneven).
- If the formulation goes monitorizacion→desabastecido in CONSECUTIVE snapshots, lead-time = 1.

**Pass criterion:** Median observable lead-time ≥ 1 snapshot (i.e., the warning signal precedes the shortage flag in at least half of qualifying cases).

**Null criterion:** Median observable lead-time = 0 OR fewer than 3 qualifying formulations (insufficient power).

**Partial-null criterion:** Lead-time ≥ 1 in some cases but the qualifying-vs-left-truncated ratio is below 0.30 — i.e., most shortage events are observed at first window entry, so the leading-signal claim does not generalize.

### H2 — openFDA `initial_posting_date` precedes the corresponding INVIMA shortage flag

**Population:**
- Drugs where (a) the openFDA `generic_name` matches an INVIMA `inn_normalized` after Spanish-to-English normalization (e.g., `carboplatino` → `carboplatin`, `metotrexato` → `methotrexate`), AND (b) the drug appears as `desabastecido*` or `descontinuado` in INVIMA at any point in our window.
- The match rule is locked in the analysis script BEFORE it runs and includes only INNs in the project's existing `INN_WHITELIST`. Cross-database name normalization edge cases are reported, not silently dropped.

**Precedence metric:**
- For each matched drug, compute `lead_days = INVIMA_first_shortage_pub_date − openFDA_initial_posting_date`. Positive = openFDA leads INVIMA.
- INVIMA `pub_date` is approximated by the first day of the snapshot's `report_period` (e.g., 2023-12 → 2023-12-01). This is a coarse approximation — actual PDF publication dates differ — and the rounding direction is documented.

**Pass criterion:** Median `lead_days` > 0 across matched drugs (openFDA flags BEFORE INVIMA).

**Null criterion:** Median `lead_days` ≤ 0 OR fewer than 2 matched drugs.

### H3 — Drugs reaching `descontinuado` had ≥1 prior `monitorizacion` or `desabastecido*` snapshot

**Population:**
- All oncology formulations (`inn_normalized`, `producto_canonical`) where the FIRST observation in our window is `descontinuado`. These are LEFT-TRUNCATED — we cannot observe their pre-discontinuation status from our data.
- All oncology formulations whose status transitions to `descontinuado` from a non-`descontinuado` initial status. These are OBSERVABLE.

**Pass criterion:** ≥ 80% of OBSERVABLE descontinuado formulations had at least 1 prior `monitorizacion` or `desabastecido*` snapshot before reaching `descontinuado`.

**Null criterion:** < 80% of observable cases show prior signal — i.e., descontinuado appears without warning often enough to undermine the leading-signal claim.

**Mandatory reporting:** Even if H3 passes on the OBSERVABLE subset, we MUST also report the count of left-truncated formulations as an explicit limitation. If left-truncated count > observable count, the H3 verdict is downgraded from PASS to PARTIAL-PASS regardless of the observable-subset percentage.

---

## Forbidden moves (enumerate, never apply)

- **Loosening any of the pre-registered thresholds** (1 snapshot for H1, 0 days for H2, 80% for H3) to make a borderline result pass.
- **Excluding drugs from the population to remove unfavorable cases.** If a drug is in the pre-registered population, it is included regardless of how it scores.
- **Reclassifying multi-formulation drugs to inflate N.** Each (`inn_normalized`, `producto_canonical`) tuple is one observation. Carboplatin polvo liofilizado and carboplatin solución inyectable are separate observations even though they share `inn_normalized`.
- **Using `fecha_inicio` as a substitute for the snapshot ordinal in H1.** `fecha_inicio` is a self-reported date inside the PDF; it can be earlier than our first observation snapshot, which would inflate apparent lead-time without any actual prediction. Snapshot-based ordinal counts only.
- **Cherry-picking the openFDA `status` filter in H2** (e.g., excluding "To Be Discontinued"). All current shortage statuses count.
- **Reporting only the favorable hypothesis** if one passes and the others null. All three results are reported, with the relative weight of left-truncated cases prominent.

---

## Power and small-N honesty clause

Based on a quick pre-flight inspection (without running the analysis), the qualifying population for H1 appears to be ≤ 10 formulations, and for H2 ≤ 5 matched drugs. Statistical power is therefore LOW and any single edge case has outsize influence on the median.

The pre-registered position is: **report the medians and the underlying point counts, with explicit narrative on which 1–2 cases drive the result.** Do not run any inferential test (no p-values, no confidence intervals) — they would be misleading at this N. The deliverable is descriptive, with the descriptions tied to specific drug formulations a reviewer can verify.

If qualifying N for H1 is ≤ 2, H1 is automatically declared NULL regardless of the observed median — two data points cannot establish a median trend.

---

## What gets reported back

For each hypothesis: a one-paragraph result block with (a) measured numbers, (b) PASS / NULL / PARTIAL-NULL / PARTIAL-PASS verdict per the pre-registered criteria, (c) the specific drugs/formulations driving the result, (d) any forbidden moves declined and why they would have been needed.

A summary table listing every oncology formulation in the population with columns: `inn_normalized | producto_canonical | first_obs_period | first_obs_estado | first_monitorizacion_period | first_desabastecido_period | first_descontinuado_period | observable_leadtime_snapshots | left_truncated`.

---

## What this result lets us claim — and what it does NOT

**If H1 PASSES:** "INVIMA's `monitorizacion` status reliably precedes formal shortage declarations by ≥ 1 monthly registry cycle." A registry monitor (OncoSupply) reading the early signal can give downstream consumers earlier warning than waiting for the final flag.

**If H1 PASSES:** We CANNOT claim the live news pipeline predicts shortages. The lead-time exists in INVIMA's own data; we are not testing whether external news predicts INVIMA.

**If H2 PASSES:** "openFDA's US-based shortage registry typically flags a drug shortage before INVIMA does, by approximately N months." Cross-database surveillance is a leading indicator. Useful for funder communication: monitoring openFDA + Spanish-language news provides predictive coverage for LATAM shortages.

**If any hypothesis NULLs:** That is an honest finding worth reporting. Either the registry data does not have the lead-time structure we hoped for, or our snapshot resolution is too coarse, or our window starts after most events occur. Each of these has implications for the OncoSupply value proposition that should be communicated to advisors and funders.

---

## Result blocks (filled in after analysis runs)

### H1 — INVIMA monitorizacion → desabastecido lead-time
[To be filled in by `run_t3_1b_leadtime_analysis.py`]

### H2 — openFDA precedes INVIMA
[To be filled in by `run_t3_1b_leadtime_analysis.py`]

### H3 — descontinuado preceded by warning
[To be filled in by `run_t3_1b_leadtime_analysis.py`]

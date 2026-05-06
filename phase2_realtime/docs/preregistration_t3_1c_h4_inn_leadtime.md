# H4 Pre-Registration — INN-Level Lead-Time Signal Analysis

**Authored:** 2026-05-06 (before analysis script is committed or run)  
**Author:** Carlos Martino  
**Supersedes / extends:** `preregistration_t3_1b_invima_leadtime.md` H1 (INN+formulation level)

---

## Why H4 exists

H1 NULLed for two reasons:
1. Window truncation (shortage events preceded our earliest snapshot)
2. Product-name canonicalization discontinuity — INVIMA renames drugs across PDF versions, severing the (INN, producto_canonical) tracking thread

H4 addresses reason (2) by collapsing all formulation variants under the normalized English INN. If any formulation of carboplatin was in `monitorizacion` before any formulation of carboplatin reached `desabastecido*`, that is a lead-time observation at the INN level.

**What H4 cannot fix:** reason (1), window truncation. INNs already in shortage at our earliest snapshot remain left-truncated.

---

## Pre-flight disclosure

Before writing this document, a sample-size query was run to count qualifying INNs. This is permitted (it is a power check, not the hypothesis test). The result is disclosed here:

| INN | First warn period | First shortage period | Lead (snapshots) | Status |
|---|---|---|---|---|
| carboplatin | 2023-04 | 2023-12 | +2 | **QUALIFYING** |
| asparaginase | 2023-04 | 2023-04 | 0 | same snapshot |
| tamoxifen | 2023-04 | 2023-04 | 0 | same snapshot |
| methotrexate | 2025-09 | 2023-04 | −9 | warn after shortage |

**Expected qualifying N = 1.** Per the auto-NULL rule below, H4 will auto-NULL regardless of carboplatin's lead. This pre-registration is written to establish the methodology and record the honest finding, not to obtain a PASS verdict.

---

## Hypothesis

**H4:** At the INN level, `monitorizacion` or `riesgo` status for any formulation of an oncology INN precedes the first `desabastecido*` status for any formulation of that same INN by at least 1 snapshot.

---

## Population (locked, no exceptions)

- `is_oncology = 1`
- INN in the project's INN whitelist (`INN_WHITELIST` in `invima_pdf_parser.py`)
- Snapshot window: 11 snapshots, 2022-12 → 2025-09 (SNAPSHOT_ORDER locked in analysis script)
- Unit of analysis: **`inn_normalized`** — all formulations of the same INN are collapsed

---

## Definitions (locked)

**WARN_ESTADOS** = {`monitorizacion`, `riesgo`}

**SHORTAGE_ESTADOS** = {`desabastecido`, `desabastecido_lmvnd`, `desabastecido_lmvnd_pendiente`, `desabastecido_no_lmvnd`}

**`inn_first_warn_index`**: the minimum SNAPSHOT_INDEX over all rows for a given INN where `estado` ∈ WARN_ESTADOS. `None` if no warn status ever observed.

**`inn_first_shortage_index`**: the minimum SNAPSHOT_INDEX over all rows for a given INN where `estado` ∈ SHORTAGE_ESTADOS. INNs with no shortage entry are excluded from H4 population.

**`lead_snapshots`** = `inn_first_shortage_index` − `inn_first_warn_index` (positive = warn precedes shortage)

**Qualifying INN:** `inn_first_warn_index` is not None AND `lead_snapshots > 0`

**Left-truncated INN:** `inn_first_shortage_index == 0` (shortage at first snapshot) AND (`inn_first_warn_index` is None OR `inn_first_warn_index >= inn_first_shortage_index`)

---

## Pass / Null criteria

**Auto-NULL:** If qualifying N < 2, H4 is NULL regardless of observed lead-times. One data point cannot establish a median trend.

**Pass criterion:** Qualifying N ≥ 2 AND median `lead_snapshots` ≥ 1.

**Null criterion:** Qualifying N < 2, OR median `lead_snapshots` < 1.

**Expected verdict based on pre-flight:** AUTO-NULL (qualifying N = 1).

---

## Forbidden moves

- **Loosening qualifying criteria** (e.g., counting same-snapshot as lead=0 as a partial qualifier, or dropping the N≥2 floor) to make the carboplatin result look generalizable.
- **Treating H4 PASS as equivalent to H1 PASS.** H4 collapses formulation identity; any PASS result would apply to INN-level surveillance, not to formulation-specific product management.
- **Reporting only the carboplatin case** without explicitly noting it is the sole qualifying INN and that H4 auto-NULLs on power grounds.

---

## What H4 NULL means

H4 NULLing is itself a finding: in our 11-snapshot window, most oncology INNs that reached shortage either (a) appeared mid-shortage at first observation or (b) appeared simultaneously in warn and shortage status across different formulations in the same snapshot. The carboplatin case — where INVIMA monitored the drug 2 snapshots before shortage — is the exception, not the rule. 

The INN-level collapse does not rescue H1. The bottleneck is not canonicalization; it is the shortage wave peaking before our observation window.

---

## What gets reported

- Lead-time table by INN: `inn_normalized | first_warn_period | first_shortage_period | lead_snapshots | qualifying | left_truncated`
- Explicit H4 verdict per criteria above (expected: AUTO-NULL)
- Carboplatin result described as a case observation, not a hypothesis PASS
- Count of left-truncated vs. qualifying vs. same-snapshot INNs

---

## Relationship to other hypotheses

| Hypothesis | Unit | Warn→Shortage path | Status |
|---|---|---|---|
| H1 | (INN, producto_canonical) | Same canonical product must transition | NULL (naming + window) |
| H4 (this doc) | INN only | ANY formulation warn → ANY formulation shortage | NULL expected (window) |
| H2 | INN (cross-DB) | openFDA → INVIMA | PASS (118d median) |

H4 confirms that neither formulation-level nor INN-level within-INVIMA tracking yields a general lead-time signal in our current window. H2 (cross-database surveillance using openFDA) remains the only PASS result and the defensible claim for funder communication.

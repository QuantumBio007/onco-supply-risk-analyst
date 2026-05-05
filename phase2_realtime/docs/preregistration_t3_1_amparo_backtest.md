# T3.1 Numerical Backtest Pre-Registration — Romero Amparo Dataset

**Authored:** 2026-05-05 (before any commit touches the dataset)
**Owner:** Carlos | **Status:** LOCKED — must be committed to git before the data file is fetched, parsed, or inspected.

This is the broader pre-registration referenced by [MASTER_ACTION_PLAN.md](MASTER_ACTION_PLAN.md) T3.1 (open defect #1, "validation criteria not pre-registered"). It is distinct from `preregistration_phase2c.md`, which covers algorithm-closure on synthetic shocks. This one tests whether OncoSupply's risk predictions correlate with real Argentinian access-failure events.

## Dataset
Romero et al. 2024 amparo dataset: 405 federal and provincial amparo (legal injunction) cases 2017–2020, filed by patients to compel access to oncology drugs. Cited in `knowledge_base/docs/argentina_procurement_system.txt`. Public, not previously analyzed by this project.

## Hypothesis
Drug × province × quarter cells where OncoSupply predicts elevated stockout risk should over-represent amparo filings vs cells predicted as low risk.

## Primary outcome (locked)
Spearman rank correlation `ρ` between (a) predicted CVaR_90 from `supply_sim.simulate(drug, province=Argentina, scenario=Baseline)` per cell, run with the COUNTRY_PARAMS in effect at this commit, and (b) amparo filing count per cell, normalized by drug-class patient population (proxy: drug-class incidence × province population).

**Pass criterion:** ρ ≥ **0.40** with two-sided p < 0.05.
**Null criterion:** ρ < 0.20 OR p ≥ 0.05.
**Inconclusive:** 0.20 ≤ ρ < 0.40.

## Secondary outcome (locked)
Binary classification — top-quartile-predicted-risk cells vs bottom-quartile — predicting any-amparo-filed (yes/no) at the cell level.

**Pass criterion:** AUC ≥ **0.65**.

## Data scope (locked before fetch)
- **Drugs included:** cisplatin, carboplatin, doxorubicin, trastuzumab. Other oncology drugs in the Romero dataset are excluded (out of OncoSupply scope).
- **Provinces:** all in Romero dataset that have ≥3 filings across the 4 drugs over the 4-year window. Provinces below threshold dropped to avoid sparse-cell instability.
- **Time:** quarterly bins, 2017Q1–2020Q4 (16 quarters per drug × province cell).
- **Population normalization:** drug-class incidence rate × province population (INDEC 2018 census). If incidence rate unavailable for a class, use national oncology incidence rate × province population share. The choice between these is locked at fetch time and recorded in the analysis log.

## Forbidden moves
- Re-running OncoSupply with retuned `COUNTRY_PARAMS` after seeing amparo data. The simulation parameters are frozen at the commit hash listed at the top of the analysis log.
- Dropping drugs, provinces, or quarters after seeing the correlation result.
- Switching from Spearman to Pearson, or from AUC to F1, after seeing the result.
- Adding covariates (province GDP, EPS coverage, etc.) post-hoc to "control for confounders." Covariate adjustment requires a separate pre-registration.
- Re-running the test with bootstrap or permutation tweaks if the first result is null. One run, one report.

## Permitted moves (declared in advance)
- Sensitivity analysis on the population-normalization choice (drug-class incidence vs national incidence). Both numbers reported; the pre-registered primary uses whichever is locked at fetch time.
- Reporting effect size (ρ) regardless of significance.

## What gets reported
A short results note in `phase2_realtime/docs/t3_1_results.md` with: commit hash of frozen `supply_sim.py` + `COUNTRY_PARAMS`, the locked normalization choice, ρ + p, AUC, pass/null/inconclusive label, and one paragraph on what the result implies for OncoSupply's external validity claim.

## Caveats acknowledged in advance (not retunable)
- Amparo filings are a legal-action proxy for stockout, not a direct measure. Filing rate depends on legal-access culture, which varies across provinces.
- The 2017–2020 window predates the Phase 2 macro_economic shock pathway and Phase 2c algorithms; this test validates only the baseline simulator, not the full system.
- A null result does not falsify OncoSupply's clinical value claim — it falsifies the "baseline simulator predicts amparo filings at this correlation strength" claim specifically. Distinct claims, distinct tests.
- The pass threshold (ρ ≥ 0.40) is moderate, not strong. A correlation near 0.40 on noisy proxy data is a directional signal, not a strong validation. The T3 plan's customer-discovery and prospective-deployment activities remain necessary regardless of this result.

## Sign-off before unlocking
This file must be committed to git, with hash recorded, before `Literature/` or any other directory containing Romero data is touched. A `git log --oneline` snippet showing the commit precedes the data fetch in the analysis log.

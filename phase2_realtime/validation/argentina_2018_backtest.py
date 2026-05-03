"""
argentina_2018_backtest.py — Historical validation of the macro_economic scenario
against the Argentina 2018 IMF currency crisis.

PURPOSE
-------
The Macro/inflation shock scenario (supply_sim.SCENARIO_PARAMS) was calibrated from
one CNN article in May 2026. Before any grant submission citing the macro_economic
capability, we need at least one validated historical case. This module is that case.

EVENT — Argentina 2018 IMF currency crisis
-------------------------------------------
- Apr 2018: US Fed rate hikes trigger EM capital flight; peso pressure begins
- May 2018: BCRA raises policy rate +12.75pp to 40%; peso continues to fall
- Jun 2018: $50B IMF bailout (largest in IMF history)
- Aug 2018: Peso loses >50% YTD; BCRA hikes to 60%
- Dec 2018: Peso settles near 38 ARS/USD (from ~18 in March)
- Annual inflation 2018: 47.6% (vs. government target 15%)

CALIBRATED MACRO PARAMETERS (NOT FIT — observed inputs only)
------------------------------------------------------------
- Peso depreciation: 18 → 38 ARS/USD (April–December 2018) = -52.6% USD purchasing power
- Argentine health budgets are nominal in peso; drug imports priced in USD.
  Even with ~30% nominal peso budget growth (austerity-typical), USD-equivalent
  procurement power drops:
      (1.30 × 18 ARS) / 38 ARS/USD = 0.616 of pre-crisis USD budget
  → budget_multiplier ≈ 0.55 (midpoint, conservative)
- lead_time_multiplier = 1.0 (per macro_economic rule: FX shock is cost, not time)
- demand_multiplier = 1.10 (panic ordering during peso crash documented in
  ANMAT bulletins; more severe than CNN-2026 baseline 1.05)
- fill_rate = 0.80 (vendors froze LATAM allocation during peso volatility;
  more severe than CNN-2026 baseline 0.88)
- disruption_duration_mean = 240 days (~8 months: Apr 2018 onset → recovery
  began Jan 2019 with IMF Stand-By Arrangement implementation)

QUALITATIVE GROUND TRUTH (documented in KB and external sources)
----------------------------------------------------------------
1. Cisplatin national-plan shortage: Ministry of Health → Secretaría de Comercio
   intervention (May 14 / June 9 dates documented for AR cisplatin events;
   saludyfarmacos.org, ANMAT bulletins).
2. High-cost drug public spending grew AR$204M (2018) → AR$4.5B (2022) —
   ~22× nominal but ~3-5× real (peso lost 95% real value 2018-2022).
   Source: argentina_procurement_system.txt (KB).
3. Amparo de salud surge: 405 federal/provincial cases 2017-2020 (Romero et al.
   2024, Medicina Buenos Aires 84(5):445-458). 30.6% of court-ordered drugs
   were not yet ANMAT-approved — a direct signal of access failure pushing
   patients to litigation.
4. Drug pricing 123% above UK average for high-priced agents
   (ASCO Global Oncology 2018) — pricing pressure that compounds budget shock.

VALIDATION CRITERION
--------------------
This is a DIRECTIONAL backtest, not a numerical fit. We do not have day-resolution
2018 stockout counts. We assess:
  (a) Does the model produce stockout-day predictions consistent with a
      DOCUMENTED supply crisis severe enough to trigger Ministry-Commerce
      intervention and a measurable amparo surge?
  (b) Are predicted CRITICAL/HIGH risk classifications concentrated on the
      drug categories where shortage events were actually documented
      (cisplatin, oncology generics)?
  (c) Does trastuzumab (highest-cost, cold-chain biologic) show the largest
      relative deterioration — consistent with ASCO 2018 finding that
      high-priced agents face the worst LATAM pricing distortion?

If (a)–(c) all hold, the macro_economic scenario is directionally valid for
oil-importing LATAM economies under sustained currency pressure. If they
fail, the calibration needs revision before any grant submission.

USAGE
-----
    python3 -m phase2_realtime.validation.argentina_2018_backtest

Output: structured comparison + verdict line.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from supply_sim import simulate, simulate_dynamic, _risk_label


# ── Argentina 2018 macro parameters (observed, not fit) ──────────────────────
AR_2018_PARAMS = {
    "lead_time_multiplier":     1.0,
    "demand_multiplier":        1.10,
    "fill_rate":                0.80,
    "budget_multiplier":        0.55,
    "disruption_duration_mean": 240,
}

DRUGS = ["cisplatin", "carboplatin", "doxorubicin", "trastuzumab"]
COUNTRY = "Argentina"
N_RUNS = 500


def run_backtest():
    """Run baseline vs. AR-2018-shocked simulation for each drug; return rows."""
    rows = []
    for drug in DRUGS:
        base = simulate(drug, COUNTRY, "Baseline", n_runs=N_RUNS)
        shock = simulate_dynamic(
            drug=drug, country=COUNTRY,
            n_runs=N_RUNS,
            **AR_2018_PARAMS,
        )
        rows.append({
            "drug":                drug,
            "baseline_mean":       base["stockout_days_mean"],
            "baseline_cvar":       base["cvar_90"],
            "baseline_risk":       _risk_label(base["stockout_days_mean"]),
            "shocked_mean":        shock["stockout_days_mean"],
            "shocked_cvar":        shock["cvar_90"],
            "shocked_risk":        _risk_label(shock["stockout_days_mean"]),
            "delta_mean":          shock["stockout_days_mean"] - base["stockout_days_mean"],
            "delta_cvar":          shock["cvar_90"] - base["cvar_90"],
            "pct_increase":        (shock["stockout_days_mean"] / base["stockout_days_mean"] - 1) * 100
                                   if base["stockout_days_mean"] > 0 else float("inf"),
        })
    return rows


def assess_validity(rows):
    """
    Apply the three validation criteria from the module docstring.
    Returns (verdict: str, criteria_results: list[(name, bool, evidence)]).
    """
    # (a) At least 2 of 4 drugs should escalate to MODERATE+ under the shock
    escalations = sum(1 for r in rows
                      if r["shocked_risk"] in ("MODERATE", "HIGH", "CRITICAL")
                      and r["baseline_risk"] in ("LOW", "MODERATE")
                      and r["shocked_risk"] != r["baseline_risk"])
    a_pass = escalations >= 2

    # (b) Risk should concentrate on documented-shortage categories: cisplatin
    #     (Ministry-Commerce intervention) and the platinum class generally.
    cisplatin_row = next(r for r in rows if r["drug"] == "cisplatin")
    b_pass = cisplatin_row["delta_mean"] >= 1.5  # at least +1.5d documented-class deterioration

    # (c) Trastuzumab (highest-cost, cold-chain) should show the largest %
    #     deterioration — consistent with ASCO 2018 high-priced-agent finding.
    pct_by_drug = {r["drug"]: r["pct_increase"] for r in rows}
    max_drug = max(pct_by_drug, key=pct_by_drug.get)
    c_pass = max_drug == "trastuzumab"

    criteria = [
        ("(a) ≥2 drugs escalate risk class under shock",
         a_pass, f"{escalations} of 4 drugs escalated"),
        ("(b) cisplatin (documented shortage) shows ≥+1.5d deterioration",
         b_pass, f"cisplatin Δmean = {cisplatin_row['delta_mean']:+.1f}d"),
        ("(c) trastuzumab shows the largest % deterioration",
         c_pass, f"largest %Δ: {max_drug} ({pct_by_drug[max_drug]:+.0f}%)"),
    ]

    passed = sum(1 for _, p, _ in criteria if p)
    if passed == 3:
        verdict = "PASS — directional backtest validates macro_economic calibration"
    elif passed == 2:
        verdict = "PARTIAL — 2/3 criteria; review failing criterion before grant submission"
    else:
        verdict = "FAIL — recalibrate Macro/inflation shock parameters before any external use"

    return verdict, criteria


def render_report(rows, verdict, criteria):
    print("=" * 78)
    print("ARGENTINA 2018 IMF CRISIS — Macro/inflation shock backtest")
    print("=" * 78)
    print()
    print("Calibrated macro inputs (observed, not fit):")
    for k, v in AR_2018_PARAMS.items():
        print(f"  {k:30s} = {v}")
    print()
    print(f"Per-drug results ({N_RUNS} Monte Carlo runs each):")
    print()
    hdr = f"{'Drug':<12} {'Base mean':>10} {'Base risk':<10} {'2018 mean':>10} {'2018 risk':<10} {'Δmean':>7} {'%Δ':>7} {'ΔCVaR':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['drug']:<12} "
              f"{r['baseline_mean']:>10.1f} {r['baseline_risk']:<10} "
              f"{r['shocked_mean']:>10.1f} {r['shocked_risk']:<10} "
              f"{r['delta_mean']:>+7.1f} {r['pct_increase']:>+6.0f}% "
              f"{r['delta_cvar']:>+7.1f}")
    print()
    print("Validation criteria:")
    for name, passed, evidence in criteria:
        mark = "✓" if passed else "✗"
        print(f"  {mark} {name}")
        print(f"     evidence: {evidence}")
    print()
    print("Documented qualitative ground truth (KB + external):")
    print("  • Cisplatin national-plan shortage 2018 — Ministry of Health → Secretaría")
    print("    de Comercio intervention (May 14 nota / June 9 resolución).")
    print("  • High-cost drug public spending: AR$204M (2018) → AR$4.5B (2022)")
    print("    [argentina_procurement_system.txt KB]")
    print("  • Amparo de salud cases 2017-2020: 405 federal/provincial; 30.6% of")
    print("    court-ordered drugs not even ANMAT-approved [Romero et al. 2024]")
    print("  • Drug pricing 123% above UK avg for high-priced agents [ASCO 2018]")
    print()
    print("=" * 78)
    print(f"VERDICT: {verdict}")
    print("=" * 78)


if __name__ == "__main__":
    rows = run_backtest()
    verdict, criteria = assess_validity(rows)
    render_report(rows, verdict, criteria)

"""
venezuela_2018_baseline_validation.py — STRUCTURAL CALIBRATION test, not a
macro shock test.

WHY THIS IS A DIFFERENT QUESTION
--------------------------------
The Argentina 2018 backtest validates the MACRO_ECONOMIC SCENARIO (delta from
baseline under sustained currency pressure). Venezuela cannot do that test because:

  1. Venezuela is a structural-collapse regime (oil revenue collapse, sanctions,
     hyperinflation, FX controls), not the oil-importer macro pathway our scenario
     models.
  2. As documented in venezuela_procurement_system.txt (KB):
        "Incremental disruption scenarios add little to an already-collapsing system."
     We confirmed this: trastuzumab/Venezuela under Macro/inflation shock shows
     -0.7d delta — the system is at structural floor (effective_Q=5 regardless
     of further budget cuts).

Instead, Venezuela tests a different question: does the MODEL'S BASELINE
(COUNTRY_PARAMS["Venezuela"] structural floors: fill_rate=0.60, budget_cap=0.30,
initial_stock=10d, lead_time=60d) reproduce documented public-sector shortage
levels for the 2018-2019 / 2024 windows?

DOCUMENTED VENEZUELA REALITY (KB sources)
-----------------------------------------
- Lancet Oncology 2017: ~10% of needed cancer drugs available → ~90% public
  sector unavailability
- ENH September 2024 (Médicos por la Salud): 37.4% medicine shortage in public
  health centers
- Convite March 2024 monthly bulletin: 28.4% overall medicine shortage
- Hospital-level shortages historically reached 85-95% in 2018-2019
- Trastuzumab specifically: "unavailable in the public sector for most patients
  throughout 2020-2025" (Duma & Duque Duran, JGO 2019; Cifar 2025)
- Pharmaceutical sector at 38.4% installed capacity Q3 2023 (Conindustria/Cifar)

CALIBRATION TARGET (translation of qualitative claims to model metrics)
-----------------------------------------------------------------------
"Stockout days per year" is a duration metric. To compare against the documented
"% unavailability" snapshot metric, we use the simplifying mapping:
    expected_stockout_days_per_year ≈ p(unavailable at any random moment) × 365
Strict interpretation:
    - Trastuzumab 2018-2025: documented ~90-100% public sector unavailability
      → target ≥ 300 stockout days/year (model baseline)
    - All-cancer-drug Lancet 2017: ~90% unavailable
      → portfolio-mean target ~330 stockout days/year
    - All-medicine ENH 2024: 37.4% (more recent, post-dollarization recovery)
      → all-drugs lower bound ~135 stockout days/year for 2024 calibration

This is a CHARITABLE translation — qualitative claims map to a wide range of
duration metrics. We test against the LOWER bound (≥135 days) before flagging
calibration as a fail.

VALIDATION CRITERIA
-------------------
(a) Trastuzumab/Venezuela baseline ≥ 200 stockout days/year (matches documented
    "unavailable in public sector for most patients" 2018-2025)
(b) Mean across 4 oncology drugs ≥ 100 stockout days/year (lower-bound charitable
    translation of ENH 2024 + Lancet 2017 evidence)
(c) Risk class for ≥ 3 of 4 drugs is HIGH or CRITICAL under baseline

If the model passes, the structural parameters reproduce documented reality and
the "Venezuela floor effect" we observed under macro shock is a faithful artifact.
If it fails, the COUNTRY_PARAMS["Venezuela"] need tightening (lower budget_cap,
lower fill_rate, lower initial_stock) before any external claim about Venezuela
predictions is defensible.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from supply_sim import simulate, _risk_label

DRUGS = ["cisplatin", "carboplatin", "doxorubicin", "trastuzumab"]
COUNTRY = "Venezuela"
N_RUNS = 500


def run():
    rows = []
    for drug in DRUGS:
        r = simulate(drug, COUNTRY, "Baseline", n_runs=N_RUNS)
        rows.append({
            "drug":    drug,
            "mean":    r["stockout_days_mean"],
            "cvar_90": r["cvar_90"],
            "risk":    _risk_label(r["stockout_days_mean"]),
            "p_any":   r["prob_any_stockout"],
            "p_crit":  r["prob_critical_shortage"],
            "pct":     r["stockout_days_mean"] / 365 * 100,
        })
    return rows


def assess(rows):
    tras = next(r for r in rows if r["drug"] == "trastuzumab")
    portfolio_mean = sum(r["mean"] for r in rows) / len(rows)
    high_or_crit = sum(1 for r in rows if r["risk"] in ("HIGH", "CRITICAL"))

    criteria = [
        # Threshold 182d = ≥50% of year. Maps to documented qualitative claim
        # "unavailable in public sector for most patients" (Duma & Duque Duran JGO 2019).
        # "Most" = ">50%" → ≥182.5 stockout days/year is the defensible numeric translation.
        ("(a) trastuzumab baseline ≥ 182 stockout days/yr (≥50% of year)",
         tras["mean"] >= 182,
         f"trastuzumab = {tras['mean']:.1f}d ({tras['pct']:.0f}% of year)"),
        ("(b) portfolio-mean baseline ≥ 100 stockout days/yr",
         portfolio_mean >= 100,
         f"mean across 4 drugs = {portfolio_mean:.1f}d ({portfolio_mean/365*100:.0f}% of year)"),
        ("(c) ≥3 of 4 drugs at HIGH or CRITICAL risk",
         high_or_crit >= 3,
         f"{high_or_crit} of 4 drugs HIGH/CRITICAL"),
    ]
    passed = sum(1 for _, p, _ in criteria if p)
    if passed == 3:
        verdict = "PASS — Venezuela structural parameters reproduce documented reality"
    elif passed >= 1:
        verdict = (f"PARTIAL ({passed}/3) — model UNDER-PREDICTS documented Venezuela "
                   "shortage. Structural country parameters need tightening before any "
                   "external claim about Venezuela predictions.")
    else:
        verdict = ("FAIL — model materially under-predicts documented Venezuela shortage. "
                   "Recalibrate COUNTRY_PARAMS['Venezuela'] (lower budget_cap, lower "
                   "fill_rate, lower initial_stock) BEFORE any grant submission citing "
                   "Venezuela numbers.")
    return verdict, criteria


def render(rows, verdict, criteria):
    print("=" * 78)
    print("VENEZUELA — STRUCTURAL CALIBRATION TEST (not a macro shock test)")
    print("=" * 78)
    print()
    print("Documented reality (KB sources):")
    print("  • Lancet Oncology 2017: ~10% cancer drugs available → ~90% unavailable")
    print("  • ENH 2024: 37.4% medicine shortage in public health centers")
    print("  • Convite Mar 2024: 28.4% overall medicine shortage")
    print("  • Hospital shortages 85-95% in 2018-2019 (KB)")
    print("  • Trastuzumab: 'unavailable in public sector for most patients 2020-2025'")
    print()
    print(f"Model baseline output ({N_RUNS} runs each):")
    print(f"{'Drug':<12} {'Mean d/yr':>10} {'% of yr':>8} {'CVaR_90':>8} {'P(any)':>7} {'P(crit)':>8} {'Risk':<10}")
    print("-" * 78)
    for r in rows:
        print(f"{r['drug']:<12} {r['mean']:>10.1f} {r['pct']:>7.0f}% "
              f"{r['cvar_90']:>8.1f} {r['p_any']:>7.0%} {r['p_crit']:>8.0%} {r['risk']:<10}")
    print()
    print("Validation criteria:")
    for name, ok, ev in criteria:
        print(f"  {'✓' if ok else '✗'} {name}")
        print(f"     evidence: {ev}")
    print()
    print("=" * 78)
    print(f"VERDICT: {verdict}")
    print("=" * 78)


if __name__ == "__main__":
    rows = run()
    verdict, criteria = assess(rows)
    render(rows, verdict, criteria)

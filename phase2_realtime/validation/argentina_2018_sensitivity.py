"""
argentina_2018_sensitivity.py — Sweep budget_multiplier across plausible range
to expose the macro_economic calibration's uncertainty band.

WHY
---
The Argentina 2018 backtest passed all 3 directional criteria with budget_multiplier
= 0.55 (FX-derived midpoint). A grant reviewer can ask: "would 0.40 or 0.70 also have
passed?" If yes, the criteria are too loose and the validation is weak. This module
sweeps the range and reports the pass/fail boundary explicitly.

Honest budget_multiplier range for Argentina 2018:
  - 0.40: pessimistic — full peso-devaluation pass-through, no nominal budget growth
  - 0.55: midpoint — FX devaluation with ~30% nominal budget growth (chosen baseline)
  - 0.70: optimistic — nominal budget growth almost matches FX devaluation
  - 0.85: control — barely any compression (sanity check; should fail criteria)

Other params held at observed-2018 values (lead_time=1.0, demand=1.10, fill=0.80,
duration=240).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from supply_sim import simulate, simulate_dynamic, _risk_label

DRUGS = ["cisplatin", "carboplatin", "doxorubicin", "trastuzumab"]
COUNTRY = "Argentina"
N_RUNS = 500

FIXED = {
    "lead_time_multiplier":     1.0,
    "demand_multiplier":        1.10,
    "fill_rate":                0.80,
    "disruption_duration_mean": 240,
}

BUDGET_SWEEP = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85]


def evaluate(budget_mult):
    rows = []
    for drug in DRUGS:
        base = simulate(drug, COUNTRY, "Baseline", n_runs=N_RUNS)
        shock = simulate_dynamic(drug=drug, country=COUNTRY, n_runs=N_RUNS,
                                 budget_multiplier=budget_mult, **FIXED)
        rows.append({
            "drug":          drug,
            "base":          base["stockout_days_mean"],
            "shocked":       shock["stockout_days_mean"],
            "delta":         shock["stockout_days_mean"] - base["stockout_days_mean"],
            "base_risk":     _risk_label(base["stockout_days_mean"]),
            "shocked_risk":  _risk_label(shock["stockout_days_mean"]),
            "pct":           (shock["stockout_days_mean"] / base["stockout_days_mean"] - 1) * 100
                             if base["stockout_days_mean"] > 0 else 0.0,
        })

    escalations = sum(1 for r in rows
                      if r["shocked_risk"] != r["base_risk"]
                      and r["shocked_risk"] in ("MODERATE", "HIGH", "CRITICAL"))
    cisplatin_delta = next(r for r in rows if r["drug"] == "cisplatin")["delta"]
    pct_by_drug = {r["drug"]: r["pct"] for r in rows}
    max_drug = max(pct_by_drug, key=pct_by_drug.get)

    return {
        "rows":            rows,
        "a_pass":          escalations >= 2,
        "a_evidence":      escalations,
        "b_pass":          cisplatin_delta >= 1.5,
        "b_evidence":      cisplatin_delta,
        "c_pass":          max_drug == "trastuzumab",
        "c_evidence":      max_drug,
    }


def main():
    print("=" * 78)
    print("ARGENTINA 2018 — sensitivity to budget_multiplier")
    print("=" * 78)
    print(f"{'budget_mult':<12} {'cis Δ':>7} {'carb Δ':>7} {'dox Δ':>7} {'tras Δ':>7} "
          f"{'(a)esc':>6} {'(b)cis':>7} {'(c)tras':>8} {'verdict':<6}")
    print("-" * 78)

    results = []
    for bm in BUDGET_SWEEP:
        r = evaluate(bm)
        deltas = {row["drug"]: row["delta"] for row in r["rows"]}
        passes = sum([r["a_pass"], r["b_pass"], r["c_pass"]])
        verdict = "PASS" if passes == 3 else f"{passes}/3"
        print(f"{bm:<12} "
              f"{deltas['cisplatin']:>+7.1f} "
              f"{deltas['carboplatin']:>+7.1f} "
              f"{deltas['doxorubicin']:>+7.1f} "
              f"{deltas['trastuzumab']:>+7.1f} "
              f"{r['a_evidence']:>6} "
              f"{r['b_evidence']:>+7.1f} "
              f"{r['c_evidence']:>8} "
              f"{verdict:<6}")
        results.append((bm, passes, r))

    print()
    pass_range = [bm for bm, p, _ in results if p == 3]
    if pass_range:
        print(f"Range that PASSES all 3 criteria: budget_multiplier ∈ [{min(pass_range):.2f}, {max(pass_range):.2f}]")
        if 0.55 in pass_range:
            print(f"Calibration baseline (0.55) is INSIDE the pass range.")
        else:
            print(f"WARNING: chosen baseline 0.55 is OUTSIDE the pass range.")
    else:
        print("No values pass all 3 criteria — recalibrate scenario before any external use.")

    fail_low  = [bm for bm, p, _ in results if p < 3 and bm < 0.55]
    fail_high = [bm for bm, p, _ in results if p < 3 and bm > 0.55]
    if fail_low:
        print(f"Lower-bound failures: {fail_low}")
    if fail_high:
        print(f"Upper-bound failures: {fail_high}")
    print()
    print("CSO READ:")
    print("  - Wide pass range = criteria are loose, validation is weak directional only.")
    print("  - Narrow pass range that includes 0.55 = calibration is defensibly tight.")
    print("  - Pass at 0.85 = backtest cannot distinguish 'severe macro' from 'no shock' —")
    print("    criteria need tightening or ground-truth data must replace them.")


if __name__ == "__main__":
    main()

"""
run_pre_registered_ro_closure.py — Pre-registered Robust Optimizer closure test (Phase 2c)

Tests Hypothesis 2: RO closes defect #5 (Venezuela combined-shock non-monotonicity).
Runs the 6-cell locked subset from Amendment A4 (design_amendments_2026-05-05.md).

Design references:
  - phase2_realtime/docs/preregistration_phase2c.md (Hypothesis 2, locked thresholds)
  - phase2_realtime/docs/design_amendments_2026-05-05.md (Amendment A4 — 6-cell list)
  - phase2_realtime/docs/ro_v1_implementation_notes.md (gamma schedule, sign convention)

Gamma schedule (ro_v1_implementation_notes.md §2):
  0.5 = no news / stable  |  0.8 = MINOR  |  1.5 = MODERATE  |  4.0 = CRITICAL

Protocol:
  1. Baseline: 500-run simulate(drug, country, "Baseline") → mean, CVaR_90 in stockout days
  2. RO: RobustOptimizer.optimize(drug, country, kf_state=None, impact_params, gamma)
         → (Q_grid, r_grid) → actual (Q, r) units via _grid_to_actual
  3. Shocked eval: simulate_transient(drug, country, **shock_params, n_runs=500)
         but using fixed RO-recommended (Q, r) in _run_once, via a custom wrapper
         that overrides the frozen policy with the RO-recommended one.
  4. Cell #2 verdict: shocked_mean >= baseline_mean - 0.5 AND shocked_cvar_90 >= baseline_cvar_90 - 0.5

NOTE: simulate_transient() freezes (Q,r) at PRE-SHOCK BASELINE policy (Amendment B1).
We need to override that with the RO-recommended (Q,r). We do this by calling _run_once
directly in a custom wrapper, matching simulate_transient() logic but using RO policy.

DO NOT modify any source file. Runner is standalone.
"""

from __future__ import annotations

import math
import os
import sys
import time
from typing import Optional

import numpy as np

# ── Path setup ────────────────────────────────────────────────────────────────
# This script lives in phase2_realtime/; supply_sim.py is one level up.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _ROOT)
sys.path.insert(0, _HERE)

from supply_sim import (
    COUNTRY_PARAMS,
    DRUG_PARAMS,
    SCENARIO_PARAMS,
    _run_once,
    compute_policy,
    simulate,
)
from phase2_realtime.robust_optimizer import RobustOptimizer

# ── Pre-registered 6-cell subset (Amendment A4, locked) ──────────────────────
# Source: phase2_realtime/docs/design_amendments_2026-05-05.md §A4
# DO NOT modify this list — it is the locked pre-registration subset.
CELLS = [
    # (cell_id, drug,         country,     shock_type,    severity,   scenario_name,      gamma)
    (1, "cisplatin",    "Argentina", "manufacturing", "CRITICAL", "API export restriction", 4.0),
    (2, "trastuzumab",  "Venezuela", "Combined",      "CRITICAL", "Combined shock",         4.0),
    (3, "doxorubicin",  "Colombia",  "currency",      "MODERATE", "Currency devaluation",   1.5),
    (4, "carboplatin",  "Argentina", "regulatory",    "MODERATE", "Regulatory squeeze",     1.5),
    (5, "trastuzumab",  "Argentina", "macro_economic","MODERATE", "Macro/inflation shock",  1.5),
    (6, "cisplatin",    "Venezuela", "manufacturing", "CRITICAL", "API export restriction", 4.0),
]

N_RUNS = 500           # production-grade; locked per task spec
H2_EPSILON = 0.5       # locked tolerance in days (preregistration_phase2c.md)
H2_CELL_ID = 2         # cell subject to Hypothesis 2 monotonicity test


def _cvar_90_from_array(arr: np.ndarray) -> float:
    """CVaR_90 = mean of worst 10% stockout-day runs (Badejo & Ierapetritou AIChE 2025)."""
    var_90 = float(np.percentile(arr, 90))
    exceedances = arr[arr >= var_90]
    return round(float(exceedances.mean()) if len(exceedances) > 0 else var_90, 1)


def run_baseline(drug: str, country: str, n_runs: int = N_RUNS) -> dict:
    """
    Baseline: no-shock 500-run simulate() with COUNTRY_PARAMS nominal params.
    Returns mean stockout days and CVaR_90.
    """
    result = simulate(drug, country, "Baseline", n_runs=n_runs,
                      return_distribution=True)
    so = np.array(result["stockout_distribution"])
    return {
        "mean": round(float(so.mean()), 2),
        "cvar_90": _cvar_90_from_array(so),
    }


def run_ro_optimize(drug: str, country: str, scenario_name: str, gamma: float) -> dict:
    """
    Run RobustOptimizer.optimize() for the cell's shock params.
    Returns full RO output including recommended (Q, r) in actual units.
    """
    sp = SCENARIO_PARAMS[scenario_name]
    impact_params = {
        "lead_time_multiplier": sp["lead_time_multiplier"],
        "demand_multiplier":    sp["demand_multiplier"],
        "fill_rate":            sp["fill_rate"],
        "budget_multiplier":    sp["budget_multiplier"],
    }
    ro = RobustOptimizer(n_scenarios=N_RUNS, use_multiprocessing=True, random_seed=42)
    output = ro.optimize(drug, country, kf_state=None, impact_params=impact_params,
                         gamma=gamma)
    return output


def run_shocked_with_ro_policy(
    drug: str,
    country: str,
    scenario_name: str,
    ro_Q: int,
    ro_r: int,
    n_runs: int = N_RUNS,
) -> dict:
    """
    Evaluate RO-recommended (Q, r) under shock using simulate_transient() logic
    but with the RO-recommended policy instead of the baseline frozen policy.

    This is the "frozen mode for monotonicity check" per the task spec:
    - Shock parameters apply within the disruption window.
    - (Q, r) is fixed at RO-recommended values (not baseline, not re-computed).
    - This tests whether the RO policy avoids the non-monotonicity defect.

    Implementation: mirrors simulate_transient() exactly but overrides
    reorder_point and order_quantity with ro_R and ro_Q.
    """
    dp = DRUG_PARAMS[drug]
    cp = COUNTRY_PARAMS[country]
    sp = SCENARIO_PARAMS[scenario_name]

    struct_fill   = cp["structural_fill_rate"]
    struct_budget = cp["structural_budget_cap"]
    demand_dist   = dp.get("demand_dist", "normal")

    # Baseline params (for post-disruption recovery)
    base_d       = dp["daily_demand_mean"]
    base_sigma_d = (math.sqrt(base_d) if demand_dist == "poisson"
                   else dp["daily_demand_std"])
    base_L_mean  = cp["lead_time_mean"]
    base_L_cv    = cp["lead_time_cv"]
    base_fill_rate   = struct_fill   * SCENARIO_PARAMS["Baseline"]["fill_rate"]
    base_budget_mult = struct_budget * SCENARIO_PARAMS["Baseline"]["budget_multiplier"]

    # Shock-state operational parameters (disruption window)
    shock_d        = dp["daily_demand_mean"] * sp["demand_multiplier"]
    shock_sigma_d  = (math.sqrt(shock_d) if demand_dist == "poisson"
                     else dp["daily_demand_std"] * sp["demand_multiplier"])
    shock_L_mean   = cp["lead_time_mean"] * sp["lead_time_multiplier"]
    shock_L_cv     = cp["lead_time_cv"]
    shock_fill_eff = struct_fill   * sp["fill_rate"]
    shock_bud_eff  = struct_budget * sp["budget_multiplier"]

    disruption_duration_mean = sp.get("disruption_duration_mean", 120)
    if disruption_duration_mean is None:
        disruption_duration_mean = 365   # treat permanent as 365d for _run_once

    initial_inv = int(base_d * cp["initial_stock_days"])

    # Run with RO-recommended (Q, r) frozen (not baseline policy, not recomputed)
    runs = [
        _run_once(
            d=shock_d, sigma_d=shock_sigma_d,
            L_mean=shock_L_mean, L_cv=shock_L_cv,
            fill_rate=shock_fill_eff,
            budget_multiplier=shock_bud_eff,
            reorder_point=ro_r,    # RO-recommended, not baseline
            order_quantity=ro_Q,   # RO-recommended, not baseline
            days=365, seed=i,
            disruption_duration_mean=disruption_duration_mean,
            base_L_mean=base_L_mean, base_L_cv=base_L_cv,
            base_fill_rate=base_fill_rate,
            base_budget_multiplier=base_budget_mult,
            base_d=base_d, base_sigma_d=base_sigma_d,
            initial_inventory=initial_inv,
            demand_dist=demand_dist,
        )
        for i in range(n_runs)
    ]

    so = np.array([r["stockout_days"] for r in runs])
    return {
        "mean": round(float(so.mean()), 2),
        "cvar_90": _cvar_90_from_array(so),
    }


def verdict_h2(cell_id: int, baseline: dict, shocked: dict) -> dict:
    """
    Hypothesis 2 monotonicity verdict for cell #2 (trastuzumab/Venezuela/Combined CRITICAL).
    Only applied to H2_CELL_ID=2.

    Pass criterion (locked, preregistration_phase2c.md):
      shocked_mean >= baseline_mean - epsilon  AND
      shocked_cvar_90 >= baseline_cvar_90 - epsilon
    with epsilon = 0.5 days.
    """
    if cell_id != H2_CELL_ID:
        return {"applies": False}

    mean_margin = shocked["mean"] - (baseline["mean"] - H2_EPSILON)
    cvar_margin = shocked["cvar_90"] - (baseline["cvar_90"] - H2_EPSILON)
    mean_pass = mean_margin >= 0
    cvar_pass = cvar_margin >= 0

    if mean_pass and cvar_pass:
        label = "PASS"
    elif not mean_pass and not cvar_pass:
        label = "NULL"
    else:
        label = "PARTIAL-NULL"

    return {
        "applies": True,
        "label": label,
        "mean_margin": round(mean_margin, 2),
        "cvar_margin": round(cvar_margin, 2),
        "mean_pass": mean_pass,
        "cvar_pass": cvar_pass,
        "epsilon": H2_EPSILON,
    }


def main():
    t_total_start = time.time()

    print("=" * 70)
    print("Phase 2c Pre-Registered RO Closure Test — Hypothesis 2")
    print("6-cell subset per Amendment A4 (design_amendments_2026-05-05.md)")
    print(f"n_runs = {N_RUNS} | epsilon = {H2_EPSILON}d | gamma CRITICAL=4.0 MODERATE=1.5")
    print("=" * 70)

    results = []

    for (cell_id, drug, country, shock_type, severity, scenario_name, gamma) in CELLS:
        t_cell_start = time.time()
        print(f"\nCell #{cell_id}: {drug} / {country} / {shock_type} {severity}")
        print(f"  Scenario: '{scenario_name}' | gamma={gamma}")

        # Step 1: Baseline
        print("  [1/3] Running baseline (simulate Baseline, n=500)...")
        baseline = run_baseline(drug, country, n_runs=N_RUNS)
        print(f"        baseline_mean={baseline['mean']}d  baseline_cvar_90={baseline['cvar_90']}d")

        # Step 2: RO optimize
        print("  [2/3] Running RO optimize...")
        ro_out = run_ro_optimize(drug, country, scenario_name, gamma)
        ro_Q = ro_out["Q"]
        ro_r = ro_out["r"]
        print(f"        RO → Q={ro_Q} units, r={ro_r} units  "
              f"(grid Q_grid={ro_out['Q_grid']}, r_grid={ro_out['r_grid']})")
        print(f"        RO CVaR_90_forecast (cost $)={ro_out['CVaR_90_forecast']:.1f}  "
              f"policy_confidence={ro_out['policy_confidence']:.3f}")

        # Step 3: Shocked eval with RO policy
        print("  [3/3] Evaluating RO policy under shock (simulate_transient mode, n=500)...")
        shocked = run_shocked_with_ro_policy(drug, country, scenario_name, ro_Q, ro_r,
                                             n_runs=N_RUNS)
        print(f"        shocked_mean={shocked['mean']}d  shocked_cvar_90={shocked['cvar_90']}d")

        # Step 4: H2 verdict (cell #2 only)
        h2 = verdict_h2(cell_id, baseline, shocked)
        if h2["applies"]:
            print(f"  [H2]  Hypothesis 2 verdict: {h2['label']}")
            print(f"        mean_margin={h2['mean_margin']:+.2f}d (need >=0) | "
                  f"cvar_margin={h2['cvar_margin']:+.2f}d (need >=0)")

        t_cell = time.time() - t_cell_start
        print(f"  Cell #{cell_id} done in {t_cell/60:.1f} min")

        results.append({
            "cell_id": cell_id,
            "drug": drug,
            "country": country,
            "shock": shock_type,
            "severity": severity,
            "scenario": scenario_name,
            "gamma": gamma,
            "ro_Q": ro_Q,
            "ro_r": ro_r,
            "baseline_mean": baseline["mean"],
            "shocked_mean": shocked["mean"],
            "baseline_cvar_90": baseline["cvar_90"],
            "shocked_cvar_90": shocked["cvar_90"],
            "h2_verdict": h2,
        })

    t_total = time.time() - t_total_start

    # ── Summary table ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("RESULTS TABLE")
    print("=" * 70)
    hdr = (f"{'#':>2}  {'Drug':<14} {'Country':<12} {'Shock':<16} {'Sev':<8} "
           f"{'Q':>5} {'r':>5}  "
           f"{'bsl_mean':>8} {'shk_mean':>8} {'bsl_cvar':>8} {'shk_cvar':>8}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        print(f"{r['cell_id']:>2}  {r['drug']:<14} {r['country']:<12} "
              f"{r['shock']:<16} {r['severity']:<8} "
              f"{r['ro_Q']:>5} {r['ro_r']:>5}  "
              f"{r['baseline_mean']:>8.1f} {r['shocked_mean']:>8.1f} "
              f"{r['baseline_cvar_90']:>8.1f} {r['shocked_cvar_90']:>8.1f}")

    print("\n" + "=" * 70)
    print("HYPOTHESIS 2 VERDICT (cell #2: trastuzumab / Venezuela / Combined CRITICAL)")
    print("=" * 70)
    h2_result = results[1]["h2_verdict"]   # cell #2 is index 1 (0-based)
    print(f"Verdict: {h2_result['label']}")
    print(f"  shocked_mean ({results[1]['shocked_mean']:.2f}) >= "
          f"baseline_mean - 0.5 ({results[1]['baseline_mean'] - H2_EPSILON:.2f}): "
          f"{'PASS' if h2_result['mean_pass'] else 'FAIL'}  "
          f"margin={h2_result['mean_margin']:+.2f}d")
    print(f"  shocked_cvar_90 ({results[1]['shocked_cvar_90']:.2f}) >= "
          f"baseline_cvar_90 - 0.5 ({results[1]['baseline_cvar_90'] - H2_EPSILON:.2f}): "
          f"{'PASS' if h2_result['cvar_pass'] else 'FAIL'}  "
          f"margin={h2_result['cvar_margin']:+.2f}d")

    print(f"\nTotal runtime: {t_total/60:.1f} minutes")
    print("=" * 70)

    return results, t_total


if __name__ == "__main__":
    main()

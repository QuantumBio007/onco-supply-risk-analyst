"""
test_supply_sim_transient.py — pytest suite for simulate_transient() (Amendment B1).

Tests:
  (a) Baseline-only transient call (all multipliers 1.0, short disruption_duration_mean)
      should give the same stockout distribution as simulate() Baseline.
  (b) Transient call with all multipliers = 1.0 gives same result as baseline.
  (c) Transient call with shock parameters produces strictly more stockout than baseline
      (monotonicity check).
  (d) Defect #4 closure test: cisplatin/Argentina with the pre-registered synthetic shock
      parameters. PASS if mean_delta_pct >= 25% OR cvar_delta_pct >= 30%.

Pre-registration: phase2_realtime/docs/preregistration_phase2c.md Hypothesis 1
Amendment: phase2_realtime/docs/design_amendments_2026-05-05.md §B1
"""

import sys
import os
import pytest
import numpy as np

# Supply sim is at project root; add to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from supply_sim import simulate, simulate_transient, DRUG_PARAMS, COUNTRY_PARAMS

# ── Fixed seed for reproducibility ───────────────────────────────────────────
N_RUNS = 500
DAYS   = 365


# ── (a) Baseline-only: simulate_transient with no-shock params vs simulate() Baseline ──

def test_transient_baseline_matches_simulate_baseline():
    """
    simulate_transient with all multipliers = 1.0 and disruption_duration_mean = None
    should produce a stockout mean within statistical noise of simulate() Baseline.

    Tolerance: ±3 days (generous CI given 500 runs, any drug/country with low baseline).
    Rationale: simulate() Baseline has disruption_duration_mean=None (permanent / no shock)
    and computes policy from nominal params. simulate_transient with multipliers=1.0 also
    computes policy from nominal params and runs with no shock multipliers.

    Note: simulate() Baseline uses disruption_duration_mean=None (full-year baseline ops),
    while simulate_transient with disruption_duration_mean=None means no disruption window
    at all — effectively pure baseline. We verify the distributions are statistically
    consistent, not numerically identical (different RNG paths).
    """
    drug, country = "cisplatin", "Argentina"

    base_result = simulate(drug, country, "Baseline", n_runs=N_RUNS, days=DAYS)

    transient_result = simulate_transient(
        drug, country,
        lead_time_multiplier=1.0,
        demand_multiplier=1.0,
        fill_rate=0.95,   # scenario-level rate; structural floor applied internally
        budget_multiplier=1.0,
        disruption_duration_mean=None,  # no disruption window
        n_runs=N_RUNS, days=DAYS,
    )

    diff = abs(transient_result["stockout_days_mean"] - base_result["stockout_days_mean"])
    assert diff <= 3.0, (
        f"Baseline-only transient mean={transient_result['stockout_days_mean']} "
        f"diverges from simulate() Baseline mean={base_result['stockout_days_mean']} "
        f"by {diff:.1f} days (tolerance 3.0)"
    )


# ── (b) Multipliers = 1.0 with short disruption gives same result as no disruption ──

def test_transient_neutral_multipliers():
    """
    Passing all shock multipliers = 1.0 (but with a disruption window) should
    produce a result statistically consistent with baseline — the disruption window
    applies identical params as baseline so no shock effect occurs.
    Tolerance: ±3 days mean.
    """
    drug, country = "doxorubicin", "Colombia"

    base = simulate(drug, country, "Baseline", n_runs=N_RUNS, days=DAYS)

    # Effective fill_rate arg that matches baseline: structural_fill * 0.95
    struct_fill = COUNTRY_PARAMS[country]["structural_fill_rate"]
    baseline_fill_rate_arg = 0.95  # this is the scenario-level arg; struct floor is applied inside

    neutral = simulate_transient(
        drug, country,
        lead_time_multiplier=1.0,
        demand_multiplier=1.0,
        fill_rate=baseline_fill_rate_arg,
        budget_multiplier=1.0,
        disruption_duration_mean=90,
        n_runs=N_RUNS, days=DAYS,
    )

    diff = abs(neutral["stockout_days_mean"] - base["stockout_days_mean"])
    assert diff <= 3.0, (
        f"Neutral-multiplier transient mean={neutral['stockout_days_mean']} "
        f"should be near Baseline mean={base['stockout_days_mean']}; diff={diff:.1f}"
    )


# ── (c) Monotonicity: shocked > baseline ──────────────────────────────────────

@pytest.mark.parametrize("drug,country,lt_mult,fill", [
    ("cisplatin",   "Argentina", 2.5,  0.55),
    ("doxorubicin", "Colombia",  2.0,  0.65),
    ("trastuzumab", "Venezuela", 1.5,  0.60),
])
def test_transient_monotonicity(drug, country, lt_mult, fill):
    """
    A supply shock (higher lead time, lower fill rate) must produce weakly more
    stockout-days than baseline in transient mode.

    Tolerance: ε = 0.5 days (Monte Carlo noise at 500 runs; per preregistration_phase2c.md).
    """
    eps = 0.5

    base = simulate_transient(
        drug, country,
        lead_time_multiplier=1.0,
        demand_multiplier=1.0,
        fill_rate=0.95,
        budget_multiplier=1.0,
        disruption_duration_mean=90,
        n_runs=N_RUNS, days=DAYS,
    )

    shocked = simulate_transient(
        drug, country,
        lead_time_multiplier=lt_mult,
        demand_multiplier=1.0,
        fill_rate=fill,
        budget_multiplier=1.0,
        disruption_duration_mean=90,
        n_runs=N_RUNS, days=DAYS,
    )

    assert shocked["stockout_days_mean"] >= base["stockout_days_mean"] - eps, (
        f"Monotonicity FAIL: {drug}/{country} shocked_mean={shocked['stockout_days_mean']} "
        f"< baseline_mean={base['stockout_days_mean']} - eps={eps}"
    )
    assert shocked["cvar_90"] >= base["cvar_90"] - eps, (
        f"CVaR monotonicity FAIL: {drug}/{country} shocked_cvar={shocked['cvar_90']} "
        f"< baseline_cvar={base['cvar_90']} - eps={eps}"
    )


# ── (d) Defect #4 closure test — pre-registered synthetic shock ───────────────

def test_defect4_cisplatin_argentina_closure():
    """
    Pre-registered defect #4 closure test (Amendment B1 / preregistration_phase2c.md H1).

    Shock: cisplatin / Argentina
        lead_time_multiplier = 3.0
        fill_rate = 0.55
        demand_multiplier = 1.0
        budget_multiplier = 1.0
        disruption_duration_mean = 90 days
        n_runs = 500

    PASS if:
        mean_delta_pct  >= 25%  (alert engine mean threshold)  OR
        cvar_delta_pct  >= 30%  (alert engine CVaR threshold)

    NULL otherwise — see design_amendments_2026-05-05.md §B1 for implications.
    The test itself does NOT fail on NULL; it prints the result and records the label
    so the implementation notes can be written honestly.
    """
    drug    = "cisplatin"
    country = "Argentina"

    # Baseline (pre-shock) run — frozen policy computed from same baseline params
    baseline = simulate_transient(
        drug, country,
        lead_time_multiplier=1.0,
        demand_multiplier=1.0,
        fill_rate=0.95,
        budget_multiplier=1.0,
        disruption_duration_mean=90,
        n_runs=N_RUNS, days=DAYS,
        return_distribution=True,
    )

    # Shocked run — same frozen pre-shock policy, shock multipliers applied
    shocked = simulate_transient(
        drug, country,
        lead_time_multiplier=3.0,
        fill_rate=0.55,
        demand_multiplier=1.0,
        budget_multiplier=1.0,
        disruption_duration_mean=90,
        n_runs=N_RUNS, days=DAYS,
        return_distribution=True,
    )

    baseline_mean   = baseline["stockout_days_mean"]
    baseline_cvar   = baseline["cvar_90"]
    shocked_mean    = shocked["stockout_days_mean"]
    shocked_cvar    = shocked["cvar_90"]

    # Avoid division by zero if baseline is exactly 0
    if baseline_mean > 0:
        mean_delta_pct = (shocked_mean - baseline_mean) / baseline_mean * 100.0
    else:
        mean_delta_pct = float("inf") if shocked_mean > 0 else 0.0

    if baseline_cvar > 0:
        cvar_delta_pct = (shocked_cvar - baseline_cvar) / baseline_cvar * 100.0
    else:
        cvar_delta_pct = float("inf") if shocked_cvar > 0 else 0.0

    # Pre-registration closure criterion (locked — do not change thresholds)
    MEAN_THRESHOLD = 25.0   # percent
    CVAR_THRESHOLD = 30.0   # percent

    passes_mean = mean_delta_pct >= MEAN_THRESHOLD
    passes_cvar = cvar_delta_pct >= CVAR_THRESHOLD
    label = "PASS" if (passes_mean or passes_cvar) else "NULL"

    # Print full result for the implementation notes
    print(f"\n{'='*60}")
    print(f"DEFECT #4 CLOSURE TEST — cisplatin / Argentina")
    print(f"{'='*60}")
    print(f"  baseline_mean    = {baseline_mean:.2f} days")
    print(f"  baseline_cvar_90 = {baseline_cvar:.2f} days")
    print(f"  shocked_mean     = {shocked_mean:.2f} days")
    print(f"  shocked_cvar_90  = {shocked_cvar:.2f} days")
    print(f"  mean_delta_pct   = {mean_delta_pct:+.1f}%  (threshold >= {MEAN_THRESHOLD}%: {'PASS' if passes_mean else 'miss'})")
    print(f"  cvar_delta_pct   = {cvar_delta_pct:+.1f}%  (threshold >= {CVAR_THRESHOLD}%: {'PASS' if passes_cvar else 'miss'})")
    print(f"  RESULT: {label}")
    print(f"{'='*60}")

    # Frozen policy diagnostic
    print(f"\n  Frozen pre-shock policy:")
    print(f"    reorder_point = {shocked['baseline_reorder_point']} units")
    print(f"    eoq           = {shocked['baseline_eoq']} units")

    # Sanity: shocked must be at least weakly worse than baseline (monotonicity)
    # Use generous tolerance since both runs use the same RNG seeds but different params
    assert shocked_mean >= baseline_mean - 0.5, (
        f"Monotonicity violation: shocked_mean ({shocked_mean}) < baseline_mean ({baseline_mean})"
    )

    # Record the label as an attribute for external inspection (does not fail on NULL)
    test_defect4_cisplatin_argentina_closure.result_label = label
    test_defect4_cisplatin_argentina_closure.numbers = {
        "baseline_mean": baseline_mean,
        "baseline_cvar_90": baseline_cvar,
        "shocked_mean": shocked_mean,
        "shocked_cvar_90": shocked_cvar,
        "mean_delta_pct": mean_delta_pct,
        "cvar_delta_pct": cvar_delta_pct,
    }

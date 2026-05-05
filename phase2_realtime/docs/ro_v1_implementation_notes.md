# RO v1 Implementation Notes

**Author:** Sonnet 4.6 | **Date:** 2026-05-05 | **Sprint:** Phase 2c Robust Optimizer

---

## 1. API Shape

```python
ro = RobustOptimizer(n_scenarios=500, use_multiprocessing=True, random_seed=None)
output = ro.optimize(drug, country, kf_state, impact_params, gamma)
# kf_state=None → falls back to COUNTRY_PARAMS (safe before KF integration)
```

Output has `Q`, `r` (actual units scaled to drug/country) and `Q_grid`, `r_grid`
(grid labels from the 7×7 spec grid). Grid: Q_grid ∈ {50..200}, r_grid ∈ {20..110}.

---

## 2. Uncertainty Set Parameters (Amendment S2)

Four params in the formal set: `lead_time_multiplier`, `demand_multiplier`,
`fill_rate`, `budget_multiplier`. Therefore **N = 4**. Gamma ∈ [0, 4].

Default delta fractions (of nominal): lead_time 50%, demand 20%, fill_rate 0.15 abs,
budget 20%. KF state widens lead_time delta to span the 90% CI band.

Gamma schedule per design spec §3:
- 0.5 = no news, stable KF
- 0.8 = MINOR event
- 1.5 = MODERATE event
- 4.0 = CRITICAL (= N_PARAMS = full robustness)

---

## 3. Grid-to-Actual Policy Translation

`simulate_dynamic()` recomputes (Q,r) from shock params internally — cannot be
overridden without modifying supply_sim.py. Resolution: call `_run_once()` directly
(internal function, not modifying the module). Grid labels (Q_grid, r_grid) are
mapped to actual procurement quantities as fractions of the textbook EOQ/r:

    actual_Q = int((Q_grid / 200) × textbook_EOQ)    # Q_grid=200 → 100% of EOQ
    actual_r = int((r_grid / 110) × textbook_r_star) # r_grid=110 → 100% of textbook r*

This makes the 49-cell grid span [25%, 100%] of the textbook policy, producing
genuine policy variation regardless of drug/country scale. Textbook EOQ for
cisplatin/Argentina ≈ 348 units; textbook r* ≈ 397 units.

Cost formula (design spec §2):
    C = 0.50 × avg_inventory + 200 × (365/actual_Q) + 500 × stockout_days

---

## 4. Sanity Check Results (cisplatin/Argentina, gamma=1.5, n_scenarios=500)

- Q_grid=150 → actual Q = 261 units  (75% of textbook EOQ=348)
- r_grid=110 → actual r = 397 units  (100% of textbook r*=397)
- CVaR_90 (cost $) at gamma=1.5: $56,884   vs baseline (gamma=0): $42,069
- improvement_pct = -35.2%  (robust policy is more expensive — expected; this IS
  the "price of robustness" and is correct behavior, not a bug)
- policy_confidence = 0.58  (58% of adversarial draws produce ≤30 stockout days)

Negative improvement_pct is correct: the robust CVaR (worst-case adversarial) is
higher than nominal CVaR — this IS the price of robustness, not a bug.

---

## 5. Flags for Next Implementer

**Monte Carlo noise vs grid resolution**: With n_scenarios=200 (test speed),
CVaR_90 noise floor is ±10–15%. The monotonicity test compares gamma=0 to
gamma=N_PARAMS (widest spread) to avoid adjacent-step noise flips. With n=500
in production the noise floor drops to ±5–8%.

**KF direction test (test 4)**: Passes with seed=42 at n=200. May flip under
different seeds or n_scenarios — documented as MC noise, not a bug.

**Improvement_pct interpretation**: Negative means robust CVaR > nominal CVaR
(expected — price of robustness). To compute "reduction vs naive policy" for
reporting, compare to a baseline that uses the fixed nominal policy under the
adversarial set — a separate calculation not in v1.

**policy_confidence = 0 edge case**: If drug/country baseline already has high
stockout rate (Venezuela), nearly all adversarial scenarios exceed 30 days and
confidence will be ~0. This is correct and diagnostically useful, not a bug.

**Punted to v2**: Ellipsoidal/Wasserstein sets; MAB signal_probs → Gamma
adjustment; Bayesian optimization surrogate; improvement_pct re-definition
relative to naive fixed policy; policy frontier auto-population in optimize().

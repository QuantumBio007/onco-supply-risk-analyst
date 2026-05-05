# Path B Transient-Mode Simulator — Implementation Notes

**Sprint:** 2026-05-05 | **Implementer:** Sonnet 4.6
**Binding spec:** design_amendments_2026-05-05.md §B1
**Test:** phase2_realtime/tests/test_supply_sim_transient.py

---

## API Shape

```python
simulate_transient(
    drug, country,
    lead_time_multiplier=1.0, demand_multiplier=1.0,
    fill_rate=0.95, budget_multiplier=1.0,
    disruption_duration_mean=90,
    n_runs=500, days=365, service_level_target=0.95,
    return_distribution=False,
) -> dict
```

Signature mirrors `simulate_dynamic()` exactly. New keys in return dict:
- `"mode": "transient"` — distinguishes from dynamic in logs/audit
- `"baseline_reorder_point"`, `"baseline_safety_stock"`, `"baseline_eoq"` — the frozen pre-shock policy values for diagnostic inspection

## What Is Held Fixed vs. What Shocks

**Held fixed (computed from baseline COUNTRY_PARAMS only):**
- `reorder_point` (r) — uses `base_L_mean = cp["lead_time_mean"]`, not the shocked value
- `order_quantity` (Q/EOQ) — same baseline params feed `compute_policy()`

**Shocked within the disruption window:**
- Lead time distribution: `L_mean = cp["lead_time_mean"] * lead_time_multiplier`
- Demand: `d = daily_demand_mean * demand_multiplier`
- Fill rate: `eff_fill = structural_fill_rate * fill_rate`
- Budget: `eff_bud = structural_budget_cap * budget_multiplier`

After the disruption window, `_run_once()` reverts to the existing baseline params
(controlled by `base_*` arguments already in `_run_once()`).

## Departures from Amendment Doc

None material. The amendment specified "compute (Q,r) once from baseline COUNTRY_PARAMS."
That is implemented literally. The `disruption_start_override` / `disruption_end_override`
mechanism already in `_run_once()` was not needed — the geometric-distribution disruption
window path handles the 90-day mean correctly via `disruption_duration_mean`.

`simulate()` and `simulate_dynamic()` signatures and behavior are unchanged.

---

## Defect #4 Closure Result

**Shock parameters (pre-registered, locked):**
- drug=cisplatin, country=Argentina
- lead_time_multiplier=3.0, fill_rate=0.55, demand_multiplier=1.0, budget_multiplier=1.0
- disruption_duration_mean=90 days, n_runs=500

| Metric | Baseline | Shocked | Delta |
|--------|----------|---------|-------|
| stockout_days_mean | 7.30 d | 80.80 d | +1006.8% |
| cvar_90 | 22.10 d | 196.80 d | +790.5% |

**Frozen pre-shock policy:** reorder_point = 397 units, EOQ = 348 units

**RESULT: PASS** (both thresholds exceeded by a wide margin)
- mean_delta_pct = +1006.8% vs. threshold >= 25% — PASS
- cvar_delta_pct = +790.5% vs. threshold >= 30% — PASS

**Why the delta is so large (vs. the 12.9% in the original simulate_dynamic test):**
In `simulate_dynamic()`, the 3x lead time multiplier fed `compute_policy()`, inflating
the reorder point from 397 to ~1200 units. That large safety-stock buffer absorbed most
of the shock, producing only 12.9% mean increase. With the frozen 397-unit reorder point,
a 105-day mean lead time overwhelms the buffer and produces a 10x mean increase.

## Implications for Next Sprint

Path B unambiguously closes defect #4 at the pre-registered threshold. The diagnosis
in the amendment doc was correct: the root cause was policy adaptation masking the shock,
not inventory state estimation (Path A / KF). KF integration is still planned for lead-time
tracking, but it is NOT needed to close the alert miss. The next implementer can proceed
with KF for its own signal-quality value without pressure to also close this alert defect.

The +1006% delta is larger than expected and warrants calibration review: are Argentina's
baseline parameters (initial_stock_days=45, lead_time_mean=35) realistic for the hospitals
the model is intended to represent? The finding is valid as stated; the magnitude suggests
the frozen-policy assumption may be conservative (real procurement teams would emergency-order
earlier). That is a separate discussion from defect closure.

# Robust Optimization Design — OncoSupply Phase 2c

**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** SPEC (implementation in Weeks 4–8)  
**Depends on:** kalman_filter_design.md (KF_State output is RO primary input)  
**Purpose:** Compute worst-case (Q, r) inventory policies via CVaR-DRO. Replaces fixed SCENARIO_MAP scenario selection with continuous parameter-driven optimization.

---

## 1. Problem Statement

**Current constraint:** shock_mapper.py maps (shock_type, severity) → one of 4 fixed scenarios:
```python
("currency", "CRITICAL"): "Combined shock"   # static lookup
```

**Issue:** This discards the continuous impact parameters computed by event_classifier:
```python
{"lead_time_multiplier": 1.8, "fill_rate": 0.6, "demand_multiplier": 1.1, "budget_multiplier": 0.7}
```
These are wired to a fixed scenario instead of feeding directly into simulation.

**Solution:** Robust Optimization wraps supply_sim.py as a black-box objective. Given KF uncertainty estimates + event_classifier impact parameters, it finds the (Q, r) pair that minimizes worst-case CVaR_90 cost across all plausible supply-chain realizations.

**What it enables:**
- Continuous risk-cost tradeoff (policy frontier), not discrete scenario buckets
- Parameter uncertainty from KF directly propagates into procurement policy
- Auditable, defensible recommendations (regulators can see the uncertainty set)
- Expert-tunable conservatism via Gamma dial

---

## 2. Core Formulation

### Decision Variables
- $Q$: order quantity (units per order)
- $r$: reorder point (trigger inventory level)

### Objective
Minimize worst-case CVaR_90 of total cost:

$$\min_{Q, r} \max_{u \in \mathcal{U}} \text{CVaR}_{90}\left[ C(Q, r, u) \right]$$

Where:
- $u$: uncertain parameters (lead time, demand rate, fill rate, budget)
- $\mathcal{U}$: uncertainty set (defined below)
- $C(Q, r, u)$: total cost = holding cost + ordering cost + shortage penalty

**CVaR_90 interpretation:** Minimize expected cost in the worst 10% of scenarios. More conservative than minimizing expected cost; less conservative than worst-case (minimax).

### Cost Function (from supply_sim.py)
```python
C(Q, r, u) = holding_cost_per_unit * avg_inventory(Q, r, u)
           + ordering_cost_per_order * orders_per_year(Q, r, u)
           + shortage_penalty_per_day * stockout_days(Q, r, u)
```

Default weights (from Phase 1 SCENARIO_PARAMS):
- Holding cost: $0.50/unit/day
- Ordering cost: $200/order
- Shortage penalty: $500/day (oncology drugs — high penalty)

---

## 3. Uncertainty Set

### Type: Box Uncertainty (Bertsimas-Sim)

$$\mathcal{U}(\Gamma) = \left\{ u : u_i \in [\hat{u}_i - \delta_i, \hat{u}_i + \delta_i], \; \sum_i \frac{|u_i - \hat{u}_i|}{\delta_i} \leq \Gamma \right\}$$

Where:
- $\hat{u}_i$: nominal parameter value (from KF estimates or COUNTRY_PARAMS)
- $\delta_i$: uncertainty radius per parameter (from KF confidence intervals)
- $\Gamma$: conservatism budget (0 = nominal, N = fully robust across all N params simultaneously)

**Why Box + Gamma (not pure box, not ellipsoidal):**
- Pure box (Gamma = N): too conservative, requires all params to be simultaneously worst-case
- Ellipsoidal: requires covariance estimation (limited data in LATAM)
- Bertsimas-Sim: controls conservatism via single Gamma dial; computationally tractable; interpretable to non-experts

### Parameter Bounds from KF + Event Classifier

```python
uncertainty_set = {
    "lead_time": {
        "nominal": kf_state["uncertainty_bands"]["L_mean"][1],  # KF point estimate (exp(s[0]))
        "lower":   kf_state["uncertainty_bands"]["L_mean"][0],  # KF 90% lower
        "upper":   kf_state["uncertainty_bands"]["L_mean"][1],  # KF 90% upper
        # Expand on news event:
        "event_multiplier": impact_params.get("lead_time_multiplier", 1.0)
    },
    "fill_rate": {
        "nominal": 1.0,
        "lower":   impact_params.get("fill_rate", 1.0),         # from event_classifier
        "upper":   1.0
    },
    "demand_rate": {
        "nominal": country_params["demand_mean"],
        "lower":   country_params["demand_mean"],
        "upper":   country_params["demand_mean"] * impact_params.get("demand_multiplier", 1.0)
    }
}
```

### Gamma Schedule

| Condition | Gamma | Interpretation |
|-----------|-------|----------------|
| No news events, stable KF | 0.5 | Mild conservatism; 50% of params can shift |
| MINOR news event | 0.8 | Moderate hedge |
| MODERATE news event | 1.5 | Significant hedge; 2-3 params at bounds |
| CRITICAL news event | N (= 3) | Full robustness; assume all params worst-case |
| KF covariance growing fast | +0.3 to Gamma | Regime shift detected; add buffer |

**Expert elicitation target (Phase 2c Week 6):** Interview oncology pharmacist + procurement lead to validate these Gamma values against their intuitions about acceptable cost inflation.

---

## 4. Solver Strategy

**Approach:** Wrap supply_sim.py as a black-box objective; use exhaustive grid search over a coarse (Q, r) candidate grid.

**Why not Nelder-Mead:** Nelder-Mead optimizing a noisy Monte Carlo CVaR_90 estimate will not reliably converge. The noise floor on CVaR_90 from 500 samples is ~±15%. Optimizer steps of <1 unit in (Q, r) space produce CVaR changes smaller than that noise floor — the optimizer wanders randomly, not toward the optimum. Estimated actual runtime with Nelder-Mead: 2–4 hours, not 10 min.

### Grid Search (default)

```python
Q_candidates = [50, 75, 100, 125, 150, 175, 200]   # units per order
r_candidates = [20, 35, 50, 65, 80, 95, 110]        # reorder point (units)
# 7 × 7 = 49 combinations × 500 Monte Carlo samples = 24,500 draws total
# Runtime: ~8-12 min serial; ~2 min with multiprocessing.Pool(4)
```

```python
def optimize_policy(drug, country, kf_state, impact_params, gamma):
    best_policy = None
    best_cvar = float("inf")

    for Q in Q_candidates:
        for r in r_candidates:
            cvar = cvar_90_estimate(Q, r, uncertainty_set=U, n_scenarios=500)
            if cvar < best_cvar:
                best_cvar = cvar
                best_policy = (Q, r)

    return best_policy[0], best_policy[1], best_cvar
```

- Pros: deterministic; no optimizer convergence issues; trivially parallelizable; easy to reason about
- Cons: coarse grid misses continuous optimum — acceptable for procurement planning (±5 units in Q, r doesn't matter clinically)

### Future Option: Bayesian Optimization (Phase 3)

Once we have >50 (Q, r) evaluations logged, fit a Gaussian Process surrogate on the CVaR surface and use acquisition functions (EI, UCB) to query efficiently. This is the correct approach for expensive black-box objectives — not Nelder-Mead.

### CVaR_90 Estimator
```python
def cvar_90_estimate(Q: int, r: int, uncertainty_set: dict, n_scenarios: int = 500) -> float:
    """Sample n_scenarios from uncertainty set; return mean of worst 10%."""
    costs = []
    for _ in range(n_scenarios):
        u = sample_uncertainty_set(uncertainty_set)
        result = simulate(Q=Q, r=r, **u)
        costs.append(total_cost(result))
    costs.sort(reverse=True)
    return np.mean(costs[:int(0.10 * n_scenarios)])  # worst 10%
```

---

## 5. Policy Frontier

Beyond a single (Q, r) recommendation, compute a Pareto frontier sweeping Gamma:

```python
frontier = []
for gamma in [0.0, 0.5, 1.0, 1.5, 2.0, 3.0]:
    Q_opt, r_opt, cvar_90 = optimize_policy(gamma=gamma, ...)
    holding = estimate_holding_cost(Q_opt, r_opt)
    frontier.append({"gamma": gamma, "Q": Q_opt, "r": r_opt,
                      "cvar_90_days": cvar_90, "holding_cost_delta": holding})
```

This lets procurement teams pick their operating point on the cost–risk tradeoff, rather than accepting a single recommendation.

---

## 6. Input Interface (from KF + event_classifier + MAB)

```python
RO_Input = {
    # From KF
    "kf_state": KF_State,                      # see kalman_filter_design.md
    # From event_classifier
    "impact_params": {
        "lead_time_multiplier": 1.5,
        "demand_multiplier": 1.2,
        "fill_rate": 0.7,
        "budget_multiplier": 0.6
    },
    # From MAB (Phase 2c Week 8+)
    "signal_probs": {                           # P(shortage | signal) per category
        "manufacturing": 0.85,
        "currency": 0.70,
        ...
    },
    # Manual tuning
    "gamma": 1.5,                              # conservatism level
    "drug": "cisplatin",
    "country": "Argentina"
}
```

**Phase 2c Week 4–8:** Impact params and KF state wired. MAB signal_probs is optional (defaults to uniform if MAB not yet implemented).

---

## 7. Output Interface (to shock_mapper, alert_engine, dashboard)

```python
RO_Output = {
    "Q": 120,                          # recommended order quantity (units)
    "r": 65,                           # recommended reorder point (units)
    "CVaR_90_forecast": 14.2,          # expected stockout days in worst 10% of scenarios
    "policy_confidence": 0.78,         # fraction of uncertainty set where policy is feasible
    "gamma_used": 1.5,
    "policy_frontier": [               # optional: full Pareto curve
        {"gamma": 0.5, "Q": 100, "r": 50, "cvar_90_days": 8.1},
        {"gamma": 1.5, "Q": 120, "r": 65, "cvar_90_days": 14.2},
        {"gamma": 3.0, "Q": 155, "r": 85, "cvar_90_days": 22.0}
    ],
    "baseline_Q": 100,                 # current fixed-params policy for comparison
    "baseline_r": 50,
    "baseline_CVaR_90": 18.5,          # baseline policy's CVaR_90
    "improvement_pct": 23.2            # % reduction in CVaR_90 vs baseline
}
```

---

## 8. Integration with Existing Pipeline

### Replace shock_mapper.py fixed lookup:

**Current (Phase 2b):**
```python
scenario = SCENARIO_MAP.get((shock_type, severity), "Baseline")
result = run_simulation(drug, country, scenario)
```

**Phase 2c (parallel path — keep old path as fallback):**
```python
if kf_state and impact_params:
    ro_output = robust_optimizer.optimize(drug, country, kf_state, impact_params, gamma)
    alert = evaluate_risk_change_from_ro(ro_output)
else:
    scenario = SCENARIO_MAP.get((shock_type, severity), "Baseline")
    result = run_simulation(drug, country, scenario)
```

**Backward-compatible:** Phase 2b pipeline remains fully functional; RO is additive.

---

## 9. File Structure

```
phase2_realtime/
├── robust_optimizer.py             # RO class + CVaR estimator (Weeks 4-8)
├── uncertainty_sets.py             # Box, ellipsoidal, Wasserstein set classes
├── tests/
│   └── test_robust_optimizer.py   # unit + integration + backtesting
└── docs/
    ├── robust_optimization_design.md    # ← this file
    ├── gamma_tuning_rationale.md        # expert elicitation results (Week 6)
    └── ro_implementation_notes.md      # added during implementation
```

---

## 10. Acceptance Criteria (Gate for Week 8)

- [ ] RO produces feasible (Q, r) for all 4 drugs × 3 countries × 3 shock severities (36 cases)
- [ ] Cost inflation vs. baseline: < 15% at Gamma=1.5 (not overly conservative)
- [ ] CVaR_90 improvement vs. baseline: > 10% on at least 3 cases
- [ ] Policy frontier: generates 6-point Pareto curve without crashes
- [ ] Backtesting: historical scenarios (Venezuela 2018 FX crash, Argentina 2019 API restriction) → (Q, r) feasible in hindsight
- [ ] Expert validation: gamma schedule mapped to pharmacist/procurement input
- [ ] All tests pass; no solver divergence

---

## 11. Known Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Noisy Monte Carlo → slow convergence | High | Slow optimization (~10min) | Reduce n_scenarios to 200 for dev; 500 for production |
| Grid search misses between-grid optimum | Low | ±5 units error in (Q,r) | Clinically irrelevant; refine grid if needed |
| KF uncertainty bands too wide → very conservative RO | Medium | Inflated holding cost | Cap delta_i at 2× COUNTRY_PARAMS default |
| supply_sim.py not vectorized → bottleneck | High | Slow backtesting | Parallelize with multiprocessing.Pool |
| Expert elicitation unavailable | Medium | Gamma unvalidated | Use Delphi method with published LATAM shortage literature |

---

## References

- Bertsimas & Sim (2004). "The Price of Robustness." Operations Research 52(1):35–53.
- Ben-Tal, El Ghaoui, Nemirovski (2009). *Robust Optimization.* Princeton University Press.
- kalman_filter_design.md: KF_State interface (input to RO)
- TRACKER.md Phase 2c: timeline and milestones
- phase2_realtime/docs/phase2b_critical_findings.md: known modeling limitations

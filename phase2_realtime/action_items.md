# Phase 2 Action Items — Executable Checklist

**Last Updated:** 2026-05-02  
**Status:** Ready for Phase 2b pre-capstone validation → Phase 2c post-capstone implementation  
**Timeline:** Phase 2b (~1 week), Phase 2c (10-15 weeks)

---

## ✅ PHASE 2b — Pre-Capstone Validation (COMPLETE — 2026-05-02)

All Phase 2b tasks completed. See `docs/phase2b_critical_findings.md` for full analysis.

### 1. Classification Quality Test ✅ COMPLETE
**Result:** v1: 81.2% (13/16) → system prompt fixed → v2: 87.5% (14/16) ✅ PASS  
**3 misclassifications fixed:** FDA Form 483 → regulatory; healthcare budget cuts → demand; indirect climate → climate (not IRRELEVANT)  
**2 remaining:** Venezuela dollar restriction → currency (acceptable; downstream scenario is more correct); Colombia flooding → logistics (acceptable; same downstream scenario as climate)  
**Reports:** `classification_quality_report.md` (v1), `classification_quality_report_v2.md` (v2)

**Command:**
```bash
python3 -c "
from phase2_realtime.news_listener import QUERIES
from phase2_realtime.scheduler import run_cycle
import json

for category in QUERIES.keys():
    results = run_cycle(category, limit_articles=5)
    print(f'\n=== {category} ===')
    for alert in results.get('alerts_triggered', []):
        print(f\"{alert['drug']}: {alert['shock_type']}\")
"
```

---

### 2. Alert Integration End-to-End Test ✅ COMPLETE
**Method:** Synthetic event injection (bypassing news_listener) into shock_mapper → supply_sim → alert_engine  
**Results:** 3/3 scenarios mapped correctly; 2/3 fired alerts where expected  
**Known gap:** Manufacturing CRITICAL cisplatin/Argentina → +12.9% (below 25% threshold); root cause: steady-state Monte Carlo doesn't track real inventory level → Phase 2c Kalman Filter fix  
**Pipeline code verified correct:** scheduler.py calls format_alert() with correct args  
**Report:** `alert_integration_test.md`

**Example test case:**
```json
{
  "title": "India halts API exports to LATAM amid supply shortage",
  "description": "Indian manufacturing authority restricts pharmaceutical API exports...",
  "expected_shock_type": "manufacturing",
  "expected_severity": "CRITICAL",
  "expected_affected_drugs": ["cisplatin", "carboplatin"]
}
```

---

### 3. Regulatory MODERATE Mapping Fix ✅ COMPLETE
**Change:** `("regulatory","MODERATE")` → "Currency devaluation" (was: "API export restriction")  
**Rationale:** Regulatory pricing caps compress procurement budgets (like FX devaluation), not API supply  
**Note:** CRITICAL mapping kept as "Combined shock" — a full regulatory shutdown (import ban, licensing revocation) justifies both API + budget impact  
**File:** `shock_mapper.py` line 34

---

### 4. news_listener.py load_dotenv Fix ✅ COMPLETE
**Change:** Added `override=True` to `load_dotenv()` call at line 21  
**File:** `news_listener.py`

---

### 5. Capstone Documentation ✅ COMPLETE
**Files created:**
- `docs/phase_2_capstone_summary.md` — full architecture, validation results, Phase 2c roadmap
- `docs/phase2b_critical_findings.md` — honest critical review of all Phase 2b work
- `docs/classification_quality_report_v2.md` — v2 classifier results (87.5%)
- `docs/alert_integration_test.md` — corrected pipeline integration test
- `TRACKER.md` updated — Phase 2b complete; Phase 2c roadmap documented

---

## 🚀 PHASE 2c — Post-Capstone Implementation (10-15 weeks)

Start immediately after capstone submission (May 16 → June 27).

### WEEKS 1-2: Design & API Contracts

**Owner:** You  
**Goal:** Define interfaces between KF, RO, MAB so they work together  

#### Kalman Filter Design
- [x] Write specification: `phase2_realtime/docs/kalman_filter_design.md`
  - State vector definition: `[log(L_mean), log(sigma_L), demand_rate, demand_rate_drift, ...]`
  - Process noise Q: half-life ~30-60 days (matches SCENARIO_PARAMS disruption_duration_mean)
  - Measurement noise R: estimated from ERP error rates
  - Missing-observation handling: skip update, propagate prediction
- [x] Define KF output interface (to be consumed by RO + supply_sim):
  ```python
  KF_State = {
    "state": np.array([...]),
    "covariance": np.matrix([...]),
    "uncertainty_bands": {"L_mean": (lower, upper), "sigma_L": (lower, upper)}
  }
  ```

#### Robust Optimization Design
- [x] Write specification: `phase2_realtime/docs/robust_optimization_design.md`
  - Uncertainty set type: box vs. ellipsoid vs. Wasserstein-DRO
  - Gamma schedule: static (0.5) or event-triggered (varies by shock severity)
  - CVaR_90 objective: cost weights (holding, ordering, shortage penalty)
  - Integration: wrap `supply_sim.py` as black-box objective
- [x] Define RO input interface (from KF, event_classifier, MAB):
  ```python
  RO_Input = {
    "L_mean_hat": float,          # from KF
    "sigma_L_hat": float,         # from KF
    "covariance_P": np.matrix,    # from KF
    "impact_params": {            # from event_classifier
      "lead_time_multiplier": 1.5,
      "demand_multiplier": 1.2,
      "fill_rate": 0.7,
      "budget_multiplier": 0.6
    },
    "signal_probs": {...},        # from MAB: P(shortage | category_i)
    "gamma": 0.5                  # tuning parameter
  }
  ```
- [x] Define RO output interface (to shock_mapper, alert_engine):
  ```python
  RO_Output = {
    "Q": int,                     # order quantity
    "r": int,                     # reorder point
    "CVaR_90_forecast": float,    # forecasted tail risk
    "policy_confidence": float    # certainty of recommendation
  }
  ```

#### MAB Design
- [x] Write specification: `phase2_realtime/docs/mab_design.md`
  - Arms: 8 news categories
  - Reward: binary (shortage occurred within lead window) or continuous (magnitude)
  - Posterior: Beta(α,β) per category per SKU class
  - Cold-start priors: uniform Beta(1,1) or informed from Phase 2 alert history
- [x] Define MAB input interface (from event_classifier, shortage labeling system):
  ```python
  MAB_Update = {
    "category": "manufacturing",  # fired alert category
    "drug": "cisplatin",
    "country": "Argentina",
    "shortage_observed": True,    # labeled after 30-90 days
    "shortage_magnitude": 0.8     # fraction of demand unmet
  }
  ```
- [x] Define MAB output interface (to RO):
  ```python
  MAB_Output = {
    "posteriors": {               # Beta(α,β) summaries per category
      "manufacturing": {"mean": 0.85, "std": 0.10},
      "logistics_latam": {"mean": 0.60, "std": 0.15},
      ...
    },
    "top_signals": ["manufacturing", "regulatory", "currency"]  # ranked
  }
  ```

#### Master API Contract
- [x] Create `phase2_realtime/docs/api_contracts.md`
  - Mock JSON examples for all interfaces above
  - Define error handling (missing data, solver failures, etc.)
  - Version control: v1.0 baseline for Phase 2c

**Checklist:**
- [x] All 3 design specs written
- [x] All 3 input/output interfaces defined
- [x] Master API contract documented
- [ ] **Gate:** Code review with yourself: are interfaces coherent? Can you mock them?

---

### WEEKS 2-4: Kalman Filter Implementation

**Owner:** You  
**Timeline:** 2-3 weeks  
**Goal:** Online state estimation from noisy ERP feeds  

#### Code Structure
```
phase2_realtime/
├── kalman_filter.py          # KF class + state/covariance updates
├── tests/
│   └── test_kalman_filter.py  # unit + integration tests
└── docs/
    ├── kalman_filter_design.md
    └── kalman_filter_implementation_notes.md
```

#### Implementation Tasks
- [ ] Create `kalman_filter.py`:
  - [ ] Class `KalmanFilterSupplyChain(drug: str, country: str)`
    - [ ] `__init__()`: initialize state s_0, covariance P_0
    - [ ] `predict(dt: float)`: propagate state forward (random walk)
    - [ ] `update(observation, observation_type)`: update posterior via Bayes
    - [ ] `get_state()`: return current estimate + covariance
    - [ ] `handle_missing_observation()`: skip update, propagate
  - [ ] Support for 2D lead-time KF (log space): `[log(L_mean), log(sigma_L)]`
  - [ ] Optional: demand-rate tracking `[demand_rate, demand_rate_drift]`

- [ ] Create test harness:
  - [ ] Synthetic data: known lead times + noise → verify KF recovery within ±10%
  - [ ] ERP audit logs: real shipment receipts → verify estimates match ground truth
  - [ ] Missing-observation handling: drop 20% of observations, verify covariance grows gracefully
  - [ ] **Gate:** All tests pass; MAE < 10% after 30 observations

- [ ] Integration with `supply_sim.py`:
  - [ ] In `simulate()`: replace fixed `COUNTRY_PARAMS['lead_time_mean']` with `KF.state[0]`
  - [ ] Replace fixed `COUNTRY_PARAMS['lead_time_cv']` with `KF.state[1]`
  - [ ] Run side-by-side comparison: fixed (Q,r) vs. KF-estimated (Q,r) on same KPIs
  - [ ] **Gate:** Both variants runnable, results logged

**Effort Estimate:** 200 LOC (including tests), 2-3 weeks

---

### WEEKS 4-8: Robust Optimization Implementation

**Owner:** You  
**Timeline:** 4-6 weeks  
**Goal:** Worst-case (Q,r) policies via CVaR-DRO  

#### Code Structure
```
phase2_realtime/
├── robust_optimizer.py        # RO formulation + solver
├── uncertainty_sets.py        # box, ellipsoid, Wasserstein
├── tests/
│   └── test_robust_optimizer.py
└── docs/
    ├── robust_optimization_design.md
    └── gamma_tuning_rationale.md
```

#### Implementation Tasks
- [ ] Create `robust_optimizer.py`:
  - [ ] Class `RobustOptimizer(drug: str, country: str)`
    - [ ] `set_uncertainty_set(type: str, bounds: dict, gamma: float)`: define U
    - [ ] `optimize(objective_fn, KF_state: dict, impact_params: dict) → (Q, r, confidence)`: solve RO
    - [ ] `get_policy_frontier()`: return Pareto curve (cost vs. CVaR) for visualization
  - [ ] Solver: cvxpy with Gurobi/MOSEK backend for SOCP
  - [ ] Support for uncertainty-set expansion on news events (e.g., FDA Form 483 → lead-time bound × 2.5)

- [ ] Create `uncertainty_sets.py`:
  - [ ] `BoxUncertaintySet(demand_bounds, lead_time_bounds)`: min/max for each parameter
  - [ ] `EllipsoidalUncertaintySet(mean, covariance, radius)`: ellipsoid around KF estimate
  - [ ] `WassersteinUncertaintySet(empirical_dist, radius)`: Wasserstein ball
  - [ ] All three support dynamic radius adjustment on events

- [ ] Create test harness:
  - [ ] Backtesting: historical scenarios (FDA Form 483, FX crash) → verify (Q,r) feasible for all
  - [ ] Sensitivity: vary Gamma 0.0 → 1.0 → plot cost vs. CVaR_90 frontier
  - [ ] Comparison: RO vs. baseline (Q,r) on KPIs (stockout_days, cvar_90, holding_cost)
  - [ ] **Gate:** RO policy feasible for all scenarios; cost inflation < 15% vs. baseline

- [ ] Expert elicitation on Gamma:
  - [ ] Interview oncology pharmacist: "How risk-averse should inventory be?"
  - [ ] Interview procurement lead: "What's acceptable excess cost to avoid shortages?"
  - [ ] Map answers to Gamma values (e.g., 0.2 = risk-taking, 0.8 = conservative)
  - [ ] Write `docs/gamma_tuning_rationale.md` documenting expert input

- [ ] Integration with Phase 2:
  - [ ] Wrapper function: `RO_optimize(drug, country, KF_state, event_classifier_output) → RO_Output`
  - [ ] Replace or run in parallel with `compute_policy()` in `supply_sim.py`
  - [ ] Log all (Q, r) recommendations for comparison

**Effort Estimate:** 300 LOC (including uncertainty sets), 4-6 weeks

---

### WEEKS 8-10: Multi-Armed Bandit Implementation

**Owner:** You  
**Timeline:** 2-3 weeks  
**Goal:** Learn which news signals predict shortages  

#### Code Structure
```
phase2_realtime/
├── signal_learner.py         # Thompson Sampling
├── tests/
│   └── test_signal_learner.py
└── docs/
    └── mab_design.md
```

#### Implementation Tasks
- [ ] Create `signal_learner.py`:
  - [ ] Class `BanditLearner(arms: list = 8_news_categories)`
    - [ ] `__init__()`: initialize Beta(1,1) prior per arm
    - [ ] `reward(arm_id: int, success: bool, magnitude: float = 1.0)`: update posterior
    - [ ] `posterior_mean()`: return E[p_i | data] per arm
    - [ ] `posterior_cov()`: return uncertainty per arm
    - [ ] `rank_arms()`: return arms sorted by posterior mean
  - [ ] Support for contextual bandits (optional): condition on (country, drug_class)

- [ ] Create test harness:
  - [ ] Synthetic signals: known ground-truth arm probabilities → verify bandit learns correct ranking
  - [ ] Posterior entropy: should decrease over time (less uncertainty as data accumulates)
  - [ ] Cold-start regret: measure cumulative regret over first 100 pulls
  - [ ] **Gate:** Posterior means converge to ground truth within 20% error

- [ ] Integration with Phase 2:
  - [ ] When `event_classifier.py` fires alert (category=manufacturing), pass to bandit
  - [ ] When shortage is labeled (manual or auto-detected), call `reward(category_id, True)`
  - [ ] Feed `posterior_mean()` output to RO: adjust uncertainty-set radius by signal confidence
  - [ ] Log all signal weights and rankings for transparency

**Effort Estimate:** 200 LOC (including tests), 2-3 weeks

---

### WEEKS 10-12: Integration & System Testing

**Owner:** You  
**Timeline:** 2 weeks  
**Goal:** End-to-end pipeline: news → KF → MAB → RO → alert  

#### Integration Checklist
- [ ] End-to-end flow:
  - [ ] NewsAPI feed → `news_listener.py`
  - [ ] Articles → `event_classifier.py` (capture shock_type + impact params)
  - [ ] Classification → `signal_learner.py` (update bandit)
  - [ ] Bandit posterior + KF state → `robust_optimizer.py` (optimize (Q,r))
  - [ ] Recommendation → `alert_engine.py` (format alert)
  - [ ] Run 100 simulated days; verify all components fire in order

- [ ] Dashboard updates:
  - [ ] KF display: state estimates + uncertainty bands (σ_L plot)
  - [ ] RO display: policy frontier (cost vs. CVaR); current (Q,r) position
  - [ ] MAB display: posterior probabilities per news category (bar chart)
  - [ ] Alert display: trace signal → shock → order impact

- [ ] Regression tests:
  - [ ] Phase 2v3 alerts still fire correctly (no degradation)
  - [ ] Latency: KF + RO + MAB adds < 5 seconds to end-to-end cycle
  - [ ] CPU/memory: no runaway growth over 1000 cycles
  - [ ] **Gate:** All Phase 2b tests still pass

---

### WEEKS 12-15: Validation & Hardening

**Owner:** You + Oncology Pharmacist + Procurement Lead  
**Timeline:** 3 weeks  
**Goal:** Regulatory approval + operational handoff  

#### Documentation Tasks
- [ ] Regulatory brief: `phase2_realtime/docs/regulatory_brief.md`
  - [ ] KF: explain state vector, uncertainty quantification, missing-data handling
  - [ ] RO: uncertainty set definition, Gamma tuning rationale, worst-case guarantee proof (CVaR_90 feasibility)
  - [ ] MAB: posterior interpretation, cold-start period (6 months), decision rules
  - [ ] Target audience: FDA/ANVISA/COFEPRIS reviewers
  - [ ] **Gate:** Pharmacist + regulatory expert review

- [ ] Operations manual: `phase2_realtime/docs/operations_manual.md`
  - [ ] How to retune KF: Q, R parameters, when to refit
  - [ ] How to adjust RO: Gamma, uncertainty-set bounds, when to recalibrate
  - [ ] How to bootstrap MAB: initial priors, labeled data collection, when to reset
  - [ ] Alerting thresholds: CPU, memory, latency
  - [ ] Rollback procedure: how to switch back to Phase 2v3 if KF/RO/MAB fail

- [ ] Shadow-mode deployment:
  - [ ] Run KF + RO + MAB in production ERP environment (read-only)
  - [ ] Log all decisions; do NOT affect procurement (yet)
  - [ ] Compare KF + RO + MAB recommendations vs. current (Q,r) for 2-4 weeks
  - [ ] **Gate:** Recommendations differ from (Q,r) in expected ways; no surprises
  - [ ] Example: KF detects demand-rate increase → RO recommends higher r (reorder point) → sensible?

- [ ] Sign-off:
  - [ ] Pharmacist review: "Do the recommendations make clinical sense?"
  - [ ] Procurement lead review: "Are we comfortable with the policy frontier tradeoffs?"
  - [ ] Operations approval: "Can we operationalize this in our ERP?"
  - [ ] **Gate:** All three sign off before production deployment

---

## 📊 Success Criteria

- [ ] **Phase 2b:** Classification accuracy ≥ 80%; alert pipeline end-to-end working
- [ ] **Phase 2c Week 2:** KF, RO, MAB designs finalized; API contracts locked
- [ ] **Phase 2c Week 4:** KF fully implemented + integrated with supply_sim.py
- [ ] **Phase 2c Week 8:** RO fully implemented + policy frontier generated
- [ ] **Phase 2c Week 10:** MAB fully implemented + posterior tracking active
- [ ] **Phase 2c Week 12:** End-to-end pipeline working; dashboard updated; regression tests passing
- [ ] **Phase 2c Week 15:** Regulatory docs + operations manual finalized; sign-off complete
- [ ] **Production Readiness:** Shadow-mode deployment successful; ready for controlled rollout

---

## 📁 Folder Structure (All Under phase2_realtime/)

```
phase2_realtime/
├── __init__.py
├── news_listener.py           [EXISTING]
├── event_classifier.py        [EXISTING]
├── shock_mapper.py            [EXISTING]
├── alert_engine.py            [EXISTING]
├── scheduler.py               [EXISTING]
│
├── kalman_filter.py           [NEW - Phase 2c]
├── robust_optimizer.py        [NEW - Phase 2c]
├── uncertainty_sets.py        [NEW - Phase 2c]
├── signal_learner.py          [NEW - Phase 2c]
│
├── tests/                     [EXPANDED]
│   ├── __init__.py
│   ├── test_news_listener.py  [EXISTING]
│   ├── test_event_classifier.py [EXISTING]
│   ├── test_kalman_filter.py  [NEW]
│   ├── test_robust_optimizer.py [NEW]
│   └── test_signal_learner.py [NEW]
│
├── docs/                      [NEW - Phase 2c]
│   ├── classification_quality_report.md
│   ├── alert_integration_test.md
│   ├── phase_2_capstone_summary.md
│   ├── kalman_filter_design.md
│   ├── robust_optimization_design.md
│   ├── gamma_tuning_rationale.md
│   ├── mab_design.md
│   ├── api_contracts.md
│   ├── regulatory_brief.md
│   ├── operations_manual.md
│   └── kalman_filter_implementation_notes.md
│
└── action_items.md            [THIS FILE]
```

---

## 🔗 Reference Documents

- **TRACKER.md** — Executive summary (source of truth)
- **action_items.md** — Working checklist (this file)
- Individual design docs in `docs/` folder

---

## 📞 Sign-Off

**Phase 2b Sign-Off (COMPLETE — 2026-05-02):**
- [x] Classification quality test: ✅ PASS (87.5% after system prompt v2 fix)
- [x] Alert integration test: ✅ PASS (pipeline correct; 1 known calibration gap documented)
- [x] Regulatory MODERATE mapping: ✅ DECIDED → Currency devaluation
- [x] news_listener fix: ✅ COMMITTED (override=True)
- [x] event_classifier system prompt v2: ✅ COMMITTED (3 boundary cases fixed)
- [x] Capstone docs: ✅ COMPLETE
- Ready for capstone: ✅ YES

**Phase 2c Sign-Off (Before Production):**
- [ ] KF fully tested and integrated: YES/NO
- [ ] RO policy frontier validated: YES/NO
- [ ] MAB posterior tracking active: YES/NO
- [ ] Regulatory brief reviewed: YES/NO
- [ ] Pharmacist approved: YES/NO
- [ ] Procurement approved: YES/NO
- [ ] Operations approved: YES/NO
- Ready for production: YES/NO

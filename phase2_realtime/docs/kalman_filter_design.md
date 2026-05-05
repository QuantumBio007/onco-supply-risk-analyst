# Kalman Filter Design — OncoSupply Phase 2c

**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** SPEC (implementation in Weeks 2–4)  
**Purpose:** Online state estimation from noisy ERP/supply-chain data; feeds Robust Optimization uncertainty set and supply_sim.py (Q,r) policies.

---

## 1. Problem Statement

**Current constraint:** `supply_sim.py` uses fixed COUNTRY_PARAMS:
```python
"Argentina": {"lead_time_mean": 28, "lead_time_cv": 0.25, ...}
```
These are static snapshot estimates. LATAM supply chains drift (shipping regime shifts, carrier changes, regulatory delays). The Kalman Filter tracks this drift in real time with quantified uncertainty.

**What it enables:**
- Adaptive (Q,r) policies that tighten when data is stable and widen when regime shift detected
- Uncertainty bands for Robust Optimization's uncertainty set (no more fixed CV assumptions)
- Outlier flagging that correlates with news events from event_classifier

---

## 2. State Vector

### 2D Core (Lead-Time Only — implement first)

$$s_t = \begin{bmatrix} \log(L_{\text{mean},t}) \\ \log(\sigma_{L,t}) \end{bmatrix}$$

- $L_{\text{mean},t}$: expected procurement lead time (days)
- $\sigma_{L,t}$: standard deviation of lead time (days)
- **Log-space rationale:** Both quantities are strictly positive. Multiplicative shocks (e.g., "lead times doubled") become additive in log space. Symmetric noise in log space stays positive in natural space.

### 4D Extended (Lead-Time + Demand — optional v2)

$$s_t = \begin{bmatrix} \log(L_{\text{mean},t}) \\ \log(\sigma_{L,t}) \\ \mu_{d,t} \\ \theta_{d,t} \end{bmatrix}$$

- $\mu_{d,t}$: demand rate (units/day)
- $\theta_{d,t}$: demand drift (units/day²)

**Decision:** Start with 2D. Add demand tracking in Phase 2c Week 3 if MAB signals suggest demand-surge category is a top predictor.

---

## 3. Process Model

**Model:** Random walk (no mean reversion). LATAM supply chains have regime shifts — mean-reversion models assume return to steady state, which doesn't hold here.

$$s_{t+1} = s_t + w_t, \quad w_t \sim \mathcal{N}(0, Q)$$

$$Q = \begin{bmatrix} \sigma_w^2 & 0 \\ 0 & \sigma_w^2 \end{bmatrix}$$

**Tuning $\sigma_w$:**

LATAM oncology procurement runs on bulk purchase cycles (~quarterly; 4–12 POs per drug per country per year). The KF must track **slow structural drift** (lead times shifting from 28→33 days over 6 months). Fast shocks are handled by the news pipeline — not the KF.

**Why $\sigma_w = 0.05$/day is wrong:** Over a 90-day observation gap, covariance grows by $0.05^2 \times 90 = 0.225$. Starting from $P_0 = 0.04$, the posterior becomes $P = 0.265$, giving a 90% CI of approximately $[11, 72]$ days — uselessly wide. The filter degrades to the prior between every procurement cycle.

**Revised default: $\sigma_w = 0.005$/day.**
- Over a 90-day gap: $P$ grows by only $0.005^2 \times 90 = 0.0023$. CI stays near $[24, 33]$ days — meaningful.
- Over 1 year with no updates: CI reaches $\sim[21, 38]$ days — captures plausible year-long structural drift.
- After 4 quarterly observations, $P$ converges to $\sim0.01$–$0.02$ (tight posterior).

**Separation of concerns:**
- KF ($\sigma_w = 0.005$/day): tracks slow structural drift between quarterly PO cycles
- News pipeline (event_classifier + RO uncertainty set expansion): handles fast shocks in real time
- Do NOT increase $\sigma_w$ to capture news-shock speed — that conflates two different mechanisms

- **Recalibrate after 12 PO observations** (~1 year of data): compare predicted vs. actual variance growth

---

## 4. Measurement Model

### Observable A: Lead-Time (Primary)

**Source:** PO receipt logs — `receipt_date - order_date` per shipment.

$$z_t^{(L)} = \log(L_{\text{actual},t}) + v_t^{(L)}, \quad v_t^{(L)} \sim \mathcal{N}(0, R_L)$$

**Default $R_L = 0.01$** (~10% ERP measurement error in log space).

### Observable B: Demand (Secondary)

**Source:** Daily units withdrawn from inventory.

$$z_t^{(d)} = d_{\text{actual},t} + v_t^{(d)}, \quad v_t^{(d)} \sim \mathcal{N}(0, R_d)$$

**Default $R_d = (\mu_d \times 0.30)^2$** (~30% demand variability, Poisson-like).

### Observable C: On-Hand Inventory (Optional)

**Source:** Daily ERP balance sheets (if available).

**Default $R_{\text{inv}} = (\text{safety stock} \times 0.20)^2$** (physical count error ~20%).

---

## 5. Initialization

From existing COUNTRY_PARAMS:

```python
# Argentina example
s_0 = [log(28), log(7)]   # lead_time_mean=28, cv=0.25 → sigma=7
P_0 = [[0.04, 0],          # ~20% initial uncertainty in log space
       [0, 0.04]]
```

Use COUNTRY_PARAMS for all three countries. P_0 = 0.04 diagonal means we trust the priors at ±20% (log space).

---

## 6. Missing Observations

Real ERP feeds are incomplete. Strategy:

1. **Skip update, propagate prediction:**
   ```python
   # No observation on day t
   s_t = s_{t-1}          # state unchanged
   P_t = P_{t-1} + Q      # uncertainty grows
   ```

2. **Warning threshold:** If no lead-time observations for >14 days, log warning.

3. **Partial updates:** If demand observed but not lead-time, update on demand only. Lead-time uncertainty continues growing.

4. **Event-triggered re-init:** On CRITICAL news event (from event_classifier), reset P to P_0 to reflect regime uncertainty. Do NOT reset state (we don't know new mean yet).

---

## 7. Outlier Handling

Do NOT discard outliers — they may be real shocks.

**Rule:** If $|z_t - \hat{z}_t| > 3\sqrt{R + H P H^T}$ (>3σ residual):
- Update filter normally (Kalman gain naturally downweights)
- Flag for cross-reference with news events:
  ```python
  # Flag example
  {"timestamp": t, "type": "lead_time_outlier", 
   "observed": 54, "expected": 28, "z_score": 4.1,
   "check_news": True}
  ```

---

## 8. Output Interface (to RO + supply_sim)

```python
KF_State = {
    "state": np.array([log_L_mean, log_sigma_L]),  # 2D
    "covariance": np.array([[P00, P01], [P10, P11]]),  # 2x2
    "uncertainty_bands": {
        "L_mean": (L_lower_90, L_upper_90),    # 90% CI in natural space
        "sigma_L": (sigma_lower_90, sigma_upper_90)
    },
    "drug": "cisplatin",
    "country": "Argentina",
    "last_updated": "2026-05-02",
    "observations_count": 47
}
```

**Computing 90% bands:**
```python
z90 = 1.645
L_lower = exp(s[0] - z90 * sqrt(P[0,0]))
L_upper = exp(s[0] + z90 * sqrt(P[0,0]))
sigma_lower = exp(s[1] - z90 * sqrt(P[1,1]))
sigma_upper = exp(s[1] + z90 * sqrt(P[1,1]))
```

These bands feed directly into Robust Optimization's uncertainty set.

---

## 9. Integration with supply_sim.py

**Current:**
```python
def simulate(..., lead_time_mean=28, lead_time_cv=0.25):
    lead_time = np.random.normal(lead_time_mean, lead_time_mean * lead_time_cv)
```

**Phase 2c (add kf_state param):**
```python
def simulate(..., kf_state=None):
    if kf_state is not None:
        L_mean = np.exp(kf_state["state"][0])
        sigma_L = np.exp(kf_state["state"][1])
    else:
        L_mean = lead_time_mean  # fallback to COUNTRY_PARAMS
        sigma_L = lead_time_mean * lead_time_cv
    lead_time = max(1, np.random.normal(L_mean, sigma_L))
```

**Backward-compatible:** Existing calls without kf_state still work.

---

## 10. Tuning Parameters

| Parameter | Default | Range | Rationale |
|-----------|---------|-------|-----------|
| `sigma_w` | 0.005/day | 0.001–0.02 | Slow structural drift; quarterly PO cycle; fast shocks handled by news pipeline |
| `R_L` | 0.01 | 0.005–0.05 | ERP lead-time measurement noise |
| `R_d` | (μ×0.30)² | varies | Demand variability; calibrate from history |
| `P_0` | 0.04 | 0.01–0.10 | Initial uncertainty; 20% in log space |
| CI level | 90% (z=1.645) | 80–95% | Uncertainty band width for RO |
| Outlier threshold | 3σ | 2–4σ | Flag for news correlation |
| Missing-obs warning | 14 days | 7–30 | Log warning if no updates |

---

## 11. File Structure

```
phase2_realtime/
├── kalman_filter.py                    # KF class implementation (Weeks 2-4)
├── tests/
│   └── test_kalman_filter.py           # unit + integration tests
└── docs/
    ├── kalman_filter_design.md         # ← this file
    └── kalman_filter_implementation_notes.md  # added during Week 3-4
```

---

## 12. Acceptance Criteria (Gate for Week 4)

- [ ] KF converges: MAE < 10% after 30 synthetic observations
- [ ] No divergence under 30-day observation gap (covariance grows, no NaN)
- [ ] Outlier flagging works (3σ threshold, manual spot-check)
- [ ] supply_sim.py accepts kf_state, produces valid (Q,r)
- [ ] Side-by-side: KF-adaptive vs. fixed params on 1 baseline case (results logged)
- [ ] All unit tests pass

---

## References

- Welch & Bishop (2006). "An Introduction to the Kalman Filter." UNC-CS TR 95-041.
- TRACKER.md: SCENARIO_PARAMS (disruption durations, COUNTRY_PARAMS priors)
- phase2_realtime/docs/phase2b_critical_findings.md: real event examples for validation

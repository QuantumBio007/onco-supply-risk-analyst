# Multi-Armed Bandit Design — OncoSupply Phase 2c

**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** SPEC (implementation in Weeks 8–10)  
**Depends on:** event_classifier.py (8 news categories), RO_Input interface  
**Purpose:** Learn which of the 8 news signal categories best predict actual drug shortages. Feeds posterior probabilities into Robust Optimization to weight uncertainty set dynamically.

---

## 1. Problem Statement

**Current constraint:** All 8 news categories are treated equally. A "currency" article and a "company" article both trigger identical pipeline behavior if classified at the same severity.

**Issue:** In practice, some signals predict shortages much better than others. A currency collapse in Venezuela has historically caused real stockouts. A company earnings announcement rarely does. But we don't know the true signal quality — and it varies by drug class and country.

**Solution:** Thompson Sampling (Bayesian multi-armed bandit). Treat each news category as an "arm." After each news-triggered event, observe whether a shortage materialized within the lead window. Update the posterior probability P(shortage | category). Feed these posteriors into RO to adjust conservatism by signal quality.

**What it enables:**
- RO Gamma dial calibrated by observed signal reliability (not just expert intuition)
- Transparent signal weights — procurement teams can see why one category triggers a larger hedge
- Self-improving: as more shortage/no-shortage labels arrive, signal weights become more accurate

---

## 2. Arms Definition

8 arms = 8 news categories from event_classifier:

| Arm ID | Category | Prior Hypothesis |
|--------|----------|-----------------|
| 0 | `manufacturing` | High predictive value — direct production disruption |
| 1 | `logistics` | High — port/shipping disruptions cascade quickly |
| 2 | `regulatory` | Medium-high — regulatory actions have long lead times |
| 3 | `demand` | Low-medium — demand surges strain supply but don't break it |
| 4 | `currency` | High for Venezuela/Argentina — FX collapse → procurement collapse |
| 5 | `political` | Medium — unpredictable; sometimes resolves without supply impact |
| 6 | `climate` | Medium — seasonal; recovery depends on port alternatives |
| 7 | `company` | Low — company news rarely translates to shortage |

These are **priors only** — MAB will learn actual values from data.

---

## 3. Reward Definition

**Reward signal:** Did a shortage materialize following this news event?

### The Base-Rate Problem

A naïve binary reward (shortage occurred = 1, else = 0) is **confounded by country-level base rates.** Venezuela has chronic shortages ~8–10 months/year regardless of any specific news event. If `currency` fires 30 times and 25 Venezuela shortages occur, the posterior learns P(shortage | currency) ≈ 0.83. But the background shortage rate is already ~0.80. The currency signal added almost nothing — yet the MAB will treat it as highly informative and inflate RO's Gamma unnecessarily.

**The MAB must learn marginal predictive value, not absolute shortage rates.**

### Architecture Fix: Country-Stratified Arms + Background Arm

Run a separate MAB instance per country (3 instances: Argentina, Colombia, Venezuela). Each has:
- 8 **signal arms**: one per news category
- 1 **background arm**: tracks shortage rate when *no* signal fired in the window

```python
# Per country, per drug class:
alpha_signal[country][category]  # signal arm successes
beta_signal[country][category]   # signal arm failures
alpha_background[country]        # background arm successes (no signal fired)
beta_background[country]         # background arm failures
```

**Signal lift** is the operative metric — not raw posterior mean:

```python
signal_lift[category] = posterior_mean(signal_arm) - posterior_mean(background_arm)
# Venezuela currency: 0.83 - 0.80 = +0.03 (low lift — signal barely beats baseline)
# Argentina currency: 0.72 - 0.12 = +0.60 (high lift — signal actually predicts something)
```

This is what feeds RO's Gamma: a signal with low lift gets no Gamma boost even if its absolute posterior is high.

### Binary Reward (v1 — implement first)
```
reward = 1  if stockout_days > threshold within lead_window days of event
reward = 0  otherwise
```

- `threshold`: 3+ stockout-days (matches HIGH severity definition)
- `lead_window`: 90 days (typical procurement lead time in LATAM)
- Background arm updated every 90-day window where no signal fires for that country

### Continuous Reward (v2 — optional)
```
reward = min(stockout_days / 30.0, 1.0)   # normalized 0–1
```
Captures magnitude, not just binary occurrence. Same base-rate correction applies using continuous lift.

**Default: Binary reward (v1) with per-country stratification + background arm.**

---

## 4. Thompson Sampling

### Posterior Model

Beta-Bernoulli conjugate: each arm $i$ has posterior $\text{Beta}(\alpha_i, \beta_i)$

- $\alpha_i$: number of times arm $i$ fired and shortage occurred + prior
- $\beta_i$: number of times arm $i$ fired and no shortage + prior
- $P(\text{shortage} | \text{arm}_i) \sim \text{Beta}(\alpha_i, \beta_i)$

### Cold-Start Priors

**Option A: Uniform (no knowledge):** $\text{Beta}(1, 1)$ for all arms. Exploration-heavy early on.

**Option B: Informed priors from Phase 2b alert history:** Use Phase 2 SCENARIO_MAP expert judgment:
```python
INFORMED_PRIORS = {
    "manufacturing": Beta(3, 1),   # high prior — 75% base rate
    "logistics":     Beta(2, 1),   # medium-high
    "regulatory":    Beta(2, 2),   # medium
    "demand":        Beta(1, 2),   # low-medium
    "currency":      Beta(3, 1),   # high (LATAM-specific)
    "political":     Beta(1, 2),   # low-medium
    "climate":       Beta(1, 2),   # medium
    "company":       Beta(1, 3),   # low
}
```

**Default: Option B (informed priors).** Reduces cold-start exploration period; priors are weakly informative (total count = 3–4, so data overwhelms after ~20 observations).

### Update Rule

```python
def reward(arm_id: int, shortage_observed: bool, magnitude: float = 1.0):
    if shortage_observed:
        alpha[arm_id] += 1
    else:
        beta[arm_id] += 1
```

### Sampling (for Gamma selection in RO)

```python
def sample_posteriors() -> dict:
    return {
        arm: np.random.beta(alpha[arm], beta[arm])
        for arm in arms
    }

def posterior_mean() -> dict:
    return {
        arm: alpha[arm] / (alpha[arm] + beta[arm])
        for arm in arms
    }
```

---

## 5. Integration with Robust Optimization

MAB feeds **signal lift** (not raw posterior mean) into RO's Gamma schedule. A signal that merely confirms a country's chronic shortage rate earns no Gamma boost.

### Gamma Mapping (lift-based)

```python
def compute_gamma(signal_category: str, country: str, base_severity: str) -> float:
    """Map MAB signal lift + event severity → Gamma for RO."""
    p_signal     = mab[country].posterior_mean_signal(signal_category)
    p_background = mab[country].posterior_mean_background()
    signal_lift  = max(p_signal - p_background, 0.0)  # clamp to [0, 1]

    base_gamma = {
        "CRITICAL": 3.0,
        "MODERATE": 1.5,
        "MINOR": 0.5
    }[base_severity]

    # Lift in [0,1] → multiplier in [0.5, 1.5]
    # lift=0.0 (signal = background): multiplier=0.5, Gamma halved — signal is noise
    # lift=0.5 (signal is meaningfully predictive): multiplier=1.0, Gamma unchanged
    # lift=1.0 (signal perfectly predicts beyond baseline): multiplier=1.5, Gamma boosted
    reliability_multiplier = 0.5 + signal_lift

    return min(base_gamma * reliability_multiplier, 3.0)  # cap at 3.0
```

**Example:** Currency CRITICAL, Venezuela (lift=0.03): Gamma = 3.0 × 0.53 = 1.59 — signal barely beats baseline, conservatism reduced  
**Example:** Currency CRITICAL, Argentina (lift=0.60): Gamma = 3.0 × 1.10 = 3.0 — signal highly informative, full conservatism warranted  
**Example:** Company MINOR, Argentina (lift=0.05): Gamma = 0.5 × 0.55 = 0.28 — minimal hedge

---

## 6. Shortage Labeling System

MAB requires ground-truth labels. This is the hardest operational requirement.

### Labeling Sources (in order of preference)

1. **ERP stockout logs:** Actual days where on-hand inventory = 0. Best source; requires ERP integration.
2. **Procurement team reports:** Manual weekly reports of drug availability. Reliable but delayed.
3. **Public shortage databases:** FDA drug shortage database, PAHO shortage alerts. Partial coverage.
4. **Proxy: simulation-based labels:** If no real data, use supply_sim.py to classify: "did the shock scenario produce HIGH/CRITICAL outcome?" — imperfect but enables system to run before real data arrives.

**Phase 2c v1:** Use proxy (simulation-based) labels to bootstrap MAB. Replace with real ERP labels when available.

### Label Delay

Real shortage data arrives 30–90 days after the triggering event. Handle via delayed-reward queue:

```python
PENDING_LABELS = []  # events awaiting shortage outcome

# On event:
PENDING_LABELS.append({
    "event_id": uuid,
    "category": "currency",
    "drug": "trastuzumab",
    "country": "Venezuela",
    "event_date": "2026-05-02",
    "label_due_date": "2026-08-02"  # +90 days
})

# On label arrival (or due date):
mab.reward(arm_id="currency", shortage_observed=True)
```

---

## 7. Persistence

MAB posteriors must survive restarts (unlike PROCESSED_ARTICLES which resets in Phase 2b).

```python
# Save state
import json

def save_state(filepath: str):
    state = {"alpha": alpha, "beta": beta, "n_updates": n_updates}
    with open(filepath, "w") as f:
        json.dump(state, f)

def load_state(filepath: str):
    with open(filepath) as f:
        state = json.load(f)
    alpha.update(state["alpha"])
    beta.update(state["beta"])
```

**Default path:** `phase2_realtime/mab_state.json` (gitignored — contains operational learning data, not code).

---

## 8. Output Interface (to RO)

Note: output is **per country** (stratified). RO selects the relevant country instance.

```python
MAB_Output = {
    "country": "Venezuela",
    "background_rate": 0.80,          # P(shortage | no signal) for this country
    "signal_lifts": {                  # KEY metric: P(shortage|signal) - background_rate
        "manufacturing": 0.05,         # currency barely beats Venezuela baseline
        "logistics":     0.03,
        "regulatory":    0.06,
        "demand":        0.02,
        "currency":      0.03,         # Venezuela: all lifts near zero (chronic shortage)
        "political":     0.04,
        "climate":       0.03,
        "company":       0.01
    },
    "posterior_means": {               # raw P(shortage | signal) — for audit only
        "manufacturing": 0.85,
        "currency":      0.83,
        ...
    },
    "top_signals": ["manufacturing", "regulatory", "currency"],  # ranked by signal_lift
    "n_observations": {
        "manufacturing": 23,
        "currency": 31,
        "background": 12,              # 90-day windows with no signal
        ...
    },
    "last_updated": "2026-05-02"
}
```

**Contrast: Argentina MAB_Output** (low base rate — signals are actually informative):
```python
{
    "country": "Argentina",
    "background_rate": 0.10,
    "signal_lifts": {
        "currency":      0.62,         # peso crash reliably predicts shortages above baseline
        "manufacturing": 0.45,
        "regulatory":    0.38,
        "company":       0.05
    },
    ...
}
```

---

## 9. File Structure

```
phase2_realtime/
├── signal_learner.py              # BanditLearner class (Weeks 8-10)
├── mab_state.json                 # runtime posterior state (gitignored)
├── tests/
│   └── test_signal_learner.py
└── docs/
    └── mab_design.md              # ← this file
```

---

## 10. Acceptance Criteria (Gate for Week 10)

- [ ] Thompson Sampling updates correctly (unit test: 100 forced rewards → posterior mean converges to true rate ±10%)
- [ ] Cold-start priors load correctly; uniform priors also supported
- [ ] Delayed-reward queue: labels applied correctly after lead_window
- [ ] Persistence: save/load state roundtrip without data loss
- [ ] Gamma mapping uses signal_lift not raw posterior — Venezuela currency CRITICAL gets lower Gamma than Argentina currency CRITICAL when both have same raw posterior (sanity check)
- [ ] Background arm updates correctly on 90-day no-signal windows
- [ ] Integration with RO: MAB signal_lifts feed compute_gamma(), which feeds RO grid search
- [ ] All tests pass

---

## 11. Known Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| No real shortage labels available | High (near-term) | MAB can't learn | Use simulation-based proxy labels until ERP integrated |
| High chronic shortage base rate (Venezuela) confounds signal learning | High | All arm posteriors near prior; lifts near zero | Addressed by per-country stratification + background arm; signal_lift is the operative metric |
| Background arm cold start | Medium | background_rate estimate unreliable early | Require min 10 background windows before using lift; fall back to prior-based Gamma |
| 8 arms + 3 countries = 24 signal arms + 3 background arms | Low | Data thinly spread | Arms are independent Beta models; no curse of dimensionality |
| Posterior drift over time | Medium | Old data distorts signal | Add forgetting factor: decay alpha/beta by 0.99/month |

---

## References

- Russo et al. (2018). "A Tutorial on Thompson Sampling." Foundations and Trends in ML.
- Chapelle & Li (2011). "An Empirical Evaluation of Thompson Sampling." NeurIPS.
- event_classifier.py: 8 category definitions (arm labels)
- kalman_filter_design.md, robust_optimization_design.md: upstream interfaces

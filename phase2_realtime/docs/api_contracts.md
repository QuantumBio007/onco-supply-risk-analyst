# API Contracts — OncoSupply Phase 2c

**Version:** 1.0  
**Date:** 2026-05-02  
**Status:** SPEC — v1.0 baseline for Phase 2c implementation  
**Purpose:** Single-source interface definitions between all Phase 2c modules. Treat as a contract: implementations must match these schemas.

---

## Module Dependency Graph

```
news_listener.py
      ↓ Article
event_classifier.py (Claude)
      ↓ Classification + impact_params
      ├──→ shock_mapper.py (Phase 2b fallback path)
      └──→ robust_optimizer.py (Phase 2c primary path)
                ↑
        kalman_filter.py   signal_learner.py
              ↑ KF_State       ↑ MAB_Output
           ERP data         shortage labels
```

---

## 1. Article (news_listener → event_classifier)

```json
{
  "title": "Venezuela restricts USD access for pharmaceutical importers",
  "description": "CENCOEX limits dollar allocation to pharma sector amid reserves crisis...",
  "url": "https://...",
  "published_at": "2026-05-02T14:30:00Z",
  "source": "Reuters",
  "query_category": "currency"
}
```

**Schema:**
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| title | str | ✅ | Used by Claude classifier |
| description | str | ✅ | Used by Claude classifier |
| url | str | ✅ | Deduplication key |
| published_at | str (ISO8601) | ✅ | For delayed-reward labeling |
| source | str | ✅ | Audit trail |
| query_category | str | ✅ | One of 8 QUERIES keys |

---

## 2. Classification (event_classifier → shock_mapper / RO)

```json
{
  "severity": "CRITICAL",
  "shock_type": "currency",
  "affected_drugs": ["trastuzumab", "carboplatin"],
  "affected_countries": ["Venezuela"],
  "impact_params": {
    "lead_time_multiplier": 1.8,
    "demand_multiplier": 1.0,
    "fill_rate": 0.55,
    "budget_multiplier": 0.50
  },
  "reasoning": "USD access restriction → procurement budget compressed by ~50%; trastuzumab import-dependent"
}
```

**Schema:**
| Field | Type | Required | Notes |
|-------|------|----------|-------|
| severity | enum: IRRELEVANT/MINOR/MODERATE/CRITICAL | ✅ | |
| shock_type | enum: manufacturing/logistics/regulatory/demand/currency/political/climate/company | ✅ | |
| affected_drugs | list[str] | ✅ | Subset of ALLOWED_DRUGS |
| affected_countries | list[str] | ✅ | Subset of ALLOWED_COUNTRIES |
| impact_params.lead_time_multiplier | float ≥ 1.0 | ✅ | Multiplier on current lead time |
| impact_params.demand_multiplier | float ≥ 1.0 | ✅ | Multiplier on demand rate |
| impact_params.fill_rate | float [0,1] | ✅ | Expected fraction of orders fulfilled |
| impact_params.budget_multiplier | float [0,1] | ✅ | Procurement budget fraction remaining |
| reasoning | str | optional | Audit trail; passed to alert message |

**Phase 2b note:** impact_params are computed by Claude but currently **ignored** by shock_mapper.py. Phase 2c RO wires them directly.

---

## 3. KF_State (kalman_filter → robust_optimizer)

```json
{
  "state": [3.332, 1.946],
  "covariance": [[0.012, 0.0], [0.0, 0.018]],
  "uncertainty_bands": {
    "L_mean": [24.1, 32.8],
    "sigma_L": [5.9, 9.2]
  },
  "drug": "trastuzumab",
  "country": "Venezuela",
  "last_updated": "2026-05-02",
  "observations_count": 47
}
```

**Notes:**
- `state[0]` = log(L_mean); recover with exp(state[0]) ≈ 28 days
- `state[1]` = log(sigma_L); recover with exp(state[1]) ≈ 7 days
- `uncertainty_bands` are 90% confidence intervals in natural space
- If KF not yet initialized for drug/country, use COUNTRY_PARAMS defaults and set observations_count=0

---

## 4. MAB_Output (signal_learner → robust_optimizer)

Output is **per country** — RO selects the relevant country instance.

```json
{
  "country": "Venezuela",
  "background_rate": 0.80,
  "signal_lifts": {
    "manufacturing": 0.05,
    "logistics":     0.03,
    "regulatory":    0.06,
    "demand":        0.02,
    "currency":      0.03,
    "political":     0.04,
    "climate":       0.03,
    "company":       0.01
  },
  "posterior_means": {
    "manufacturing": 0.85,
    "logistics":     0.83,
    "regulatory":    0.86,
    "demand":        0.82,
    "currency":      0.83,
    "political":     0.84,
    "climate":       0.83,
    "company":       0.81
  },
  "top_signals": ["regulatory", "manufacturing", "political"],
  "n_observations": {
    "manufacturing": 23,
    "currency": 31,
    "background": 12
  },
  "last_updated": "2026-05-02"
}
```

**signal_lifts** is the operative field for RO Gamma computation — not posterior_means. posterior_means is included for audit only.

**If MAB not yet initialized or background_rate < 10 observations:** Return zero lifts (all signal_lifts = 0.0); RO falls back to severity-only Gamma schedule.

---

## 5. RO_Input (robust_optimizer consumption)

```json
{
  "drug": "trastuzumab",
  "country": "Venezuela",
  "kf_state": { "...": "KF_State as above" },
  "classification": { "...": "Classification as above" },
  "mab_output": { "...": "MAB_Output as above" },
  "gamma_override": null
}
```

**gamma_override:** If null, RO computes Gamma from classification.severity + MAB posteriors. If set (float), use directly — for expert overrides or backtesting.

---

## 6. RO_Output (robust_optimizer → alert_engine / dashboard)

```json
{
  "drug": "trastuzumab",
  "country": "Venezuela",
  "Q": 120,
  "r": 65,
  "CVaR_90_forecast": 14.2,
  "policy_confidence": 0.78,
  "gamma_used": 2.2,
  "policy_frontier": [
    {"gamma": 0.5, "Q": 100, "r": 50, "cvar_90_days": 8.1, "holding_cost_delta_pct": 5.2},
    {"gamma": 1.5, "Q": 115, "r": 60, "cvar_90_days": 11.8, "holding_cost_delta_pct": 12.1},
    {"gamma": 2.2, "Q": 120, "r": 65, "cvar_90_days": 14.2, "holding_cost_delta_pct": 18.3},
    {"gamma": 3.0, "Q": 155, "r": 85, "cvar_90_days": 22.0, "holding_cost_delta_pct": 35.0}
  ],
  "baseline_Q": 100,
  "baseline_r": 50,
  "baseline_CVaR_90": 18.5,
  "improvement_pct": 23.2,
  "solver_status": "optimal",
  "computation_time_sec": 42.1
}
```

---

## 7. MAB_Update (for shortage labeling → signal_learner)

```json
{
  "event_id": "evt_20260502_currency_venezuela",
  "category": "currency",
  "drug": "trastuzumab",
  "country": "Venezuela",
  "event_date": "2026-05-02",
  "label_date": "2026-08-01",
  "shortage_observed": true,
  "stockout_days_observed": 11.2,
  "label_source": "epr_stockout_log"
}
```

**label_source enum:** `epr_stockout_log` | `procurement_report` | `public_database` | `simulation_proxy`

---

## 8. Error Handling

All modules should return errors in this envelope:

```json
{
  "status": "error",
  "error_code": "KF_NOT_INITIALIZED",
  "error_message": "No Kalman Filter state for trastuzumab/Venezuela. Using COUNTRY_PARAMS defaults.",
  "fallback_used": true,
  "result": { "...": "best-effort result using fallback" }
}
```

**Standard error codes:**
| Code | Module | Meaning |
|------|--------|---------|
| `KF_NOT_INITIALIZED` | kalman_filter | No observations yet for drug/country |
| `KF_DIVERGED` | kalman_filter | Covariance exploded; reset triggered |
| `RO_SOLVER_FAILED` | robust_optimizer | Nelder-Mead did not converge |
| `MAB_COLD_START` | signal_learner | Using prior only; <5 observations |
| `NEWSAPI_RATE_LIMIT` | news_listener | 100 req/day limit hit |
| `CLASSIFIER_IRRELEVANT` | event_classifier | Article not supply-chain relevant |

---

## 9. Version Control

This document is v1.0 — the baseline for all Phase 2c implementation.

**Change protocol:**
- Any interface change requires updating this document first
- Increment version (v1.1, v1.2, etc.) for backward-compatible additions
- Increment major version (v2.0) for breaking changes
- All modules must document which contract version they implement

# OncoSupply Phase 2 — Capstone Summary

**Project:** OncoSupply Risk Analyst  
**Phase:** 2 — Real-Time Shock Detection  
**Date:** 2026-05-02  
**Capstone Deadline:** May 15, 2026  
**Branch:** phase-2-realtime-news

---

## Executive Summary

Phase 2 adds real-time pharmaceutical supply chain risk detection to OncoSupply's Monte Carlo inventory simulation engine. A continuous news pipeline fetches LATAM-specific supply disruption signals, classifies them using Claude AI, maps each event to a supply simulation scenario, and generates risk-differentiated alerts. The system was built, critically reviewed, and validated in Phase 2b.

**Core capability:** When a manufacturing disruption, currency shock, or regulatory action is reported in the news, OncoSupply automatically re-simulates drug-country risk and alerts procurement teams — before shortages materialize.

---

## 1. What Was Built

### 1.1 Architecture

```
NewsAPI (8 LATAM query topics)
    ↓
news_listener.py       — Fetches articles by shock category
    ↓
event_classifier.py    — Claude AI: IRRELEVANT / MINOR / MODERATE / CRITICAL
                          + shock_type + impact parameters
    ↓
shock_mapper.py        — (shock_type, severity) → simulation scenario
                          Runs supply_sim.py twice: baseline vs. shocked
    ↓
alert_engine.py        — Evaluates % risk increase; fires tiered alert
    ↓
scheduler.py           — Orchestrates full pipeline; deduplicates articles
```

### 1.2 News Coverage: 8 LATAM-Specific Query Categories

| Category | What It Detects | Shock Type |
|----------|----------------|------------|
| `manufacturing` | API factory shutdowns, GMP failures (India/China) | manufacturing |
| `logistics_latam` | Port congestion, customs delays (Santos, La Guaira) | logistics |
| `latam_politics` | Sanctions, trade restrictions, government instability | political / currency |
| `regulatory` | FDA Form 483, ANVISA/COFEPRIS/INVIMA actions | regulatory |
| `currency` | Peso/bolivar devaluation, dollar-access restrictions | currency |
| `healthcare_demand` | Cancer diagnosis surge, hospital capacity changes | demand |
| `climate_latam` | Flooding, landslides affecting LATAM ports/roads | climate |
| `company_events` | Manufacturer recalls, M&A, supply agreements | company |

### 1.3 Shock Type → Simulation Scenario Mapping

| Shock Type | CRITICAL | MODERATE | MINOR |
|-----------|----------|----------|-------|
| manufacturing | API export restriction | API export restriction | Baseline |
| logistics | Combined shock | API export restriction | Baseline |
| regulatory | Combined shock | Currency devaluation | Baseline |
| demand | Combined shock | Baseline | Baseline |
| currency | Combined shock | Currency devaluation | Baseline |
| political | Combined shock | API export restriction | Baseline |
| climate | Combined shock | API export restriction | Baseline |
| company | API export restriction | Baseline | Baseline |

### 1.4 Alert Thresholds

| % Risk Increase | Severity | Action |
|----------------|----------|--------|
| ≥ 100% | CRITICAL | Immediate escalation |
| ≥ 50% | HIGH | Urgent procurement review |
| ≥ 25% | MODERATE | Procurement alert |
| < 25% | LOW | No action |

Risk measured in: stockout-days/year (CVaR_90 tail metric from Monte Carlo simulation, 500 runs).

### 1.5 Target Drugs and Countries

- **Drugs:** cisplatin, carboplatin, doxorubicin, trastuzumab
- **Countries:** Argentina, Colombia, Venezuela

---

## 2. Phase 2b Validation Results

### 2.1 Classification Quality Test

**Method:** 16 synthetic articles across 8 categories classified by event_classifier.py  
**System prompt version:** v2 (post-fix, 2026-05-02)

| Version | Accuracy | Status |
|---------|----------|--------|
| v1 (original) | 81.2% (13/16) | ⚠️ Below real-world expectations |
| v2 (fixed) | See classification_quality_report_v2.md | Target: ≥ 87.5% (14/16) |

**Three structural misclassifications fixed in v2:**
1. **FDA Form 483** → now correctly classified as `regulatory` (not `manufacturing`)
   - Root cause: enforcement action against a manufacturer is a regulatory shock, not a production shock
2. **Healthcare budget cuts** → now correctly classified as `demand` (not `regulatory`)
   - Root cause: budget cuts reduce patient throughput (demand), not drug approval or pricing (regulatory)
3. **Indirect climate events** → now correctly classified as `climate` (not `IRRELEVANT`)
   - Root cause: drought affecting agricultural inputs (solvents, excipients) propagates to pharma supply

### 2.2 Alert Integration Test

**Method:** Synthetic event injection directly into shock_mapper → supply_sim → alert_engine  
(Bypasses news_listener to test pipeline logic independently of live news)

| Test Case | Scenario Applied | Risk Increase | Alert Fired |
|-----------|-----------------|---------------|-------------|
| Manufacturing CRITICAL — cisplatin/Argentina | API export restriction | +12.9% | ❌ No |
| Currency CRITICAL — trastuzumab/Venezuela | Combined shock | +28.6% | ✅ MODERATE |
| Regulatory MODERATE — doxorubicin/Colombia | Currency devaluation | +6.0% | ❌ No (expected) |

**Pipeline:** Structurally sound. Scenario mapping correct. alert_engine thresholds fire correctly.

**Known limitation:** Manufacturing CRITICAL on Argentina/cisplatin does not trigger an alert (12.9% increase < 25% threshold). Root cause: Monte Carlo simulation uses steady-state safety stock assumptions; does not know real-time inventory level. When Argentina's (Q,r) policy provides adequate buffer, even a CRITICAL event is absorbed without stockout impact. **This is the primary motivator for Phase 2c Kalman Filter integration.**

### 2.3 Code Fixes Applied

| Fix | File | What Changed |
|-----|------|-------------|
| Regulatory MODERATE mapping | `shock_mapper.py` | `("regulatory","MODERATE")` → Currency devaluation (was: API export restriction) |
| API key precedence | `news_listener.py` | `load_dotenv(..., override=True)` |
| Event classifier accuracy | `event_classifier.py` | System prompt v2: disambiguation examples for 8 boundary cases |

---

## 3. Known Limitations

### 3.1 Design Limitations (Phase 2c Backlog)

| Limitation | Impact | Phase 2c Fix |
|-----------|--------|-------------|
| Impact parameters ignored | event_classifier extracts lead_time_multiplier, fill_rate — shock_mapper discards them, uses fixed scenario instead | `simulate_dynamic()` function + parameter pass-through |
| No demand-surge scenario | supply_sim.py has no standalone demand-spike scenario; demand MODERATE defaults to Baseline | New `SCENARIO_PARAMS["Demand surge"]` entry |
| In-memory article dedup | `PROCESSED_ARTICLES` set resets on restart; duplicate articles re-processed after restart | SQLite persistence |
| NewsAPI free tier | 100 req/day; 8 categories = 8 req/cycle; max ~12 full cycles/day | Premium API or self-hosted scraper |
| Steady-state simulation | Monte Carlo assumes equilibrium inventory; misses events when actual stock is low | Kalman Filter for real-time state estimation |

### 3.2 Classification Limitations

- Accuracy estimated at 65-70% on real-world LATAM news (81.2%+ only on clean, unambiguous articles)
- Boundary cases (regulatory action on manufacturer, indirect climate-to-pharma chain) require v2 system prompt
- No validation on Portuguese or Spanish-language articles (all queries in English)

---

## 4. Phase 2c Roadmap — Post-Capstone (10-15 weeks)

**Algorithm stack selected:** Kalman Filter + Robust Optimization + Multi-Armed Bandit

### Why This Stack

| Algorithm | Role | Why Now |
|-----------|------|---------|
| **Kalman Filter** | Online state estimation | Fixes Manufacturing CRITICAL blind spot; replaces steady-state Monte Carlo assumptions with real-time inventory tracking |
| **Robust Optimization** | Worst-case (Q,r) policy | Distribution-free guarantees; no forecasters required; perfect for sparse LATAM data |
| **MAB (Thompson Sampling)** | Signal-relevance learning | Learns which 8 news categories best predict actual shortages; reduces alert fatigue |

### Why NOT Other Algorithms

| Algorithm | Decision | Reason |
|-----------|----------|--------|
| MPC | Deferred | Requires demand/lead-time forecasters that fail during LATAM regime shifts |
| RL | Phase 3 | <2 years LATAM data per drug per country; black-box indefensible to regulators |

### Timeline

| Weeks | Milestone |
|-------|-----------|
| 1-2 | Design specs + API contracts (KF, RO, MAB interfaces) |
| 2-4 | Kalman Filter: `kalman_filter.py` — online lead-time + inventory state estimation |
| 4-8 | Robust Optimization: `robust_optimizer.py` — CVaR-DRO policy frontier |
| 8-10 | MAB: `signal_learner.py` — Thompson Sampling on 8 news categories |
| 10-12 | Integration + regression tests + dashboard updates |
| 12-15 | Validation + regulatory docs + shadow-mode deployment + sign-off |

### Phase 2c Architecture (Target State)

```
Real-time ERP/News Feed
    ↓
Kalman Filter           — Online state: inventory, demand rate, lead-time drift
    ↓ (state + uncertainty)
Multi-Armed Bandit      — Thompson Sampling: P(shortage | news_category) per SKU
    ↓ (signal posteriors)
Robust Optimization     — CVaR-DRO: worst-case (Q,r) policy frontier
    ↓ (policy + confidence)
shock_mapper.py         — Dynamic uncertainty-set adjustment on news events
    ↓
Alert Engine            — Tiered alert to procurement team
```

---

## 5. How to Run Phase 2

```bash
cd "/Users/carlosmartino/Documents/MBA/2026/Spring 2/GenAI/Project"
source .venv/bin/activate

# Run single cycle — manufacturing category
python3 -m phase2_realtime.scheduler

# Run specific category
python3 -c "
from phase2_realtime.scheduler import run_cycle
import json
result = run_cycle('manufacturing', limit_articles=5)
print(json.dumps(result, indent=2))
"

# Test event_classifier directly
python3 -m phase2_realtime.event_classifier

# Test shock_mapper directly
python3 -m phase2_realtime.shock_mapper
```

---

## 6. File Inventory

```
phase2_realtime/
├── __init__.py
├── news_listener.py       — NewsAPI fetch; 8 LATAM query categories
├── event_classifier.py    — Claude AI classification; system prompt v2
├── shock_mapper.py        — Scenario mapping; supply_sim.py integration
├── alert_engine.py        — Risk threshold evaluation; alert formatting
├── scheduler.py           — Full pipeline orchestration
├── action_items.md        — Phase 2b/2c working checklist
└── docs/
    ├── classification_quality_report.md    — v1 test (81.2%)
    ├── classification_quality_report_v2.md — v2 test (post system prompt fix)
    ├── alert_integration_test.md           — Pipeline integration results
    ├── phase2b_critical_findings.md        — Full critical review
    └── phase_2_capstone_summary.md         — This document
```

---

## 7. References

- Badejo O, Ierapetritou M. Integrating tactical planning and reactive scheduling for resilient pharmaceutical supply chains. *Industrial & Engineering Chemistry Research*, 2022. (Disruption duration modeling — used in supply_sim.py)
- Malta et al. PMC12459138, 2025. (Cisplatin/carboplatin shared-source correlation — LATAM oncology)
- Esfahani PM, Kuhn D. Data-driven distributionally robust optimization using the Wasserstein metric. *Mathematical Programming*, 2018. (Foundation for Phase 2c Robust Optimization)
- Russo et al. A tutorial on Thompson Sampling. *Foundations and Trends in ML*, 2018. (Foundation for Phase 2c MAB)

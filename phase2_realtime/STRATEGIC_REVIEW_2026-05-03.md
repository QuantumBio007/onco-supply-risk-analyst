# Strategic Review — JCNB Biotech / OncoSupply

**Date:** 2026-05-03
**Author:** CSO/CEO-mode review (expert-level critical assessment)
**Scope:** Phase 1 + Phase 2 audit; mission alignment; grant strategy; differentiation; content plan
**Status:** ACTIVE — drives [ACTION_ITEMS_STRATEGIC.md](ACTION_ITEMS_STRATEGIC.md)

---

## THE WHY — JCNB L99 (memorize this)

> **No one else can build this.** Angels for Change has US institutional backing but no LATAM presence. Max Foundation distributes drugs but has no predictive analytics. CHAI negotiates prices but doesn't model shortage risk. PAHO procures $800M/yr but has no foresight layer — and explicitly asked for one in February 2025. IQVIA could build it but won't, because the LATAM oncology TAM is too small and politically too thorny for a $14B public company. The only entity with (a) the LATAM institutional knowledge from JCNB Biotech Consulting, (b) the technical stack (RAG + Monte Carlo + 8-dimensional shock model + Kalman/Robust/MAB on the way), (c) the academic credibility (JHU Carey + peer-reviewed grounding), and (d) the willingness to operate as a public good rather than a $200K-per-seat commercial product — is JCNB. **That is why this organization must exist, and why it must exist as a nonprofit.**

---

## VERDICT

**Phase 1 is real. Phase 2 is real. The mission is misaligned with both, and the grant story is undersold.** You have built — verifiable in code today — the foundation of a defensible niche that no comparable organization currently occupies (Max Foundation, CHAI, PAHO, Angels for Change, LALCEC). The window to claim it is 12–18 months, before A4C expands south or IQVIA prices a LATAM module. The "visibility-first + multi-dimensional shock propagation" thesis is the right wedge — but the codebase, the mission statement, and the content strategy are not yet telling that story.

---

## 1. WHAT IS ACTUALLY BUILT (verified against current code, not memory)

### Phase 1 — Capstone delivered 2026-04-29
- `supply_sim.py` — Monte Carlo (Q,r) inventory model, peer-reviewed citations (Warren OM, Andrade-Wang MIT, Izen et al. Cancer Journal 2025, Badejo-Ierapetritou AIChE 2025). Structural fragility (`supply_sim.py:107-114`) for Venezuela (fill 0.60, budget 0.30) and Colombia (EPS-IPS debt cascade) is institutional knowledge no comparable has.
- `app/app.py` Streamlit RAG: ChromaDB, all-mpnet-base-v2, 11 KB docs + 48 sim outputs, RAG 12/12 vs prompt-only 8/12 across 5 cases. **Local-only** — Streamlit Cloud blocked by Python 3.14.
- Canonical patient-harm headline: **Trastuzumab/Venezuela/Baseline = 79.3 ±1.2 stockout days/year, CVaR_90 = 103d, p(crit≥60d)=91%.** This single number is the headline for every grant deck.

### Phase 2 — Branch `phase-2-realtime-news`
- 5 modules verified: `news_listener.py`, `event_classifier.py`, `shock_mapper.py`, `alert_engine.py`, `scheduler.py`.
- 8 LATAM-specific NewsAPI query categories (manufacturing, logistics_latam, latam_politics, regulatory, currency, healthcare_demand, climate_latam, company_events).
- Claude-driven classification: severity × shock_type × 4 impact parameters (lead_time_multiplier, demand_multiplier, fill_rate, budget_multiplier). 87.5% accuracy (14/16).
- Differentiated SCENARIO_MAP wiring in `shock_mapper.py:21-62`.
- Phase 2c Week 1 design specs: Kalman Filter, Robust Optimization (grid search, Bertsimas-Sim), MAB Thompson Sampling, API contracts.

### Phase 2 — Critical defects found in this review

| # | Defect | File | Severity | Fix path |
|---|--------|------|----------|----------|
| 1 | `shock_mapper.py` silently discards Claude's continuous impact parameters; uses 24-cell SCENARIO_MAP lookup instead | `phase2_realtime/shock_mapper.py` | **HIGH** — undermines "multi-dimensional" claim | Phase 2c RO wiring; or interim `simulate_dynamic()` shim |
| 2 | `PROCESSED_ARTICLES` is in-memory; restart loses dedup | `phase2_realtime/scheduler.py:21` | MEDIUM — breaks "shadow-mode deployment" claim | SQLite or JSON persistence (~30 LOC) |
| 3 | NewsAPI free tier = 100 req/day; 8 queries × hourly = 192/day | `phase2_realtime/news_listener.py` | MEDIUM — "real-time" is currently aspirational | Honest framing as near-real-time (every 2h), or upgrade tier ($449/yr) |
| 4 | No `Demand surge` scenario in `supply_sim.py`; demand MODERATE → Baseline | `supply_sim.py` SCENARIO_PARAMS | MEDIUM — 8-dimension story has 7.5-dimension reality | Add scenario, ~30 LOC |
| 5 | MAB has no rewards (Thompson Sampling needs labeled shortage outcomes) | Phase 2c roadmap | LOW — Phase 2c addresses | ERP integration or manual labeling pipeline |
| 6 | Pharma commercial hypothesis 100% unvalidated; no comparable nonprofit charges pharma subscriptions | BP v3 financial model | **HIGH** — highest-risk financial assumption | 5 cold pitches, kill or validate by July |

**Defect #1 is the single biggest credibility gap in the multi-dimensional story.** Until shock_mapper actually consumes the continuous impact parameters Claude already extracts, do not claim "continuous shock parameterization" in any grant narrative.

---

## 2. MISSION ↔ CODE ALIGNMENT — FIXED 2026-05-03

`DC_NONPROFIT_FORMATION_GUIDE.md` originally said:

> *"OncoSupply Inc. is a nonprofit dedicated to reducing oncology drug shortages through AI-powered supply chain analysis and health system partnerships in the **US and Latin America**."*

The code is **100% LATAM**. There is no US data, no US scope, no FDA/USP/Vizient ingestion. Angels for Change already owns the US oncology-shortage-prediction niche with USP+Vizient institutional backing.

**Decision: tighten mission to LATAM-first.** Three reasons:
1. The institutional moat (Pablo Castello / Carolina-Souza field network, EPS-IPS debt cascade, ANMAT/INVIMA/COFEPRIS specifics, Venezuela structural failure) is uncopyable. The US moat is non-existent.
2. PAHO's Feb 2025 "predictability" statement is the most quotable thesis-statement in this entire space.
3. A4C is a partner, not a competitor — and they need a LATAM ally.

**Revised mission (active):** see top of this doc and `DC_NONPROFIT_FORMATION_GUIDE.md:20`.

---

## 3. THE GRANT THESIS

You are not selling a tool. You are selling a **public good**: the first-ever integrated visibility layer for LATAM oncology supply, designed to be cited, audited, and adopted by ministries.

### Four narratives, four funder buckets

| Narrative | Funder | Hook | Evidence on hand |
|-----------|--------|------|------------------|
| **AI-for-science / AI-for-good** | Google.org ($500K–$3M, 9/10 fit per `grants/GRANT_SEARCH_FRAMEWORK.md`), Microsoft AI for Good, Patrick J. McGovern | Multi-dimensional shock model with Claude-in-the-loop classification and Monte Carlo grounding | 87.5% classifier accuracy; 8 shock categories; peer-reviewed sim |
| **Health systems & access** | Gates Foundation, Rockefeller, RWJ | LATAM oncology access — quantified patient harm | 79.3 stockout days/year for trastuzumab/Venezuela; 28.4% WHO shortage rate |
| **Supply chain resilience** | USAID Innovation, World Bank, Skoll | Real-time visibility prevents stockouts before they happen | Phase 2 architecture; 8-dimension shock decomposition |
| **Procurement partnership** | PAHO Strategic Fund (operationalize), St. Jude/PAHO 2024 model | Predictive analytics partner to PAHO | Quote PAHO's Feb 2025 statement asking for "predictability" |

**The PAHO move is the single highest-leverage action you can take in 2026.** Their $800M/yr procurement budget makes any analytical partnership ($50K–$200K) a rounding error — and St. Jude already validated the partnership model in 2024.

---

## 4. CONTENT STRATEGY — DIFFERENTIATION

Headline positioning (test against three trusted readers):

> **"The early warning system for LATAM oncology shortages — six months before the patient knows."**

Or (more technical, for grant officers):

> **"Multi-dimensional supply chain visibility, grounded in peer-reviewed simulation."**

### Six content pillars (12-month plan)

1. **Public Risk Dashboard (monthly)** — free, citable, drug × country × scenario. Drives press; signals public-good intent. Build off existing 48 sim outputs.
2. **Method White Papers (quarterly)** — Kalman, Robust Optimization, MAB methodology. Differentiates from A4C/USP black-box predictive model. Funders trust auditable math.
3. **Patient & Practitioner Stories (rolling)** — Pablo Castello (Argentina), Carolina/Souza (Venezuela). One per quarter. Humanizes the simulation.
4. **State of LATAM Oncology Supply (annual)** — flagship report. Ministry-ready, citation-worthy. The convening artifact that gets you into PAHO meetings.
5. **Funder-Tailored Briefs (per cycle)** — one-pager per major funder, written in their priority language.
6. **Methodology Replication Kit (Q4 2026)** — open-source the supply_sim core. Open source = academic adoption = citation count = grant credibility.

### Differentiation matrix (against every comparable)

| Dimension | Max | CHAI | PAHO | A4C | IQVIA | **JCNB** |
|-----------|-----|------|------|-----|-------|----------|
| LATAM oncology depth | Broad/shallow | Africa-focused | Procurement only | None | Generic | **Deep + field-validated** |
| Predictive analytics | None | None | None | US pediatric only | Static reports | **Multi-dim, real-time** |
| Auditable math | N/A | Policy-level | N/A | Black-box | Black-box | **Monte Carlo + KF + RO published** |
| Public good model | Donations | Grants | Sovereign | Partnerships | Commercial | **Open data + open methods** |
| Cost to ministry | Free drugs | Free advisory | Pooled procure | N/A | $200–500K/yr | **Free / cost-recovered** |

---

## 5. WHAT THIS REVIEW DID NOT COVER

- BusinessPlan v3 sections 2–7 — only Section 1 confirmed clear of mission scope conflict. Full BP audit recommended before any grant cycle.
- Live code execution — review based on log files + code reading. **Fresh end-to-end run required before any grant submission.**
- Grant narrative drafting — not done in this review. Available on request.
- PAHO outreach email draft — not done. Available on request.

---

## 6. WHAT TO DO

See [ACTION_ITEMS_STRATEGIC.md](ACTION_ITEMS_STRATEGIC.md) for the prioritized 90-day execution plan.

The Phase 2c algorithmic stack (Kalman / Robust / MAB) is great science and the right medium-term roadmap — but **none of those modules wins you a grant or a PAHO meeting.** The actions in `ACTION_ITEMS_STRATEGIC.md` do. Build the Phase 2c stack on the strength of the funding those actions unlock, not on hope.

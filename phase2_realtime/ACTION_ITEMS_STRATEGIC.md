# Strategic Action Items — JCNB Biotech / OncoSupply

**Source:** [STRATEGIC_REVIEW_2026-05-03.md](STRATEGIC_REVIEW_2026-05-03.md)
**Last updated:** 2026-05-03
**Owner:** Carlos Martino
**Scope:** 90-day execution to convert built capability into funded nonprofit traction
**Companion to:** `phase2_realtime/action_items.md` (technical Phase 2c roadmap)

---

## ▶ THE WHY — READ THIS BEFORE EVERY WORK SESSION

> **No one else can build this.** Angels for Change has US institutional backing but no LATAM presence. Max Foundation distributes drugs but has no predictive analytics. CHAI negotiates prices but doesn't model shortage risk. PAHO procures $800M/yr but has no foresight layer — and explicitly asked for one in February 2025. IQVIA could build it but won't, because the LATAM oncology TAM is too small and politically too thorny for a $14B public company. The only entity with (a) the LATAM institutional knowledge from JCNB Biotech Consulting, (b) the technical stack (RAG + Monte Carlo + 8-dimensional shock model + Kalman/Robust/MAB on the way), (c) the academic credibility (JHU Carey + peer-reviewed grounding), and (d) the willingness to operate as a public good rather than a $200K-per-seat commercial product — is JCNB. **That is why this organization must exist, and why it must exist as a nonprofit.**

**Patient-harm headline (use in every funder pitch):** Trastuzumab in Venezuela = **79.3 stockout days/year**, CVaR_90 = 103 days, p(critical ≥60d) = 91%. WHO 2023: 28.4% LATAM shortage rate.

**The wedge (the niche statement, memorize):**

> "The early warning system for LATAM oncology shortages — six months before the patient knows."

---

## CRITICAL HONESTY (the things to fix before you tell the multi-dimensional story to anyone)

These are the gaps that, if a grant officer or a PAHO program manager scrutinized the codebase today, would erode credibility. Fix them in the order shown.

| # | Gap | Why it matters | Effort | Status |
|---|-----|---------------|--------|--------|
| H1 | `shock_mapper.py` discards Claude's continuous impact parameters; uses lookup table instead | Until fixed, "multi-dimensional shock propagation" is a categorical decision tree, not continuous. Defect #1 in strategic review. | Shim 1–2 days | **✅ DONE 2026-05-03** — `simulate_dynamic()` shim added to `supply_sim.py`; `shock_mapper.py` chooses dynamic vs. scenario_map per Claude's output; clamping defense in place; 4-case test passing |
| H2 | `PROCESSED_ARTICLES` in-memory only; restart wipes dedup | Breaks any "always-on" or "shadow-mode" claim | 2 hours (SQLite) | ⏳ NOT STARTED |
| H3 | No `Demand surge` scenario in `supply_sim.py` | demand MODERATE → Baseline silently in fallback path; dynamic path resolves when Claude provides params | 1 hour | ⏳ Partial — dynamic path resolves when Claude returns demand params; SCENARIO_MAP fallback gap remains |
| H4 | NewsAPI free tier = 100/day; 8 queries × hourly = 192/day | "Real-time" is aspirational; current capacity is 12 cycles/day max | Honest framing OR $449/yr | ⏳ NOT STARTED |
| H5 | Pharma commercial hypothesis 100% unvalidated; no comparable nonprofit sells subscriptions to pharma | Highest-risk financial assumption in the BP | 5 cold pitches, decision by July | ⏳ NOT STARTED |
| **CVaR-blind alerts (was NEW)** | `alert_engine.py` only uses `stockout_days_mean` for severity tiering; ignores `cvar_90` | (Q,r) policy adaptation can suppress mean while CVaR_90 doubles — alerts can miss tail-risk-only shocks | 1 hour | **✅ DONE 2026-05-03** — `evaluate_risk_change()` now accepts `baseline_cvar/shocked_cvar`; severity = max of mean / CVaR-abs / CVaR-rel triggers; backward-compatible (cvar args optional). H1 silent-miss case (cisplatin/AR manufacturing CRITICAL) now correctly fires HIGH. End-to-end smoke test through `scheduler.run_cycle` produces 6 CRITICAL alerts with all CVaR fields populated. |

These are listed here, not below in the 90-day list, because **they are not "actions to win grants" — they are "actions to not get caught lying in a grant proposal."** Fix them on a parallel track.

---

## 90-DAY ACTION PLAN (priority order)

### ✅ ACTION 1 — Rewrite mission statement to LATAM-first
**Status:** **COMPLETED 2026-05-03**
**Why:** Original "US and Latin America" mission misaligned with 100%-LATAM codebase. Angels for Change owns US shortage-prediction niche with USP+Vizient backing JCNB cannot match. LATAM-deep is defensible; US-and-LATAM is not.
**What:** New active mission landed in `DC_NONPROFIT_FORMATION_GUIDE.md:20`. Legacy version preserved for audit trail.
**Active mission (memorize):**
> *"JCNB Biotech is a nonprofit dedicated to preventing oncology drug shortages in Latin America through AI-driven, multi-dimensional supply chain visibility — combining real-time news intelligence, peer-reviewed Monte Carlo simulation, and institutional knowledge across Argentina, Colombia, and Venezuela. We give ministries, hospitals, and pharmaceutical partners the foresight to act months before patients are harmed."*

**Downstream:** Every BP section, README, pitch deck, and 1023-EZ application should now use this language verbatim. Audit BP v3 sections 1–7 against this mission before any grant submission.

---

### ✅ ACTION 2 — Wire Claude impact parameters into supply_sim
**Status:** **COMPLETED 2026-05-03** (shim landed; full Phase 2c RO will wrap this same `simulate_dynamic()` later).
**What was done:**
- Added `simulate_dynamic(drug, country, lead_time_multiplier, demand_multiplier, fill_rate, budget_multiplier, disruption_duration_mean, n_runs)` to `supply_sim.py`. Same Monte Carlo engine as `simulate()`; same structural country floors. Equivalence verified against named scenarios (delta = 0.0 days when params match — deterministic seed reuse).
- Updated `shock_mapper.py`:
  - Path selection: when Claude returns non-default impact parameters, run `simulate_dynamic` with them. Otherwise fall back to legacy `SCENARIO_MAP` lookup.
  - Defensive clamping: `lead_time_multiplier ∈ [1.0, 5.0]`, `demand_multiplier ∈ [0.5, 2.0]`, `fill_rate ∈ [0.10, 1.0]`, `budget_multiplier ∈ [0.20, 1.0]`. Bad-type inputs (e.g., string "NaN") fall back to no-shock defaults.
  - All-default impact dict (Claude classified severity but didn't quantify) → fallback to SCENARIO_MAP. Empty/missing impact dict → fallback.
  - Per-shock-type `DEFAULT_DURATION_BY_SHOCK` map (manufacturing=90d, regulatory=365d, currency=180d, etc.) used when Claude doesn't extract duration.
  - New `simulation_mode` field in result dict: `"dynamic"` | `"scenario_map"` | `"skipped"` | `"error"` — full audit trail of which path fired.
- Regression check: `simulate('trastuzumab','Venezuela','Baseline')` still returns canonical 79.3 ± 1.2 days, CVaR_90 = 103.3.
- Test cases (`python3 -m phase2_realtime.shock_mapper`): 4/4 pass — dynamic path, fallback path, defensive clamping, all-default-impact fallback.

**Critical finding from this work (logged for follow-up):**
- For lead-time-heavy shocks the (Q,r) policy adapts (`r = d × L_mean + SS` scales linearly), so `stockout_days_mean` can DECREASE while `cvar_90` doubles (e.g., Trastuzumab/Venezuela bad-output test: mean barely moved, CVaR_90 jumped 103 → 167). **`alert_engine.py` currently only thresholds on mean, not CVaR.** This means the alert engine can miss tail-risk-only shocks. Added as a new high-honesty defect row above; resolve in a separate session.
- Grant copy may now honestly claim: *"continuous shock parameter propagation through Monte Carlo simulation, with structural-country fragility floors maintained as constraints — driven by Claude-extracted article-level impact parameters (lead time, demand, fill rate, budget) clamped to physically defensible ranges."*

---

### ⏳ ACTION 3 — Add `Demand surge` scenario to `supply_sim.py`
**Why:** Defect #4. demand MODERATE currently maps to Baseline silently; the 8-dimension story has a 7.5-dimension reality.
**What:** Add to `SCENARIO_PARAMS`:
```python
"Demand surge": {
    "lead_time_multiplier": 1.0,
    "demand_multiplier": 1.3,   # +30% (cancer incidence surge or guideline change)
    "fill_rate": 0.90,
    "budget_multiplier": 1.0,
    "disruption_duration_mean": 180,
    "label": "Demand surge (disease outbreak or guideline change)",
},
"Regulatory squeeze": {
    "lead_time_multiplier": 1.2,
    "demand_multiplier": 1.0,
    "fill_rate": 0.80,
    "budget_multiplier": 0.75,
    "disruption_duration_mean": 365,
    "label": "Regulatory shock (pricing controls, budget cuts)",
},
```
Then update `shock_mapper.SCENARIO_MAP` for `("demand", "MODERATE")` and `("regulatory", "MODERATE")`.
**Effort:** 1 hour code + 1 hour test/regression.
**Gate:** Re-run classification quality test after; verify accuracy ≥87.5% maintained.

---

### ⏳ ACTION 4 — Persist `PROCESSED_ARTICLES` to SQLite
**Why:** Defect #2. Current in-memory cache wipes on restart. Any claim of "shadow-mode" or "24/7 monitoring" is unsupportable.
**What:** Replace `PROCESSED_ARTICLES = set()` in `scheduler.py:21` with SQLite-backed deduplication. Schema: `(article_hash TEXT PRIMARY KEY, processed_at DATETIME, classification TEXT)`. Path: `phase2_data/processed.db`.
**Effort:** 2 hours.

---

### ⏳ ACTION 5 — File DC 501(c)(3) (Form 1023-EZ if eligible)
**Why:** Most golden grants — Google.org included — gate on 501(c)(3) status. 60–90 day clock. Filing in May = approval window for 2026 Q4 grant cycles. Filing in August = exclusion from 2026 cycles entirely.
**What:** Execute `DC_NONPROFIT_FORMATION_GUIDE.md` Phases 1–4. Eligibility check: Form 1023-EZ if expected gross receipts < $50K Year 1 (likely yes pre-grant).
**Effort:** Real cash $3,500–$5,500. Calendar 60–90 days. Founder time ~20 hours over the period.
**Critical:** This is the **single most schedule-sensitive item** in this list. Every week of delay narrows 2026 grant access.

---

### ⏳ ACTION 6 — Email PAHO Strategic Fund leadership
**Why:** PAHO Feb 2025 statement explicitly asks for "predictability" in cancer medicine access. JCNB IS that ask. Their $800M/yr procurement budget makes any analytical partnership ($50K–$200K) a rounding error. St. Jude/PAHO 2024 model already validated the partnership template.
**What:** One-paragraph cold email quoting their own Feb 2025 statement, attaching one-page brief with the Trastuzumab/Venezuela 79.3-day result.
**Effort:** 2 hours including brief. Send this week.
**Critical:** Highest-leverage single action in 2026. **Do not let Phase 2c implementation delay this.**

---

### ⏳ ACTION 7 — Email Angels for Change for partnership conversation
**Why:** A4C has US institutional backing (USP/Vizient/Mark Cuban Cost Plus); JCNB has LATAM institutional knowledge. Joint USAID or Google.org application = stronger than either alone. A4C is a partner, not a competitor — confirmed by `Strategy/COMPARABLE_NONPROFIT_ANALYSIS.md`.
**What:** Reach out to A4C founder. Frame: LATAM analogue to A4C's US predictive model. Explore co-funding one grant cycle.
**Effort:** 1 hour outreach. Multi-month relationship build.

---

### ⏳ ACTION 8 — Validate or kill the pharma subscription hypothesis
**Why:** Defect #6. Comparable nonprofit analysis: NO comparable charges pharma a subscription for intelligence. IQVIA does — as a $14B for-profit. The $150K/yr line in BP v3 is the highest-risk financial assumption in the entire plan. If wrong, the funding model needs restructuring before any grant submission citing the BP financials.
**What:** 5 cold pitches to LATAM-active pharma supply heads (Roche, Pfizer, Hikma, Cipla, Eurofarma). Track responses. Decision rule: 5 → 0 calls = pivot to A4C-style partnership/grants model.
**Effort:** 4 weeks.
**Decision deadline:** July 15, 2026 — ahead of any grant submission citing the BP financial model.

---

### ⏳ ACTION 9 — Build the public risk dashboard (static v0)
**Why:** Funders click artifacts. Press picks up on numbers. A free public dashboard showing Trastuzumab/Venezuela = 79.3 days IS the convening artifact that legitimizes the public-good positioning vs. IQVIA's paywalled reports.
**What:** GitHub Pages site, static charts derived from existing 48 sim outputs. No backend required for v0. Use Plotly/Observable.
**Effort:** 1 week.
**Gate:** Live URL in time for Action 6 (PAHO email) and Action 7 (A4C outreach) attachments.

---

### ⏳ ACTION 10 — Outline "State of LATAM Oncology Supply 2026" annual report
**Why:** Citation-worthy, ministry-ready convening artifact. The thing that gets you a PAHO panel invitation in 2027.
**What:** 2-page outline now (table of contents + key data sources). Full draft Q3. Publish Q4 alongside DC 501(c)(3) approval announcement.
**Effort:** 8 hours outline. 8 weeks draft (part-time).

---

## SEQUENCING (critical path)

```
Week 1 (May 5–11):
  ✅ Action 1 (mission rewrite) — DONE 2026-05-03
  → Action 5 (file 501(c)(3)) — START NOW, biggest schedule risk
  → Action 4 (SQLite persistence) — 2 hours
  → Action 3 (Demand surge scenario) — 2 hours
  → Action 6 (PAHO email) — send by Friday
  → Action 7 (A4C outreach) — send by Friday

Week 2 (May 12–18):
  → Action 2 shim (simulate_dynamic) — 1–2 days
  → Action 9 (public dashboard v0) — full week
  → Action 10 (annual report outline)

Weeks 3–6 (May 19 – June 15):
  → Action 8 (pharma validation cycle, 5 pitches)
  → Phase 2c Week 2: Kalman Filter implementation (per phase2_realtime/action_items.md)
  → Iterate on funder briefs based on PAHO/A4C responses

Weeks 7–12 (June 16 – July 27):
  → Action 8 decision deadline (July 15) — pivot or proceed
  → Phase 2c continues (RO implementation)
  → First grant submissions (Google.org cycle, Gates Q3 if open)
```

---

## WHAT THIS LIST IS NOT

This is not the technical Phase 2c roadmap. That lives in `phase2_realtime/action_items.md` (Kalman / Robust / MAB implementation, weeks 1–15). Phase 2c is the science. **This list is the business — and without it, the science doesn't get funded, deployed, or used.**

The two lists run in parallel. When in conflict, this list wins, because algorithmic elegance does not pay legal fees, file 1023-EZ forms, or get PAHO meetings.

---

## REVIEW CADENCE

- Weekly: re-read THE WHY block above before starting work
- Monthly: re-prioritize this list against actual funder responses and Phase 2c progress
- Quarterly: reconfirm mission alignment against any new evidence (especially A4C international expansion signals)

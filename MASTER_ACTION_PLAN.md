# OncoSupply — Master Action Plan
**Owner:** Carlos Martino (solo founder; advisory board pending)
**Last updated:** 2026-05-04 (session 20)
**Companion docs:** [TRACKER.md](TRACKER.md), [phase2_realtime/ACTION_ITEMS_STRATEGIC.md](phase2_realtime/ACTION_ITEMS_STRATEGIC.md), [phase2_realtime/STRATEGIC_REVIEW_2026-05-03.md](phase2_realtime/STRATEGIC_REVIEW_2026-05-03.md)
**Read this before every session.** Check off items as completed.

---

## ▶ THE WHY (memorize)

> No one else can build this. Angels for Change has US institutional backing but no LATAM presence. Max Foundation distributes drugs but has no predictive analytics. CHAI negotiates prices but doesn't model shortage risk. PAHO procures $800M/yr but has no foresight layer — and explicitly asked for one in February 2025. IQVIA could build it but won't, because the LATAM oncology TAM is too small and politically too thorny for a $14B public company. Only OncoSupply has (a) LATAM institutional knowledge, (b) the technical stack, (c) academic credibility, and (d) the willingness to operate as a public good.

## ▶ HEADLINE NUMBER (memorize, recalibrated 2026-05-03)

**Trastuzumab/Venezuela = 185 stockout days/year (51% of year), CVaR_90 = 204d, p(any stockout) = 100%, p(critical ≥60d) = 100%.**
Validated against Lancet Oncology 2017, Duma & Duque Duran JGO 2019, ENH Sept 2024, Convite Mar 2024.

## ▶ THE CEO GATE (discipline)

Phase 2c implementation is GATED behind ALL of these:
- [x] 501(c)(3) Form 1023-EZ filing initiated — EIN SS-4 faxed 2026-05-04
- [x] PAHO email sent — Christopher Lim (email) + Vasquez (LinkedIn) 2026-05-04
- [ ] One advisory board signature secured
- [ ] One numerical backtest with pre-registered criteria

**If these are not in motion, do not write Kalman Filter code.** Tech is ahead of the institution. Catch up.

---

## STATUS DASHBOARD

| Track | State | Next milestone |
|---|---|---|
| Phase 1 — RAG + Simulation | ✅ COMPLETE (RAG 12/12 perfect on 5 cases) | Streamlit demo refresh |
| Phase 2 — News Pipeline + Macro Shock | ✅ COMPLETE (live-tested end-to-end) | Real NewsAPI smoke test |
| Phase 2c Week 1 — Design specs | ✅ COMPLETE | — |
| Phase 2c Weeks 2-15 — Implementation | 🔒 GATED | Kalman Filter |
| Phase 3 — RL / ERP / Regulatory | 🔲 NOT DEFINED | Concept only |
| Business — Legal entity (501c3) | 🟡 IN PROGRESS — EIN faxed 2026-05-04 | DC Articles (after EIN arrives ~May 5) |
| Business — Funder pipeline | 🟡 IN PROGRESS — PAHO email sent 2026-05-04 | Reply ~May 9–13; A4C outreach pending |
| Business — Validation depth | 🟡 PARTIAL (directional only) | Numerical backtest |
| Business — Team | 🔲 NOT STARTED | Advisory board |

---

# TIER 1 — TONIGHT / TOMORROW (BLOCKING)

These items block all other progress. Order matters.

## 1.1 — PAHO Strategic Fund email
- [x] **Status:** SENT 2026-05-04 — Christopher Lim (email) + Dr. Liliana Vasquez (LinkedIn) + Dr. Mauricio Maza (LinkedIn pending acceptance)
- **Owner:** Carlos | **Deadline:** May 4 EOD ✅ | **Effort:** 1 hour
- **Why:** Highest-leverage 2026 action. PAHO Feb 2025 statement explicitly asked for "predictability."
- **Next:** Monitor Lim reply (5–7 business days, ~May 9–13). Accept Maza connection when he responds.

## 1.2 — Angels for Change partnership outreach
- [x] **Status:** SENT 2026-05-04 — communications@angelsforchange.org
- **Revised ask:** Data co-citation (congressional briefs/SummitONE) + EDSA membership ($500, 90+ pharma contacts) + call with Anthony Flammia (COO, global supply chain background)
- **Note:** Original "joint USAID/Google.org" framing was wrong — A4C is a $690K advocacy org that grants TO manufacturers, not analytics nonprofits. Real value is EDSA network access and Flammia as potential advisory board member.

## 1.3 — DC 501(c)(3) Form 1023-EZ
- [x] **EIN SS-4 faxed** 2026-05-04 to 1-855-641-6935 — response expected ~May 5
- [ ] **DC Articles of Incorporation** — file via CorpOnline (corponline.dlcp.dc.gov) after EIN arrives ($350, 5–7 days)
- [ ] **Form 1023-EZ** — file after Articles approved (~May 20+)
- **Owner:** Carlos | **Hard deadline:** Filing started by May 11 ✅ (EIN already in motion) | **Effort:** $3,500–5,500 cash + 20 hours
- **Reference:** [DC_NONPROFIT_FORMATION_GUIDE.md](DC_NONPROFIT_FORMATION_GUIDE.md) Phases 1–4

---

# TIER 2 — THIS WEEK (BLOCKING-ADJACENT)

## 2.1 — Advisory board: 1 cold email
- [ ] **Status:** NOT STARTED
- **Owner:** Carlos | **Deadline:** May 11 | **Effort:** 1 hour
- **Why:** CSO red flag #1 is solo founder. One credentialed name (JHU Carey biostatistician, Bloomberg School health systems researcher) changes how funders read the project. Even unpaid, even informal.

## 2.2 — Streamlit demo update (`app/app.py:1157`)
- [x] **Status:** DONE — commit a5c9b92d (2026-05-04). `Demand surge`, `Regulatory squeeze`, `Macro/inflation shock` added and live.

## 2.3 — Real NewsAPI macro_latam smoke test
- [ ] **Status:** NOT RUN
- **Owner:** Carlos | **Effort:** 30 min
- **What:** `python3 -m phase2_realtime.scheduler` against `macro_latam` query. First time pipeline meets reality. Document hit rate, classifier behavior on noisy real text.

## 2.4 — NewsAPI capacity rotation
- [ ] **Status:** NOT STARTED
- **Owner:** Carlos | **Effort:** 2 hours
- **Why:** 9 categories × hourly = 216 req/day vs. 100/day free tier. Currently over budget. Round-robin schedule or cut categories.

## 2.5 — Customer discovery: 1 conversation this week
- [ ] **Status:** NOT STARTED
- **Owner:** Carlos | **Effort:** 1 hour outreach + 1 conversation
- **Targets:** LATAM ministry of health procurement officer OR pharma supply chain head (Roche/Pfizer/Hikma/Cipla/Eurofarma LATAM)
- **Why:** Pharma subscription hypothesis is the highest-risk financial assumption in the BP. Must validate or kill before any grant cites it.

---

# TIER 3 — WEEKS 2–4 (VALIDATION DEPTH)

## 3.1 — Numerical backtest — pick ONE path

**Pre-register criteria via git commit BEFORE running.** No post-hoc tuning. (Lesson from today's Argentina sensitivity result: pass range [0.40–0.80] is too loose to falsify.)

- [ ] **Path A (recommended):** Romero et al. 2024 amparo dataset (already cited in KB). 405 federal/provincial cases 2017–2020. Use as access-failure proxy. Effort: 2 days extract + reframe.
- [ ] **Path B:** ANMAT bulletin scrape — Spanish-language official shortage notifications by date. Effort: 1 week.
- [ ] **Path C:** Pablo Castello hospital pharmacy data partnership. Best validation; requires relationship build.

## 3.2 — Customer discovery: 4 more conversations
- [ ] Total target: 5 LATAM ministry / 3 pharma supply heads by July 15 (Action 8 deadline)
- **Decision rule:** If 5/5 pharma calls return zero subscription interest → pivot BP financial model to A4C-style partnership/grants only.

## 3.3 — Public risk dashboard v0
- [ ] **Status:** NOT STARTED | **Effort:** 1 week
- **What:** GitHub Pages site, static Plotly/Observable charts from existing 84 sim_outputs. Show 185-day trastuzumab/Venezuela result + portfolio heatmap.
- **Gate:** Live URL before any TIER 1 follow-up meeting (PAHO/A4C).

## 3.4 — alert_engine threshold tuning for macro_economic
- [ ] **Status:** NOT STARTED | **Effort:** 2 hours
- **Why:** Trastuzumab/Colombia silent case (Δmean +1.3d, ΔCVaR +3.2d both below thresholds) — macro shocks systematically produce smaller deltas than direct shocks; current thresholds may miss real signals.

## 3.5 — paclitaxel + oxaliplatin
- [ ] **Status:** NOT STARTED | **Effort:** 2 hours
- **Why:** Classifier suggests them, scheduler silently filters. Either add to DRUG_PARAMS or restrict classifier output.

---

# TIER 4 — PHASE 2C IMPLEMENTATION (Weeks 5–15+)

🔒 **GATED** — do not start until ALL TIER 1 items complete (PAHO sent, 501c3 started, advisory signature, numerical backtest pre-registered).

## 4.1 — Kalman Filter (Weeks 5–7)
- [ ] `phase2_realtime/kalman_filter.py` — KF class, state/covariance updates per `phase2_realtime/docs/kalman_filter_design.md`
- [ ] Unit + integration tests; gate: MAE < 10% after 30 observations
- [ ] Replace fixed `COUNTRY_PARAMS` lead time with `KF.state[0]`

## 4.2 — Robust Optimization (Weeks 7–11)
- [ ] `phase2_realtime/robust_optimizer.py` — Bertsimas-Sim box uncertainty + Wasserstein-DRO
- [ ] `phase2_realtime/uncertainty_sets.py`
- [ ] Backtest against historical scenarios; gate: feasible for all scenarios, cost inflation <15% vs baseline (Q,r)

## 4.3 — MAB / Thompson Sampling (Weeks 11–13)
- [ ] `phase2_realtime/signal_learner.py`
- [ ] Posterior tracking per news category × SKU class
- [ ] Gate: top-ranked arms match Phase 2 alert history (manufacturing > climate)

## 4.4 — Integration & system testing (Weeks 13–15)
- [ ] End-to-end pipeline: news → KF → MAB → RO → alert
- [ ] 100 simulated days; verify all components fire in order
- [ ] Dashboard updates: KF state bands, RO policy frontier, MAB posteriors

## 4.5 — Validation & hardening (Weeks 15+)
- [ ] Shadow-mode deployment (log decisions, no procurement effect) — 2–4 weeks
- [ ] Regulatory technical briefs (FDA/ANVISA/COFEPRIS) — state vector definitions, uncertainty guarantees, decision rules
- [ ] Operations manual (Q/R tuning, Gamma adjustment, rollback)
- [ ] Pharmacist + procurement sign-off

---

# TIER 5 — PHASE 3: RL / ERP / REGULATORY (DEFERRED)

🔲 **CONCEPT ONLY** — do not begin until Phase 2c shadow-mode runs successfully for 6+ months and at least one customer engagement is signed.

- [ ] ERP integration scaffolding (hospital pharmacy systems API)
- [ ] RL policy learning with shadow-mode logged data
- [ ] FDA / ANVISA / COFEPRIS pre-submission packages
- [ ] Multi-echelon extension (Clark & Scarf 1960, Graves & Willems 2000)
- [ ] Operations manual v2 (regulatory-grade)

---

# OPEN HONEST DEFECTS — CSO RED FLAGS

These are the things a sophisticated reviewer would push back on. Address before any external claim or grant submission.

| # | Defect | Track / Tier | Action |
|---|---|---|---|
| 1 | Validation criteria not pre-registered | T3.1 | Pre-register via git commit BEFORE next backtest |
| 2 | Calibration is anecdotal (CNN article, Wikipedia) | T3.1 | Numerical backtest closes this |
| 3 | Venezuela combined-shock < baseline (non-monotonicity) | T2/T4 | Document explicitly + fold into Phase 2c RO |
| 4 | No external biostatistician audit | T2.1 | Advisory board signature |
| 5 | Solo founder; no team | T2.1, T4 | Advisory + post-grant hire |
| 6 | Pharma subscription hypothesis 0% validated | T2.5, T3.2 | 5 cold pitches by July 15 |
| 7 | NewsAPI capacity overrun (216 vs 100/day) | T2.4 | Rotation logic |
| 8 | macro_economic alert threshold may produce false negatives | T3.4 | Recalibrate after numerical backtest |
| 9 | paclitaxel/oxaliplatin silently dropped | T3.5 | Expand DRUG_PARAMS or restrict classifier |
| 10 | Argentina backtest pass range [0.40–0.80] = loose criteria | T3.1 | Numerical backtest replaces directional |

---

# DECISION RULES (CEO DISCIPLINE)

- Before any TIER 4 (Phase 2c) code: TIER 1 must show 4/4 complete
- Before any grant submission: TIER 3.1 must show numerical backtest with ±X% accuracy
- Before any pharma subscription cite in BP: TIER 2.5 + T3.2 = 5 conversations done
- **Pharma subscription pivot deadline:** July 15. If 5/5 zero interest → pivot to A4C-style partnership/grants only
- **501(c)(3) latest start:** May 11. Later filing → exclusion from 2026 Q4 grant cycles
- **PAHO email:** if not sent by May 4 EOD, the diagnosis is execution, not strategy

---

# REVIEW CADENCE

- **Daily** (start of each session): re-read THE WHY + HEADLINE NUMBER + check TIER 1 status
- **Weekly** (Sunday evening): re-prioritize TIER 2 against TIER 1 progress; mark items [x]
- **Monthly:** re-evaluate TIER 3 against funder responses; update Open Defects table
- **Quarterly:** reconfirm Phase 2c gate status; reconfirm mission against new evidence

---

# CHANGE LOG

- 2026-05-03 (session 17): Document created. Phase 1 perfect 12/12 post-recalibration. Venezuela canonical recalibrated 79.3d → 185.4d. Macro_economic shock pathway shipped. Argentina 2018 + Venezuela structural validations PASS.

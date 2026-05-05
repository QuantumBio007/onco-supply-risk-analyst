# Phase 2c Implementation Handoff — for Sonnet 4.6 Coding Session

**Owner:** Carlos | **Authored:** 2026-05-05 (Opus 4.7 analysis pass) | **Reads cold — no prior context required**

---

## Mission (one line)
Implement Kalman Filter, Robust Optimizer, and MAB on the **reference path** `phase2_realtime/`. Swap to fast variants and archive afterward. Do not touch `optimized/` until told to.

## Sequence rule (do not violate)
1. Implement on `phase2_realtime/`
2. Validate against existing battery (Argentina 2018 backtest, Venezuela 2018 baseline, alert integration test)
3. Port to `optimized/` (post-May-14, separate task)
4. Archive `phase2_realtime/` originals only after the swap is green

Rationale: the reference path is the validated source of truth. Implementing on the fast path first conflates algorithm bugs with swap regressions.

## Files of interest

**Canonical pipeline** (read before writing):
- [phase2_realtime/news_listener.py](phase2_realtime/news_listener.py) — NewsAPI poller, 9 categories. **Known overrun: 216 req/day vs 100/day free tier.**
- [phase2_realtime/event_classifier.py](phase2_realtime/event_classifier.py) — Claude (haiku-4-5) JSON classifier, returns `severity / shock_type / impact{lead_time_multiplier, demand_multiplier, fill_rate, budget_multiplier}`.
- [phase2_realtime/shock_mapper.py](phase2_realtime/shock_mapper.py) — Dual path: dynamic (consumes Claude impact) or `SCENARIO_MAP` fallback. Has monotonicity guard against (Q,r) anti-artifact (line 231).
- [phase2_realtime/scheduler.py](phase2_realtime/scheduler.py) — Orchestrator.
- [phase2_realtime/alert_engine.py](phase2_realtime/alert_engine.py) — CVaR-aware, three-dimensional thresholds (mean / CVaR / probability).
- [supply_sim.py](supply_sim.py) — `simulate()` and `simulate_dynamic()`. The integration target for Kalman.

**Design specs** (your contract — read before coding):
- `phase2_realtime/docs/kalman_filter_design.md`
- `phase2_realtime/docs/robust_optimization_design.md`
- `phase2_realtime/docs/mab_design.md`
- `phase2_realtime/docs/api_contracts.md` — input/output JSON for all three modules

**Validation harness** (must still pass):
- `phase2_realtime/validation/argentina_2018_backtest.py`
- `phase2_realtime/validation/venezuela_2018_baseline_validation.py`
- `phase2_realtime/validation/argentina_2018_sensitivity.py`

**Out of scope this session — do not edit:**
- `optimized/*` — fast variants, swap target post-May-14
- `app/`, `agent_core.py` — Phase 1 RAG; only touch if Phase 2c integration requires a new tab
- `evaluation/` — Phase 1 RAG eval; frozen
- `knowledge_base/` — frozen
- Anything under `grants/`, `BusinessPlan/`, `Strategy/`, `Literature/`

## The three algorithms

### 1. Kalman Filter — `phase2_realtime/kalman_filter.py` (NEW, ~200 LOC)
- **What:** Online state estimation; replaces fixed `COUNTRY_PARAMS['lead_time_mean']` and `lead_time_cv` with `KF.state[0]`, `KF.state[1]`.
- **State vector:** `[log(L_mean), log(sigma_L), demand_rate, demand_rate_drift]` (per design doc).
- **Process noise Q:** half-life ~30–60 days. Per memory note, parameter was corrected for quarterly observations — read design doc carefully.
- **Integration:** modify `supply_sim.simulate()` to optionally accept a `KF_state` dict and use it in place of static `COUNTRY_PARAMS`. Side-by-side comparison required.
- **Done when:** unit tests pass synthetic recovery within ±10% MAE after 30 observations; missing-observation handling passes; integration test logs both fixed-vs-KF (Q,r) on same KPIs.

### 2. Robust Optimizer — `phase2_realtime/robust_optimizer.py` + `uncertainty_sets.py` (NEW, ~300 LOC)
- **What:** Worst-case (Q,r) policy under box / ellipsoid / Wasserstein-DRO uncertainty.
- **Solver:** **Grid search** (decision finalized per design review — was Nelder-Mead, changed for robustness against non-smooth CVaR objective). Do not switch back without writing a justification.
- **Objective:** CVaR_90 with cost weights (holding, ordering, shortage penalty).
- **Integration:** wrapper `RO_optimize(drug, country, KF_state, classifier_output) → {Q, r, CVaR_90_forecast, policy_confidence}`. Run in parallel with existing `compute_policy()` initially; do not replace yet.
- **Done when:** feasible for all historical scenarios in backtest; cost inflation <15% vs baseline (Q,r); policy frontier (cost vs CVaR) plots cleanly across Gamma 0→1.

### 3. MAB / Thompson Sampling — `phase2_realtime/signal_learner.py` (NEW, ~200 LOC)
- **What:** Learn which of the 9 news categories actually predict shortages.
- **Arms:** the 9 `QUERIES` keys in `news_listener.py` (manufacturing, logistics_latam, latam_politics, regulatory, currency, healthcare_demand, climate_latam, company_events, macro_latam).
- **Posterior:** Beta(α,β) per arm. **Base-rate correction is finalized** — read design doc; do not re-derive.
- **Integration:** when `event_classifier` fires, log `(category, drug, country, time)`. When shortage labeled (manual or auto, 30–90d window), call `reward(category, success)`. Feed `posterior_mean()` to RO for uncertainty-set radius adjustment.
- **Done when:** posteriors converge to known ground truth within 20% on synthetic test; top-ranked arms match Phase 2 alert history (manufacturing should outrank climate).

## Known defects to be aware of (do NOT fix this session unless the algorithm directly closes them)

| # | Defect | Owner | Likely closure |
|---|---|---|---|
| 1 | NewsAPI 216 vs 100/day overrun | T2.4 | Out of scope; rotation logic, separate task |
| 2 | macro_economic threshold may produce false negatives (Trastuzumab/Colombia silent case) | T3.4 | Closed by RO + MAB tuning |
| 3 | paclitaxel/oxaliplatin silently dropped by scheduler | T3.5 | Out of scope |
| 4 | Manufacturing CRITICAL cisplatin/Argentina +12.9% < 25% threshold | (KF item) | **Closed by Kalman** — root cause is steady-state Monte Carlo not tracking real inventory |
| 5 | Venezuela combined-shock < baseline (non-monotonicity) | T4 RO | **Closed by Robust Opt** if uncertainty set is correctly specified |

## Runtime / model context
- Anthropic key in `.env` at project root. Code uses `claude-haiku-4-5-20251001` for the classifier — leave that alone.
- Python 3.9 venv at `.venv` (NumPy <2 constraint, torch 2.2.0). Activate before any test run.
- The `chroma_db/` directory belongs to Phase 1 RAG — do not rebuild.

## What to deliver back to Carlos
- New files listed above, each with unit tests under `phase2_realtime/tests/`.
- A short note on **any departure** from the design specs (with reason).
- Validation battery still green: `python3 -m phase2_realtime.validation.argentina_2018_backtest` etc.
- Updated `action_items.md` checkboxes for Weeks 2–8 (KF), 4–8 (RO), 8–10 (MAB).

## CEO gate (modified 2026-05-05 — proceed with implementation)
Per [MASTER_ACTION_PLAN.md](MASTER_ACTION_PLAN.md), TIER 4 was originally gated on four items. Status as of this handoff:
- 501(c)(3) filing started ✅
- PAHO email sent ✅
- Advisory board signature: **deferred** (Carlos decision, 2026-05-05) — recruitment needs lead time; the pre-registered closure criteria below substitute for biostatistician audit only weakly, and that gap is acknowledged.
- Pre-registered numerical backtest: **closed via [phase2_realtime/docs/preregistration_phase2c.md](phase2_realtime/docs/preregistration_phase2c.md)** for the Phase 2c implementation specifically. The broader T3.1 backtest (Romero amparo / ANMAT bulletins / Pablo data) remains separate and open.

**Therefore: proceed with implementation.** Read `preregistration_phase2c.md` before writing the closure tests for defects #4 and #5. The pre-registration locks the pass thresholds; do not retune them to make a result pass. A null result is a publishable finding, not a bug.

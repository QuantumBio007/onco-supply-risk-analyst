# Phase 2c Design Review — 2026-05-05 (Opus 4.7)

**Scope:** End-to-end critical read of `news_listener.py`, `event_classifier.py`, `shock_mapper.py`, `scheduler.py`, `alert_engine.py`, plus `kalman_filter_design.md`, `robust_optimization_design.md`, `mab_design.md`. Goal: surface gaps the Sonnet 4.6 coding session would otherwise inherit silently.

**One-line verdict:** the news → predictive chain is well-architected. The three algorithm design specs are good but contain three blocking inconsistencies that must be resolved before code is written, not after.

---

## 🔴 BLOCKING — fix before Sonnet starts

### B1. KF design does not address the root cause attributed to defect #4
Per `phase2b_critical_findings.md` (referenced by `action_items.md:39`), defect #4 root cause is *"steady-state Monte Carlo doesn't track real inventory level."* But the KF design (§2) tracks `[log(L_mean), log(sigma_L)]` — lead-time parameters, not inventory level. Inventory tracking appears in design §4 as **Observable C: On-Hand Inventory (Optional)**.

A 2D lead-time KF feeding `simulate()` will produce a (Q,r) policy that **adapts** to the higher lead-time and partially offsets the shock — the same anti-artifact already documented in `shock_mapper.py:226-241`. The pre-registered Hypothesis 1 (+25% mean / +30% CVaR closure) likely **fails** under the current KF design, not because the algorithm is wrong, but because lead-time tracking does not address an inventory-state diagnosis.

**Required decision before implementation:**
- **Path A:** Promote Observable C (inventory) from "Optional" to primary. KF tracks `[log(L_mean), log(sigma_L), inventory_on_hand]` 3D. Closes the diagnosed root cause.
- **Path B:** Accept that defect #4 is partly a (Q,r) policy-adaptation artifact, not an inventory-tracking gap, and refine the diagnosis. Likely answer: simulator must run TRANSIENT (policy fixed at pre-shock values, params change mid-run), not STEADY-STATE.
- **Path C:** Acknowledge in pre-registration that KF closure of defect #4 is conditional on a specific design path; report the null result if 2D KF leaves the alert miss intact.

I recommend Path B + Path A in combination: the cleanest fix is a transient-mode `simulate()` that holds (Q,r) fixed for the disruption window, plus inventory tracking in KF. Lead-time-only KF will not move the needle on defect #4.

### B2. MAB design has 8 arms; production code has 9 categories
`mab_design.md:28-40` lists 8 arms. `news_listener.QUERIES` has 9 keys: manufacturing, logistics_latam, latam_politics, regulatory, currency, healthcare_demand, climate_latam, company_events, **macro_latam**.

The `macro_latam` category was added to handle indirect macro-economic shocks — the largest scope expansion of Phase 2. It is missing from MAB. If Sonnet implements 8 arms, every macro_economic alert goes unweighted and never updates a posterior.

**Required action:** add macro_latam as a 9th arm with informed prior (recommend Beta(2, 2) — medium predictive value; oil-shock → procurement-budget pathway is real but slow). Update §2, §4 cold-start priors, §8 MAB_Output schema.

### B3. Arm names in MAB design don't match `QUERIES` keys
Design uses `logistics / political / climate / company / demand`. Code uses `logistics_latam / latam_politics / climate_latam / company_events / healthcare_demand`. A 1:1 mapping table is needed. If Sonnet writes `arms = ["logistics", ...]` the integration with `event_classifier` shock_type strings will silently no-op.

**Required action:** add an explicit `ARM_TO_CATEGORY = {...}` mapping at the top of the MAB design and have Sonnet implement against it.

---

## 🟡 SIGNIFICANT — should be addressed but won't block implementation

### S1. RO uncertainty set type contradicts master plan
- `MASTER_ACTION_PLAN.md:138` says: "Bertsimas-Sim box uncertainty + Wasserstein-DRO."
- `robust_optimization_design.md:67-80` says: "Type: Box Uncertainty (Bertsimas-Sim)" — Wasserstein only mentioned as a class to implement in `uncertainty_sets.py`.
- `action_items.md:253` lists all three (Box, Ellipsoid, Wasserstein) as required.

Ambiguity: is the v1 RO box-only, with the others as future work? Or are all three required from day one? Different scopes by ~2x.

**Recommendation:** v1 = Box only. Lock that decision; defer Wasserstein-DRO to a v2 task with separate gate.

### S2. RO Gamma=N hardcodes N=3 but uncertainty set has 4 params
`robust_optimization_design.md:113` says CRITICAL → Gamma = N = 3, with N defined as "all params worst-case." But §3 lists four parameters (lead_time, fill_rate, demand_rate, AND budget_multiplier from `impact_params`). The budget multiplier appears in `RO_Input` at line 197 but not in the formal uncertainty set construction. Either the uncertainty set is missing budget, or N should be 4.

### S3. KF process noise σ_w=0.005/day produces unrealistically tight posterior
Design §3 derives σ_w=0.005 to keep CI manageable across 90-day gaps. But "After 4 quarterly observations, P converges to ~0.01–0.02" → 90% CI on lead-time of roughly ±16% in log space → ±5 days on L=28. Real LATAM lead-time variance is much wider — Argentina 2018 export restriction added 20+ days. The KF will be over-confident on stable data and slow to widen on shocks.

**Recommendation:** validate σ_w against the Argentina 2018 backtest data before committing. If KF underestimates variance during the 2018 disruption, raise σ_w or add a mixture-Gaussian component for shock detection.

### S4. KF event-triggered P-reset contradicts the doc's own separation-of-concerns principle
- §3.5: "Do NOT increase σ_w to capture news-shock speed — that conflates two different mechanisms."
- §6.4: "On CRITICAL news event (from event_classifier), reset P to P_0 to reflect regime uncertainty."

Both can't be true. P-reset on news events is exactly using news to drive KF state — the conflation §3.5 forbids. Pick one.

**Recommendation:** drop §6.4 P-reset. Let the news pipeline drive the RO uncertainty set directly (which it already does); KF stays a state estimator on observations only.

### S5. MAB v1 with simulation-based labels is a circular learner
`mab_design.md:200` proposes simulation-based labels to bootstrap MAB before ERP integration. But MAB-trained-on-simulation will simply learn to mirror SCENARIO_MAP severity → simulation outcome — which is what RO already optimizes. No new information enters the system. v1 MAB does not learn real signal quality; it learns that the simulator behaves like the simulator.

**Recommendation:** acknowledge in §3 that v1 MAB is calibration-only, not signal learning. Real signal learning waits on either (a) ERP labels, (b) public shortage databases (FDA, PAHO), or (c) the Romero amparo dataset already pre-registered for T3.1. Option (c) is closest to free.

---

## 🟠 ARCHITECTURAL — Phase 2 chain has bugs worth noting

### A1. `scheduler.py:121-123` marks article processed BEFORE running simulation
```python
if classification["severity"] in ["CRITICAL", "MODERATE"]:
    results["shocks_detected"] += 1
    _mark_processed(...)   # ← marks done here
    ...
    for drug, country in ...:
        shock_result = trigger_simulation(...)   # ← can crash, never retried
```
If `simulate()` raises (e.g., NumPy regression, OOM), the article is permanently marked processed. Should mark only after at least one successful simulation. Low-risk in practice — `simulate()` is stable — but a real bug.

### A2. `scheduler.py:135-136` drug × country fanout has unbounded latency
A single CRITICAL article that mentions "all LATAM" and is unspecific on drugs gets fanned out to 4 drugs × 3 countries = **12 simulations per article × ~5s each = 1 minute per article**. With NewsAPI returning 100 articles per cycle and even 10% being CRITICAL, that's 10–60 minutes of compute per cycle. Synchronous, blocking. Worse: `paclitaxel` and `oxaliplatin` (per MAP defect #9) are silently filtered — extra waste.

**Recommendation:** parallelize the `for drug in ... for country in ...` loop with `multiprocessing.Pool` (already proposed in RO §11 for grid search — same primitive). Also: tighten the "if no drugs identified, fan out to all" default in `scheduler.py:131`. Most real CRITICAL articles name specific drug classes.

### A3. `alert_engine.py` CVaR thresholds don't adapt to MAB-modulated RO output
Hardcoded `shocked_cvar >= 90 / 45 / 21` in `_cvar_abs_trigger()`. When MAB signal_lift halves Gamma → RO chooses less-conservative (Q,r) → CVaR_90 forecast drops by 30-50% — **but the alert engine threshold doesn't move**. The alert system treats MAB-discounted CVaR identically to nominal CVaR. Architectural disconnect; means MAB cannot influence alert volume, only RO's procurement recommendations.

**Recommendation:** at minimum, log MAB signal_lift alongside CVaR in the alert audit trail so a human can see whether a CVaR drop was MAB-driven. Long-term: thresholds become functions of signal_lift.

### A4. RO 36-case backtest at ~10 min/case = ~6 hours per pre-registered run
`robust_optimization_design.md:128-133` quotes 8-12 min serial / ~2 min parallelized per `optimize_policy()` call. MAP T4.2 acceptance criterion requires 4 drugs × 3 countries × 3 severities = 36 cases. Even with `Pool(4)`: ~70 minutes per backtest run. This makes any kind of iterative tuning expensive.

**Recommendation:** for the **pre-registration runs only**, reduce to representative subset (cisplatin/Argentina, trastuzumab/Venezuela, doxorubicin/Colombia × 2 severities = 6 cases). Pre-registration must specify which subset. Full 36-case sweep stays as a periodic sanity check, not the inner loop.

---

## What I'd want you to decide before Sonnet starts

1. **B1 (KF closure of defect #4):** Path A, B, C, or combination? Without a decision, Hypothesis 1 of `preregistration_phase2c.md` is set up to fail.
2. **B2 (9th arm = macro_latam):** Add to MAB? Almost certainly yes.
3. **B3 (arm name mapping):** Lock the 1:1 ARM_TO_CATEGORY table.
4. **S1 (RO uncertainty set type for v1):** Box-only, or all three?
5. **S5 (MAB v1 label source):** Acknowledge calibration-only, or wait for amparo data?
6. **A4 (pre-registration RO subset):** Which 6 cells go in the locked subset?

The other items are either deferrable (S2, S3, S4) or fixable during implementation (A1, A2, A3).

---

## What is NOT broken (notable strengths)

- `shock_mapper.py` dynamic vs. scenario-map dual path with clamping and monotonicity guard is well thought out. Sonnet should leave this alone.
- `alert_engine.py` three-dimensional CVaR-aware thresholds (mean / CVaR_abs / CVaR_rel max-of-triggers) is the right architecture; the H1 fix history is well documented.
- `event_classifier.py` system prompt's PRECEDENCE rules + macro_economic severity caps + worked examples are unusually disciplined. The 87.5% v2 accuracy is hard-earned.
- MAB design's signal_lift + background arm + per-country stratification (§3) is the strongest single piece of design across all three docs. Whoever wrote that thought hard about the Venezuela base-rate trap.

---

**Status:** uncommitted. Read, decide on the 6 questions above, then I (or Sonnet) act.

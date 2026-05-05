# Phase 2c Design Amendments — 2026-05-05

**Status:** LOCKED. These amendments supersede the listed sections of the design specs. Implementer (Sonnet 4.6) MUST treat these as binding when they contradict the original spec.

**One amendment outstanding:** B1 (KF closure approach for defect #4) is deferred — requires Carlos's judgment between Path A (inventory KF), Path B (transient-mode simulator), or Path C (accept null risk). Until B1 lands, KF v1 implementation MUST NOT attempt defect #4 closure. See `design_review_2026-05-05.md` §B1.

---

## Amendment B2 — MAB has 9 arms, not 8

**Supersedes:** `mab_design.md` §2 (Arms Definition).

The 9th arm is `macro_latam`. Add to the arm table:

| Arm ID | Category (matches `news_listener.QUERIES` key) | Cold-start prior | Rationale |
|--------|------------------------------------------------|------------------|-----------|
| 8 | `macro_latam` | Beta(2, 2) | Indirect macro-economic pathway (oil shock → LATAM inflation → procurement budget compression). Real but slow; medium prior. |

Update §4 INFORMED_PRIORS dict to include `"macro_latam": Beta(2, 2)`. Update §8 MAB_Output schemas (`signal_lifts`, `posterior_means`, `n_observations`) to include the macro_latam key.

---

## Amendment B3 — ARM_TO_CATEGORY mapping (locked)

**Supersedes:** `mab_design.md` §2 arm names.

The MAB implementation MUST use exact strings from `news_listener.QUERIES.keys()`. No paraphrasing. Lock this dict in `signal_learner.py`:

```python
ARM_TO_CATEGORY = {
    0: "manufacturing",
    1: "logistics_latam",
    2: "latam_politics",
    3: "regulatory",
    4: "currency",
    5: "healthcare_demand",
    6: "climate_latam",
    7: "company_events",
    8: "macro_latam",
}
CATEGORY_TO_ARM = {v: k for k, v in ARM_TO_CATEGORY.items()}
```

Cold-start informed priors (full 9-arm table, supersedes mab_design.md §4):
```python
INFORMED_PRIORS = {
    "manufacturing":     (3, 1),   # Beta(α, β) — high prior
    "logistics_latam":   (2, 1),
    "latam_politics":    (1, 2),
    "regulatory":        (2, 2),
    "currency":          (3, 1),   # high for Argentina/Venezuela
    "healthcare_demand": (1, 2),
    "climate_latam":     (1, 2),
    "company_events":    (1, 3),   # low
    "macro_latam":       (2, 2),   # medium — added in B2
}
```

The shock_type strings emitted by `event_classifier` (e.g., `"political"`, `"climate"`, `"company"`, `"demand"`) do NOT match QUERIES keys 1:1. The classifier emits the short form; the QUERIES key is the long form. The MAB MUST be keyed on QUERIES keys (the news category, which is what fired the article into the pipeline), not on classifier shock_type. The scheduler is responsible for passing the QUERIES key to MAB.reward(), not the classifier shock_type. This is a critical wiring detail: classifier shock_type is a property of the article; QUERIES key is a property of the channel that delivered it. MAB learns channel reliability, not classification accuracy.

---

## Amendment S1 — RO v1 = Box uncertainty only

**Supersedes:** `MASTER_ACTION_PLAN.md:138`, `action_items.md:253`, ambiguity in `robust_optimization_design.md`.

V1 implements Bertsimas-Sim Box uncertainty only. Wasserstein-DRO and Ellipsoidal sets are **deferred to v2** with a separate gate. The `uncertainty_sets.py` module still gets created, but only `BoxUncertaintySet` is required for v1. Stub classes for `EllipsoidalUncertaintySet` and `WassersteinUncertaintySet` may be left as `NotImplementedError` placeholders.

Rationale: v1 scope discipline. Box uncertainty is interpretable to non-experts via single Gamma dial; matches RO design doc §3 primary text; lets MAB integration ship sooner. Wasserstein-DRO needs empirical distributions we don't have yet.

---

## Amendment S5 — MAB v1 is calibration-only, not signal learning

**Supersedes:** `mab_design.md` §6 implication that v1 MAB performs real signal learning.

V1 MAB uses simulation-based proxy labels (`mab_design.md` §6.1.4). This means v1 MAB learns to predict simulator outputs from classifier inputs — a calibration loop, not real-world signal quality. **This is acknowledged in advance, not a defect to fix.**

Documentation discipline: every MAB output emitted by v1 must carry a `label_source: "simulation_proxy"` field. When real labels arrive (ERP, FDA shortage database, PAHO alerts, or Romero amparo dataset per T3.1 pre-registration), the field becomes `label_source: "real"` and posteriors should be reset or down-weighted to avoid contamination from the calibration phase.

This caveat MUST appear in any external description of MAB output. Funder pitches that describe MAB as "learning from real shortage signals" before real labels are integrated are misleading.

---

## Amendment A4 — Pre-registration subset (6 cells, locked)

**Supersedes:** `preregistration_phase2c.md` Hypothesis 2's "full 8-cell Venezuela × Combined-shock matrix"; supplements `robust_optimization_design.md` §10 acceptance criterion.

The pre-registered RO closure run uses these **6 cells** (selected for diversity across drug class, country profile, shock type, and severity):

| # | Drug | Country | Shock | Severity | Why included |
|---|------|---------|-------|----------|--------------|
| 1 | cisplatin | Argentina | manufacturing | CRITICAL | Defect #4 case (KF closure target) |
| 2 | trastuzumab | Venezuela | Combined shock | CRITICAL | Defect #5 case (RO closure target); biologic + structural floor |
| 3 | doxorubicin | Colombia | currency | MODERATE | Currency channel; EPS debt cascade context |
| 4 | carboplatin | Argentina | regulatory | MODERATE | Pricing-controls channel |
| 5 | trastuzumab | Argentina | macro_economic | MODERATE | Macro pathway; budget_multiplier; biologic |
| 6 | cisplatin | Venezuela | manufacturing | CRITICAL | Structural floor; tests Venezuela non-monotonicity from a different angle |

Coverage check: 4/4 drugs, 3/3 countries, 5 distinct shock types, 2 severity levels, both pre-registration test cases included.

Pre-registration Hypothesis 2 amendment: "all 8 cells" → "the cells in design_amendments_2026-05-05.md A4 that include Venezuela Combined shock" — i.e., cell #2 (trastuzumab) plus any future addition with the same shock+country. Other cells in the 6-cell subset test RO feasibility and CVaR improvement but are not subject to the monotonicity test.

Full 36-case sweep remains as the periodic acceptance gate per `robust_optimization_design.md` §10, but is not the inner pre-registration loop.

---

## Amendment B1 — LOCKED 2026-05-05: Path B (transient-mode simulator)

**Decision:** Defect #4 is closed via a transient-mode simulator, not via inventory tracking in KF.

**Rationale:** The diagnosed root cause ("steady-state Monte Carlo doesn't track real inventory level") is partly a misattribution. The actual mechanism is that `simulate()` recomputes the (Q,r) policy from the *post-shock* parameters, so the policy adapts to the longer lead-time and partially offsets the shock. Inventory tracking in KF does not address this — only fixing the policy at pre-shock values during the disruption window does.

**What gets built:**
- A new function `simulate_transient(...)` (or a `transient_mode=True` flag on `simulate_dynamic`) in `supply_sim.py`. During the disruption window: shock parameters (lead_time_multiplier, fill_rate, demand_multiplier, budget_multiplier) apply to the simulation, BUT the (Q,r) policy stays fixed at the values computed from pre-shock COUNTRY_PARAMS.
- After the disruption window, simulation can either return to baseline params or continue with shock params (caller's choice).
- KF stays 2D lead-time only — Path A (3D inventory KF) is NOT implemented.

**Pre-registration impact:** Hypothesis 1 in `preregistration_phase2c.md` is unchanged — closure criterion (≥25% mean OR ≥30% CVaR) is locked. Path B is the implementation route to test against that criterion. If Path B still doesn't produce ≥25% delta, that's a null result — meaning the diagnosis was deeper than (Q,r) adaptation, and a Path A inventory KF or a different fix is the next iteration.

**Out of scope for the Path B Sonnet sprint:**
- No KF integration. The transient simulator is built and tested standalone.
- No alert engine wiring. We test the simulator output directly (mean stockout, CVaR_90 from the synthetic India-API shock), then check whether the deltas cross the locked thresholds.
- No backward-incompatible changes to `simulate()` or `simulate_dynamic()`. The transient mode is additive.

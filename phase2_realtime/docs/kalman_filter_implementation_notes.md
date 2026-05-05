# Kalman Filter v1 — Implementation Notes

**Author:** Sonnet 4.6 coding session  
**Date:** 2026-05-05  
**Status:** v1 complete; awaiting B1 decision for scope of v2

---

## Departures from design spec

### 1. `event_triggered_reset_P` behavior (§6.4) — DROPPED

Design spec §6.4 states: "On CRITICAL news event (from event_classifier), reset P to P_0 to
reflect regime uncertainty."

Dropped per design review S4 finding: resetting covariance on external news events violates
the separation-of-concerns principle stated in §3.5 of the same spec ("Do NOT increase sigma_w
to capture news-shock speed — that conflates two different mechanisms"). The KF tracks slow
structural drift; fast shocks are handled by the news pipeline → event_classifier → RO
uncertainty set. Allowing news events to directly modify KF covariance would re-couple the two
mechanisms S4 explicitly separated.

**Consequence:** Consumers (RO, alert engine) who relied on P reset to signal "high uncertainty
now" will not see that effect from the KF. The news pipeline's own uncertainty-set expansion
is the correct mechanism.

### 2. sigma_w = 0.005/day — used as specified, but flagged

Process noise is set to 0.005/day per design spec §3 and the brief. Design review S3 flagged
this as potentially too tight: the value was reasoned from slow quarterly-cycle drift, but under
a genuine regime shift (e.g., ANMAT policy change) the filter will be slow to respond.

This is NOT retouched here — per brief instructions. If the 12-PO recalibration (§3 last
bullet) shows residuals are larger than expected, the correct response is to raise sigma_w
and re-run the pre-registered acceptance tests, not to tune it before seeing the data.

### 3. 4D state vector — not implemented

Design spec §2 defines a 4D optional extension `[log(L_mean), log(sigma_L), demand_rate,
demand_rate_drift]`. The brief and amendment B1 confirm: v1 is 2D only. The demand dimensions
will be considered in v2 if MAB signals indicate demand-surge category is a top predictor, per
§2 decision note.

### 4. Observable B (demand) and Observable C (inventory) — not implemented

v1 handles only Observable A (lead-time observations). Observable B (demand) and C
(on-hand inventory) are in the spec (§4) but require the 4D state vector (B) or
B1 decision resolution (C — Path A for defect #4). Both deferred.

The `update()` method accepts an `observation_type` argument and will silently skip
unknown types with a debug log, so callers passing "demand" or "inventory" will not crash;
they will simply get no update. This is the correct behavior for a staged rollout.

### 5. Defect #4 closure — explicitly out of scope

Per amendment B1, the v1 KF does NOT attempt to close defect #4
(cisplatin/Argentina +12.9% miss). Carlos must first decide between Path A, B, or C.
No inventory tracking, no transient-mode logic, no integration into supply_sim.py.

### 6. supply_sim.py not modified

The design spec §9 shows how `simulate()` would accept a `kf_state` param. That
integration is not done here: the brief says "Do NOT modify supply_sim.py" and
"New files only." The KF module is self-contained and standalone.

---

## Notes for next implementer

- The Joseph form `(I-KH) P (I-KH)^T + K R K^T` is used for the covariance update instead
  of the simpler `(I-KH) P` form. This is numerically more stable when K approaches 1 (many
  tightly-spaced observations). No material difference at the current data frequency, but the
  habit is correct.

- The `predict(dt)` signature accepts a non-integer dt (e.g., 30.0 for monthly cycles). All
  tests use dt=30.0 to simulate monthly PO observations; production callers should pass the
  actual elapsed days since the last observation.

- The `sys.path.insert` at module top makes `from supply_sim import COUNTRY_PARAMS` work both
  when the module is run from the project root and from the phase2_realtime/ directory. If the
  project is later packaged (setup.py / pyproject.toml), this path manipulation should be
  replaced with a proper relative import or package structure.

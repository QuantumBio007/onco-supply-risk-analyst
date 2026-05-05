"""
test_kalman_filter.py — pytest suite for KalmanFilterSupplyChain (v1)

Covers all §12 acceptance gates from kalman_filter_design.md:
  1. Synthetic convergence: MAE < 10% after 30 observations
  2. Observation gap: covariance grows monotonically, no NaN (30-day gap)
  3. Outlier flagging: 3σ residual produces the expected flag dict

Plus three additional tests (6 total, per brief requirement):
  4. get_state() output schema is correct
  5. handle_missing_observation propagates covariance correctly
  6. Initialization from COUNTRY_PARAMS is self-consistent
"""

import math
import sys
import os

import numpy as np
import pytest

# Allow import from project root regardless of how pytest is invoked
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from phase2_realtime.kalman_filter import KalmanFilterSupplyChain, SIGMA_W, P0_DIAG
from supply_sim import COUNTRY_PARAMS


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _feed_observations(kf, L_true, sigma_L_true, n, seed=0):
    """
    Feed n noisy lead-time observations drawn from N(L_true, sigma_L_true)
    through predict + update and return the KF after all updates.
    """
    rng = np.random.default_rng(seed)
    for _ in range(n):
        kf.predict(dt=30.0)  # ~monthly procurement cycle
        obs_raw = rng.normal(L_true, sigma_L_true)
        obs = max(1.0, obs_raw)   # keep positive
        kf.update(obs, "lead_time")
    return kf


# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Synthetic convergence (§12 gate 1)
# ─────────────────────────────────────────────────────────────────────────────

def test_convergence_mae_within_10pct_after_30_obs():
    """
    After 30 synthetic observations drawn from a known true distribution,
    the KF estimate of L_mean should be within ±10% MAE of L_true.

    Uses Argentina cisplatin as the test case. True lead time is set to 40d
    (different from the prior of 35d) to verify the filter actually tracks drift.
    """
    kf = KalmanFilterSupplyChain("cisplatin", "Argentina")

    L_true = 40.0      # days — different from prior (35d) to verify tracking
    sigma_L_true = 10.0
    n_obs = 30

    _feed_observations(kf, L_true, sigma_L_true, n_obs, seed=42)

    estimated = kf.L_mean
    mae_pct = abs(estimated - L_true) / L_true

    assert mae_pct < 0.10, (
        f"MAE after {n_obs} obs: {mae_pct:.1%} — expected < 10%. "
        f"L_true={L_true}d, estimated={estimated:.2f}d"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Observation gap: covariance grows monotonically, no NaN (§12 gate 2)
# ─────────────────────────────────────────────────────────────────────────────

def test_30_day_gap_covariance_grows_monotonically_no_nan():
    """
    Under a 30-day observation gap (30 calls to handle_missing_observation),
    covariance must:
      - grow monotonically (each day's trace > previous day's trace)
      - contain no NaN or inf values
    """
    kf = KalmanFilterSupplyChain("carboplatin", "Colombia")

    # First: a few real observations so the filter has a non-trivial state
    _feed_observations(kf, L_true=30.0, sigma_L_true=8.0, n=5, seed=7)

    P_trace_prev = float(np.trace(kf._P))
    for day in range(30):
        kf.handle_missing_observation()
        P_now = kf._P
        assert not np.any(np.isnan(P_now)), f"NaN in covariance on gap day {day+1}"
        assert not np.any(np.isinf(P_now)), f"Inf in covariance on gap day {day+1}"
        P_trace_now = float(np.trace(P_now))
        assert P_trace_now > P_trace_prev, (
            f"Covariance trace did not grow on gap day {day+1}: "
            f"{P_trace_prev:.6f} -> {P_trace_now:.6f}"
        )
        P_trace_prev = P_trace_now


# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Outlier flagging (§12 gate 3)
# ─────────────────────────────────────────────────────────────────────────────

def test_outlier_flagged_on_3sigma_residual():
    """
    A lead-time observation that is implausibly far from the current estimate
    (well beyond 3σ in log space) must produce a non-None flag dict matching
    the §7 schema: keys timestamp, type, observed, expected, z_score, check_news.
    """
    kf = KalmanFilterSupplyChain("cisplatin", "Venezuela")

    # Warm up filter so covariance is tighter (easier to flag outliers)
    _feed_observations(kf, L_true=60.0, sigma_L_true=36.0, n=10, seed=1)

    # Inject a wildly implausible observation: 10× the prior mean
    extreme_obs = kf.L_mean * 10.0
    flag = kf.update(extreme_obs, "lead_time")

    assert flag is not None, (
        f"Expected outlier flag for obs={extreme_obs:.1f}d "
        f"(expected ~{kf.L_mean:.1f}d) but got None"
    )
    for key in ("timestamp", "type", "observed", "expected", "z_score", "check_news"):
        assert key in flag, f"Outlier flag missing key '{key}': {flag}"
    assert flag["type"] == "lead_time_outlier"
    assert flag["check_news"] is True
    assert flag["z_score"] >= 3.0


# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — get_state() output schema
# ─────────────────────────────────────────────────────────────────────────────

def test_get_state_schema_and_values():
    """
    get_state() must return a dict matching the §8 output interface:
    keys state, covariance, uncertainty_bands, drug, country,
    last_updated, observations_count.

    Also verifies that uncertainty_bands are finite and ordered (lower < upper).
    """
    kf = KalmanFilterSupplyChain("trastuzumab", "Colombia")
    _feed_observations(kf, L_true=28.0, sigma_L_true=7.84, n=5, seed=3)

    s = kf.get_state()

    required_keys = {
        "state", "covariance", "uncertainty_bands",
        "drug", "country", "last_updated", "observations_count"
    }
    assert required_keys == set(s.keys()), (
        f"Missing keys: {required_keys - set(s.keys())}"
    )
    assert s["drug"] == "trastuzumab"
    assert s["country"] == "Colombia"
    assert s["observations_count"] == 5
    assert s["last_updated"] is not None

    for band_key in ("L_mean", "sigma_L"):
        lo, hi = s["uncertainty_bands"][band_key]
        assert math.isfinite(lo) and math.isfinite(hi), (
            f"Non-finite band for {band_key}: ({lo}, {hi})"
        )
        assert lo < hi, f"Lower bound >= upper bound for {band_key}: ({lo}, {hi})"
        assert lo > 0, f"Lower bound non-positive for {band_key}: lo={lo}"

    assert s["covariance"].shape == (2, 2)
    assert s["state"].shape == (2,)


# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — handle_missing_observation propagates covariance correctly
# ─────────────────────────────────────────────────────────────────────────────

def test_handle_missing_observation_state_unchanged_covariance_grows():
    """
    handle_missing_observation() must:
      - NOT change the state vector
      - Increase the covariance trace by exactly sigma_w^2 per call
        (diagonal Q; each call adds Q to P)
    """
    kf = KalmanFilterSupplyChain("doxorubicin", "Argentina")

    x_before = kf._x.copy()
    P_trace_before = float(np.trace(kf._P))

    kf.handle_missing_observation()

    x_after = kf._x.copy()
    P_trace_after = float(np.trace(kf._P))

    assert np.allclose(x_before, x_after), (
        f"State changed during missing-obs handling: {x_before} -> {x_after}"
    )
    expected_trace_increase = 2 * (SIGMA_W ** 2)  # 2 diagonal elements, each + sigma_w^2
    actual_increase = P_trace_after - P_trace_before
    assert abs(actual_increase - expected_trace_increase) < 1e-12, (
        f"Trace increase {actual_increase:.2e} != expected {expected_trace_increase:.2e}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — Initialization from COUNTRY_PARAMS is consistent
# ─────────────────────────────────────────────────────────────────────────────

def test_initialization_from_country_params():
    """
    For every country in COUNTRY_PARAMS, the KF must initialize without error.
    The initial L_mean and sigma_L (in natural space) must match the COUNTRY_PARAMS priors.
    Initial covariance must be P0_DIAG * I.
    """
    for country, cp in COUNTRY_PARAMS.items():
        kf = KalmanFilterSupplyChain("cisplatin", country)

        expected_L_mean = float(cp["lead_time_mean"])
        expected_sigma = expected_L_mean * float(cp["lead_time_cv"])

        assert abs(kf.L_mean - expected_L_mean) < 0.01, (
            f"{country}: L_mean mismatch: {kf.L_mean:.4f} vs {expected_L_mean}"
        )
        assert abs(kf.sigma_L - expected_sigma) < 0.01, (
            f"{country}: sigma_L mismatch: {kf.sigma_L:.4f} vs {expected_sigma}"
        )

        # Covariance should be P0_DIAG * I
        expected_P = np.eye(2) * P0_DIAG
        assert np.allclose(kf._P, expected_P), (
            f"{country}: initial covariance is not P0_DIAG*I"
        )

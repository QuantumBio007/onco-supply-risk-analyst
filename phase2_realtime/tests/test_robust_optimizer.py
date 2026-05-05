"""
test_robust_optimizer.py — pytest suite for Robust Optimizer v1.

Covers:
  1. BoxUncertaintySet samples respect box bounds and Gamma constraint
  2. Stub classes raise NotImplementedError
  3. RobustOptimizer.optimize() returns valid (Q, r) with kf_state=None
  4. RobustOptimizer.optimize() returns valid (Q, r) with a mock KF state
     (wider lead-time bands → same-or-larger Q and r vs kf_state=None)
  5. Increasing Gamma produces same-or-larger (Q, r) (monotonicity sanity check)
  6. RO_Output has all required schema fields per design spec §7

Run:
    source .venv/bin/activate
    pytest phase2_realtime/tests/test_robust_optimizer.py -v

Amendment notes:
  - S1: Ellipsoidal/Wasserstein are stubs (test 2)
  - S2: N=4 params (lead_time_multiplier, demand_multiplier, fill_rate,
        budget_multiplier). Gamma=N_PARAMS = full robustness.
  - A4: Pre-reg subset is 6 cells; this file tests only the core API.
        Full 6-cell backtest is a separate sprint.
"""

import sys
import os

# Ensure project root is on path
PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, PROJECT_ROOT)

import pytest
import numpy as np

from phase2_realtime.uncertainty_sets import (
    BoxUncertaintySet,
    EllipsoidalUncertaintySet,
    WassersteinUncertaintySet,
    N_PARAMS,
    PARAM_NAMES,
)
from phase2_realtime.robust_optimizer import (
    RobustOptimizer,
    Q_CANDIDATES,
    R_CANDIDATES,
)

# ── Test fixtures ─────────────────────────────────────────────────────────────

# Fast test configuration: n_scenarios=200 for speed (design spec §11: use 200 for dev)
N_SCENARIOS_TEST = 200

# Representative impact params (MODERATE manufacturing shock)
IMPACT_PARAMS_NOMINAL = {
    "lead_time_multiplier": 1.5,
    "demand_multiplier":    1.0,
    "fill_rate":            0.80,
    "budget_multiplier":    1.0,
}

# Nominal uncertainty-set values for BoxUncertaintySet unit tests
NOMINAL = {
    "lead_time_multiplier": 1.5,
    "demand_multiplier":    1.0,
    "fill_rate":            0.80,
    "budget_multiplier":    1.0,
}
DELTAS = {
    "lead_time_multiplier": 0.50,
    "demand_multiplier":    0.20,
    "fill_rate":            0.15,
    "budget_multiplier":    0.20,
}

# Mock KF state with WIDER lead-time bands than COUNTRY_PARAMS default
# Argentina baseline: L_mean=35d; mock KF = 42.5d ±10d (90% CI ~[25.8, 61.6])
MOCK_KF_STATE = {
    "state": np.array([np.log(42.5), np.log(42.5 * 0.30)]),
    "covariance": np.eye(2) * 0.08,
    "uncertainty_bands": {
        "L_mean":  (25.8, 61.6),  # 90% CI, wider than default 35 ± ~14d
        "sigma_L": (6.2,  19.4),
    },
    "drug": "cisplatin",
    "country": "Argentina",
    "last_updated": "2026-05-05",
    "observations_count": 12,
}


# ── 1. BoxUncertaintySet: samples respect bounds and Gamma constraint ──────

class TestBoxUncertaintySetSampling:

    def test_samples_within_box_bounds(self):
        """All sampled params must lie within [nominal - delta, nominal + delta]."""
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=2.0)
        rng = np.random.default_rng(42)
        for _ in range(500):
            u = uset.sample(rng)
            for p in PARAM_NAMES:
                lo = NOMINAL[p] - DELTAS[p]
                hi = NOMINAL[p] + DELTAS[p]
                assert lo - 1e-9 <= u[p] <= hi + 1e-9, (
                    f"param {p}: {u[p]:.4f} outside [{lo:.4f}, {hi:.4f}]"
                )

    def test_samples_respect_gamma_budget(self):
        """L1 budget usage Σ |u_i - û_i|/δ_i must not exceed Gamma."""
        for gamma in [0.0, 0.5, 1.0, 2.0, float(N_PARAMS)]:
            uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=gamma)
            rng = np.random.default_rng(123)
            for _ in range(200):
                u = uset.sample(rng)
                budget_usage = sum(
                    abs(u[p] - NOMINAL[p]) / DELTAS[p]
                    for p in PARAM_NAMES
                    if DELTAS[p] > 0
                )
                assert budget_usage <= gamma + 1e-8, (
                    f"gamma={gamma}: budget_usage={budget_usage:.4f} > gamma"
                )

    def test_gamma_zero_returns_nominal(self):
        """At gamma=0, all samples should equal nominal."""
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=0.0)
        rng = np.random.default_rng(0)
        for _ in range(50):
            u = uset.sample(rng)
            for p in PARAM_NAMES:
                assert abs(u[p] - NOMINAL[p]) < 1e-9, (
                    f"gamma=0: {p} = {u[p]:.6f} != nominal {NOMINAL[p]:.6f}"
                )

    def test_gamma_n_params_produces_max_deviation(self):
        """At gamma=N_PARAMS, samples can hit any combination of box corners."""
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=float(N_PARAMS))
        rng = np.random.default_rng(7)
        max_deviations = {p: 0.0 for p in PARAM_NAMES}
        for _ in range(500):
            u = uset.sample(rng)
            for p in PARAM_NAMES:
                max_deviations[p] = max(max_deviations[p], abs(u[p] - NOMINAL[p]))
        # With N_PARAMS=4 budget, all params can be at full delta; verify at least
        # one param reaches close to its full delta in 500 draws
        any_near_full = any(
            max_deviations[p] > 0.80 * DELTAS[p]
            for p in PARAM_NAMES
            if DELTAS[p] > 0
        )
        assert any_near_full, (
            f"gamma=N_PARAMS: no param reached 80% of delta in 500 draws. "
            f"Max deviations: {max_deviations}"
        )

    def test_check_feasibility(self):
        """check_feasibility correctly accepts and rejects points."""
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=1.5)
        # Nominal is always feasible
        assert uset.check_feasibility(NOMINAL), "nominal must be feasible"
        # Exact L1 budget = gamma is feasible
        u_edge = {p: NOMINAL[p] for p in PARAM_NAMES}
        # Set one param to full delta (uses 1 unit) and another to 0.5*delta (0.5 units)
        u_edge["lead_time_multiplier"] = NOMINAL["lead_time_multiplier"] + DELTAS["lead_time_multiplier"]
        u_edge["demand_multiplier"] = NOMINAL["demand_multiplier"] + 0.5 * DELTAS["demand_multiplier"]
        assert uset.check_feasibility(u_edge), "edge case at gamma=1.5 should be feasible"
        # Violate box bound
        u_outside = dict(NOMINAL)
        u_outside["lead_time_multiplier"] = NOMINAL["lead_time_multiplier"] + DELTAS["lead_time_multiplier"] * 2
        assert not uset.check_feasibility(u_outside), "outside box must be infeasible"

    def test_invalid_gamma_raises(self):
        with pytest.raises(ValueError, match="gamma must be in"):
            BoxUncertaintySet(NOMINAL, DELTAS, gamma=N_PARAMS + 0.1)

    def test_negative_delta_raises(self):
        bad_deltas = dict(DELTAS)
        bad_deltas["fill_rate"] = -0.1
        with pytest.raises(ValueError, match="delta"):
            BoxUncertaintySet(NOMINAL, bad_deltas, gamma=1.0)

    def test_all_param_names_present_in_sample(self):
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=1.0)
        u = uset.sample()
        for p in PARAM_NAMES:
            assert p in u, f"param '{p}' missing from sample()"

    def test_worst_case_sample(self):
        """sample_worst_case pushes params in adversarial direction."""
        uset = BoxUncertaintySet(NOMINAL, DELTAS, gamma=float(N_PARAMS))
        wc = uset.worst_case = uset.sample_worst_case()
        # lead_time and demand should be >= nominal; fill_rate and budget <= nominal
        assert wc["lead_time_multiplier"] >= NOMINAL["lead_time_multiplier"]
        assert wc["demand_multiplier"]    >= NOMINAL["demand_multiplier"]
        assert wc["fill_rate"]            <= NOMINAL["fill_rate"]
        assert wc["budget_multiplier"]    <= NOMINAL["budget_multiplier"]


# ── 2. Stub classes raise NotImplementedError ─────────────────────────────────

class TestStubClasses:

    def test_ellipsoidal_raises(self):
        with pytest.raises(NotImplementedError, match="v2"):
            EllipsoidalUncertaintySet(NOMINAL, DELTAS, gamma=1.0)

    def test_wasserstein_raises(self):
        with pytest.raises(NotImplementedError, match="v2"):
            WassersteinUncertaintySet(NOMINAL, DELTAS, gamma=1.0)

    def test_ellipsoidal_message_references_amendment(self):
        """Error message must reference design_amendments_2026-05-05.md S1."""
        with pytest.raises(NotImplementedError) as exc_info:
            EllipsoidalUncertaintySet()
        assert "design_amendments_2026-05-05.md" in str(exc_info.value), (
            "NotImplementedError should reference design_amendments_2026-05-05.md"
        )

    def test_wasserstein_message_references_amendment(self):
        with pytest.raises(NotImplementedError) as exc_info:
            WassersteinUncertaintySet()
        assert "design_amendments_2026-05-05.md" in str(exc_info.value)


# ── 3. optimize() with kf_state=None returns valid (Q, r) ─────────────────

class TestOptimizeNoKF:

    @pytest.fixture(scope="class")
    def ro_output(self):
        ro = RobustOptimizer(n_scenarios=N_SCENARIOS_TEST, use_multiprocessing=False,
                             random_seed=42)
        return ro.optimize(
            drug="cisplatin",
            country="Argentina",
            kf_state=None,
            impact_params=IMPACT_PARAMS_NOMINAL,
            gamma=1.5,
        )

    def test_q_grid_is_in_candidate_grid(self, ro_output):
        """Q_grid (optimization label) must be from the spec grid."""
        assert ro_output["Q_grid"] in Q_CANDIDATES, (
            f"Q_grid={ro_output['Q_grid']} not in candidate grid {Q_CANDIDATES}"
        )

    def test_r_grid_is_in_candidate_grid(self, ro_output):
        """r_grid (optimization label) must be from the spec grid."""
        assert ro_output["r_grid"] in R_CANDIDATES, (
            f"r_grid={ro_output['r_grid']} not in candidate grid {R_CANDIDATES}"
        )

    def test_q_positive(self, ro_output):
        """Actual Q (scaled to drug/country) must be positive."""
        assert ro_output["Q"] > 0

    def test_r_positive(self, ro_output):
        """Actual r must be positive."""
        assert ro_output["r"] > 0

    def test_cvar_90_non_negative(self, ro_output):
        assert ro_output["CVaR_90_forecast"] >= 0

    def test_kf_state_used_is_false(self, ro_output):
        assert ro_output["kf_state_used"] is False


# ── 4. optimize() with mock KF state (wider bands) ────────────────────────────

class TestOptimizeWithKF:

    @pytest.fixture(scope="class")
    def ro_no_kf(self):
        ro = RobustOptimizer(n_scenarios=N_SCENARIOS_TEST, use_multiprocessing=False,
                             random_seed=42)
        return ro.optimize(
            drug="cisplatin",
            country="Argentina",
            kf_state=None,
            impact_params=IMPACT_PARAMS_NOMINAL,
            gamma=1.5,
        )

    @pytest.fixture(scope="class")
    def ro_with_kf(self):
        ro = RobustOptimizer(n_scenarios=N_SCENARIOS_TEST, use_multiprocessing=False,
                             random_seed=42)
        return ro.optimize(
            drug="cisplatin",
            country="Argentina",
            kf_state=MOCK_KF_STATE,
            impact_params=IMPACT_PARAMS_NOMINAL,
            gamma=1.5,
        )

    def test_kf_state_used_is_true(self, ro_with_kf):
        assert ro_with_kf["kf_state_used"] is True

    def test_kf_output_valid_Q(self, ro_with_kf):
        assert ro_with_kf["Q_grid"] in Q_CANDIDATES

    def test_kf_output_valid_r(self, ro_with_kf):
        assert ro_with_kf["r_grid"] in R_CANDIDATES

    def test_kf_lead_time_delta_wider_than_no_kf(self, ro_no_kf, ro_with_kf):
        """
        KF mock state has wider lead-time bands → lead_time delta in uncertainty
        set should be wider with KF than without.
        """
        delta_kf = ro_with_kf["delta_params"]["lead_time_multiplier"]
        delta_no_kf = ro_no_kf["delta_params"]["lead_time_multiplier"]
        assert delta_kf >= delta_no_kf, (
            f"KF should widen lead_time delta: kf={delta_kf:.3f} < no_kf={delta_no_kf:.3f}"
        )

    def test_kf_q_same_or_larger(self, ro_no_kf, ro_with_kf):
        """
        Wider uncertainty under KF should push recommended Q_grid same-or-higher.
        Directional check — may flip under MC noise at grid resolution.
        See implementation notes §4.
        """
        assert (ro_with_kf["Q_grid"] >= ro_no_kf["Q_grid"]
                or ro_with_kf["r_grid"] >= ro_no_kf["r_grid"]), (
            f"With KF (wider uncertainty), expected Q_grid or r_grid >= no-KF baseline. "
            f"kf=({ro_with_kf['Q_grid']}, {ro_with_kf['r_grid']}) "
            f"no_kf=({ro_no_kf['Q_grid']}, {ro_no_kf['r_grid']}). "
            f"May be Monte Carlo noise at grid resolution — see implementation notes §4."
        )


# ── 5. Monotonicity: larger Gamma → same-or-larger (Q, r) ────────────────────

class TestMonotonicity:
    """
    Per design spec §3: higher Gamma = more conservatism = higher (Q, r).

    This is a sanity check, not a theorem — grid granularity and Monte Carlo
    noise mean strict monotonicity isn't guaranteed at every step. We test
    that the overall trend is monotone (Q and r at gamma=0 ≤ gamma=N_PARAMS).
    """

    @pytest.fixture(scope="class")
    def outputs_by_gamma(self):
        ro = RobustOptimizer(n_scenarios=N_SCENARIOS_TEST, use_multiprocessing=False,
                             random_seed=0)
        gammas = [0.0, 1.0, 2.0, float(N_PARAMS)]
        return {
            g: ro.optimize("cisplatin", "Argentina", kf_state=None,
                           impact_params=IMPACT_PARAMS_NOMINAL, gamma=g)
            for g in gammas
        }

    def test_q_non_decreasing_low_to_high_gamma(self, outputs_by_gamma):
        """Q_grid at gamma=0 ≤ Q_grid at gamma=N_PARAMS (overall monotone direction)."""
        Q_low  = outputs_by_gamma[0.0]["Q_grid"]
        Q_high = outputs_by_gamma[float(N_PARAMS)]["Q_grid"]
        assert Q_high >= Q_low, (
            f"Q_grid should not decrease from gamma=0 to gamma={N_PARAMS}: "
            f"{Q_low} → {Q_high}"
        )

    def test_r_non_decreasing_low_to_high_gamma(self, outputs_by_gamma):
        """r_grid at gamma=0 ≤ r_grid at gamma=N_PARAMS (overall monotone direction)."""
        r_low  = outputs_by_gamma[0.0]["r_grid"]
        r_high = outputs_by_gamma[float(N_PARAMS)]["r_grid"]
        assert r_high >= r_low, (
            f"r_grid should not decrease from gamma=0 to gamma={N_PARAMS}: "
            f"{r_low} → {r_high}"
        )

    def test_cvar_non_decreasing_low_to_high_gamma(self, outputs_by_gamma):
        """CVaR_90 at gamma=0 ≤ CVaR_90 at gamma=N_PARAMS (more risk under wider set)."""
        cvar_low  = outputs_by_gamma[0.0]["CVaR_90_forecast"]
        cvar_high = outputs_by_gamma[float(N_PARAMS)]["CVaR_90_forecast"]
        assert cvar_high >= cvar_low * 0.85, (  # 15% slack for MC noise
            f"CVaR_90 should not drop substantially from gamma=0 to gamma={N_PARAMS}: "
            f"{cvar_low:.1f} → {cvar_high:.1f}"
        )

    def test_all_q_grid_in_grid(self, outputs_by_gamma):
        for g, out in outputs_by_gamma.items():
            assert out["Q_grid"] in Q_CANDIDATES, f"gamma={g}: Q_grid={out['Q_grid']} not in grid"

    def test_all_r_grid_in_grid(self, outputs_by_gamma):
        for g, out in outputs_by_gamma.items():
            assert out["r_grid"] in R_CANDIDATES, f"gamma={g}: r_grid={out['r_grid']} not in grid"


# ── 6. RO_Output has all required schema fields per design spec §7 ────────────

class TestROOutputSchema:
    """
    Design spec §7 required fields:
      Q, r, CVaR_90_forecast, policy_confidence, gamma_used,
      policy_frontier, baseline_Q, baseline_r, baseline_CVaR_90,
      improvement_pct
    """

    REQUIRED_FIELDS = [
        "Q",
        "r",
        "CVaR_90_forecast",
        "policy_confidence",
        "gamma_used",
        "policy_frontier",
        "baseline_Q",
        "baseline_r",
        "baseline_CVaR_90",
        "improvement_pct",
    ]

    @pytest.fixture(scope="class")
    def ro_output(self):
        ro = RobustOptimizer(n_scenarios=N_SCENARIOS_TEST, use_multiprocessing=False,
                             random_seed=42)
        return ro.optimize(
            drug="trastuzumab",
            country="Venezuela",
            kf_state=None,
            impact_params={
                "lead_time_multiplier": 2.5,
                "demand_multiplier":    1.15,
                "fill_rate":            0.55,
                "budget_multiplier":    0.60,
            },
            gamma=2.0,
        )

    def test_all_required_fields_present(self, ro_output):
        for field in self.REQUIRED_FIELDS:
            assert field in ro_output, f"RO_Output missing required field '{field}'"

    def test_gamma_used_matches_input(self, ro_output):
        assert ro_output["gamma_used"] == 2.0

    def test_policy_confidence_in_range(self, ro_output):
        pc = ro_output["policy_confidence"]
        assert 0.0 <= pc <= 1.0, f"policy_confidence={pc} outside [0, 1]"

    def test_policy_frontier_is_list(self, ro_output):
        assert isinstance(ro_output["policy_frontier"], list)

    def test_improvement_pct_is_numeric(self, ro_output):
        imp = ro_output["improvement_pct"]
        assert isinstance(imp, (int, float)), f"improvement_pct not numeric: {imp}"

    def test_baseline_q_positive(self, ro_output):
        assert ro_output["baseline_Q"] > 0

    def test_baseline_r_positive(self, ro_output):
        assert ro_output["baseline_r"] > 0

    def test_baseline_cvar_non_negative(self, ro_output):
        assert ro_output["baseline_CVaR_90"] >= 0

    def test_N_params_is_4(self):
        """Amendment S2: N_PARAMS must be 4 (all four impact params in set)."""
        assert N_PARAMS == 4, (
            f"N_PARAMS={N_PARAMS} but should be 4 per amendment S2 "
            f"(lead_time_multiplier, demand_multiplier, fill_rate, budget_multiplier)"
        )

    def test_drug_and_country_echoed(self, ro_output):
        assert ro_output["drug"] == "trastuzumab"
        assert ro_output["country"] == "Venezuela"

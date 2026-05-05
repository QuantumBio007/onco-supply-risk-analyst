"""
robust_optimizer.py — RobustOptimizer v1 (Bertsimas-Sim Box uncertainty)

Wraps supply_sim.simulate_dynamic() as a black-box CVaR_90 estimator.
Grid-searches (Q, r) candidates to find the policy minimizing worst-case
CVaR_90 over the box uncertainty set parameterized by Gamma.

Design spec:  phase2_realtime/docs/robust_optimization_design.md
Amendments:   phase2_realtime/docs/design_amendments_2026-05-05.md (S1, S2)
Notes:        phase2_realtime/docs/ro_v1_implementation_notes.md

Usage:
    from phase2_realtime.robust_optimizer import RobustOptimizer
    ro = RobustOptimizer()
    output = ro.optimize("cisplatin", "Argentina", kf_state=None,
                         impact_params={"lead_time_multiplier": 2.5,
                                        "fill_rate": 0.55,
                                        "demand_multiplier": 1.0,
                                        "budget_multiplier": 1.0},
                         gamma=1.5)
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, List, Optional

import numpy as np

# Supply sim is at project root (one level up from phase2_realtime/)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from supply_sim import COUNTRY_PARAMS, DRUG_PARAMS, SCENARIO_PARAMS, simulate_dynamic, _run_once

from phase2_realtime.uncertainty_sets import BoxUncertaintySet, N_PARAMS

logger = logging.getLogger(__name__)

# ── Grid candidates per design spec §4 ───────────────────────────────────────
Q_CANDIDATES: List[int] = [50, 75, 100, 125, 150, 175, 200]
R_CANDIDATES: List[int] = [20, 35, 50, 65, 80, 95, 110]

# Default production scenario count; tests override to 200 for speed
DEFAULT_N_SCENARIOS: int = 500

# ── Default uncertainty deltas: fraction of nominal value ────────────────────
# lead_time_multiplier: ±0.5 × nominal (aggressive but realistic for LATAM)
# demand_multiplier:    ±0.2 × nominal
# fill_rate:            ±0.15 absolute
# budget_multiplier:    ±0.20 × nominal
# Cap: delta cannot exceed 2 × default range (per design spec §11 Known Risks)
DEFAULT_DELTA_FRACTIONS = {
    "lead_time_multiplier": 0.50,
    "demand_multiplier":    0.20,
    "fill_rate":            0.15,   # absolute (not fraction of nominal)
    "budget_multiplier":    0.20,
}

# Default disruption duration for RO scenarios (days)
DEFAULT_DISRUPTION_DURATION: int = 120


class RobustOptimizer:
    """
    Grid-search robust optimizer minimizing worst-case CVaR_90 over a
    Bertsimas-Sim box uncertainty set.

    Public API:
        optimize(drug, country, kf_state, impact_params, gamma) -> RO_Output
    """

    def __init__(
        self,
        n_scenarios: int = DEFAULT_N_SCENARIOS,
        use_multiprocessing: bool = True,
        random_seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            n_scenarios:        Monte Carlo draws per (Q, r) candidate.
                                Use 200 in tests; 500 in production.
            use_multiprocessing: Attempt Pool(4) parallelism. Falls back
                                 gracefully to serial if unavailable.
            random_seed:        If set, evaluations are reproducible.
        """
        self.n_scenarios = n_scenarios
        self.use_multiprocessing = use_multiprocessing
        self.random_seed = random_seed

    # ── Main entry point ─────────────────────────────────────────────────────

    def optimize(
        self,
        drug: str,
        country: str,
        kf_state: Optional[dict],
        impact_params: dict,
        gamma: float,
    ) -> dict:
        """
        Find the (Q, r) policy that minimizes worst-case CVaR_90 over U(Γ).

        Args:
            drug:          e.g. "cisplatin"
            country:       e.g. "Argentina"
            kf_state:      KF state dict per kalman_filter.py §get_state() schema,
                           OR None to fall back to COUNTRY_PARAMS defaults.
            impact_params: dict with lead_time_multiplier, demand_multiplier,
                           fill_rate, budget_multiplier (from event_classifier).
            gamma:         Bertsimas-Sim budget ∈ [0, N_PARAMS=4].

        Returns:
            RO_Output dict per design spec §7.
        """
        if drug not in DRUG_PARAMS:
            raise ValueError(f"Unknown drug '{drug}'. Valid: {list(DRUG_PARAMS)}")
        if country not in COUNTRY_PARAMS:
            raise ValueError(f"Unknown country '{country}'. Valid: {list(COUNTRY_PARAMS)}")
        if not (0.0 <= gamma <= N_PARAMS):
            raise ValueError(f"gamma must be in [0, {N_PARAMS}]; got {gamma}")

        # 1. Build nominal parameters (KF or COUNTRY_PARAMS fallback)
        nominal, deltas = self._build_nominal_and_deltas(
            country, kf_state, impact_params
        )

        # 2. Build uncertainty set
        uncertainty_set = BoxUncertaintySet(nominal=nominal, deltas=deltas, gamma=gamma)

        # 3. Compute baseline (Q,r) under COUNTRY_PARAMS nominal (no shock).
        #    baseline_Q / baseline_r: textbook EOQ values from simulate_dynamic.
        #    baseline_CVaR_90: cost-proxy CVaR at gamma=0 (nominal params only)
        #    evaluated at the *best grid point under gamma=0* so the comparison
        #    is apples-to-apples with best_cvar (both in dollar cost units).
        baseline_sim = self._evaluate_baseline(drug, country)
        baseline_Q = baseline_sim["eoq"]
        baseline_r = baseline_sim["reorder_point"]

        # Cost-proxy baseline: grid-search at gamma=0 (nominal only, no adversarial)
        nominal_uset = BoxUncertaintySet(nominal=nominal, deltas=deltas, gamma=0.0)
        _bQ, _br, baseline_cvar = self._grid_search(drug, country, nominal_uset)

        # 4. Grid search → best grid-label (Q_grid, r_grid)
        best_Q_grid, best_r_grid, best_cvar = self._grid_search(
            drug, country, uncertainty_set
        )

        # Translate grid labels to actual procurement quantities
        best_Q, best_r = self._grid_to_actual(drug, country, best_Q_grid, best_r_grid)

        # 5. Policy confidence
        policy_confidence = self._compute_policy_confidence(
            drug, country, best_Q_grid, best_r_grid, uncertainty_set
        )

        # 6. Improvement vs baseline
        improvement_pct = (
            (baseline_cvar - best_cvar) / baseline_cvar * 100
            if baseline_cvar > 0 else 0.0
        )

        output: dict = {
            "Q": best_Q,           # actual recommended order quantity (units)
            "r": best_r,           # actual recommended reorder point (units)
            "Q_grid": best_Q_grid, # grid label used in optimization
            "r_grid": best_r_grid,
            "CVaR_90_forecast": round(best_cvar, 2),
            "policy_confidence": round(policy_confidence, 3),
            "gamma_used": gamma,
            "policy_frontier": [],   # populated only if build_frontier=True
            "baseline_Q": baseline_Q,
            "baseline_r": baseline_r,
            "baseline_CVaR_90": round(baseline_cvar, 2),
            "improvement_pct": round(improvement_pct, 2),
            # Provenance fields (not in spec §7 but needed for auditability)
            "drug": drug,
            "country": country,
            "kf_state_used": kf_state is not None,
            "n_scenarios": self.n_scenarios,
            "uncertainty_set_type": "BoxUncertaintySet",
            "N_params": N_PARAMS,
            "nominal_params": nominal,
            "delta_params": deltas,
        }
        return output

    def build_frontier(
        self,
        drug: str,
        country: str,
        kf_state: Optional[dict],
        impact_params: dict,
        gammas: Optional[List[float]] = None,
    ) -> List[dict]:
        """
        Compute RO_Output for a sweep of gamma values (Pareto frontier).

        Args:
            gammas: List of gamma values. Defaults to [0.0, 0.5, 1.0, 1.5, 2.0, N_PARAMS].
        """
        if gammas is None:
            gammas = [0.0, 0.5, 1.0, 1.5, 2.0, float(N_PARAMS)]

        frontier = []
        for g in gammas:
            out = self.optimize(drug, country, kf_state, impact_params, gamma=g)
            frontier.append({
                "gamma":       g,
                "Q":           out["Q"],
                "r":           out["r"],
                "cvar_90_days": out["CVaR_90_forecast"],
            })
        return frontier

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_nominal_and_deltas(
        self,
        country: str,
        kf_state: Optional[dict],
        impact_params: dict,
    ):
        """
        Derive nominal parameter vector and uncertainty deltas.

        KF state expands lead-time uncertainty bands if provided.
        Nominal values come from impact_params (event_classifier output) with
        country structural floors applied implicitly by simulate_dynamic().

        Returns:
            nominal: dict[str, float] — parameter point estimates
            deltas:  dict[str, float] — half-widths
        """
        # Nominal: impact params as supplied (simulate_dynamic applies structural floors)
        lt_mult    = float(impact_params.get("lead_time_multiplier", 1.0))
        d_mult     = float(impact_params.get("demand_multiplier",    1.0))
        fill       = float(impact_params.get("fill_rate",            0.95))
        budget     = float(impact_params.get("budget_multiplier",    1.0))

        nominal = {
            "lead_time_multiplier": lt_mult,
            "demand_multiplier":    d_mult,
            "fill_rate":            fill,
            "budget_multiplier":    budget,
        }

        # Default deltas from fractions of nominal
        deltas = {
            "lead_time_multiplier": max(0.0, lt_mult  * DEFAULT_DELTA_FRACTIONS["lead_time_multiplier"]),
            "demand_multiplier":    max(0.0, d_mult   * DEFAULT_DELTA_FRACTIONS["demand_multiplier"]),
            "fill_rate":            DEFAULT_DELTA_FRACTIONS["fill_rate"],   # absolute
            "budget_multiplier":    max(0.0, budget   * DEFAULT_DELTA_FRACTIONS["budget_multiplier"]),
        }

        # KF expansion: if KF state provided, widen lead-time delta to span the
        # KF 90% confidence interval mapped back to a multiplier deviation.
        if kf_state is not None:
            try:
                bands = kf_state["uncertainty_bands"]["L_mean"]  # (lower_90, upper_90) days
                cp = COUNTRY_PARAMS[country if country in COUNTRY_PARAMS else "Argentina"]
                base_lt = cp["lead_time_mean"]
                # Convert KF band to multiplier delta relative to nominal
                # upper band maps to max multiplier; use half-range as delta
                kf_upper_mult = bands[1] / base_lt if base_lt > 0 else lt_mult
                kf_lower_mult = bands[0] / base_lt if base_lt > 0 else lt_mult
                kf_delta = max(
                    deltas["lead_time_multiplier"],
                    (kf_upper_mult - kf_lower_mult) / 2.0,
                )
                deltas["lead_time_multiplier"] = kf_delta
                logger.debug(
                    "KF expanded lead_time delta: %.3f → %.3f (bands=[%.1f, %.1f])",
                    DEFAULT_DELTA_FRACTIONS["lead_time_multiplier"] * lt_mult,
                    kf_delta, bands[0], bands[1],
                )
            except (KeyError, TypeError, ZeroDivisionError) as exc:
                logger.warning("KF state parsing failed (%s); using default deltas.", exc)

        # Clamp deltas: fill_rate cannot push below 0 or above 1
        deltas["fill_rate"] = min(deltas["fill_rate"], fill)   # can't go below 0 after subtraction
        # Budget delta: cannot push multiplier below 0
        deltas["budget_multiplier"] = min(deltas["budget_multiplier"], budget)

        return nominal, deltas

    def _grid_search(
        self,
        drug: str,
        country: str,
        uncertainty_set: BoxUncertaintySet,
    ):
        """
        Exhaustive grid search over Q_CANDIDATES × R_CANDIDATES.

        Returns (best_Q, best_r, best_cvar).
        """
        # Build evaluation tasks: list of (Q, r)
        tasks = [(Q, r) for Q in Q_CANDIDATES for r in R_CANDIDATES]

        # Attempt parallel evaluation
        results = self._evaluate_parallel(drug, country, uncertainty_set, tasks)

        best_Q, best_r, best_cvar = None, None, float("inf")
        for (Q, r), cvar in zip(tasks, results):
            if cvar < best_cvar:
                best_cvar = cvar
                best_Q = Q
                best_r = r

        return best_Q, best_r, best_cvar

    def _evaluate_parallel(
        self,
        drug: str,
        country: str,
        uncertainty_set: BoxUncertaintySet,
        tasks: list,
    ) -> list:
        """
        Evaluate CVaR_90 for each (Q, r) in tasks.

        Tries multiprocessing.Pool(4); falls back to serial if unavailable
        (CI-friendly). Serial is always used when n_scenarios is small or
        when use_multiprocessing=False.
        """
        use_mp = (
            self.use_multiprocessing
            and self.n_scenarios >= 200
            and len(tasks) > 10
        )

        if use_mp:
            try:
                from multiprocessing import Pool
                with Pool(4) as pool:
                    results = pool.starmap(
                        _evaluate_candidate,
                        [
                            (drug, country, Q, r, uncertainty_set,
                             self.n_scenarios, self.random_seed)
                            for Q, r in tasks
                        ],
                    )
                return results
            except Exception as exc:
                logger.warning("multiprocessing failed (%s); falling back to serial.", exc)

        # Serial fallback
        return [
            _evaluate_candidate(
                drug, country, Q, r, uncertainty_set,
                self.n_scenarios, self.random_seed
            )
            for Q, r in tasks
        ]

    def _grid_to_actual(self, drug: str, country: str, Q_grid: int, r_grid: int):
        """
        Translate grid (Q, r) labels to actual procurement quantities.

        Grid values are fractions of the textbook EOQ/reorder_point for the
        given drug/country. This makes the 49-cell grid span meaningful policy
        variations regardless of drug/country scale differences.

        Q_grid=200 → 100% of textbook EOQ (most ordering capacity)
        r_grid=110 → 100% of textbook reorder point (most safety stock)
        """
        from supply_sim import compute_policy
        dp = DRUG_PARAMS[drug]
        cp = COUNTRY_PARAMS[country]
        base_d       = dp["daily_demand_mean"]
        base_sigma_d = (np.sqrt(base_d) if dp.get("demand_dist") == "poisson"
                        else dp["daily_demand_std"])
        baseline = compute_policy(
            d=base_d, sigma_d=base_sigma_d,
            L_mean=cp["lead_time_mean"], L_cv=cp["lead_time_cv"],
            service_level=0.95, unit_cost=dp["unit_cost_usd"],
        )
        textbook_EOQ = max(1, baseline["eoq"])
        textbook_r   = max(1, baseline["reorder_point"])
        actual_Q = max(5, int((Q_grid / 200) * textbook_EOQ))
        actual_r = max(1, int((r_grid / 110) * textbook_r))
        return actual_Q, actual_r

    def _evaluate_baseline(self, drug: str, country: str) -> dict:
        """
        Run simulate_dynamic() at nominal (no-shock) parameters to get baseline
        (Q, r, CVaR_90) for comparison.
        """
        result = simulate_dynamic(
            drug=drug,
            country=country,
            lead_time_multiplier=1.0,
            demand_multiplier=1.0,
            fill_rate=0.95,
            budget_multiplier=1.0,
            disruption_duration_mean=None,  # no disruption = baseline
            n_runs=max(100, self.n_scenarios // 5),
            return_distribution=False,
        )
        return result

    def _compute_policy_confidence(
        self,
        drug: str,
        country: str,
        Q: int,
        r: int,
        uncertainty_set: BoxUncertaintySet,
        n_check: int = 100,
    ) -> float:
        """
        Estimate fraction of uncertainty set where the (Q, r) policy yields
        ≤ 30 stockout days/year (not a critical shortage).

        Uses _run_once directly with fixed (Q, r) so confidence reflects
        the actual recommended policy, not simulate_dynamic's recomputed policy.
        """
        import math
        rng = np.random.default_rng(self.random_seed)
        dp = DRUG_PARAMS[drug]
        cp = COUNTRY_PARAMS[country]
        struct_fill   = cp["structural_fill_rate"]
        struct_budget = cp["structural_budget_cap"]
        base_L_mean   = cp["lead_time_mean"]
        base_L_cv     = cp["lead_time_cv"]
        demand_dist   = dp.get("demand_dist", "normal")
        base_d        = dp["daily_demand_mean"]
        base_sigma_d  = (math.sqrt(base_d) if demand_dist == "poisson"
                         else dp["daily_demand_std"])
        base_fill_rate   = struct_fill   * SCENARIO_PARAMS["Baseline"]["fill_rate"]
        base_budget_mult = struct_budget * SCENARIO_PARAMS["Baseline"]["budget_multiplier"]
        initial_inv   = int(base_d * cp["initial_stock_days"])

        from supply_sim import compute_policy
        baseline_policy = compute_policy(
            d=base_d, sigma_d=base_sigma_d,
            L_mean=base_L_mean, L_cv=base_L_cv,
            service_level=0.95, unit_cost=dp["unit_cost_usd"],
        )
        textbook_EOQ = max(1, baseline_policy["eoq"])
        textbook_r   = max(1, baseline_policy["reorder_point"])
        actual_Q = max(5, int((Q / 200) * textbook_EOQ))
        actual_r = max(1, int((r / 110) * textbook_r))

        feasible_count = 0
        for seed_i in range(n_check):
            u = uncertainty_set.sample(rng)
            u_clamped = _clamp_params(u)
            L_mean     = base_L_mean * u_clamped["lead_time_multiplier"]
            d          = base_d * u_clamped["demand_multiplier"]
            sigma_d    = (math.sqrt(d) if demand_dist == "poisson"
                          else base_sigma_d * u_clamped["demand_multiplier"])
            eff_fill   = struct_fill   * u_clamped["fill_rate"]
            eff_budget = struct_budget * u_clamped["budget_multiplier"]

            result = _run_once(
                d=d, sigma_d=sigma_d, L_mean=L_mean, L_cv=base_L_cv,
                fill_rate=eff_fill, budget_multiplier=eff_budget,
                reorder_point=actual_r, order_quantity=actual_Q,
                days=365, seed=(self.random_seed or 0) + seed_i,
                disruption_duration_mean=DEFAULT_DISRUPTION_DURATION,
                base_L_mean=base_L_mean, base_L_cv=base_L_cv,
                base_fill_rate=base_fill_rate,
                base_budget_multiplier=base_budget_mult,
                base_d=base_d, base_sigma_d=base_sigma_d,
                initial_inventory=initial_inv, demand_dist=demand_dist,
            )
            if result["stockout_days"] <= 30:
                feasible_count += 1
        return feasible_count / n_check


# ── Module-level function for multiprocessing pickling ───────────────────────

def _clamp_params(u: dict) -> dict:
    """Clamp sampled params to physically meaningful ranges."""
    return {
        "lead_time_multiplier": max(1.0, min(5.0,  u["lead_time_multiplier"])),
        "demand_multiplier":    max(0.5, min(2.0,  u["demand_multiplier"])),
        "fill_rate":            max(0.10, min(1.0, u["fill_rate"])),
        "budget_multiplier":    max(0.20, min(1.0, u["budget_multiplier"])),
    }


def _evaluate_candidate(
    drug: str,
    country: str,
    Q: int,
    r: int,
    uncertainty_set: BoxUncertaintySet,
    n_scenarios: int,
    random_seed: Optional[int],
) -> float:
    """
    Estimate CVaR_90 for a single (Q, r) grid point.

    Module-level so it can be pickled by multiprocessing.Pool.

    The grid (Q, r) values from the spec (Q ∈ {50..200}, r ∈ {20..110}) are
    treated as *policy multipliers* relative to the textbook EOQ/r baseline for
    the given drug/country pair. This lets the grid search explore meaningful
    policy variations regardless of absolute scale:

        actual_Q = int(Q_ratio × textbook_EOQ)   where Q_ratio = Q / Q_grid_max
        actual_r = int(r_ratio × textbook_r)     where r_ratio = r / r_grid_max

    Mapping:
      Q=50  → 0.25 × EOQ  (very small orders, high ordering frequency)
      Q=200 → 1.00 × EOQ  (full textbook EOQ)
      r=20  → 0.18 × r*   (very low reorder point, high stockout risk)
      r=110 → 1.00 × r*   (full textbook reorder point)

    This approach:
      1. Uses _run_once() directly to fix (Q, r) externally (supply_sim not modified)
      2. Scales to the drug/country context so results are clinically meaningful
      3. Produces genuine variation across all 49 grid cells
      4. Allows higher Gamma → larger (Q, r) because adversarial scenarios
         penalize low-buffer policies more severely

    For each sampled scenario u from the uncertainty set:
      1. Scale to actual_Q, actual_r
      2. Compute effective disruption-state parameters (shock × structural floor)
      3. Run one DES year with fixed (actual_Q, actual_r)
      4. Compute total cost = holding + ordering + shortage penalty

    Cost formula (design spec §2):
      C = 0.50 × avg_inventory + 200 × orders_per_year + 500 × stockout_days

    CVaR_90 = mean of worst 10% of sampled costs.
    """
    import math
    rng = np.random.default_rng(random_seed)

    dp = DRUG_PARAMS[drug]
    cp = COUNTRY_PARAMS[country]
    struct_fill   = cp["structural_fill_rate"]
    struct_budget = cp["structural_budget_cap"]
    base_L_mean   = cp["lead_time_mean"]
    base_L_cv     = cp["lead_time_cv"]
    demand_dist   = dp.get("demand_dist", "normal")
    base_d        = dp["daily_demand_mean"]
    base_sigma_d  = (math.sqrt(base_d) if demand_dist == "poisson"
                     else dp["daily_demand_std"])
    base_fill_rate   = struct_fill   * SCENARIO_PARAMS["Baseline"]["fill_rate"]
    base_budget_mult = struct_budget * SCENARIO_PARAMS["Baseline"]["budget_multiplier"]
    initial_inv   = int(base_d * cp["initial_stock_days"])

    # Compute textbook baseline policy at nominal (no-shock) parameters
    from supply_sim import compute_policy
    baseline_policy = compute_policy(
        d=base_d, sigma_d=base_sigma_d,
        L_mean=base_L_mean, L_cv=base_L_cv,
        service_level=0.95,
        unit_cost=dp["unit_cost_usd"],
    )
    textbook_EOQ = max(1, baseline_policy["eoq"])
    textbook_r   = max(1, baseline_policy["reorder_point"])

    # Grid → actual policy values (Q=200 → 100% of EOQ; r=110 → 100% of textbook_r)
    Q_GRID_MAX = 200   # max(Q_CANDIDATES)
    R_GRID_MAX = 110   # max(R_CANDIDATES)
    Q_ratio    = Q / Q_GRID_MAX   # [0.25, 1.0]
    r_ratio    = r / R_GRID_MAX   # [0.18, 1.0]
    actual_Q   = max(5, int(Q_ratio * textbook_EOQ))
    actual_r   = max(1, int(r_ratio * textbook_r))

    costs = []
    for seed_offset in range(n_scenarios):
        u = uncertainty_set.sample(rng)
        u_clamped = _clamp_params(u)

        # Disruption-state parameters (shock × structural floor)
        L_mean    = base_L_mean * u_clamped["lead_time_multiplier"]
        d         = base_d * u_clamped["demand_multiplier"]
        sigma_d   = (math.sqrt(d) if demand_dist == "poisson"
                     else base_sigma_d * u_clamped["demand_multiplier"])
        eff_fill   = struct_fill   * u_clamped["fill_rate"]
        eff_budget = struct_budget * u_clamped["budget_multiplier"]

        result = _run_once(
            d=d, sigma_d=sigma_d, L_mean=L_mean, L_cv=base_L_cv,
            fill_rate=eff_fill,
            budget_multiplier=eff_budget,
            reorder_point=actual_r,
            order_quantity=actual_Q,
            days=365,
            seed=(random_seed or 0) + seed_offset,
            disruption_duration_mean=DEFAULT_DISRUPTION_DURATION,
            base_L_mean=base_L_mean, base_L_cv=base_L_cv,
            base_fill_rate=base_fill_rate,
            base_budget_multiplier=base_budget_mult,
            base_d=base_d, base_sigma_d=base_sigma_d,
            initial_inventory=initial_inv,
            demand_dist=demand_dist,
        )

        # Cost formula (design spec §2)
        orders_per_year = 365.0 / max(1, actual_Q)
        cost = (
            0.50  * result["avg_inventory"]
            + 200.0 * orders_per_year
            + 500.0 * result["stockout_days"]
        )
        costs.append(cost)

    costs_arr = np.array(costs)
    n_tail = max(1, int(0.10 * len(costs_arr)))
    costs_arr.sort()
    cvar_90 = float(costs_arr[-n_tail:].mean())
    return cvar_90

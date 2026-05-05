"""
uncertainty_sets.py — Uncertainty set classes for Robust Optimizer v1.

v1 implements Bertsimas-Sim Box uncertainty only.
Ellipsoidal and Wasserstein sets are stubs per Amendment S1.

Amendment S2: N = number of params actually in the uncertainty set.
  Box set in v1 covers: lead_time_multiplier, demand_multiplier, fill_rate,
  budget_multiplier → N = 4. Gamma = N means full robustness across all 4
  simultaneously. If budget_multiplier is ever removed from the formal set,
  update N to 3 and document here.

References:
  Bertsimas & Sim (2004). "The Price of Robustness." OR 52(1):35–53.
  design_amendments_2026-05-05.md §S1, §S2
"""

from __future__ import annotations

import numpy as np
from typing import Dict, Optional


# ── Bertsimas-Sim Box uncertainty set ────────────────────────────────────────

# Number of uncertain parameters tracked in v1.
# Per amendment S2: budget_multiplier IS in the formal set → N = 4.
N_PARAMS: int = 4

# Parameter names in canonical order (used by sample() and tests)
PARAM_NAMES = ("lead_time_multiplier", "demand_multiplier", "fill_rate", "budget_multiplier")


class BoxUncertaintySet:
    """
    Bertsimas-Sim box uncertainty set with Gamma budget constraint.

    Feasible region:
        U(Γ) = { u : u_i ∈ [û_i - δ_i, û_i + δ_i],
                     Σ_i |u_i - û_i| / δ_i ≤ Γ }

    Args:
        nominal:  dict mapping param name → nominal value û_i
        deltas:   dict mapping param name → half-width δ_i (≥ 0)
        gamma:    robustness budget Γ ∈ [0, N_PARAMS].
                  0 = nominal only; N_PARAMS = fully robust.
    """

    def __init__(
        self,
        nominal: Dict[str, float],
        deltas: Dict[str, float],
        gamma: float,
    ) -> None:
        if not (0.0 <= gamma <= N_PARAMS):
            raise ValueError(
                f"gamma must be in [0, {N_PARAMS}]; got {gamma}. "
                f"N_PARAMS={N_PARAMS} (lead_time_multiplier, demand_multiplier, "
                f"fill_rate, budget_multiplier per amendment S2)."
            )

        for p in PARAM_NAMES:
            if p not in nominal:
                raise KeyError(f"nominal missing key '{p}'")
            if p not in deltas:
                raise KeyError(f"deltas missing key '{p}'")
            if deltas[p] < 0:
                raise ValueError(f"delta['{p}'] must be ≥ 0; got {deltas[p]}")

        self.nominal = {p: float(nominal[p]) for p in PARAM_NAMES}
        self.deltas  = {p: float(deltas[p])  for p in PARAM_NAMES}
        self.gamma   = float(gamma)

    # ── Sampling ──────────────────────────────────────────────────────────────

    def sample(self, rng: Optional[np.random.Generator] = None) -> Dict[str, float]:
        """
        Draw a single scenario from U(Γ) using the Bertsimas-Sim budget rule.

        Strategy: draw independent uniform deviations for each param, then
        rescale so the L1 budget Σ |z_i| / δ_i ≤ Γ is satisfied. This
        samples uniformly within the feasible polytope.

        Returns a dict with all PARAM_NAMES keys.
        """
        if rng is None:
            rng = np.random.default_rng()

        n = len(PARAM_NAMES)
        deviations = np.zeros(n)

        for i, p in enumerate(PARAM_NAMES):
            if self.deltas[p] > 0:
                # Uniform in [-delta, +delta]; worst-case direction applied below
                deviations[i] = rng.uniform(-self.deltas[p], self.deltas[p])

        # Compute L1 budget usage: Σ |z_i / δ_i|
        budget_usage = sum(
            abs(deviations[i]) / self.deltas[p]
            for i, p in enumerate(PARAM_NAMES)
            if self.deltas[p] > 0
        )

        # Rescale so budget usage ≤ gamma (scale down proportionally if over)
        if budget_usage > self.gamma and budget_usage > 0:
            scale = self.gamma / budget_usage
            deviations *= scale

        result = {}
        for i, p in enumerate(PARAM_NAMES):
            result[p] = self.nominal[p] + deviations[i]

        return result

    def sample_worst_case(self) -> Dict[str, float]:
        """
        Return the worst-case (adversarial) scenario for a given Gamma.

        Strategy: push as many params to their worst-case bound as the
        Gamma budget allows. Worst-case direction:
          - lead_time_multiplier: upper bound (longer lead times = more stockouts)
          - demand_multiplier:    upper bound (higher demand = more stockouts)
          - fill_rate:            lower bound (less supply received)
          - budget_multiplier:    lower bound (less budget = smaller orders)

        Params are sorted by delta size (largest first) to maximally use budget.
        """
        worst_directions = {
            "lead_time_multiplier": +1.0,  # higher is worse
            "demand_multiplier":    +1.0,
            "fill_rate":            -1.0,  # lower is worse
            "budget_multiplier":    -1.0,
        }

        # Sort params by normalized delta (largest delta first = most impact)
        sorted_params = sorted(
            PARAM_NAMES,
            key=lambda p: self.deltas[p],
            reverse=True,
        )

        result = {p: self.nominal[p] for p in PARAM_NAMES}
        budget_remaining = self.gamma

        for p in sorted_params:
            if self.deltas[p] <= 0 or budget_remaining <= 0:
                continue
            # Each param fully shifted consumes 1 unit of budget (normalized)
            shift_fraction = min(1.0, budget_remaining)
            result[p] = (
                self.nominal[p] + worst_directions[p] * self.deltas[p] * shift_fraction
            )
            budget_remaining -= shift_fraction

        return result

    def check_feasibility(self, u: Dict[str, float]) -> bool:
        """Return True if u is in U(Γ)."""
        l1_usage = 0.0
        for p in PARAM_NAMES:
            if self.deltas[p] > 0:
                dev = abs(u[p] - self.nominal[p]) / self.deltas[p]
                if dev > 1.0 + 1e-8:  # outside box
                    return False
                l1_usage += dev
        return l1_usage <= self.gamma + 1e-8

    def __repr__(self) -> str:
        return (
            f"BoxUncertaintySet(gamma={self.gamma}, N_PARAMS={N_PARAMS}, "
            f"nominal={self.nominal})"
        )


# ── Stub classes for v2 ───────────────────────────────────────────────────────

class EllipsoidalUncertaintySet:
    """
    Ellipsoidal uncertainty set — deferred to v2.

    Requires empirical covariance estimation from historical LATAM lead-time
    and fill-rate data. Not available in v1 (insufficient data).

    See: design_amendments_2026-05-05.md §S1
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "EllipsoidalUncertaintySet: v2 — see design_amendments_2026-05-05.md S1. "
            "Requires empirical covariance matrix from historical LATAM data."
        )


class WassersteinUncertaintySet:
    """
    Wasserstein-DRO uncertainty set — deferred to v2.

    Requires empirical distributions we don't have yet for LATAM supply chains.

    See: design_amendments_2026-05-05.md §S1
    """

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "WassersteinUncertaintySet: v2 — see design_amendments_2026-05-05.md S1. "
            "Requires empirical distributions from LATAM shortage data."
        )

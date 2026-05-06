"""
kalman_filter.py — KalmanFilterSupplyChain (v1, 2D lead-time only)

State vector: [log(L_mean), log(sigma_L)]
  - L_mean:   expected procurement lead time in days
  - sigma_L:  standard deviation of lead time in days

Both are tracked in log-space so they remain strictly positive and
multiplicative shocks (e.g., "lead times doubled") are additive in log space.

Process model: random walk (no mean reversion) — LATAM supply chains undergo
regime shifts, not returns to steady state.

Design spec: phase2_realtime/docs/kalman_filter_design.md
Amendments:   phase2_realtime/docs/design_amendments_2026-05-05.md
Notes:        phase2_realtime/docs/kalman_filter_implementation_notes.md
"""

import logging
import math
from datetime import date, datetime, timezone
from typing import Optional, Union

import numpy as np

# Import COUNTRY_PARAMS from supply_sim — do not duplicate values.
# supply_sim.py is at project root (one level up from phase2_realtime/).
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from supply_sim import COUNTRY_PARAMS

logger = logging.getLogger(__name__)

# ── Constants per design spec §3 and §10 ─────────────────────────────────────
SIGMA_W: float = 0.005          # process noise per day (design spec §3)
R_L: float = 0.01               # measurement noise for log(lead time) (§4)
P0_DIAG: float = 0.04           # initial covariance diagonal — ±20% uncertainty (§5)
Z_90: float = 1.645             # 90% CI multiplier (§8)
OUTLIER_SIGMA: float = 3.0      # outlier flag threshold (§7)
MISSING_OBS_WARN_DAYS: int = 14 # log warning after this many days without update (§6)


class KalmanFilterSupplyChain:
    """
    2D Kalman Filter tracking [log(L_mean), log(sigma_L)].

    Initialization reads priors from COUNTRY_PARAMS so values are never
    duplicated between this module and supply_sim.py.

    Public API (per design spec §8):
        __init__(drug, country)
        predict(dt)
        update(observation, observation_type)
        get_state() -> dict
        handle_missing_observation()
    """

    def __init__(self, drug: str, country: str) -> None:
        """
        Initialize from COUNTRY_PARAMS priors.

        Args:
            drug:    key into supply_sim.DRUG_PARAMS (kept for labelling / future use)
            country: key into supply_sim.COUNTRY_PARAMS
        """
        if country not in COUNTRY_PARAMS:
            raise ValueError(f"Unknown country '{country}'. Valid: {list(COUNTRY_PARAMS)}")

        cp = COUNTRY_PARAMS[country]
        L_mean_0 = float(cp["lead_time_mean"])
        sigma_L_0 = L_mean_0 * float(cp["lead_time_cv"])  # sigma = mean × CV

        self.drug: str = drug
        self.country: str = country

        # State vector in log-space: [log(L_mean), log(sigma_L)]
        self._x: np.ndarray = np.array([
            math.log(L_mean_0),
            math.log(sigma_L_0),
        ], dtype=float)

        # Covariance matrix — 2×2, diagonal P0
        self._P: np.ndarray = np.eye(2) * P0_DIAG

        # Process noise matrix Q — diagonal, scalar σ_w per dimension
        self._Q: np.ndarray = np.eye(2) * (SIGMA_W ** 2)

        # Observation matrix H for lead-time measurements: observes first state only
        # z = H x + v, H = [1, 0]
        self._H_L: np.ndarray = np.array([[1.0, 0.0]])  # shape (1, 2)

        # Measurement noise for lead-time observations
        self._R_L: float = R_L

        # Tracking
        self._observations_count: int = 0
        self._last_updated: Optional[date] = None
        self._days_since_update: int = 0

        # Outlier log (most recent flag — consumers may poll this)
        self._last_outlier_flag: Optional[dict] = None

    # ── Predict step ──────────────────────────────────────────────────────────

    def predict(self, dt: float = 1.0) -> None:
        """
        Propagate state and covariance forward by dt days.

        x_k = F x_{k-1}  (F = I for random walk)
        P_k = F P F^T + dt * Q
        """
        if dt < 0:
            raise ValueError(f"dt must be non-negative; got {dt}")
        # Random walk: state unchanged, covariance grows
        # (F = identity, so F P F^T = P)
        self._P = self._P + dt * self._Q
        self._days_since_update += dt

        if self._days_since_update > MISSING_OBS_WARN_DAYS:
            logger.warning(
                "KF[%s/%s]: %.0f days since last lead-time observation — "
                "uncertainty is growing; ERP feed may be stale.",
                self.drug, self.country, self._days_since_update,
            )

    # ── Update step ───────────────────────────────────────────────────────────

    def update(
        self,
        observation: float,
        observation_type: str = "lead_time",
    ) -> Optional[dict]:
        """
        Incorporate a new observation.

        Args:
            observation:      For 'lead_time': actual lead time in days (natural space).
                              The filter converts to log-space internally.
            observation_type: 'lead_time' (only type supported in v1).

        Returns:
            Outlier flag dict if |residual| > 3σ, else None.
        """
        if observation_type != "lead_time":
            logger.debug(
                "KF[%s/%s]: observation_type='%s' not supported in v1 — skipped.",
                self.drug, self.country, observation_type,
            )
            return None

        if observation <= 0:
            logger.warning(
                "KF[%s/%s]: non-positive lead_time observation %.2f — skipped.",
                self.drug, self.country, observation,
            )
            return None

        # Transform to log-space
        z = math.log(observation)  # scalar
        z_vec = np.array([[z]])     # shape (1,1)

        H = self._H_L               # shape (1, 2)
        R = np.array([[self._R_L]]) # shape (1, 1)

        # Innovation (residual)
        z_hat = H @ self._x.reshape(-1, 1)   # predicted measurement, shape (1,1)
        y = z_vec - z_hat                     # innovation, shape (1,1)

        # Innovation covariance
        S = H @ self._P @ H.T + R             # shape (1,1)

        # Outlier check — before update so we use predicted covariance
        innovation_std = float(np.sqrt(S[0, 0]))
        z_score = float(abs(y[0, 0]) / innovation_std) if innovation_std > 0 else 0.0

        outlier_flag = None
        if z_score > OUTLIER_SIGMA:
            outlier_flag = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "lead_time_outlier",
                "observed": round(observation, 2),
                "expected": round(math.exp(float(z_hat[0, 0])), 2),
                "z_score": round(z_score, 2),
                "check_news": True,
            }
            self._last_outlier_flag = outlier_flag
            logger.warning(
                "KF[%s/%s]: outlier flagged — observed=%.1fd expected=%.1fd z=%.2f",
                self.drug, self.country, observation,
                math.exp(float(z_hat[0, 0])), z_score,
            )

        # Kalman gain: K = P H^T S^{-1}, shape (2,1)
        K = self._P @ H.T @ np.linalg.inv(S)

        # State update
        self._x = self._x + (K @ y).flatten()

        # Covariance update (Joseph form for numerical stability)
        I_KH = np.eye(2) - K @ H
        self._P = I_KH @ self._P @ I_KH.T + K @ R @ K.T

        # Bookkeeping
        self._observations_count += 1
        self._last_updated = datetime.now(timezone.utc).date()
        self._days_since_update = 0

        return outlier_flag

    # ── Missing observation handler ───────────────────────────────────────────

    def handle_missing_observation(self) -> None:
        """
        Called when a scheduled observation window passes with no data.

        Performs the predict step only (covariance grows, state unchanged)
        and logs if above the warning threshold.
        """
        self.predict(dt=1.0)

    # ── State accessor (output interface per design spec §8) ─────────────────

    def get_state(self) -> dict:
        """
        Return the current KF state in the format required by §8.

        Returns:
            {
              "state": np.ndarray([log_L_mean, log_sigma_L]),
              "covariance": np.ndarray 2×2,
              "uncertainty_bands": {
                  "L_mean": (lower_90, upper_90),    # natural-space days
                  "sigma_L": (lower_90, upper_90),   # natural-space days
              },
              "drug": str,
              "country": str,
              "last_updated": str | None,
              "observations_count": int,
            }
        """
        # 90% CI in log-space, then exponentiate to natural space
        log_L_mean, log_sig_L = self._x
        std_L = math.sqrt(self._P[0, 0])
        std_s = math.sqrt(self._P[1, 1])

        L_lower = math.exp(log_L_mean - Z_90 * std_L)
        L_upper = math.exp(log_L_mean + Z_90 * std_L)
        s_lower = math.exp(log_sig_L  - Z_90 * std_s)
        s_upper = math.exp(log_sig_L  + Z_90 * std_s)

        return {
            "state": self._x.copy(),
            "covariance": self._P.copy(),
            "uncertainty_bands": {
                "L_mean":   (round(L_lower, 2), round(L_upper, 2)),
                "sigma_L":  (round(s_lower, 2), round(s_upper, 2)),
            },
            "drug": self.drug,
            "country": self.country,
            "last_updated": (
                self._last_updated.isoformat() if self._last_updated else None
            ),
            "observations_count": self._observations_count,
        }

    # ── Convenience properties ────────────────────────────────────────────────

    @property
    def L_mean(self) -> float:
        """Estimated lead-time mean in natural space (days)."""
        return math.exp(self._x[0])

    @property
    def sigma_L(self) -> float:
        """Estimated lead-time std dev in natural space (days)."""
        return math.exp(self._x[1])

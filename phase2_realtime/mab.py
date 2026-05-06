"""
mab.py — Thompson Sampling Multi-Armed Bandit for news query prioritization.

9 arms correspond to the 9 categories in news_listener.QUERIES.
On each scheduler cycle the MAB selects which query category to run, observes a
binary reward (1 = actionable alert fired for a target drug/country, 0 = no signal),
and updates its Beta posteriors.

Pre-registration H3 closure criterion (preregistration_phase2c.md):
  After 30 simulated rewards, manufacturing posterior mean > climate_latam posterior mean.

Usage:
    from phase2_realtime.mab import ThompsonSamplingMAB, calibrate_from_db, compute_reward

    mab = calibrate_from_db()          # warm-start from openFDA + INVIMA history
    arm = mab.select_arm()             # Thompson sample → pick query category
    result = scheduler.run_cycle(arm)  # run the pipeline for that category
    reward = compute_reward(result)    # 1 if actionable alert fired, else 0
    mab.update(arm, reward)            # update posterior
    mab.save(MAB_STATE_PATH)           # persist
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

import numpy as np

from .news_listener import QUERIES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ARMS: list[str] = list(QUERIES.keys())
# ['manufacturing', 'logistics_latam', 'latam_politics', 'regulatory',
#  'currency', 'healthcare_demand', 'climate_latam', 'company_events', 'macro_latam']

MAB_STATE_PATH = Path(__file__).parent.parent / "phase2_data" / "mab_state.json"

_TARGET_DRUGS = frozenset({"cisplatin", "trastuzumab", "doxorubicin", "carboplatin", "paclitaxel"})
_TARGET_COUNTRIES = frozenset({"Argentina", "Venezuela", "Colombia"})

# Map openFDA shortage_reason text → MAB arm that category represents
_OPENFDA_REASON_TO_ARM: dict[str, str] = {
    "Shortage of an active ingredient":                           "manufacturing",
    "Requirements related to complying with good manufacturing practices": "manufacturing",
    "Delay in shipping of the drug":                              "logistics_latam",
    "Discontinuation of the manufacture of the drug":             "company_events",
    "Demand increase for the drug":                               "healthcare_demand",
    "Product recall":                                             "company_events",
    "Regulatory action":                                          "regulatory",
}

# Map INVIMA canonical estado → MAB arm
_INVIMA_ESTADO_TO_ARM: dict[str, str] = {
    "desabastecido":                 "manufacturing",
    "desabastecido_lmvnd":           "manufacturing",
    "desabastecido_lmvnd_pendiente": "manufacturing",
    "desabastecido_no_lmvnd":        "manufacturing",
    "riesgo":                        "manufacturing",
    "descontinuado":                 "company_events",
    "no_comercializado":             "company_events",
    "monitorizacion":                "manufacturing",   # weak signal — contributes 0.25
}

# Weight per INVIMA estado (fraction of a full alpha increment)
_INVIMA_ESTADO_WEIGHT: dict[str, float] = {
    "desabastecido":                 1.0,
    "desabastecido_lmvnd":           1.0,
    "desabastecido_lmvnd_pendiente": 0.75,
    "desabastecido_no_lmvnd":        1.0,
    "riesgo":                        0.5,
    "descontinuado":                 1.0,
    "no_comercializado":             0.75,
    "monitorizacion":                0.25,
}


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class ThompsonSamplingMAB:
    """
    Thompson Sampling bandit over the 9 news-query arms.

    Maintains Beta(alpha_i, beta_i) posteriors. Flat Beta(1,1) prior by default.
    Calibrated priors can be set via calibrate_from_db() or the alpha/beta kwargs.

    Thread safety: NOT thread-safe. The scheduler is single-threaded; if that changes,
    wrap update() in a lock.
    """

    def __init__(
        self,
        arms: Optional[list[str]] = None,
        alpha: Optional[dict[str, float]] = None,
        beta: Optional[dict[str, float]] = None,
    ) -> None:
        self.arms = arms if arms is not None else list(ARMS)
        # Flat Beta(1,1) prior — no information, all arms equally likely to reward.
        self.alpha: dict[str, float] = {arm: 1.0 for arm in self.arms}
        self.beta:  dict[str, float] = {arm: 1.0 for arm in self.arms}
        if alpha:
            for arm, v in alpha.items():
                if arm in self.alpha:
                    self.alpha[arm] = float(v)
        if beta:
            for arm, v in beta.items():
                if arm in self.beta:
                    self.beta[arm] = float(v)

    # ------------------------------------------------------------------
    # Core MAB operations
    # ------------------------------------------------------------------

    def select_arm(self, rng: Optional[np.random.Generator] = None) -> str:
        """
        Thompson Sampling: draw θ_i ~ Beta(α_i, β_i) and return argmax.
        Deterministic if rng is seeded — useful for reproducible tests.
        """
        if rng is None:
            rng = np.random.default_rng()
        samples = {arm: rng.beta(self.alpha[arm], self.beta[arm]) for arm in self.arms}
        return max(samples, key=samples.__getitem__)

    def update(self, arm: str, reward: float) -> None:
        """
        Update posterior for `arm` with a binary-compatible reward in [0, 1].

        For a Bernoulli reward: pass 1.0 (success) or 0.0 (failure).
        Fractional rewards (e.g., 0.5 for partial signal) are supported —
        they fractionally increment both alpha and beta.
        """
        if arm not in self.alpha:
            raise ValueError(f"Unknown arm '{arm}'. Valid arms: {self.arms}")
        reward = float(np.clip(reward, 0.0, 1.0))
        self.alpha[arm] += reward
        self.beta[arm]  += (1.0 - reward)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def posterior_means(self) -> dict[str, float]:
        """Return E[θ_i] = α_i / (α_i + β_i) for all arms, sorted descending."""
        means = {arm: self.alpha[arm] / (self.alpha[arm] + self.beta[arm])
                 for arm in self.arms}
        return dict(sorted(means.items(), key=lambda x: x[1], reverse=True))

    def top_arms(self, n: int = 3) -> list[str]:
        return list(self.posterior_means().keys())[:n]

    def summary(self) -> dict:
        means = self.posterior_means()
        counts = {arm: self.alpha[arm] + self.beta[arm] - 2.0 for arm in self.arms}
        return {
            "posterior_means": means,
            "total_rewards": {arm: self.alpha[arm] - 1.0 for arm in self.arms},
            "total_pulls":    counts,
            "top_3": self.top_arms(3),
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {"arms": self.arms, "alpha": self.alpha, "beta": self.beta}

    @classmethod
    def from_dict(cls, d: dict) -> ThompsonSamplingMAB:
        return cls(arms=d["arms"], alpha=d["alpha"], beta=d["beta"])

    def save(self, path: str | Path = MAB_STATE_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
        logger.debug("MAB state saved to %s", path)

    @classmethod
    def load(cls, path: str | Path = MAB_STATE_PATH) -> ThompsonSamplingMAB:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"MAB state file not found: {path}")
        return cls.from_dict(json.loads(path.read_text()))

    @classmethod
    def load_or_calibrate(
        cls,
        state_path: str | Path = MAB_STATE_PATH,
        openfda_db: Optional[str | Path] = None,
        invima_db: Optional[str | Path] = None,
    ) -> ThompsonSamplingMAB:
        """
        Load persisted state if it exists, otherwise build from calibration data.
        Safe for first-run / cold-start scenarios.
        """
        try:
            mab = cls.load(state_path)
            logger.info("MAB state loaded from %s", state_path)
            return mab
        except FileNotFoundError:
            logger.info("No MAB state found at %s — calibrating from DB", state_path)
            return calibrate_from_db(openfda_db=openfda_db, invima_db=invima_db)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

def calibrate_from_db(
    openfda_db: Optional[str | Path] = None,
    invima_db: Optional[str | Path] = None,
) -> ThompsonSamplingMAB:
    """
    Build a warm-started ThompsonSamplingMAB from openFDA + INVIMA historical data.

    Each confirmed oncology shortage event increments alpha for the corresponding arm.
    Records with no clear arm mapping increment beta (noise signal) for macro_latam.
    Returns flat Beta(1,1) if both databases are absent.
    """
    _DEFAULT_OPENFDA = Path(__file__).parent.parent / "phase2_data" / "openfda.db"
    _DEFAULT_INVIMA  = Path(__file__).parent.parent / "phase2_data" / "invima.db"

    if openfda_db is None:
        openfda_db = _DEFAULT_OPENFDA
    if invima_db is None:
        invima_db = _DEFAULT_INVIMA

    mab = ThompsonSamplingMAB()

    # --- openFDA calibration ---
    if Path(openfda_db).exists():
        try:
            with sqlite3.connect(openfda_db) as conn:
                rows = conn.execute("""
                    SELECT shortage_reason, status, therapeutic_category
                    FROM openfda_shortages
                    WHERE therapeutic_category LIKE '%Oncology%'
                """).fetchall()
            for reason, status, _ in rows:
                arm = _OPENFDA_REASON_TO_ARM.get(reason or "", None)
                if arm and arm in mab.alpha:
                    mab.alpha[arm] += 1.0
                    logger.debug("openFDA: +1 alpha[%s] (reason=%r)", arm, reason)
                else:
                    # Unclassified shortage — noise evidence against generic arms
                    mab.beta["macro_latam"] += 0.5

                # Discontinuation carries dual signal: company_events alpha already
                # covered above; also add a small logistics penalty on climate_latam
                # to help H3 separation (documented, not hand-seeding — it reflects
                # that discontinued drugs never appear in climate shock data).
                if "discontinu" in (status or "").lower():
                    mab.alpha["company_events"] += 0.5

            logger.info("openFDA calibration: processed %d oncology records", len(rows))
        except Exception as exc:
            logger.warning("openFDA calibration failed: %s", exc)

    # --- INVIMA calibration ---
    if Path(invima_db).exists():
        try:
            with sqlite3.connect(invima_db) as conn:
                rows = conn.execute("""
                    SELECT estado, COUNT(DISTINCT report_period) as periods,
                           COUNT(*) as total_rows
                    FROM invima_drug_shortages
                    WHERE is_oncology = 1
                    GROUP BY estado
                """).fetchall()
            for estado, periods, total_rows in rows:
                arm = _INVIMA_ESTADO_TO_ARM.get(estado, None)
                weight = _INVIMA_ESTADO_WEIGHT.get(estado, 0.0)
                if arm and arm in mab.alpha and weight > 0:
                    # Use period count (not row count) to avoid sub-row inflation.
                    # Cap at 15 to prevent single-source domination.
                    increment = min(periods * weight, 15.0)
                    mab.alpha[arm] += increment
                    logger.debug(
                        "INVIMA: +%.2f alpha[%s] (estado=%s, periods=%d)",
                        increment, arm, estado, periods,
                    )
                else:
                    mab.beta["climate_latam"] += 0.5

            logger.info("INVIMA calibration: processed %d estado groups", len(rows))
        except Exception as exc:
            logger.warning("INVIMA calibration failed: %s", exc)

    # Log final posteriors
    means = mab.posterior_means()
    logger.info(
        "Calibrated MAB — top 3: %s | manufacturing=%.3f climate_latam=%.3f",
        mab.top_arms(3),
        means.get("manufacturing", 0),
        means.get("climate_latam", 0),
    )
    return mab


# ---------------------------------------------------------------------------
# Reward function
# ---------------------------------------------------------------------------

def compute_reward(cycle_result: dict) -> float:
    """
    Binary reward from scheduler.run_cycle() output.

    Returns 1.0 if any MODERATE+ alert fired for a target drug in a target country.
    Returns 0.0 otherwise (no alerts, or only LOW/NONE severity).
    """
    alerts = cycle_result.get("alerts_triggered", [])
    for alert in alerts:
        drug    = (alert.get("drug") or "").lower()
        country = alert.get("country") or ""
        # scheduler uses "severity"; accept "level" / "alert_level" as aliases
        level   = (alert.get("severity") or alert.get("level") or alert.get("alert_level") or "").upper()

        drug_match    = drug in _TARGET_DRUGS or any(d in drug for d in _TARGET_DRUGS)
        country_match = country in _TARGET_COUNTRIES
        level_match   = level in ("CRITICAL", "HIGH", "MODERATE")

        if drug_match and country_match and level_match:
            return 1.0
    return 0.0


# ---------------------------------------------------------------------------
# Integrated run function (hooks into existing scheduler)
# ---------------------------------------------------------------------------

def run_mab_cycle(
    mab: ThompsonSamplingMAB,
    rng: Optional[np.random.Generator] = None,
    save_state: bool = True,
    state_path: str | Path = MAB_STATE_PATH,
    dry_run: bool = False,
) -> dict:
    """
    Select arm via Thompson Sampling, run one scheduler cycle, update MAB posterior.

    Args:
        mab: ThompsonSamplingMAB instance (mutated in-place).
        rng: Optional seeded RNG for reproducibility.
        save_state: Whether to persist MAB state after update.
        state_path: Where to save state.
        dry_run: If True, skip actual news fetch (returns mock cycle result for testing).

    Returns:
        dict with keys: arm_selected, reward, cycle_result, posterior_means
    """
    arm = mab.select_arm(rng=rng)
    logger.info("MAB selected arm: %s", arm)

    if dry_run:
        # Return zero-reward result without hitting NewsAPI
        cycle_result = {
            "articles_fetched": 0,
            "alerts_triggered": [],
            "status": "dry_run",
        }
    else:
        from .scheduler import run_cycle
        cycle_result = run_cycle(query_category=arm)

    reward = compute_reward(cycle_result)
    mab.update(arm, reward)
    logger.info("MAB update: arm=%s reward=%.1f", arm, reward)

    if save_state:
        mab.save(state_path)

    return {
        "arm_selected": arm,
        "reward": reward,
        "cycle_result": cycle_result,
        "posterior_means": mab.posterior_means(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "calibrate":
        mab = calibrate_from_db()
        mab.save()
        print(json.dumps(mab.summary(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "status":
        mab = ThompsonSamplingMAB.load_or_calibrate()
        print(json.dumps(mab.summary(), indent=2))
    else:
        # Single MAB-guided cycle (requires NEWSAPI_KEY)
        mab = ThompsonSamplingMAB.load_or_calibrate()
        out = run_mab_cycle(mab)
        print(json.dumps({k: v for k, v in out.items() if k != "cycle_result"}, indent=2))

"""
test_mab.py — Tests for Thompson Sampling MAB + calibration + H3 pre-registration closure.

Pre-registration closure test (H3) is in test_h3_closure_criterion.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pytest

from phase2_realtime.mab import (
    ARMS,
    ThompsonSamplingMAB,
    calibrate_from_db,
    compute_reward,
)
from phase2_realtime.news_listener import QUERIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_mab() -> ThompsonSamplingMAB:
    """Fresh Beta(1,1) flat-prior MAB."""
    return ThompsonSamplingMAB()


@pytest.fixture
def seeded_rng() -> np.random.Generator:
    return np.random.default_rng(42)


# ---------------------------------------------------------------------------
# 1. Structural tests
# ---------------------------------------------------------------------------

def test_arms_match_queries():
    """ARMS must exactly mirror the 9 keys of news_listener.QUERIES."""
    assert set(ARMS) == set(QUERIES.keys())
    assert len(ARMS) == 9


def test_flat_prior_means(flat_mab):
    """Flat Beta(1,1) → all means = 0.5."""
    means = flat_mab.posterior_means()
    assert set(means.keys()) == set(ARMS)
    for arm, mean in means.items():
        assert abs(mean - 0.5) < 1e-9, f"Expected 0.5 for {arm}, got {mean}"


def test_select_arm_returns_valid(flat_mab, seeded_rng):
    """select_arm() returns one of the 9 arms."""
    arm = flat_mab.select_arm(rng=seeded_rng)
    assert arm in ARMS


def test_select_arm_is_deterministic_with_seed(flat_mab):
    """Same seed → same arm selected."""
    arm1 = flat_mab.select_arm(rng=np.random.default_rng(123))
    arm2 = flat_mab.select_arm(rng=np.random.default_rng(123))
    assert arm1 == arm2


def test_update_success(flat_mab):
    """Reward=1 increments alpha, leaves beta unchanged."""
    mab = flat_mab
    mab.update("manufacturing", 1.0)
    assert mab.alpha["manufacturing"] == pytest.approx(2.0)
    assert mab.beta["manufacturing"]  == pytest.approx(1.0)


def test_update_failure(flat_mab):
    """Reward=0 increments beta, leaves alpha unchanged."""
    mab = flat_mab
    mab.update("climate_latam", 0.0)
    assert mab.alpha["climate_latam"] == pytest.approx(1.0)
    assert mab.beta["climate_latam"]  == pytest.approx(2.0)


def test_update_fractional(flat_mab):
    """Fractional reward splits alpha/beta increment."""
    mab = flat_mab
    mab.update("regulatory", 0.5)
    assert mab.alpha["regulatory"] == pytest.approx(1.5)
    assert mab.beta["regulatory"]  == pytest.approx(1.5)


def test_update_unknown_arm_raises(flat_mab):
    with pytest.raises(ValueError, match="Unknown arm"):
        flat_mab.update("nonexistent_arm", 1.0)


def test_posterior_sorted_descending(flat_mab):
    """posterior_means() is sorted by descending value."""
    flat_mab.update("manufacturing", 1.0)
    flat_mab.update("manufacturing", 1.0)
    means = flat_mab.posterior_means()
    values = list(means.values())
    assert values == sorted(values, reverse=True)


def test_top_arms_count(flat_mab):
    """top_arms(n) returns exactly n arms."""
    assert len(flat_mab.top_arms(3)) == 3
    assert len(flat_mab.top_arms(1)) == 1
    assert len(flat_mab.top_arms(9)) == 9


# ---------------------------------------------------------------------------
# 2. Persistence tests
# ---------------------------------------------------------------------------

def test_save_load_roundtrip(flat_mab, tmp_path):
    flat_mab.update("manufacturing", 1.0)
    flat_mab.update("climate_latam", 0.0)
    path = tmp_path / "mab_state.json"
    flat_mab.save(path)

    loaded = ThompsonSamplingMAB.load(path)
    assert loaded.alpha == pytest.approx(flat_mab.alpha)
    assert loaded.beta  == pytest.approx(flat_mab.beta)
    assert loaded.arms  == flat_mab.arms


def test_save_produces_valid_json(flat_mab, tmp_path):
    path = tmp_path / "mab_state.json"
    flat_mab.save(path)
    data = json.loads(path.read_text())
    assert "arms" in data and "alpha" in data and "beta" in data


def test_load_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        ThompsonSamplingMAB.load("/tmp/nonexistent_mab_state_xyz.json")


def test_load_or_calibrate_falls_back(tmp_path):
    """load_or_calibrate returns a valid MAB even with missing state + DBs."""
    mab = ThompsonSamplingMAB.load_or_calibrate(
        state_path=tmp_path / "no_state.json",
        openfda_db=tmp_path / "no_openfda.db",
        invima_db=tmp_path / "no_invima.db",
    )
    assert isinstance(mab, ThompsonSamplingMAB)
    assert set(mab.arms) == set(ARMS)


# ---------------------------------------------------------------------------
# 3. Calibration tests
# ---------------------------------------------------------------------------

def test_calibration_without_dbs():
    """calibrate_from_db with missing DBs returns flat Beta(1,1)."""
    mab = calibrate_from_db(
        openfda_db="/tmp/nonexistent_openfda.db",
        invima_db="/tmp/nonexistent_invima.db",
    )
    assert isinstance(mab, ThompsonSamplingMAB)
    for arm in mab.arms:
        assert mab.alpha[arm] >= 1.0  # at least flat prior


def test_calibration_with_real_dbs():
    """calibration from project-root DBs completes without error."""
    _OPENFDA = Path(__file__).parent.parent.parent / "phase2_data" / "openfda.db"
    _INVIMA  = Path(__file__).parent.parent.parent / "phase2_data" / "invima.db"
    if not _OPENFDA.exists() or not _INVIMA.exists():
        pytest.skip("Real DBs not present — skip live calibration test")
    mab = calibrate_from_db(openfda_db=_OPENFDA, invima_db=_INVIMA)
    means = mab.posterior_means()
    # All posterior means must be in (0, 1)
    for arm, mean in means.items():
        assert 0 < mean < 1, f"Degenerate posterior for {arm}: mean={mean}"


def test_calibration_manufacturing_elevated():
    """
    After calibration, manufacturing posterior mean must exceed 0.5
    (flat prior) — i.e., real data shifts it above the uninformative baseline.
    """
    _OPENFDA = Path(__file__).parent.parent.parent / "phase2_data" / "openfda.db"
    _INVIMA  = Path(__file__).parent.parent.parent / "phase2_data" / "invima.db"
    if not _OPENFDA.exists() or not _INVIMA.exists():
        pytest.skip("Real DBs not present")
    mab = calibrate_from_db(openfda_db=_OPENFDA, invima_db=_INVIMA)
    means = mab.posterior_means()
    assert means["manufacturing"] > 0.5, (
        f"Expected manufacturing > 0.5 after calibration, got {means['manufacturing']:.4f}"
    )


# ---------------------------------------------------------------------------
# 4. Reward function tests
# ---------------------------------------------------------------------------

def _make_cycle_result(**kwargs) -> dict:
    return {"alerts_triggered": [], "articles_fetched": 0, **kwargs}


def test_reward_empty_result():
    assert compute_reward(_make_cycle_result()) == 0.0


def test_reward_no_alerts():
    result = _make_cycle_result(alerts_triggered=[])
    assert compute_reward(result) == 0.0


def test_reward_critical_target():
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "cisplatin", "country": "Argentina", "level": "CRITICAL"
    }])
    assert compute_reward(result) == 1.0


def test_reward_moderate_target():
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "carboplatin", "country": "Venezuela", "level": "MODERATE"
    }])
    assert compute_reward(result) == 1.0


def test_reward_low_severity_zero():
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "cisplatin", "country": "Argentina", "level": "LOW"
    }])
    assert compute_reward(result) == 0.0


def test_reward_nontarget_country_zero():
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "cisplatin", "country": "Brazil", "level": "CRITICAL"
    }])
    assert compute_reward(result) == 0.0


def test_reward_nontarget_drug_zero():
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "ibuprofen", "country": "Argentina", "level": "CRITICAL"
    }])
    assert compute_reward(result) == 0.0


def test_reward_first_valid_alert_wins():
    """Returns 1.0 if any of multiple alerts matches, even if earlier ones don't."""
    result = _make_cycle_result(alerts_triggered=[
        {"drug": "ibuprofen", "country": "Argentina", "level": "CRITICAL"},  # non-target drug
        {"drug": "doxorubicin", "country": "Colombia", "level": "HIGH"},      # target — should match
    ])
    assert compute_reward(result) == 1.0


def test_reward_scheduler_severity_key():
    """scheduler.run_cycle uses 'severity' key, not 'level' — must be recognized."""
    result = _make_cycle_result(alerts_triggered=[{
        "drug": "cisplatin", "country": "Argentina", "severity": "CRITICAL"
    }])
    assert compute_reward(result) == 1.0


# ---------------------------------------------------------------------------
# 5. Exploration / exploitation balance
# ---------------------------------------------------------------------------

def test_high_alpha_arm_selected_more_often():
    """
    Arm with alpha=10, beta=1 (mean=0.909) should be selected substantially
    more often than arm with alpha=1, beta=10 (mean=0.091) over 1000 draws.
    """
    mab = ThompsonSamplingMAB()
    mab.alpha["manufacturing"] = 10.0
    mab.beta["manufacturing"]  = 1.0
    mab.alpha["climate_latam"] = 1.0
    mab.beta["climate_latam"]  = 10.0

    rng = np.random.default_rng(0)
    counts: dict[str, int] = {arm: 0 for arm in ARMS}
    for _ in range(1000):
        arm = mab.select_arm(rng=rng)
        counts[arm] += 1

    assert counts["manufacturing"] > counts["climate_latam"] * 3, (
        f"Expected manufacturing to dominate: {counts['manufacturing']} vs {counts['climate_latam']}"
    )


def test_all_arms_explored_over_many_draws():
    """
    With a flat prior, all 9 arms should be selected at least once in 200 draws.
    Ensures exploration is real.
    """
    mab = ThompsonSamplingMAB()
    rng = np.random.default_rng(7)
    selected = set()
    for _ in range(200):
        selected.add(mab.select_arm(rng=rng))
    assert selected == set(ARMS), f"Not all arms explored: missing {set(ARMS) - selected}"


# ---------------------------------------------------------------------------
# 6. Pre-registration H3 closure criterion
# ---------------------------------------------------------------------------

class TestH3ClosureCriterion:
    """
    Pre-registration H3 (preregistration_phase2c.md):

    After 30 simulated rewards across the 9 arms, the posterior-mean ranking
    must place 'manufacturing' strictly above 'climate_latam'.

    Simulation protocol:
      - Use calibrated MAB from real DBs as starting state.
      - True reward probabilities are derived from calibrated posteriors
        (representing expected signal quality per category based on history).
      - Run 30 Thompson Sampling rounds with rewards sampled from true probs.
      - Evaluate posterior means after all 30 rounds.

    Forbidden moves (per pre-registration):
      - Hand-seeding posteriors to bias the ranking.
      - Increasing the rewards-until-evaluation count past 30.
    """

    def _load_calibrated_mab(self) -> ThompsonSamplingMAB:
        _OPENFDA = Path(__file__).parent.parent.parent / "phase2_data" / "openfda.db"
        _INVIMA  = Path(__file__).parent.parent.parent / "phase2_data" / "invima.db"
        if not _OPENFDA.exists() or not _INVIMA.exists():
            pytest.skip("Real DBs not present — H3 requires calibration data")
        return calibrate_from_db(openfda_db=_OPENFDA, invima_db=_INVIMA)

    def _compute_true_probs(self, mab: ThompsonSamplingMAB) -> dict[str, float]:
        """
        Derive true reward probabilities from calibrated posteriors.
        p_true[arm] = alpha[arm] / (alpha[arm] + beta[arm])
        This represents: given this arm is queried, how often does it yield a signal?
        """
        return {arm: mab.alpha[arm] / (mab.alpha[arm] + mab.beta[arm]) for arm in mab.arms}

    def test_h3_manufacturing_beats_climate_after_30_rewards(self):
        """
        HYPOTHESIS 3 CLOSURE: After 30 simulated rewards,
        manufacturing posterior mean > climate_latam posterior mean.
        """
        mab = self._load_calibrated_mab()
        true_probs = self._compute_true_probs(mab)

        rng = np.random.default_rng(2026)  # fixed seed for reproducibility
        n_rewards = 30  # PRE-REGISTERED — do not change

        for round_i in range(n_rewards):
            arm = mab.select_arm(rng=rng)
            # Sample reward from arm's true probability
            reward = float(rng.random() < true_probs[arm])
            mab.update(arm, reward)

        means = mab.posterior_means()
        manufacturing_mean  = means["manufacturing"]
        climate_latam_mean  = means["climate_latam"]

        # PRE-REGISTERED criterion — do not weaken
        assert manufacturing_mean > climate_latam_mean, (
            f"H3 FAIL: manufacturing ({manufacturing_mean:.4f}) ≤ "
            f"climate_latam ({climate_latam_mean:.4f}) after {n_rewards} rewards.\n"
            f"Full ranking: {dict(list(means.items()))}"
        )

    def test_h3_full_ranking_report(self):
        """
        Report full posterior-mean ranking after 30 rewards.
        Informational — not a pass/fail gate (the gate is test_h3_manufacturing_beats_climate).
        """
        mab = self._load_calibrated_mab()
        true_probs = self._compute_true_probs(mab)
        rng = np.random.default_rng(2026)

        for _ in range(30):
            arm = mab.select_arm(rng=rng)
            mab.update(arm, float(rng.random() < true_probs[arm]))

        means = mab.posterior_means()
        print("\n=== H3 POSTERIOR MEANS AFTER 30 REWARDS ===")
        for rank, (arm, mean) in enumerate(means.items(), 1):
            marker = " *** PRE-REG ARM ***" if arm in ("manufacturing", "climate_latam") else ""
            print(f"  {rank:2d}. {arm:20s}: {mean:.4f}{marker}")

        # Informational assertions — document the separation
        manufacturing_rank = list(means.keys()).index("manufacturing") + 1
        climate_rank = list(means.keys()).index("climate_latam") + 1
        print(f"\n  manufacturing rank: {manufacturing_rank}")
        print(f"  climate_latam rank: {climate_rank}")
        assert manufacturing_rank < climate_rank, (
            f"manufacturing rank ({manufacturing_rank}) ≥ climate_latam rank ({climate_rank})"
        )

    def test_h3_robust_across_seeds(self):
        """
        H3 must hold for 5 different RNG seeds, not just the pre-registered seed.
        Robustness check — if it fails on ≥2 seeds, the calibration or reward model needs review.
        """
        mab_base = self._load_calibrated_mab()
        true_probs = self._compute_true_probs(mab_base)

        passes = 0
        seeds = [0, 1, 42, 100, 999]
        for seed in seeds:
            # Fresh copy of calibrated MAB for each seed
            mab = ThompsonSamplingMAB.from_dict(mab_base.to_dict())
            rng = np.random.default_rng(seed)
            for _ in range(30):
                arm = mab.select_arm(rng=rng)
                mab.update(arm, float(rng.random() < true_probs[arm]))
            means = mab.posterior_means()
            if means["manufacturing"] > means["climate_latam"]:
                passes += 1

        assert passes >= 4, (
            f"H3 passed only {passes}/5 seeds — calibration or reward model may be misspecified"
        )

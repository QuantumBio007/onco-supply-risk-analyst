"""
test_simulate_schema.py — Regression test for simulate / simulate_dynamic /
simulate_transient policy schema consistency.

WHY THIS EXISTS
---------------
The three simulate wrappers in supply_sim.py duplicate ~150 lines of result-
dict construction. After the 2026-05-11 lead-time feasibility floor fix added
four new policy fields (eoq_cost_optimal, q_floor, q_floor_binding,
daily_demand_mean), all three wrappers had to be updated in parallel. The next
field addition will be at risk of desyncing one of the three. This test catches
that drift before it ships.

Run from project root:
    python3 -m pytest tests/test_simulate_schema.py -v
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supply_sim import (
    simulate, simulate_dynamic, simulate_transient, simulate_correlated_pair,
    compute_policy,
)


# Fields that EVERY simulate variant must expose. Adding to this set forces
# all wrappers to be updated. Failing this test means a wrapper has gone stale.
REQUIRED_POLICY_FIELDS = {
    "reorder_point",
    "safety_stock",
    "eoq",
    "eoq_cost_optimal",   # raw EOQ — added 2026-05-11
    "q_floor",            # lead-time feasibility floor — added 2026-05-11
    "q_floor_binding",    # diagnostic flag — added 2026-05-11
    "daily_demand_mean",  # for inventory-model chart — added 2026-05-11
    "lead_time_mean",
    "lead_time_std",
}

REQUIRED_KPI_FIELDS = {
    "stockout_days_mean",
    "stockout_days_ci",
    "cvar_90",
    "sl_units_mean",
    "sl_days_mean",
    "avg_inventory_mean",
    "prob_critical_shortage",
    "prob_any_stockout",
}


def _assert_schema(label, result, required):
    missing = required - set(result.keys())
    assert not missing, (
        f"{label} is missing required fields: {missing}. "
        f"All simulate wrappers must expose identical policy + KPI schemas — "
        f"see tests/test_simulate_schema.py module docstring."
    )


def test_simulate_main_wrapper_schema():
    r = simulate("cisplatin", "Argentina", "Baseline", n_runs=30)
    _assert_schema("simulate()", r, REQUIRED_POLICY_FIELDS)
    _assert_schema("simulate()", r, REQUIRED_KPI_FIELDS)


def test_simulate_dynamic_wrapper_schema():
    """simulate_dynamic takes shock parameters directly, no scenario name."""
    r = simulate_dynamic(
        "cisplatin", "Argentina",
        lead_time_multiplier=1.0, demand_multiplier=1.0,
        fill_rate=0.95, budget_multiplier=1.0,
        disruption_duration_mean=365, n_runs=30,
    )
    _assert_schema("simulate_dynamic()", r, REQUIRED_POLICY_FIELDS)
    _assert_schema("simulate_dynamic()", r, REQUIRED_KPI_FIELDS)


def test_simulate_transient_wrapper_schema():
    """simulate_transient also takes shock parameters directly."""
    r = simulate_transient(
        "cisplatin", "Argentina",
        lead_time_multiplier=2.0, demand_multiplier=1.0,
        fill_rate=0.55, budget_multiplier=0.9,
        disruption_duration_mean=90, n_runs=30,
    )
    _assert_schema("simulate_transient()", r, REQUIRED_POLICY_FIELDS)
    _assert_schema("simulate_transient()", r, REQUIRED_KPI_FIELDS)


def test_compute_policy_emits_all_q_diagnostic_fields():
    """The policy function itself must expose both Q values + binding flag."""
    p = compute_policy(d=1.5, sigma_d=1.0, L_mean=60.0, L_cv=0.2,
                       service_level=0.95, unit_cost=5000)
    required = {"eoq", "eoq_cost_optimal", "q_floor", "q_floor_binding",
                "reorder_point", "safety_stock", "z_score"}
    missing = required - set(p.keys())
    assert not missing, f"compute_policy missing fields: {missing}"

    # For trastuzumab-like params (high unit cost, long LT), floor must bind
    assert p["q_floor_binding"] is True, (
        "High-unit-cost biologic with 60-day lead time should trigger "
        "feasibility floor (EOQ much smaller than d × L). Got: "
        f"eoq_cost_optimal={p['eoq_cost_optimal']}, q_floor={p['q_floor']}, "
        f"final eoq={p['eoq']}."
    )
    assert p["eoq"] >= p["q_floor"], (
        "Recommended Q must be ≥ feasibility floor — that is the whole point "
        "of the floor logic."
    )


def test_compute_policy_generic_drug_no_floor_binding():
    """Cheap generic with short LT should NOT trigger floor (cost-optimal wins)."""
    # cisplatin Argentina baseline: $5/vial, ~10-day lead time, ~8 doses/day
    p = compute_policy(d=8.0, sigma_d=3.0, L_mean=10.0, L_cv=0.2,
                       service_level=0.95, unit_cost=5)
    assert p["q_floor_binding"] is False, (
        f"Generic with adequate EOQ should not bind the floor. Got "
        f"eoq_cost_optimal={p['eoq_cost_optimal']}, q_floor={p['q_floor']}."
    )
    assert p["eoq"] == p["eoq_cost_optimal"], (
        "When floor is not binding, recommended Q must equal cost-optimal EOQ."
    )


def test_correlated_pair_returns_per_drug_dicts_with_policy_block():
    """simulate_correlated_pair must expose a per-drug policy sub-block with
    the same fields as the other simulate wrappers. The blind spot identified
    in the 2026-05-11 codebase audit (no policy fields surfaced per drug) was
    closed by adding a `policy` key to each drug's sub-dict containing all of
    REQUIRED_POLICY_FIELDS. This test pins that contract."""
    r = simulate_correlated_pair("Argentina", "API export restriction", n_runs=30)
    assert "cisplatin"   in r and "carboplatin" in r
    for drug in ("cisplatin", "carboplatin"):
        sub = r[drug]
        assert "stockout_days_mean" in sub, f"{drug}: missing stockout_days_mean"
        assert "policy"             in sub, f"{drug}: missing policy sub-block"
        # Policy block must surface all the new (post-fix) Q diagnostic fields
        for f in ("eoq", "eoq_cost_optimal", "q_floor", "q_floor_binding",
                  "daily_demand_mean", "reorder_point", "safety_stock",
                  "lead_time_mean"):
            assert f in sub["policy"], (
                f"{drug}.policy missing field {f!r}. simulate_correlated_pair() "
                f"must expose the same Q diagnostic fields as the other simulate "
                f"wrappers — see audit closed 2026-05-11."
            )


if __name__ == "__main__":
    # Run without pytest for quick CLI sanity check
    print("Running simulate schema tests directly...")
    for name, fn in [(k, v) for k, v in globals().items()
                     if k.startswith("test_") and callable(v)]:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}")
            print(f"        {e}")
            raise
    print("\nAll schema tests PASS.")

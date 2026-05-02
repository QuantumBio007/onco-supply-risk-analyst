"""
shock_mapper.py — Map classified events to supply_sim.py parameters.

Takes event classification (e.g., "Hormuz closure") and maps to:
  - lead_time_multiplier
  - demand_multiplier
  - fill_rate
  - disruption_duration_mean (days)

Then triggers supply_sim.py to compute new risk estimates.
"""

from supply_sim import simulate


def map_shock_to_params(event_classification: dict, drug: str, country: str) -> dict:
    """
    Map event to supply_sim parameters.

    Args:
        event_classification: Output from event_classifier.py
        drug: e.g., "cisplatin"
        country: e.g., "Venezuela"

    Returns:
        dict with shock parameters (lead_time_multiplier, etc.)
    """

    # Default baseline (no shock)
    shock_params = {
        "lead_time_multiplier": 1.0,
        "demand_multiplier": 1.0,
        "fill_rate": 0.95,
        "budget_multiplier": 1.0,
        "disruption_duration_mean": 0,  # no disruption
    }

    classification = event_classification.get("classification", "IRRELEVANT")

    if classification == "IRRELEVANT":
        return shock_params

    # Extract impact from classification
    impact = event_classification.get("impact", {})

    # Apply mapped parameters
    if impact.get("lead_time_multiplier"):
        shock_params["lead_time_multiplier"] = impact["lead_time_multiplier"]

    if impact.get("demand_multiplier"):
        shock_params["demand_multiplier"] = impact["demand_multiplier"]

    if impact.get("fill_rate"):
        shock_params["fill_rate"] = impact["fill_rate"]

    # Estimate disruption duration based on severity
    if classification == "CRITICAL":
        shock_params["disruption_duration_mean"] = 120  # 4 months
    elif classification == "MODERATE":
        shock_params["disruption_duration_mean"] = 30  # 1 month
    elif classification == "MINOR":
        shock_params["disruption_duration_mean"] = 7  # 1 week

    return shock_params


def trigger_simulation(event_classification: dict, drug: str, country: str) -> dict:
    """
    Map event → run simulation → return risk change.

    Args:
        event_classification: From event_classifier.py
        drug: Target drug
        country: Target country

    Returns:
        dict with baseline_risk, shocked_risk, risk_delta
    """

    shock_params = map_shock_to_params(event_classification, drug, country)

    # Run simulation with shock parameters
    # (supply_sim.py integration needed)
    # result = simulate(drug=drug, country=country, **shock_params)

    print(f"[shock_mapper] Would trigger simulation for {drug}/{country}")
    print(f"  Shock params: {shock_params}")

    return {"shock_params": shock_params, "status": "ready_for_simulation"}


if __name__ == "__main__":
    # Test
    test_event = {
        "classification": "CRITICAL",
        "affected_drugs": ["cisplatin"],
        "affected_countries": ["Argentina"],
        "impact": {"lead_time_multiplier": 3.0, "fill_rate": 0.55},
    }

    result = trigger_simulation(test_event, "cisplatin", "Argentina")
    import json

    print(json.dumps(result, indent=2))

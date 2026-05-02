"""
alert_engine.py — Generate and send alerts when risk threshold exceeded.

Compares baseline risk vs. shocked risk.
If risk jumps significantly, send alert to clients/stakeholders.
"""

import json
from datetime import datetime


def evaluate_risk_change(baseline_risk: float, shocked_risk: float) -> dict:
    """
    Evaluate if risk change warrants alert.

    Args:
        baseline_risk: Baseline stockout days (from supply_sim.py)
        shocked_risk: Shocked scenario stockout days

    Returns:
        dict with alert decision, severity, message
    """

    risk_delta = shocked_risk - baseline_risk
    percent_increase = (risk_delta / baseline_risk * 100) if baseline_risk > 0 else 0

    alert = {
        "timestamp": datetime.now().isoformat(),
        "baseline_risk": baseline_risk,
        "shocked_risk": shocked_risk,
        "risk_delta": risk_delta,
        "percent_increase": percent_increase,
        "should_alert": False,
        "severity": "none",
        "message": "",
    }

    # Alert thresholds
    if percent_increase >= 100:  # >100% increase
        alert["should_alert"] = True
        alert["severity"] = "CRITICAL"
        alert["message"] = f"⚠️ CRITICAL: Risk increased {percent_increase:.0f}% ({baseline_risk:.1f}d → {shocked_risk:.1f}d)"

    elif percent_increase >= 50:  # >50% increase
        alert["should_alert"] = True
        alert["severity"] = "HIGH"
        alert["message"] = f"⚠️ HIGH: Risk increased {percent_increase:.0f}% ({baseline_risk:.1f}d → {shocked_risk:.1f}d)"

    elif percent_increase >= 25:  # >25% increase
        alert["should_alert"] = True
        alert["severity"] = "MODERATE"
        alert["message"] = f"ℹ️ MODERATE: Risk increased {percent_increase:.0f}% ({baseline_risk:.1f}d → {shocked_risk:.1f}d)"

    else:
        alert["severity"] = "LOW"
        alert["message"] = f"No action needed. Risk: {baseline_risk:.1f}d → {shocked_risk:.1f}d"

    return alert


def format_alert(alert: dict, drug: str, country: str, event_title: str) -> str:
    """Format alert for client delivery (email/Streamlit notification)."""

    if alert["severity"] == "none":
        return f"[{country}] {drug}: No supply chain impact detected."

    msg = f"""
╔══════════════════════════════════════════════════╗
║ ONCOSUPPLY RISK ALERT                           ║
╚══════════════════════════════════════════════════╝

Drug: {drug}
Country: {country}
Event: {event_title}
Severity: {alert['severity']}

{alert['message']}

Baseline stockout days/year: {alert['baseline_risk']:.1f}
Shocked scenario: {alert['shocked_risk']:.1f}
Change: +{alert['risk_delta']:.1f} days (+{alert['percent_increase']:.0f}%)

Recommendation:
- Review current inventory levels
- Consider accelerated procurement
- Evaluate alternative suppliers

Generated: {alert['timestamp']}
"""

    return msg.strip()


if __name__ == "__main__":
    # Test
    alert = evaluate_risk_change(baseline_risk=7.0, shocked_risk=35.0)
    print(json.dumps(alert, indent=2))
    print("\nFormatted alert:")
    print(
        format_alert(
            alert, "Cisplatin", "Argentina", "Iran closes Strait of Hormuz"
        )
    )

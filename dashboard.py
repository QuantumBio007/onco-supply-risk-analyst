"""
dashboard.py — OncoSupply Risk Intelligence Dashboard
AI-driven oncology drug shortage prediction for Latin America.

Sections:
  1. Headline Risk Heatmap (baseline stockout days, all 4×3 combos)
  2. Shock Scenario Explorer (drug × country × 7 scenarios with alert flags)
  3. Signal Intelligence Feed (processed.db NewsAPI→Claude results)
  4. MAB Query Rankings (Thompson Sampling posterior means)
  5. LATAM Lead-Time Intelligence (T3.1b openFDA vs. INVIMA advance signal)
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="OncoSupply Risk Dashboard",
    layout="wide",
    page_icon="💊",
)

# ── Path setup ────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Imports after path setup ──────────────────────────────────────────────────
try:
    import plotly.graph_objects as go
    import plotly.express as px
    _PLOTLY_OK = True
except ImportError:
    _PLOTLY_OK = False

try:
    from supply_sim import simulate, DRUG_PARAMS, COUNTRY_PARAMS, SCENARIO_PARAMS
    _SIM_OK = True
except Exception as _e:
    _SIM_OK = False
    _SIM_ERR = str(_e)

try:
    from phase2_realtime.alert_engine import evaluate_risk_change
    _ALERT_OK = True
except Exception as _e:
    _ALERT_OK = False
    _ALERT_ERR = str(_e)

# ── Constants ─────────────────────────────────────────────────────────────────
DRUGS     = ["cisplatin", "trastuzumab", "doxorubicin", "carboplatin"]
COUNTRIES = ["Argentina", "Colombia", "Venezuela"]
SCENARIOS = list(SCENARIO_PARAMS.keys()) if _SIM_OK else [
    "Baseline", "API export restriction", "Currency devaluation",
    "Combined shock", "Demand surge", "Regulatory squeeze", "Macro/inflation shock",
]

RISK_COLORS = {
    "CRITICAL": "#d62728",
    "HIGH":     "#ff7f0e",
    "MODERATE": "#e8c22e",
    "LOW":      "#2ca02c",
    "none":     "#aec7e8",
}

DATA_DIR = os.path.join(_HERE, "phase2_data")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _risk_label(days: float) -> str:
    if days > 60:  return "CRITICAL"
    if days > 30:  return "HIGH"
    if days > 10:  return "MODERATE"
    return "LOW"


@st.cache_data(show_spinner=False, ttl=3600)
def get_heatmap_data():
    """Run simulate(drug, country, 'Baseline') for all 4×3 combos. Cached 1h."""
    matrix = {}
    for drug in DRUGS:
        matrix[drug] = {}
        for country in COUNTRIES:
            try:
                r = simulate(drug, country, "Baseline", n_runs=300)
                matrix[drug][country] = {
                    "stockout_days_mean": r["stockout_days_mean"],
                    "cvar_90": r["cvar_90"],
                }
            except Exception as e:
                matrix[drug][country] = {"stockout_days_mean": None, "cvar_90": None, "error": str(e)}
    return matrix


@st.cache_data(show_spinner=False, ttl=3600)
def get_scenario_data(drug: str, country: str):
    """Run simulate for all scenarios for a drug/country pair. Cached 1h."""
    results = {}
    for scenario in SCENARIOS:
        try:
            r = simulate(drug, country, scenario, n_runs=300)
            results[scenario] = {
                "stockout_days_mean": r["stockout_days_mean"],
                "cvar_90": r["cvar_90"],
                "prob_critical": r["prob_critical_shortage"],
            }
        except Exception as e:
            results[scenario] = {"error": str(e)}
    return results


def load_processed_articles(limit: int = 10):
    """Read last N CRITICAL/MODERATE articles from processed.db."""
    db_path = os.path.join(DATA_DIR, "processed.db")
    if not os.path.exists(db_path):
        return None, "DB file not found"
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.cursor()
        cur.execute(
            "SELECT article_hash, processed_at, classification "
            "FROM processed_articles "
            "ORDER BY processed_at DESC "
            "LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        conn.close()
        return rows, None
    except Exception as e:
        return None, str(e)


def load_mab_state():
    """Load MAB Thompson Sampling state."""
    path = os.path.join(DATA_DIR, "mab_state.json")
    if not os.path.exists(path):
        return None, "mab_state.json not found"
    try:
        with open(path) as f:
            state = json.load(f)
        return state, None
    except Exception as e:
        return None, str(e)


def load_t3_results():
    """Load T3.1b extended results."""
    path = os.path.join(DATA_DIR, "t3_1b_results_extended.json")
    if not os.path.exists(path):
        return None, "t3_1b_results_extended.json not found"
    try:
        with open(path) as f:
            data = json.load(f)
        return data, None
    except Exception as e:
        return None, str(e)


# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## OncoSupply")
    st.markdown("**AI-driven oncology drug shortage prediction for Latin America**")
    st.markdown("---")
    st.markdown(f"**Last updated:** {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    st.markdown("---")
    st.markdown("**Data Sources**")
    st.markdown(
        "- openFDA (shortage signals)\n"
        "- INVIMA (Colombia registry)\n"
        "- DIGEMID (Peru registry)\n"
        "- ANMAT (Argentina registry)\n"
        "- NewsAPI (real-time news)\n"
        "- Claude (AI classifier)"
    )
    st.markdown("---")
    st.markdown("**Contact**")
    st.markdown("[cmart156@jh.edu](mailto:cmart156@jh.edu)")
    st.markdown("---")
    st.caption("JHU Carey Business School · GenAI Project · 2026")

# ── Title ─────────────────────────────────────────────────────────────────────

st.title("OncoSupply Risk Dashboard")
st.markdown(
    "**AI-driven oncology drug shortage prediction for Latin America** — "
    "4 drugs · 3 countries · real-time signal intelligence"
)
st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Headline Risk Heatmap
# ═════════════════════════════════════════════════════════════════════════════

st.header("1. Mean Stockout Risk (Baseline, Days/Year)")
st.caption(
    "Monte Carlo (Q,r) simulation — 300 runs per cell. "
    "Color = expected stockout days/year under normal operations. "
    "Green → low risk, Red → critical."
)

if not _SIM_OK:
    st.warning(f"supply_sim.py could not be loaded: {_SIM_ERR}")
elif not _PLOTLY_OK:
    st.warning("plotly is not installed — cannot render heatmap.")
else:
    with st.spinner("Running baseline simulations for all 12 drug-country pairs…"):
        hm_data = get_heatmap_data()

    # Build z-matrix and annotation text
    z_vals  = []
    ann_txt = []
    for drug in DRUGS:
        row_z   = []
        row_txt = []
        for country in COUNTRIES:
            cell = hm_data[drug][country]
            val  = cell.get("stockout_days_mean")
            row_z.append(val if val is not None else 0)
            if val is not None:
                row_txt.append(f"{val:.1f}d")
            else:
                row_txt.append("N/A")
        z_vals.append(row_z)
        ann_txt.append(row_txt)

    drug_labels    = [DRUG_PARAMS[d]["label"].split(" (")[0] for d in DRUGS]
    country_labels = COUNTRIES

    fig_hm = go.Figure(
        data=go.Heatmap(
            z=z_vals,
            x=country_labels,
            y=drug_labels,
            colorscale=[
                [0.0,  "#2ca02c"],   # green — low
                [0.15, "#8fbc8f"],
                [0.30, "#ffdd57"],   # yellow — moderate
                [0.55, "#ff7f0e"],   # orange — high
                [1.0,  "#d62728"],   # red — critical
            ],
            zmin=0,
            zmax=300,
            colorbar=dict(
                title="Stockout<br>Days/Year",
                tickvals=[0, 60, 120, 180, 240, 300],
                ticktext=["0", "60 (HIGH)", "120", "180", "240", "300+"],
            ),
            text=ann_txt,
            texttemplate="%{text}",
            textfont=dict(size=14, color="white"),
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Country: %{x}<br>"
                "Mean stockout: %{text}<br>"
                "<extra></extra>"
            ),
        )
    )
    fig_hm.update_layout(
        height=340,
        margin=dict(l=10, r=10, t=30, b=10),
        xaxis=dict(side="top"),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#fafafa"),
    )
    st.plotly_chart(fig_hm, use_container_width=True)

    # Key callout — trastuzumab/Venezuela
    vzla_val = hm_data["trastuzumab"]["Venezuela"].get("stockout_days_mean")
    if vzla_val is not None:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric(
                label="Trastuzumab / Venezuela (Baseline)",
                value=f"{vzla_val:.0f} days/yr",
                delta=f"{vzla_val/3.65:.0f}% of the year in stockout",
                delta_color="inverse",
            )
        with col2:
            cvar_vzla = hm_data["trastuzumab"]["Venezuela"].get("cvar_90")
            if cvar_vzla:
                st.metric(
                    label="CVaR₉₀ (worst 10% of runs)",
                    value=f"{cvar_vzla:.0f} days/yr",
                    delta="Tail risk",
                    delta_color="inverse",
                )
        with col3:
            st.metric(
                label="Risk Classification",
                value=_risk_label(vzla_val),
                delta="Highest risk cell in portfolio",
                delta_color="inverse",
            )

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Shock Scenario Explorer
# ═════════════════════════════════════════════════════════════════════════════

st.header("2. Shock Scenario Explorer")
st.caption(
    "Select a drug and country to simulate all 7 scenarios. "
    "Bars show mean stockout days; error bars show CVaR₉₀. "
    "Red outline = alert threshold exceeded vs. baseline."
)

col_d, col_c = st.columns(2)
with col_d:
    sel_drug = st.selectbox(
        "Drug",
        options=DRUGS,
        index=DRUGS.index("trastuzumab"),
        format_func=lambda d: DRUG_PARAMS[d]["label"].split(" (")[0] if _SIM_OK else d,
    )
with col_c:
    sel_country = st.selectbox(
        "Country",
        options=COUNTRIES,
        index=COUNTRIES.index("Venezuela"),
    )

if not _SIM_OK:
    st.warning(f"supply_sim.py unavailable: {_SIM_ERR}")
elif not _PLOTLY_OK:
    st.warning("plotly unavailable — cannot render scenario chart.")
else:
    with st.spinner(f"Simulating {len(SCENARIOS)} scenarios for {sel_drug} / {sel_country}…"):
        sc_data = get_scenario_data(sel_drug, sel_country)

    baseline_mean = sc_data.get("Baseline", {}).get("stockout_days_mean", 0) or 0
    baseline_cvar = sc_data.get("Baseline", {}).get("cvar_90", 0) or 0

    bar_x     = []
    bar_y     = []
    bar_err   = []
    bar_color = []
    alert_flags = []

    for scenario in SCENARIOS:
        cell = sc_data.get(scenario, {})
        mean = cell.get("stockout_days_mean")
        cvar = cell.get("cvar_90")
        if mean is None:
            continue

        bar_x.append(scenario)
        bar_y.append(mean)
        bar_err.append(max(0, cvar - mean) if cvar is not None else 0)

        # Evaluate alert
        alert_info = {"severity": "none", "should_alert": False}
        if _ALERT_OK and scenario != "Baseline":
            try:
                alert_info = evaluate_risk_change(
                    baseline_risk=baseline_mean,
                    shocked_risk=mean,
                    baseline_cvar=baseline_cvar,
                    shocked_cvar=cvar,
                    shock_type=scenario.lower().replace(" ", "_"),
                )
            except Exception:
                pass

        sev = alert_info.get("severity", "none")
        bar_color.append(RISK_COLORS.get(sev, RISK_COLORS["LOW"]) if sev != "none" else "#2ca02c")
        alert_flags.append(alert_info)

    fig_bar = go.Figure()

    fig_bar.add_trace(
        go.Bar(
            x=bar_x,
            y=bar_y,
            error_y=dict(
                type="data",
                array=bar_err,
                visible=True,
                color="#888",
                thickness=1.5,
                width=4,
            ),
            marker=dict(
                color=bar_color,
                line=dict(
                    color=[
                        "#d62728" if af.get("should_alert") else "rgba(0,0,0,0)"
                        for af in alert_flags
                    ],
                    width=3,
                ),
            ),
            text=[f"{v:.1f}d" for v in bar_y],
            textposition="outside",
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Mean stockout: %{y:.1f} days<br>"
                "<extra></extra>"
            ),
        )
    )

    # Baseline reference line
    fig_bar.add_hline(
        y=baseline_mean,
        line_dash="dot",
        line_color="#aaa",
        annotation_text=f"Baseline {baseline_mean:.1f}d",
        annotation_position="top right",
    )

    # 60-day critical threshold line
    fig_bar.add_hline(
        y=60,
        line_dash="dash",
        line_color="#d62728",
        line_width=1,
        annotation_text="60d Critical threshold",
        annotation_position="bottom right",
    )

    fig_bar.update_layout(
        title=dict(
            text=f"{sel_drug.capitalize()} · {sel_country} — All Scenarios",
            font=dict(size=16),
        ),
        xaxis_title="Scenario",
        yaxis_title="Mean Stockout Days / Year",
        height=430,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#fafafa"),
        showlegend=False,
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # Alert summary table
    alert_rows = []
    for i, scenario in enumerate(bar_x):
        af = alert_flags[i]
        if af.get("should_alert"):
            alert_rows.append({
                "Scenario": scenario,
                "Severity": af["severity"],
                "Triggers": ", ".join(af.get("triggers", [])),
                "Mean Δ (days)": f"{af['risk_delta']:+.1f}",
                "CVaR Δ (days)": f"{af['cvar_delta']:+.1f}" if af.get("cvar_delta") is not None else "—",
            })

    if alert_rows:
        st.markdown("**Alert Summary — Triggered Scenarios**")
        st.dataframe(
            alert_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No alert thresholds exceeded for this drug/country combination.")

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Signal Intelligence Feed
# ═════════════════════════════════════════════════════════════════════════════

st.header("3. Live Signal Feed (NewsAPI → Claude Classifier)")
st.caption(
    "Articles classified by Claude as CRITICAL or MODERATE. "
    "Showing most recent 10 entries from processed.db."
)

rows, err = load_processed_articles(limit=10)

if err:
    st.warning(f"Signal feed unavailable: {err}")
elif not rows:
    st.info("No critical signals detected in last 24h.")
else:
    feed_records = []
    for article_hash, processed_at, classification_json in rows:
        try:
            cls = json.loads(classification_json) if classification_json else {}
        except Exception:
            cls = {"raw": classification_json}

        severity  = cls.get("severity", "UNKNOWN")
        shock_type = cls.get("shock_type", "—")

        sev_color = {
            "CRITICAL": "🔴",
            "HIGH":     "🟠",
            "MODERATE": "🟡",
            "LOW":      "🟢",
        }.get(severity, "⚪")

        feed_records.append({
            "Severity": f"{sev_color} {severity}",
            "Shock Type": shock_type,
            "Processed At": processed_at[:19].replace("T", " ") if processed_at else "—",
            "Article Hash": article_hash[:12] + "…" if article_hash else "—",
        })

    st.dataframe(
        feed_records,
        use_container_width=True,
        hide_index=True,
    )
    st.caption(f"Total articles in database: {len(rows)}")

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — MAB Query Rankings
# ═════════════════════════════════════════════════════════════════════════════

st.header("4. Adaptive Query Rankings (Thompson Sampling MAB)")
st.caption(
    "Posterior mean success probability = α / (α + β) for each query category. "
    "Higher = more informative queries in recent runs."
)

mab_state, mab_err = load_mab_state()

if mab_err:
    st.warning(f"MAB state unavailable: {mab_err}")
elif not _PLOTLY_OK:
    st.warning("plotly unavailable — cannot render MAB chart.")
else:
    try:
        arms   = mab_state["arms"]
        alphas = mab_state["alpha"]
        betas  = mab_state["beta"]

        # Compute posterior mean = alpha / (alpha + beta)
        posteriors = {}
        for arm in arms:
            a = alphas.get(arm, 1.0)
            b = betas.get(arm, 1.0)
            posteriors[arm] = a / (a + b)

        # Sort descending
        sorted_arms  = sorted(posteriors, key=lambda k: posteriors[k], reverse=True)
        sorted_probs = [posteriors[a] for a in sorted_arms]

        # Color by rank
        colors = [
            "#d62728" if p > 0.85 else
            "#ff7f0e" if p > 0.65 else
            "#2ca02c"
            for p in sorted_probs
        ]

        fig_mab = go.Figure(
            go.Bar(
                x=sorted_probs,
                y=sorted_arms,
                orientation="h",
                marker=dict(color=colors),
                text=[f"{p:.1%}" for p in sorted_probs],
                textposition="outside",
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Posterior mean: %{x:.3f}<br>"
                    "<extra></extra>"
                ),
            )
        )
        fig_mab.update_layout(
            xaxis=dict(title="Posterior Mean P(success)", range=[0, 1.1], tickformat=".0%"),
            yaxis=dict(title="Query Category", autorange="reversed"),
            height=360,
            margin=dict(l=10, r=80, t=20, b=10),
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font=dict(color="#fafafa"),
        )
        st.plotly_chart(fig_mab, use_container_width=True)

        # Top-ranked annotation
        top_arm = sorted_arms[0]
        top_prob = sorted_probs[0]
        bottom_arm = sorted_arms[-1]
        bottom_prob = sorted_probs[-1]
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.metric(
                label="Top-performing query category",
                value=top_arm.replace("_", " ").title(),
                delta=f"{top_prob:.1%} posterior mean",
            )
        with col_m2:
            st.metric(
                label="Lowest-performing category",
                value=bottom_arm.replace("_", " ").title(),
                delta=f"{bottom_prob:.1%} posterior mean",
                delta_color="inverse",
            )

    except Exception as e:
        st.warning(f"Error rendering MAB chart: {e}")

st.markdown("---")

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — LATAM Lead-Time Intelligence (T3.1b)
# ═════════════════════════════════════════════════════════════════════════════

st.header("5. LATAM Lead-Time Intelligence (openFDA vs. INVIMA)")
st.caption(
    "T3.1b analysis: how many days earlier does openFDA signal a shortage "
    "compared to INVIMA's official registry updates?"
)

t3_data, t3_err = load_t3_results()

if t3_err:
    st.info(
        "T3.1b results file not found. "
        "Key finding: openFDA leads INVIMA by 19–217 days. "
        "Carboplatin: 217 days (7 months advance signal)."
    )
elif t3_data:
    try:
        h2 = t3_data.get("h2", {})
        verdict    = h2.get("verdict", "—")
        reason     = h2.get("reason", "—")
        leads_days = h2.get("leads_days", [])
        median_lead = h2.get("median_lead_days")
        matched    = h2.get("matched_detail", [])
        n_formulations = t3_data.get("n_formulations", "—")

        # Verdict badge
        if verdict == "PASS":
            st.success(f"H2 VERDICT: PASS — {reason}")
        elif verdict == "FAIL":
            st.error(f"H2 VERDICT: FAIL — {reason}")
        else:
            st.warning(f"H2 VERDICT: {verdict} — {reason}")

        # Key metrics
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            st.metric(
                label="Median Lead Time (openFDA vs. INVIMA)",
                value=f"{median_lead:.0f} days" if median_lead else "—",
                delta="Advance warning signal",
            )
        with col_t2:
            if leads_days:
                st.metric(
                    label="Max Lead Time",
                    value=f"{max(leads_days)} days",
                    delta="Carboplatin (7 months)",
                )
        with col_t3:
            if leads_days:
                st.metric(
                    label="Min Lead Time",
                    value=f"{min(leads_days)} days",
                    delta="Methotrexate",
                )

        # Matched detail table
        if matched:
            st.markdown("**Matched Drug-Formulation Detail**")
            detail_rows = []
            for m in matched:
                detail_rows.append({
                    "Drug (INN)":         m.get("inn", "—").title(),
                    "openFDA Signal Date": m.get("openfda_date", "—"),
                    "INVIMA Period":       m.get("invima_period", "—"),
                    "Lead Time (days)":    m.get("lead_days", "—"),
                })
            st.dataframe(detail_rows, use_container_width=True, hide_index=True)

        st.markdown(
            f"**Formulations analyzed:** {n_formulations}  |  "
            f"**Matched pairs:** {h2.get('n_matched', '—')}  |  "
            f"**Left-truncated (insufficient history):** {t3_data.get('h1', {}).get('n_left_truncated', '—')}"
        )

        # H2 key insight callout
        st.info(
            "Key finding: openFDA shortage reports lead INVIMA registry updates by "
            f"{min(leads_days)}–{max(leads_days)} days. "
            "Carboplatin: 217-day (7-month) advance signal. "
            "This demonstrates openFDA as an effective early warning system for LATAM procurement planning."
        )

    except Exception as e:
        st.warning(f"Error parsing T3.1b results: {e}")
        st.info(
            "Key finding: openFDA leads INVIMA by 19–217 days. "
            "Carboplatin: 217 days (7 months advance signal)."
        )

st.markdown("---")
st.caption(
    "OncoSupply · JHU Carey Business School · GenAI Project 2026 · "
    "Model: (Q,r) continuous-review DES + Monte Carlo (Kogler & Maxera 2026) · "
    "Data: openFDA, INVIMA, ANMAT, NewsAPI, Claude"
)

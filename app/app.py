import streamlit as st
import sys
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_core import run_agent
from supply_sim import (
    simulate, portfolio_risk_matrix,
    DRUG_PARAMS, SCENARIO_PARAMS, COUNTRY_PARAMS, RISK_COLORS, _risk_label
)

ALLOWED_DRUGS     = ["cisplatin", "doxorubicin", "carboplatin", "trastuzumab"]
ALLOWED_COUNTRIES = ["Argentina", "Venezuela", "Colombia"]
ALLOWED_SCENARIOS = ["Baseline", "API export restriction",
                     "Currency devaluation", "Combined shock",
                     "Demand surge", "Regulatory squeeze",
                     "Macro/inflation shock"]

def check_refusal(drug, country):
    """Validate that drug and country are in scope. Returns error message or None."""
    if not drug or drug.lower() not in [d.lower() for d in ALLOWED_DRUGS]:
        return f"This system only covers oncology drugs in scope. '{drug}' is not available. Allowed: {', '.join(ALLOWED_DRUGS)}"
    if country not in ALLOWED_COUNTRIES:
        return f"This system only covers Argentina, Colombia, and Venezuela. '{country}' is not in scope."
    return None

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(page_title="OncoSupply Risk Analyst", layout="wide")
st.title("OncoSupply Risk Analyst")
st.caption("Oncology drug shortage risk briefs for Latin America · JCNB Biotech Consulting")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Parameters")
    drug     = st.selectbox("Drug",     ALLOWED_DRUGS)
    country  = st.selectbox("Country",  ALLOWED_COUNTRIES)
    scenario = st.selectbox("Scenario", ALLOWED_SCENARIOS)
    generate = st.button("Generate Risk Brief", type="primary")
    st.divider()
    st.caption("Model: Claude Haiku 4.5 · Simulation: (Q,r) Monte Carlo 500 runs · KB: ChromaDB all-mpnet-base-v2")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_brief, tab_sim, tab_portfolio = st.tabs(
    ["Risk Brief", "Simulation Chart", "Portfolio Risk Matrix"]
)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1: RISK BRIEF (agentic)
# ─────────────────────────────────────────────────────────────────────────────
with tab_brief:
    if generate:
        with st.spinner("Agent working — retrieving KB, running simulation..."):
            brief, trace = run_agent(drug, country, scenario)

        with st.expander("Agent reasoning trace", expanded=True):
            st.markdown("**Tools called by the agent:**")
            for i, step in enumerate(trace, 1):
                st.markdown(f"{i}. {step}")

        st.divider()
        st.markdown(f"## {drug.title()} — {country} — {scenario}")
        st.markdown(brief)
    else:
        st.info("Select parameters in the sidebar and click **Generate Risk Brief**.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 2: SIMULATION CHART
# ─────────────────────────────────────────────────────────────────────────────
with tab_sim:
    st.subheader(f"Monte Carlo Stockout Distribution — {drug.title()} / {country} / {scenario}")
    st.caption("500-run (Q,r) inventory simulation. X-axis: stockout days per year. Y-axis: frequency across runs.")

    if generate:
        with st.spinner("Running 500 Monte Carlo simulations..."):
            result = simulate(drug, country, scenario, n_runs=500, return_distribution=True)
        dist = np.array(result["stockout_distribution"])
        risk = _risk_label(result["stockout_days_mean"])
        color = RISK_COLORS[risk]

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        fig.patch.set_facecolor("#0e1117")
        for ax in axes:
            ax.set_facecolor("#1a1f2e")
            ax.tick_params(colors="white")
            ax.spines["bottom"].set_color("#444")
            ax.spines["left"].set_color("#444")
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)

        # ── Left: histogram ──────────────────────────────────────────────────
        ax = axes[0]
        ax.hist(dist, bins=40, color=color, alpha=0.85, edgecolor="none")
        ax.axvline(result["stockout_days_mean"], color="white", linestyle="--",
                   linewidth=1.5, label=f"Mean: {result['stockout_days_mean']:.1f}d")
        ax.axvline(result["cvar_90"], color="#ff7f0e", linestyle="-.",
                   linewidth=1.5, label=f"CVaR₉₀: {result['cvar_90']:.1f}d")
        ax.axvline(60, color="#aaaaaa", linestyle=":", linewidth=1,
                   label="Critical threshold (60d)")
        ax.set_xlabel("Stockout days per year", color="white")
        ax.set_ylabel("Frequency (runs)", color="white")
        ax.set_title(f"Stockout Distribution  |  Risk: {risk}", color="white", fontsize=11)
        ax.legend(framealpha=0.2, labelcolor="white", facecolor="#0e1117")

        # ── Right: KPI summary bars ──────────────────────────────────────────
        ax2 = axes[1]
        scenarios_list = list(SCENARIO_PARAMS.keys())
        means = []
        colors_list = []
        for s in scenarios_list:
            r2 = simulate(drug, country, s, n_runs=200)
            means.append(r2["stockout_days_mean"])
            colors_list.append(RISK_COLORS[_risk_label(r2["stockout_days_mean"])])

        bars = ax2.barh(scenarios_list, means, color=colors_list, alpha=0.85)
        ax2.set_xlabel("Mean stockout days / year", color="white")
        ax2.set_title(f"Scenario Comparison — {drug.title()} / {country}", color="white", fontsize=11)
        for bar, val in zip(bars, means):
            ax2.text(max(val + 0.5, 1), bar.get_y() + bar.get_height() / 2,
                     f"{val:.1f}d", va="center", color="white", fontsize=9)

        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # KPI metrics row
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Mean stockout days", f"{result['stockout_days_mean']:.1f} ± {result['stockout_days_ci']}")
        c2.metric("CVaR₉₀ (tail risk)", f"{result['cvar_90']:.1f}d",
                  help="Expected stockout days in worst 10% of simulations (Badejo & Ierapetritou, AIChE 2025)")
        c3.metric("Unit service level", f"{result['sl_units_mean']:.1%}")
        c4.metric("P(critical >60d)", f"{result['prob_critical_shortage']:.0%}")
        c5.metric("Risk rating", risk)
    else:
        st.info("Click **Generate Risk Brief** to run the simulation and view the distribution chart.")


# ─────────────────────────────────────────────────────────────────────────────
# TAB 3: PORTFOLIO RISK MATRIX
# ─────────────────────────────────────────────────────────────────────────────
with tab_portfolio:
    st.subheader(f"Portfolio Risk Matrix — {country}")
    st.caption(
        "All 4 drugs × 4 scenarios for the selected country. "
        "Cell = mean stockout days / year. Color = risk tier. "
        "Run: 300 simulations per cell."
    )

    run_portfolio = st.button(f"Run Portfolio Analysis for {country}", key="portfolio_btn")

    if run_portfolio:
        with st.spinner(f"Running 4 × 4 = 16 simulations for {country} (may take 20-30 seconds)..."):
            pm = portfolio_risk_matrix(country, n_runs=300)

        drugs_list     = pm["drugs"]
        scenarios_list = pm["scenarios"]
        matrix         = pm["matrix"]

        # ── Heatmap ──────────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#0e1117")
        ax.set_facecolor("#0e1117")

        risk_to_num = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        data = np.array([
            [risk_to_num[matrix[d][s]["risk"]] for s in scenarios_list]
            for d in drugs_list
        ])

        cmap = plt.cm.colors.ListedColormap(["#2ca02c", "#ffdd57", "#ff7f0e", "#d62728"])
        im = ax.imshow(data, cmap=cmap, vmin=-0.5, vmax=3.5, aspect="auto")

        ax.set_xticks(range(len(scenarios_list)))
        ax.set_xticklabels([s.replace(" ", "\n") for s in scenarios_list],
                           color="white", fontsize=9)
        ax.set_yticks(range(len(drugs_list)))
        ax.set_yticklabels([DRUG_PARAMS[d]["label"].split(" (")[0] for d in drugs_list],
                           color="white", fontsize=9)
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_visible(False)

        # Annotate cells with stockout days
        for i, drug_name in enumerate(drugs_list):
            for j, sc in enumerate(scenarios_list):
                cell = matrix[drug_name][sc]
                ax.text(j, i,
                        f"{cell['stockout_days_mean']:.1f}d\n{cell['risk']}",
                        ha="center", va="center", color="black",
                        fontsize=8, fontweight="bold")

        patches = [
            mpatches.Patch(color="#2ca02c", label="LOW (<10d)"),
            mpatches.Patch(color="#ffdd57", label="MODERATE (10–30d)"),
            mpatches.Patch(color="#ff7f0e", label="HIGH (30–60d)"),
            mpatches.Patch(color="#d62728", label="CRITICAL (>60d)"),
        ]
        ax.legend(handles=patches, loc="upper right", bbox_to_anchor=(1.35, 1.05),
                  framealpha=0.2, labelcolor="white", facecolor="#0e1117", fontsize=8)
        ax.set_title(f"Portfolio Risk Matrix — {country}", color="white", fontsize=12, pad=10)
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

        # ── Worst-case summary table ──────────────────────────────────────────
        st.markdown("**Highest-risk drug-scenario pairs:**")
        rows = []
        for d in drugs_list:
            for s in scenarios_list:
                cell = matrix[d][s]
                rows.append({
                    "Drug": DRUG_PARAMS[d]["label"].split(" (")[0],
                    "Scenario": s,
                    "Stockout days/yr": cell["stockout_days_mean"],
                    "Service level": f"{cell['sl_units_mean']:.1%}",
                    "P(critical)": f"{cell['prob_critical']:.0%}",
                    "Risk": cell["risk"],
                })
        rows.sort(key=lambda x: x["Stockout days/yr"], reverse=True)

        import pandas as pd
        df = pd.DataFrame(rows[:8])  # top 8 worst

        def color_risk(val):
            colors = {"CRITICAL": "background-color: #d62728; color: black",
                      "HIGH": "background-color: #ff7f0e; color: black",
                      "MODERATE": "background-color: #ffdd57; color: black",
                      "LOW": "background-color: #2ca02c; color: black"}
            return colors.get(val, "")

        st.dataframe(df.style.applymap(color_risk, subset=["Risk"]),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Click **Run Portfolio Analysis** to see all drugs × scenarios for this country.")

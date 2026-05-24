"""
Supply Chain Analytics - Streamlit Dashboard

Two modes:
  - DEFAULT: reads live from MySQL warehouse (your local docker container)
  - SNAPSHOT MODE: reads from data/snapshot/*.parquet files
                   Activated by env var USE_SNAPSHOT=true
                   Used for deployment (Streamlit Cloud, etc.)

Run locally (MySQL mode):
    streamlit run src/dashboard/app.py

Run locally (snapshot mode - test the deployment path):
    set USE_SNAPSHOT=true     # Windows
    export USE_SNAPSHOT=true  # Mac/Linux
    streamlit run src/dashboard/app.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import joblib
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "src" / "models" / "late_delivery_classifier.joblib"
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot"

def _get_use_snapshot() -> bool:
    """Read USE_SNAPSHOT from Streamlit secrets (deployment) OR env var (local)."""
    try:
        if "USE_SNAPSHOT" in st.secrets:
            return str(st.secrets["USE_SNAPSHOT"]).lower() == "true"
    except Exception:
        pass
    return os.getenv("USE_SNAPSHOT", "false").lower() == "true"


USE_SNAPSHOT = _get_use_snapshot()

# Only import the DB engine if we'll actually use it
if not USE_SNAPSHOT:
    sys.path.append(str(PROJECT_ROOT))
    from src.db import get_engine  # noqa: E402

# ============================================================
# Page config
# ============================================================
st.set_page_config(
    page_title="Freight & Shipment Analytics",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# Cached data loaders - work in either mode
# ============================================================
@st.cache_resource
def db():
    return get_engine()


@st.cache_data(ttl=300)
def load_view(view_name: str) -> pd.DataFrame:
    if USE_SNAPSHOT:
        return pd.read_parquet(SNAPSHOT_DIR / f"{view_name}.parquet")
    return pd.read_sql(f"SELECT * FROM {view_name}", db())


@st.cache_data(ttl=300)
def load_dim_values() -> dict:
    if USE_SNAPSHOT:
        path = SNAPSHOT_DIR / "dim_values.json"
        return json.loads(path.read_text())

    eng = db()
    return {
        "shipping_modes": pd.read_sql(
            "SELECT shipping_mode_name FROM dim_shipping_mode ORDER BY 1", eng
        )["shipping_mode_name"].tolist(),
        "segments": pd.read_sql(
            "SELECT DISTINCT customer_segment FROM dim_customer "
            "WHERE customer_segment IS NOT NULL ORDER BY 1", eng
        )["customer_segment"].tolist(),
        "categories": pd.read_sql(
            "SELECT DISTINCT category_name FROM dim_product "
            "WHERE category_name IS NOT NULL ORDER BY 1", eng
        )["category_name"].tolist(),
        "markets": pd.read_sql(
            "SELECT DISTINCT market FROM dim_geography "
            "WHERE market IS NOT NULL ORDER BY 1", eng
        )["market"].tolist(),
        "payment_types": pd.read_sql(
            "SELECT DISTINCT payment_type FROM fact_orders "
            "WHERE payment_type IS NOT NULL ORDER BY 1", eng
        )["payment_type"].tolist(),
    }


@st.cache_resource
def load_model():
    if not MODEL_PATH.exists():
        return None
    return joblib.load(MODEL_PATH)


# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.title("📦 Freight Analytics")
    st.caption("Supply chain KPI + ML platform")
    if USE_SNAPSHOT:
        st.info("📸 Snapshot mode")
    st.markdown("---")
    st.markdown(
        "**About this project**\n\n"
        "End-to-end analytics platform built on a Kimball star schema in MySQL, "
        "with a scikit-learn late-delivery classifier."
    )
    st.markdown("---")
    st.markdown("**Tech stack**")
    st.markdown("- MySQL 8 (warehouse)\n- Python + pandas\n- scikit-learn\n- Streamlit + Plotly")
    st.markdown("---")
    st.caption("Data: DataCo Smart Supply Chain (180k orders, 5 markets)")


# ============================================================
# Main: Tabs
# ============================================================
st.title("Freight & Shipment Analytics Platform")
tab_overview, tab_performance, tab_routes, tab_predictor = st.tabs(
    ["🏠 Overview", "📊 Mode & Market Performance", "🗺️ Problem Routes", "🤖 Delay Predictor"]
)

# ------------------------------------------------------------
# TAB 1 - OVERVIEW
# ------------------------------------------------------------
with tab_overview:
    st.header("Headline KPIs")
    kpi = load_view("vw_kpi_summary").iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("OTIF Rate", f"{kpi['otif_rate_pct']:.2f}%",
              help="On-time AND not cancelled. Industry benchmark: 90%+")
    c2.metric("Late Delivery Rate", f"{kpi['late_delivery_rate_pct']:.2f}%",
              delta=f"{kpi['late_delivery_rate_pct'] - 10:.1f}% vs 10% target",
              delta_color="inverse")
    c3.metric("Avg Transit Variance", f"{kpi['avg_transit_variance_days']:.2f} days",
              help="Actual - scheduled days. Positive = chronically late")
    c4.metric("Overall Margin", f"{kpi['overall_margin_pct']:.2f}%")

    st.markdown("")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Orders", f"{int(kpi['total_orders']):,}")
    c2.metric("Total Sales", f"${kpi['total_sales']:,.0f}")
    c3.metric("Total Profit", f"${kpi['total_profit']:,.0f}")

    st.markdown("---")
    st.subheader("Demand trend — monthly sales by category")
    demand = load_view("vw_category_demand_monthly")
    demand["period"] = pd.to_datetime(
        demand["year"].astype(str) + "-" + demand["month_number"].astype(str) + "-01"
    )
    top_cats = (demand.groupby("category_name")["sales"].sum()
                .nlargest(8).index.tolist())
    plot_df = demand[demand["category_name"].isin(top_cats)]
    fig = px.line(plot_df, x="period", y="sales", color="category_name",
                  title="Monthly sales — top 8 categories")
    fig.update_layout(height=420, legend_title_text="Category")
    st.plotly_chart(fig, width="stretch")

# ------------------------------------------------------------
# TAB 2 - MODE & MARKET PERFORMANCE
# ------------------------------------------------------------
with tab_performance:
    st.header("Shipping mode scorecard")
    st.caption(
        "Faster promised modes are missing SLA. Standard Class (4-day SLA) holds; "
        "First Class (1-day SLA) is structurally over-promising."
    )
    mode = load_view("vw_shipping_mode_scorecard")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(mode, x="shipping_mode_name", y="on_time_pct",
                     color="shipping_mode_name", text="on_time_pct",
                     title="On-time delivery rate by mode (%)",
                     labels={"shipping_mode_name": "Shipping mode",
                             "on_time_pct": "On-time %"})
        fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig.update_layout(height=380, showlegend=False, yaxis_range=[0, 100])
        st.plotly_chart(fig, width="stretch")

    with c2:
        fig = px.bar(mode, x="shipping_mode_name", y="avg_delay_days",
                     color="shipping_mode_name", text="avg_delay_days",
                     title="Average delay days (actual − scheduled)",
                     labels={"shipping_mode_name": "Shipping mode",
                             "avg_delay_days": "Avg delay (days)"})
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(height=380, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    st.dataframe(mode, width="stretch", hide_index=True)

    st.markdown("---")
    st.header("Market performance")
    market = load_view("vw_market_performance")

    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(market.sort_values("otif_rate_pct"),
                     x="otif_rate_pct", y="market", orientation="h",
                     color="otif_rate_pct", color_continuous_scale="RdYlGn",
                     title="OTIF rate by market (%)")
        fig.update_layout(height=380, coloraxis_showscale=False)
        st.plotly_chart(fig, width="stretch")

    with c2:
        fig = px.scatter(market, x="margin_pct", y="otif_rate_pct",
                         size="volume", color="market", text="market",
                         title="Margin vs OTIF — bubble = order volume",
                         labels={"margin_pct": "Margin %",
                                 "otif_rate_pct": "OTIF %"})
        fig.update_traces(textposition="top center")
        fig.update_layout(height=380, showlegend=False)
        st.plotly_chart(fig, width="stretch")

    st.dataframe(market, width="stretch", hide_index=True)

# ------------------------------------------------------------
# TAB 3 - PROBLEM ROUTES
# ------------------------------------------------------------
with tab_routes:
    st.header("Top 20 problem routes")
    st.caption(
        "Origin market → destination country pairs with the worst average delay. "
        "This is the targeted fix list."
    )
    routes = load_view("vw_top_problem_routes")

    fig = px.bar(routes.head(15),
                 x="avg_delay_days",
                 y=routes.head(15)["origin_market"] + " → " + routes.head(15)["destination_country"],
                 orientation="h",
                 color="late_pct",
                 color_continuous_scale="Reds",
                 title="Worst 15 routes by average delay (days)",
                 labels={"y": "Route", "avg_delay_days": "Avg delay (days)",
                         "late_pct": "Late %"})
    fig.update_layout(height=520, yaxis_title="")
    st.plotly_chart(fig, width="stretch")

    st.dataframe(routes, width="stretch", hide_index=True)

    st.markdown("---")
    st.header("Customer segment profitability")
    seg = load_view("vw_customer_segment_profitability")
    st.dataframe(seg, width="stretch", hide_index=True)

# ------------------------------------------------------------
# TAB 4 - DELAY PREDICTOR
# ------------------------------------------------------------
with tab_predictor:
    st.header("Late delivery risk predictor")
    st.caption(
        "Given an order's attributes at the moment it's placed, predict the "
        "probability that it will be delivered late."
    )

    model = load_model()
    if model is None:
        st.error(
            "Model artifact not found. Run `python src/models/train.py` first to "
            "generate `src/models/late_delivery_classifier.joblib`."
        )
        st.stop()

    dim = load_dim_values()

    with st.form("predict_form"):
        c1, c2, c3 = st.columns(3)
        with c1:
            shipping_mode = st.selectbox("Shipping mode", dim["shipping_modes"], index=0)
            segment = st.selectbox("Customer segment", dim["segments"], index=0)
            market = st.selectbox("Origin market", dim["markets"], index=0)
        with c2:
            category = st.selectbox("Product category", dim["categories"], index=0)
            payment = st.selectbox("Payment type", dim["payment_types"], index=0)
            scheduled_days = st.number_input("Scheduled shipping days", min_value=0, max_value=10, value=2)
        with c3:
            qty = st.number_input("Order quantity", min_value=1, max_value=50, value=1)
            sales = st.number_input("Sales ($)", min_value=0.0, max_value=10000.0, value=120.0)
            profit = st.number_input("Profit per order ($)", min_value=-500.0, max_value=2000.0, value=15.0)

        c4, c5, c6 = st.columns(3)
        with c4:
            discount_rate = st.number_input("Discount rate", min_value=0.0, max_value=1.0,
                                            value=0.05, step=0.01, format="%.2f")
        with c5:
            day_of_week = st.selectbox(
                "Order day of week",
                options=[1, 2, 3, 4, 5, 6, 7],
                format_func=lambda x: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][x - 1],
                index=0,
            )
        with c6:
            month = st.selectbox("Order month", options=list(range(1, 13)), index=0)

        submitted = st.form_submit_button("Predict", type="primary")

    if submitted:
        X_new = pd.DataFrame([{
            "shipping_mode_name": shipping_mode,
            "customer_segment": segment,
            "category_name": category,
            "market": market,
            "payment_type": payment,
            "days_for_shipping_scheduled": scheduled_days,
            "order_item_quantity": qty,
            "sales": sales,
            "order_profit_per_order": profit,
            "order_item_discount_rate": discount_rate,
            "order_day_of_week": day_of_week,
            "order_month": month,
        }])
        proba_late = float(model.predict_proba(X_new)[0, 1])
        prediction = "LATE" if proba_late >= 0.5 else "ON-TIME"

        st.markdown("### Prediction")
        c1, c2 = st.columns(2)
        c1.metric("Predicted outcome", prediction)
        c2.metric("Probability of late delivery", f"{proba_late * 100:.1f}%")

        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=proba_late * 100,
            title={"text": "Late delivery risk"},
            domain={"x": [0, 1], "y": [0, 1]},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "darkred" if proba_late >= 0.5 else "darkgreen"},
                "steps": [
                    {"range": [0, 30], "color": "#d4edda"},
                    {"range": [30, 70], "color": "#fff3cd"},
                    {"range": [70, 100], "color": "#f8d7da"},
                ],
                "threshold": {"line": {"color": "black", "width": 4},
                              "thickness": 0.75, "value": 50},
            },
        ))
        fig.update_layout(height=320)
        st.plotly_chart(fig, width="stretch")

        if proba_late >= 0.7:
            st.error("⚠️ High delay risk — recommend proactive intervention "
                     "(expedite, alternate carrier, or proactive customer comms).")
        elif proba_late >= 0.4:
            st.warning("⚠️ Moderate delay risk — monitor.")
        else:
            st.success("✅ Low delay risk.")

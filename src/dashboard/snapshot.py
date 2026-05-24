"""
Supply Chain Analytics - Snapshot Exporter

Materializes the MySQL view results to parquet files (and dim values to JSON)
so the dashboard can run without a live database connection. This is what we
ship to Streamlit Cloud.

Run from project root (with venv active):
    python src/dashboard/snapshot.py

Outputs to: data/snapshot/
"""
from __future__ import annotations

import json
import sys
import logging
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.db import get_engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("snapshot")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_DIR = PROJECT_ROOT / "data" / "snapshot"

# All views the dashboard reads
VIEWS = [
    "vw_kpi_summary",
    "vw_shipping_mode_scorecard",
    "vw_market_performance",
    "vw_category_demand_monthly",
    "vw_top_problem_routes",
    "vw_customer_segment_profitability",
]

# Dim values used by the predictor form dropdowns
DIM_QUERIES = {
    "shipping_modes":  "SELECT shipping_mode_name FROM dim_shipping_mode ORDER BY 1",
    "segments":        "SELECT DISTINCT customer_segment FROM dim_customer WHERE customer_segment IS NOT NULL ORDER BY 1",
    "categories":      "SELECT DISTINCT category_name    FROM dim_product  WHERE category_name    IS NOT NULL ORDER BY 1",
    "markets":         "SELECT DISTINCT market           FROM dim_geography WHERE market          IS NOT NULL ORDER BY 1",
    "payment_types":   "SELECT DISTINCT payment_type     FROM fact_orders   WHERE payment_type    IS NOT NULL ORDER BY 1",
}


def main() -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    engine = get_engine()

    log.info("Exporting %d views to %s", len(VIEWS), SNAPSHOT_DIR)
    for view in VIEWS:
        df = pd.read_sql(f"SELECT * FROM {view}", engine)
        out = SNAPSHOT_DIR / f"{view}.parquet"
        df.to_parquet(out, index=False)
        log.info("  %-40s %6d rows -> %s", view, len(df), out.name)

    log.info("Exporting dim values for predictor dropdowns...")
    dim_values = {}
    for key, query in DIM_QUERIES.items():
        col = query.split("SELECT ")[1].split(" FROM")[0].strip()
        # If query has DISTINCT, the column reference is the part after DISTINCT
        col = col.replace("DISTINCT ", "")
        dim_values[key] = pd.read_sql(query, engine)[col].tolist()
        log.info("  %-15s %d values", key, len(dim_values[key]))

    out = SNAPSHOT_DIR / "dim_values.json"
    out.write_text(json.dumps(dim_values, indent=2))
    log.info("Wrote dim values -> %s", out.name)

    log.info("Snapshot complete.")


if __name__ == "__main__":
    main()

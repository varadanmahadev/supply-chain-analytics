"""
Supply Chain Analytics - Ingestion Pipeline (MySQL)

Loads the DataCo Smart Supply Chain CSV into the dimensional warehouse:
  1. Read raw CSV (Latin-1 encoded)
  2. Clean column names, parse dates, handle nulls
  3. Build dim_date, dim_customer, dim_product, dim_geography, dim_shipping_mode
  4. Build fact_orders with surrogate key lookups
  5. Bulk-load everything into MySQL via SQLAlchemy + PyMySQL

Run:
    python src/ingestion/load_data.py
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

import pandas as pd
from sqlalchemy import text

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.db import get_engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ingest")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_CSV = PROJECT_ROOT / os.getenv(
    "RAW_DATA_PATH", "data/raw/DataCoSupplyChainDataset.csv"
)

# Map: source CSV column -> warehouse column
COLUMN_MAP = {
    "Type": "payment_type",
    "Days for shipping (real)": "days_for_shipping_real",
    "Days for shipment (scheduled)": "days_for_shipping_scheduled",
    "Benefit per order": "benefit_per_order",
    "Sales per customer": "sales_per_customer",
    "Delivery Status": "delivery_status",
    "Late_delivery_risk": "late_delivery_risk",
    "Category Id": "category_id",
    "Category Name": "category_name",
    "Customer City": "customer_city",
    "Customer Country": "customer_country",
    "Customer Id": "customer_id",
    "Customer Segment": "customer_segment",
    "Customer State": "customer_state",
    "Customer Zipcode": "customer_zipcode",
    "Department Id": "department_id",
    "Department Name": "department_name",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Market": "market",
    "Order City": "order_city",
    "Order Country": "order_country",
    "order date (DateOrders)": "order_date",
    "Order Id": "order_id",
    "Order Item Discount": "order_item_discount",
    "Order Item Discount Rate": "order_item_discount_rate",
    "Order Item Id": "order_item_id",
    "Order Item Product Price": "order_item_product_price",
    "Order Item Profit Ratio": "order_item_profit_ratio",
    "Order Item Quantity": "order_item_quantity",
    "Sales": "sales",
    "Order Item Total": "order_item_total",
    "Order Profit Per Order": "order_profit_per_order",
    "Order Region": "order_region",
    "Order State": "order_state",
    "Order Status": "order_status",
    "Order Zipcode": "order_zipcode",
    "Product Card Id": "product_card_id",
    "Product Category Id": "product_category_id",
    "Product Name": "product_name",
    "Product Price": "product_price",
    "Product Status": "product_status",
    "shipping date (DateOrders)": "shipping_date",
    "Shipping Mode": "shipping_mode_name",
}


def read_raw() -> pd.DataFrame:
    if not RAW_CSV.exists():
        raise FileNotFoundError(
            f"CSV not found at {RAW_CSV}. "
            "Download DataCoSupplyChainDataset.csv from Kaggle and place it in data/raw/."
        )
    log.info("Reading %s", RAW_CSV)
    df = pd.read_csv(RAW_CSV, encoding="latin-1")
    log.info("Loaded %d rows, %d columns", len(df), df.shape[1])

    keep = [c for c in COLUMN_MAP if c in df.columns]
    df = df[keep].rename(columns=COLUMN_MAP)

    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce")
    df["shipping_date"] = pd.to_datetime(df["shipping_date"], errors="coerce")
    return df


def build_dim_date(df: pd.DataFrame) -> pd.DataFrame:
    dates = pd.concat([df["order_date"], df["shipping_date"]]).dropna().dt.normalize().unique()
    dim = pd.DataFrame({"full_date": pd.to_datetime(sorted(dates))})
    dim["date_key"] = dim["full_date"].dt.strftime("%Y%m%d").astype(int)
    dim["day_of_month"] = dim["full_date"].dt.day
    dim["day_of_week"] = dim["full_date"].dt.dayofweek + 1
    dim["day_name"] = dim["full_date"].dt.day_name().str[:10]
    dim["week_of_year"] = dim["full_date"].dt.isocalendar().week.astype(int)
    dim["month_number"] = dim["full_date"].dt.month
    dim["month_name"] = dim["full_date"].dt.month_name().str[:10]
    dim["quarter"] = dim["full_date"].dt.quarter
    dim["year"] = dim["full_date"].dt.year
    dim["is_weekend"] = dim["day_of_week"].isin([6, 7]).astype(int)
    log.info("dim_date: %d rows", len(dim))
    return dim


def build_dim_customer(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["customer_id", "customer_segment", "customer_city",
            "customer_state", "customer_country", "customer_zipcode"]
    dim = df[cols].drop_duplicates(subset=["customer_id"]).reset_index(drop=True)
    dim["customer_zipcode"] = dim["customer_zipcode"].astype(str).replace("nan", None)
    log.info("dim_customer: %d rows", len(dim))
    return dim


def build_dim_product(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["product_card_id", "product_name", "product_price", "product_status",
            "category_id", "category_name", "department_id", "department_name"]
    dim = df[cols].drop_duplicates(subset=["product_card_id"]).reset_index(drop=True)
    log.info("dim_product: %d rows", len(dim))
    return dim


def build_dim_geography(df: pd.DataFrame) -> pd.DataFrame:
    order_geo = df[["order_city", "order_state", "order_country", "market", "order_region"]].rename(
        columns={"order_city": "city", "order_state": "state",
                 "order_country": "country", "order_region": "region"}
    )
    cust_geo = df[["customer_city", "customer_state", "customer_country", "market"]].rename(
        columns={"customer_city": "city", "customer_state": "state", "customer_country": "country"}
    )
    cust_geo["region"] = None

    geo = pd.concat([order_geo, cust_geo], ignore_index=True)
    # MySQL unique key treats NULL as distinct; collapse on a normalized key
    for c in ["city", "state", "country", "market"]:
        geo[c] = geo[c].fillna("__NA__")
    geo = geo.drop_duplicates(subset=["city", "state", "country", "market"]).reset_index(drop=True)
    # Restore NULLs for storage
    for c in ["city", "state", "country", "market"]:
        geo[c] = geo[c].replace("__NA__", None)

    coords = (df[["order_city", "order_country", "latitude", "longitude"]]
              .dropna(subset=["latitude", "longitude"])
              .drop_duplicates(subset=["order_city", "order_country"])
              .rename(columns={"order_city": "city", "order_country": "country"}))
    geo = geo.merge(coords, on=["city", "country"], how="left")

    log.info("dim_geography: %d rows", len(geo))
    return geo


def build_dim_shipping_mode(df: pd.DataFrame) -> pd.DataFrame:
    dim = pd.DataFrame({"shipping_mode_name": df["shipping_mode_name"].dropna().unique()}).reset_index(drop=True)
    log.info("dim_shipping_mode: %d rows", len(dim))
    return dim


def write_dim(df: pd.DataFrame, table: str, engine) -> None:
    df.to_sql(table, engine, if_exists="append", index=False, method="multi", chunksize=1000)


def load_dimensions(engine, df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    log.info("Building dimensions...")
    dim_date = build_dim_date(df)
    dim_customer = build_dim_customer(df)
    dim_product = build_dim_product(df)
    dim_geography = build_dim_geography(df)
    dim_shipping_mode = build_dim_shipping_mode(df)

    log.info("Writing dimensions to MySQL...")
    write_dim(dim_date, "dim_date", engine)
    write_dim(dim_customer, "dim_customer", engine)
    write_dim(dim_product, "dim_product", engine)
    write_dim(dim_geography, "dim_geography", engine)
    write_dim(dim_shipping_mode, "dim_shipping_mode", engine)

    # Re-read so we get the AUTO_INCREMENT surrogate keys assigned by MySQL
    return {
        "dim_date": pd.read_sql("SELECT date_key, full_date FROM dim_date", engine),
        "dim_customer": pd.read_sql("SELECT customer_key, customer_id FROM dim_customer", engine),
        "dim_product": pd.read_sql("SELECT product_key, product_card_id FROM dim_product", engine),
        "dim_geography": pd.read_sql(
            "SELECT geography_key, city, state, country, market FROM dim_geography", engine
        ),
        "dim_shipping_mode": pd.read_sql(
            "SELECT shipping_mode_key, shipping_mode_name FROM dim_shipping_mode", engine
        ),
    }


def build_facts(df: pd.DataFrame, dims: dict[str, pd.DataFrame]) -> pd.DataFrame:
    log.info("Building fact_orders with FK lookups...")
    f = df.copy()

    f["order_date_key"] = f["order_date"].dt.strftime("%Y%m%d").astype("Int64")
    f["shipping_date_key"] = f["shipping_date"].dt.strftime("%Y%m%d").astype("Int64")

    f = f.merge(dims["dim_customer"], on="customer_id", how="left")
    f = f.merge(dims["dim_product"], on="product_card_id", how="left")
    f = f.merge(dims["dim_shipping_mode"], on="shipping_mode_name", how="left")

    # Match the NULL normalization used when building dim_geography
    geo_db = dims["dim_geography"].copy()
    for c in ["city", "state", "country", "market"]:
        geo_db[c] = geo_db[c].fillna("__NA__")

    order_geo_lookup = geo_db.rename(
        columns={"geography_key": "order_geography_key",
                 "city": "order_city", "state": "order_state",
                 "country": "order_country"}
    )[["order_geography_key", "order_city", "order_state", "order_country", "market"]]

    cust_geo_lookup = geo_db.rename(
        columns={"geography_key": "customer_geography_key",
                 "city": "customer_city", "state": "customer_state",
                 "country": "customer_country"}
    )[["customer_geography_key", "customer_city", "customer_state", "customer_country", "market"]]

    for c in ["order_city", "order_state", "order_country", "customer_city",
              "customer_state", "customer_country", "market"]:
        f[c] = f[c].fillna("__NA__")

    f = f.merge(order_geo_lookup, on=["order_city", "order_state", "order_country", "market"], how="left")
    f = f.merge(cust_geo_lookup, on=["customer_city", "customer_state", "customer_country", "market"], how="left")

    fact_cols = [
        "order_item_id", "order_id",
        "order_date_key", "shipping_date_key",
        "customer_key", "product_key",
        "order_geography_key", "customer_geography_key",
        "shipping_mode_key",
        "order_status", "delivery_status", "payment_type",
        "days_for_shipping_real", "days_for_shipping_scheduled", "late_delivery_risk",
        "order_item_quantity", "order_item_product_price",
        "order_item_discount", "order_item_discount_rate",
        "order_item_total", "sales", "order_profit_per_order",
        "order_item_profit_ratio", "benefit_per_order", "sales_per_customer",
    ]
    fact = f[fact_cols].drop_duplicates(subset=["order_item_id"])
    log.info("fact_orders: %d rows", len(fact))
    return fact


def load_facts(engine, fact: pd.DataFrame) -> None:
    log.info("Writing fact_orders to MySQL (this is the big one)...")
    fact.to_sql(
        "fact_orders", engine,
        if_exists="append", index=False,
        method="multi", chunksize=1000,
    )
    log.info("Done.")


def truncate_warehouse(engine) -> None:
    """Wipe the warehouse so the script is idempotent.

    MySQL won't allow TRUNCATE on tables referenced by FKs unless we
    disable foreign key checks first.
    """
    log.info("Truncating warehouse tables for fresh load...")
    with engine.begin() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for tbl in ["fact_orders", "dim_date", "dim_customer", "dim_product",
                    "dim_geography", "dim_shipping_mode"]:
            conn.execute(text(f"TRUNCATE TABLE {tbl}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def main() -> None:
    start = datetime.now()
    engine = get_engine()

    truncate_warehouse(engine)
    df = read_raw()
    dims = load_dimensions(engine, df)
    fact = build_facts(df, dims)
    load_facts(engine, fact)

    elapsed = (datetime.now() - start).total_seconds()
    log.info("=" * 50)
    log.info("Ingestion complete in %.1f seconds", elapsed)

    with engine.connect() as conn:
        for tbl in ["dim_date", "dim_customer", "dim_product",
                    "dim_geography", "dim_shipping_mode", "fact_orders"]:
            n = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar_one()
            log.info("  %-22s %s rows", tbl, f"{n:,}")


if __name__ == "__main__":
    main()

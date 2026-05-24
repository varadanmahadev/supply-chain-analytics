"""
Supply Chain Analytics - Late Delivery Prediction Model

Trains a binary classifier to predict whether a shipment will arrive late:
  1. Pulls a denormalized feature set from the MySQL warehouse
  2. Target: delivery_status == 'Late delivery'
  3. Trains Logistic Regression (baseline) and Gradient Boosting (champion)
  4. Compares on ROC-AUC + F1; saves the best pipeline as a joblib artifact

Run from project root (with venv active):
    python src/models/train.py

The output artifact lives at: src/models/late_delivery_classifier.joblib
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from datetime import datetime

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score, f1_score
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

# Allow `python src/models/train.py` from project root
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.db import get_engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("train")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = PROJECT_ROOT / "src" / "models"
MODEL_PATH = MODEL_DIR / "late_delivery_classifier.joblib"
METRICS_PATH = MODEL_DIR / "model_metrics.txt"

# Features used by both models
CATEGORICAL = [
    "shipping_mode_name",
    "customer_segment",
    "category_name",
    "market",
    "payment_type",
]
NUMERICAL = [
    "days_for_shipping_scheduled",
    "order_item_quantity",
    "sales",
    "order_profit_per_order",
    "order_item_discount_rate",
    "order_day_of_week",
    "order_month",
]

# Pulls a denormalized analytical dataset for training.
# We exclude cancelled shipments since 'late vs on-time' isn't meaningful there.
SQL_QUERY = """
SELECT
    f.delivery_status,
    f.days_for_shipping_scheduled,
    f.order_item_quantity,
    f.sales,
    f.order_profit_per_order,
    f.order_item_discount_rate,
    f.payment_type,
    sm.shipping_mode_name,
    c.customer_segment,
    p.category_name,
    g.market,
    d.day_of_week  AS order_day_of_week,
    d.month_number AS order_month
FROM fact_orders f
LEFT JOIN dim_shipping_mode sm ON sm.shipping_mode_key = f.shipping_mode_key
LEFT JOIN dim_customer      c  ON c.customer_key       = f.customer_key
LEFT JOIN dim_product       p  ON p.product_key        = f.product_key
LEFT JOIN dim_geography     g  ON g.geography_key      = f.order_geography_key
LEFT JOIN dim_date          d  ON d.date_key           = f.order_date_key
WHERE f.delivery_status IN ('Late delivery', 'Advance shipping', 'Shipping on time')
"""


def load_data() -> pd.DataFrame:
    """Pull the training set from the warehouse and engineer the target."""
    engine = get_engine()
    log.info("Pulling training data from MySQL...")
    df = pd.read_sql(SQL_QUERY, engine)
    log.info("Loaded %d rows", len(df))

    df["is_late"] = (df["delivery_status"] == "Late delivery").astype(int)

    n_pos = int(df["is_late"].sum())
    n_neg = len(df) - n_pos
    log.info("Target balance:")
    log.info("  on-time / advance : %6d  (%5.2f%%)", n_neg, 100 * n_neg / len(df))
    log.info("  late              : %6d  (%5.2f%%)", n_pos, 100 * n_pos / len(df))

    # Fill any null categoricals with a sentinel so OneHotEncoder doesn't error
    for c in CATEGORICAL:
        df[c] = df[c].fillna("UNKNOWN")

    return df


def build_preprocessor() -> ColumnTransformer:
    """Numerical -> StandardScaler, Categorical -> OneHotEncoder."""
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERICAL),
            # sparse_output=False -> dense numpy; required by HistGradientBoosting,
            # and fine for LogisticRegression at this dataset size.
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ],
        remainder="drop",
    )


def evaluate(name: str, model, X_test, y_test) -> dict:
    """Print classification report + confusion matrix; return metrics."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)
    f1 = f1_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)

    log.info("=" * 60)
    log.info("Model: %s", name)
    log.info("  ROC-AUC : %.4f", auc)
    log.info("  F1      : %.4f", f1)
    log.info("Confusion matrix:")
    log.info("                  Pred on-time   Pred late")
    log.info("  Actual on-time   %8d      %8d", cm[0, 0], cm[0, 1])
    log.info("  Actual late      %8d      %8d", cm[1, 0], cm[1, 1])
    log.info("\nClassification report:\n%s",
             classification_report(y_test, y_pred,
                                   target_names=["on-time", "late"], digits=4))
    return {"name": name, "auc": auc, "f1": f1, "model": model}


def write_metrics(results: list[dict], best_name: str) -> None:
    """Persist a human-readable summary of model comparison."""
    lines = ["Supply Chain Late Delivery Classifier - Training Run",
             "=" * 60]
    for r in results:
        lines += [f"Model: {r['name']}",
                  f"  ROC-AUC: {r['auc']:.4f}",
                  f"  F1     : {r['f1']:.4f}", ""]
    lines += [f"Selected best model: {best_name}",
              f"Trained at: {datetime.now().isoformat(timespec='seconds')}"]
    METRICS_PATH.write_text("\n".join(lines))
    log.info("Wrote metrics summary to %s", METRICS_PATH)


def main() -> None:
    start = datetime.now()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    df = load_data()
    X = df[CATEGORICAL + NUMERICAL]
    y = df["is_late"]

    log.info("Train/test split (80/20, stratified)...")
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y,
    )
    log.info("Train: %d rows, Test: %d rows", len(X_train), len(X_test))

    # ---------- Model 1: Logistic Regression ----------
    log.info("Training Logistic Regression (baseline)...")
    lr_pipeline = Pipeline([
        ("preprocess", build_preprocessor()),
        ("clf", LogisticRegression(max_iter=1000, n_jobs=-1)),
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_results = evaluate("Logistic Regression", lr_pipeline, X_test, y_test)

    # ---------- Model 2: Gradient Boosting ----------
    log.info("Training Gradient Boosting (champion)...")
    gb_pipeline = Pipeline([
        ("preprocess", build_preprocessor()),
        ("clf", HistGradientBoostingClassifier(
            max_iter=200, learning_rate=0.1, max_depth=6, random_state=42,
        )),
    ])
    gb_pipeline.fit(X_train, y_train)
    gb_results = evaluate("Gradient Boosting", gb_pipeline, X_test, y_test)

    # ---------- Pick winner (by ROC-AUC) and persist ----------
    best = max([lr_results, gb_results], key=lambda r: r["auc"])
    log.info("=" * 60)
    log.info("Best model: %s  (ROC-AUC=%.4f, F1=%.4f)",
             best["name"], best["auc"], best["f1"])

    log.info("Saving best model to %s", MODEL_PATH)
    joblib.dump(best["model"], MODEL_PATH)

    write_metrics([lr_results, gb_results], best["name"])

    elapsed = (datetime.now() - start).total_seconds()
    log.info("Training complete in %.1f seconds", elapsed)


if __name__ == "__main__":
    main()

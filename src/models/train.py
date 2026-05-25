"""
Supply Chain Analytics - Late Delivery Prediction Model (Phase 6)

Phase 6 improvements over the baseline:
  - New features: is_international, order_quarter, order_item_discount ($)
  - Class balancing (class_weight='balanced') to lift recall on the 'late' class
  - Threshold analysis: scores at multiple cutoffs printed after training
  - Same Pipeline pattern, persisted as a joblib artifact

Run from project root (with venv active):
    python src/models/train.py

Outputs:
  - src/models/late_delivery_classifier.joblib
  - src/models/model_metrics.txt
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report, confusion_matrix,
    roc_auc_score, f1_score, precision_score, recall_score
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

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

# ============================================================
# Features
# ============================================================
CATEGORICAL = [
    "shipping_mode_name",
    "customer_segment",
    "category_name",
    "origin_market",
    "payment_type",
]
NUMERICAL = [
    "days_for_shipping_scheduled",
    "order_item_quantity",
    "sales",
    "order_profit_per_order",
    "order_item_discount_rate",
    "order_item_discount",        # NEW: actual $ discount amount
    "order_day_of_week",
    "order_month",
    "order_quarter",              # NEW: quarter of year
    "is_international",           # NEW: origin market != destination market
]

# Pulls a denormalized training set with the new features
SQL_QUERY = """
SELECT
    f.delivery_status,
    f.days_for_shipping_scheduled,
    f.order_item_quantity,
    f.sales,
    f.order_profit_per_order,
    f.order_item_discount_rate,
    f.order_item_discount,
    f.payment_type,
    sm.shipping_mode_name,
    c.customer_segment,
    p.category_name,
    og.market AS origin_market,
    cg.market AS destination_market,
    CASE WHEN og.market <> cg.market THEN 1 ELSE 0 END AS is_international,
    d.day_of_week  AS order_day_of_week,
    d.month_number AS order_month,
    d.quarter      AS order_quarter
FROM fact_orders f
LEFT JOIN dim_shipping_mode sm ON sm.shipping_mode_key = f.shipping_mode_key
LEFT JOIN dim_customer      c  ON c.customer_key       = f.customer_key
LEFT JOIN dim_product       p  ON p.product_key        = f.product_key
LEFT JOIN dim_geography     og ON og.geography_key     = f.order_geography_key
LEFT JOIN dim_geography     cg ON cg.geography_key     = f.customer_geography_key
LEFT JOIN dim_date          d  ON d.date_key           = f.order_date_key
WHERE f.delivery_status IN ('Late delivery', 'Advance shipping', 'Shipping on time')
"""


def load_data() -> pd.DataFrame:
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

    # International share - quick sanity check on the new feature
    intl_share = 100 * df["is_international"].mean()
    log.info("New feature - International shipments: %.1f%%", intl_share)

    for c in CATEGORICAL:
        df[c] = df[c].fillna("UNKNOWN")

    return df


def build_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERICAL),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
        ],
        remainder="drop",
    )


def evaluate(name: str, model, X_test, y_test) -> dict:
    """Default-threshold (0.5) evaluation."""
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_proba)
    f1 = f1_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)

    log.info("=" * 60)
    log.info("Model: %s  (threshold=0.50)", name)
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


def threshold_table(name: str, model, X_test, y_test) -> None:
    """Compute precision/recall/F1 across decision thresholds — the headline Phase 6 output."""
    y_proba = model.predict_proba(X_test)[:, 1]
    log.info("=" * 60)
    log.info("THRESHOLD ANALYSIS: %s", name)
    log.info("(How prediction quality changes as the cutoff for 'late' shifts)")
    log.info("")
    log.info("  Threshold    Precision    Recall    F1     Predicted-Late-Count")
    log.info("  ---------    ---------    ------    -----  --------------------")
    for thr in [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        y_pred_thr = (y_proba >= thr).astype(int)
        prec = precision_score(y_test, y_pred_thr, zero_division=0)
        rec = recall_score(y_test, y_pred_thr, zero_division=0)
        f1 = f1_score(y_test, y_pred_thr, zero_division=0)
        n_pred_late = int(y_pred_thr.sum())
        log.info("    %.2f         %.4f      %.4f    %.4f      %d",
                 thr, prec, rec, f1, n_pred_late)
    log.info("")
    log.info("Note: lower threshold = catch more late shipments (higher recall) "
             "at the cost of more false alarms (lower precision).")


def write_metrics(results: list[dict], best_name: str) -> None:
    lines = [
        "Supply Chain Late Delivery Classifier",
        "Phase 6: feature engineering + class balancing",
        "=" * 60,
    ]
    for r in results:
        lines += [f"Model: {r['name']}",
                  f"  ROC-AUC: {r['auc']:.4f}",
                  f"  F1     : {r['f1']:.4f}", ""]
    lines += [f"Features ({len(NUMERICAL) + len(CATEGORICAL)}):",
              f"  Numerical:   {NUMERICAL}",
              f"  Categorical: {CATEGORICAL}",
              ""]
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

    # ---------- Model 1: Logistic Regression with balanced classes ----------
    log.info("Training Logistic Regression (baseline, class-balanced)...")
    lr_pipeline = Pipeline([
        ("preprocess", build_preprocessor()),
        ("clf", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    lr_pipeline.fit(X_train, y_train)
    lr_results = evaluate("Logistic Regression (balanced)", lr_pipeline, X_test, y_test)

    # ---------- Model 2: Gradient Boosting with balanced classes ----------
    log.info("Training Gradient Boosting (champion, class-balanced)...")
    gb_pipeline = Pipeline([
        ("preprocess", build_preprocessor()),
        ("clf", HistGradientBoostingClassifier(
            max_iter=250, learning_rate=0.08, max_depth=7,
            class_weight="balanced", random_state=42,
        )),
    ])
    gb_pipeline.fit(X_train, y_train)
    gb_results = evaluate("Gradient Boosting (balanced)", gb_pipeline, X_test, y_test)

    # ---------- Threshold analysis on both models ----------
    threshold_table(lr_results["name"], lr_pipeline, X_test, y_test)
    threshold_table(gb_results["name"], gb_pipeline, X_test, y_test)

    # ---------- Pick winner and persist ----------
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

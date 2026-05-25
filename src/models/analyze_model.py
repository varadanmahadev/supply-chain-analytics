"""
Supply Chain Analytics - Model Analyzer (Phase 6)

Deep-dive analysis of the trained classifier:
  - Threshold sensitivity table (precision/recall/F1)
  - Permutation feature importance (which features actually matter)
  - Business cost simulation: find the threshold that minimizes operational cost
    given assumed cost-per-error for false positives and false negatives

Run from project root AFTER training a model:
    python src/models/analyze_model.py
"""
from __future__ import annotations

import sys
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    confusion_matrix, precision_score, recall_score, f1_score
)
from sklearn.model_selection import train_test_split

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.db import get_engine  # noqa: E402
from src.models.train import SQL_QUERY, CATEGORICAL, NUMERICAL  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("analyze")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = PROJECT_ROOT / "src" / "models" / "late_delivery_classifier.joblib"

# ---- Business cost assumptions ----
# These are the levers you'd discuss with operations.
# At a 3PL, a missed late delivery (customer impact) is far more costly than
# an unnecessary expedite (just shipping cost).
COST_FALSE_POSITIVE = 25    # $: expediting a shipment that would've been on time
COST_FALSE_NEGATIVE = 150   # $: missed late delivery (refund + customer churn risk)


def load_test_data():
    """Reconstruct the same train/test split as training (random_state=42)."""
    engine = get_engine()
    df = pd.read_sql(SQL_QUERY, engine)
    df["is_late"] = (df["delivery_status"] == "Late delivery").astype(int)
    for c in CATEGORICAL:
        df[c] = df[c].fillna("UNKNOWN")

    X = df[CATEGORICAL + NUMERICAL]
    y = df["is_late"]
    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y,
    )
    return X_test, y_test


def threshold_sweep(model, X_test, y_test) -> pd.DataFrame:
    """Compute metrics at fine-grained thresholds. Returns a tidy DataFrame."""
    y_proba = model.predict_proba(X_test)[:, 1]
    rows = []
    for thr in np.arange(0.20, 0.81, 0.02):
        y_pred = (y_proba >= thr).astype(int)
        cm = confusion_matrix(y_test, y_pred)
        tn, fp, fn, tp = cm.ravel()
        rows.append({
            "threshold": round(thr, 2),
            "precision": precision_score(y_test, y_pred, zero_division=0),
            "recall": recall_score(y_test, y_pred, zero_division=0),
            "f1": f1_score(y_test, y_pred, zero_division=0),
            "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "total_cost_$": fp * COST_FALSE_POSITIVE + fn * COST_FALSE_NEGATIVE,
        })
    return pd.DataFrame(rows)


def business_cost_analysis(df: pd.DataFrame) -> None:
    """Find the threshold minimizing total expected operational cost."""
    log.info("=" * 70)
    log.info("BUSINESS COST ANALYSIS")
    log.info("(Find the threshold that minimizes total operational cost)")
    log.info("")
    log.info("Cost assumptions:")
    log.info("  False positive (unnecessary expedite): $%d per shipment", COST_FALSE_POSITIVE)
    log.info("  False negative (missed late delivery): $%d per shipment", COST_FALSE_NEGATIVE)
    log.info("")

    best = df.loc[df["total_cost_$"].idxmin()]
    default = df.loc[(df["threshold"] - 0.50).abs().idxmin()]

    log.info("Cost-optimal threshold:")
    log.info("  Threshold      : %.2f", best["threshold"])
    log.info("  Total cost     : $%s", f"{int(best['total_cost_$']):,}")
    log.info("  Precision      : %.4f", best["precision"])
    log.info("  Recall         : %.4f", best["recall"])
    log.info("  F1             : %.4f", best["f1"])
    log.info("")
    log.info("Default threshold (0.50) baseline:")
    log.info("  Total cost     : $%s", f"{int(default['total_cost_$']):,}")
    savings = default["total_cost_$"] - best["total_cost_$"]
    pct_saving = 100 * savings / default["total_cost_$"] if default["total_cost_$"] else 0
    log.info("")
    log.info("Savings from tuning the threshold: $%s  (%.1f%%)",
             f"{int(savings):,}", pct_saving)
    log.info("")
    log.info("Interpretation: at our assumed cost structure, lowering the")
    log.info("threshold below 0.50 catches more late shipments. Each missed")
    log.info("late is %dx more costly than a false alarm.",
             COST_FALSE_NEGATIVE // COST_FALSE_POSITIVE)


def threshold_summary_table(df: pd.DataFrame) -> None:
    """Print a clean 9-row summary of the threshold sweep."""
    sample = df[df["threshold"].isin([0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70])]
    log.info("=" * 70)
    log.info("THRESHOLD SENSITIVITY TABLE")
    log.info("")
    log.info("  Threshold   Precision   Recall    F1      Total Cost ($)")
    log.info("  ---------   ---------   ------    -----   --------------")
    for _, r in sample.iterrows():
        log.info("    %.2f       %.4f     %.4f   %.4f       %s",
                 r["threshold"], r["precision"], r["recall"], r["f1"],
                 f"{int(r['total_cost_$']):>10,}")


def feature_importance(model, X_test, y_test, top_n: int = 12) -> None:
    """Permutation importance: shuffle each feature, see how much accuracy drops."""
    log.info("=" * 70)
    log.info("FEATURE IMPORTANCE (Permutation, n_repeats=5)")
    log.info("(Higher score = more important to model accuracy)")
    log.info("")

    result = permutation_importance(
        model, X_test, y_test,
        n_repeats=5, random_state=42, n_jobs=-1, scoring="roc_auc",
    )
    importance = pd.DataFrame({
        "feature": X_test.columns,
        "importance_mean": result.importances_mean,
        "importance_std": result.importances_std,
    }).sort_values("importance_mean", ascending=False).head(top_n)

    log.info("  Rank   Feature                              Importance    ± Std")
    log.info("  ----   ----------------------------------   ----------    -----")
    for rank, (_, row) in enumerate(importance.iterrows(), start=1):
        log.info("   %2d    %-36s   %.4f       %.4f",
                 rank, row["feature"], row["importance_mean"], row["importance_std"])


def main() -> None:
    if not MODEL_PATH.exists():
        log.error("Model artifact not found at %s", MODEL_PATH)
        log.error("Run `python src/models/train.py` first.")
        return

    log.info("Loading model from %s", MODEL_PATH)
    model = joblib.load(MODEL_PATH)

    log.info("Reconstructing test set from MySQL...")
    X_test, y_test = load_test_data()
    log.info("Test set: %d rows", len(X_test))

    df = threshold_sweep(model, X_test, y_test)
    threshold_summary_table(df)
    business_cost_analysis(df)
    feature_importance(model, X_test, y_test)

    log.info("=" * 70)
    log.info("Analysis complete.")


if __name__ == "__main__":
    main()

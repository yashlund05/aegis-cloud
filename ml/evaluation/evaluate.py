"""
Evaluation module for Aegis ML pipeline.
Provides WMAPE, Pinball loss, interval coverage calculation,
and walk-forward rolling-origin cross-validation for time series.
"""

import json
import logging
from typing import Dict, Any, List, Tuple
import pandas as pd
import numpy as np

from ml.training.train_lightgbm import train_quantile_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def wmape(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Weighted Mean Absolute Percentage Error:
    WMAPE = sum(|y_true - y_pred|) / sum(|y_true|)
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    denom = np.sum(np.abs(y_t))
    if denom == 0:
        return 0.0
    return float(np.sum(np.abs(y_t - y_p)) / denom)


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, quantile: float) -> float:
    """
    Pinball (quantile) loss:
    L_tau(y, y_hat) = max(tau * (y - y_hat), (tau - 1) * (y - y_hat))
    """
    y_t = np.asarray(y_true, dtype=float)
    y_p = np.asarray(y_pred, dtype=float)
    diff = y_t - y_p
    return float(np.mean(np.maximum(quantile * diff, (quantile - 1.0) * diff)))


def interval_coverage(y_true: np.ndarray, y_lower: np.ndarray, y_upper: np.ndarray) -> float:
    """
    Percentage of actual observations bounded inside the [y_lower, y_upper] prediction interval.
    For a p10-p90 forecast, target coverage is >= 80-85%.
    """
    y_t = np.asarray(y_true, dtype=float)
    y_l = np.asarray(y_lower, dtype=float)
    y_u = np.asarray(y_upper, dtype=float)
    covered = (y_t >= y_l) & (y_t <= y_u)
    return float(np.mean(covered))


def walk_forward_validation(
    df: pd.DataFrame,
    horizon: int = 10,
    quantiles: List[float] = None,
    n_splits: int = 5,
    target_col: str = "cpu_usage",
) -> Dict[str, Any]:
    """
    Rolling-origin walk-forward temporal cross-validation.
    Splits the time series into expanding chronological training windows
    and tests on subsequent non-overlapping periods without shuffling.
    """
    quantiles = quantiles or [0.1, 0.5, 0.9]
    exclude_cols = [target_col, "timestamp", "workload_id", "status"]
    feature_cols = [c for c in df.columns if c not in exclude_cols and pd.api.types.is_numeric_dtype(df[c])]

    n = len(df)
    min_train_size = int(n * 0.4)
    step_size = (n - min_train_size) // (n_splits + 1)

    logger.info(
        f"Starting walk-forward validation: total={n}, min_train={min_train_size}, "
        f"step={step_size}, splits={n_splits}"
    )

    folds = []
    wmapes_p50 = []
    pinball_losses = {q: [] for q in quantiles}
    coverages = []

    for fold in range(n_splits):
        train_end = min_train_size + fold * step_size
        test_end = min(train_end + step_size, n)

        train_data = df.iloc[:train_end].copy()
        test_data = df.iloc[train_end:test_end].copy()

        y_train = train_data[target_col].shift(-horizon)
        y_test = test_data[target_col].shift(-horizon)

        valid_train = y_train.notna()
        valid_test = y_test.notna()

        X_tr, y_tr = train_data.loc[valid_train, feature_cols], y_train[valid_train]
        X_te, y_te = test_data.loc[valid_test, feature_cols], y_test[valid_test]

        if len(X_te) == 0:
            continue

        # Split train into train & val for early stopping
        val_split = int(len(X_tr) * 0.85)
        X_t, y_t = X_tr.iloc[:val_split], y_tr.iloc[:val_split]
        X_v, y_v = X_tr.iloc[val_split:], y_tr.iloc[val_split:]

        predictions = {}
        for q in quantiles:
            wrapper = train_quantile_model(X_t, y_t, X_v, y_v, quantile=q)
            pred = wrapper.predict(X_te)
            predictions[q] = pred
            p_loss = pinball_loss(y_te.values, pred, quantile=q)
            pinball_losses[q].append(p_loss)

        # Evaluate p50 WMAPE
        fold_wmape = wmape(y_te.values, predictions[0.5])
        wmapes_p50.append(fold_wmape)

        # Evaluate p10-p90 coverage
        if 0.1 in predictions and 0.9 in predictions:
            cov = interval_coverage(y_te.values, predictions[0.1], predictions[0.9])
            coverages.append(cov)
        else:
            cov = 0.0

        fold_summary = {
            "fold": fold + 1,
            "train_size": len(X_tr),
            "test_size": len(X_te),
            "wmape_p50": round(fold_wmape, 4),
            "coverage_p10_p90": round(cov, 4),
            "pinball_loss": {q: round(pinball_losses[q][-1], 4) for q in quantiles},
        }
        folds.append(fold_summary)
        logger.info(f"Fold {fold + 1} - WMAPE(p50): {fold_wmape:.4f}, Coverage: {cov:.4f}")

    avg_wmape = float(np.mean(wmapes_p50)) if wmapes_p50 else 0.0
    avg_coverage = float(np.mean(coverages)) if coverages else 0.0
    avg_pinball = {q: float(np.mean(pinball_losses[q])) for q in quantiles}

    report = {
        "horizon_minutes": horizon,
        "n_splits": n_splits,
        "average_metrics": {
            "mean_wmape_p50": round(avg_wmape, 4),
            "mean_coverage_p10_p90": round(avg_coverage, 4),
            "mean_pinball_loss": {q: round(val, 4) for q, val in avg_pinball.items()},
        },
        "target_met": {
            "wmape_threshold": avg_wmape < 0.35,
            "coverage_threshold": avg_coverage >= 0.80,
        },
        "folds": folds,
    }

    return report


def generate_evaluation_report(results: dict, output_path: str = "ml/evaluation/report.json") -> None:
    """
    Saves validation report as structured JSON.
    """
    import os

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Evaluation report successfully saved to {output_path}")

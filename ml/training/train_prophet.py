"""
Baseline forecasting models for comparison against Aegis Quantile LightGBM models.
Implements Facebook Prophet baseline (if installed) and an Exponential Smoothing baseline.
"""

from typing import Dict, Any
import numpy as np
import pandas as pd
import logging

from ml.evaluation.evaluate import wmape

logger = logging.getLogger(__name__)


def train_prophet_baseline(df: pd.DataFrame, horizon_minutes: int = 10, target_col: str = "cpu_usage") -> Dict[str, Any]:
    """
    Trains a baseline model for workload demand forecasting to benchmark against LightGBM.
    """
    if "timestamp" not in df.columns or target_col not in df.columns:
        raise ValueError(f"DataFrame must contain 'timestamp' and '{target_col}' columns.")

    data = df[["timestamp", target_col]].dropna().copy()
    data.columns = ["ds", "y"]

    train_size = int(len(data) * 0.8)
    train_df = data.iloc[:train_size]
    test_df = data.iloc[train_size:]

    try:
        from prophet import Prophet

        logger.info(f"Fitting Prophet baseline for horizon={horizon_minutes}m...")
        m = Prophet(interval_width=0.8, daily_seasonality=True, weekly_seasonality=True)
        m.fit(train_df)

        future = m.make_future_dataframe(periods=len(test_df), freq="1min")
        forecast = m.predict(future)
        y_pred = forecast.iloc[-len(test_df) :]["yhat"].values
        model_type = "prophet"
    except ImportError:
        logger.info("Prophet not installed; using Exponential Smoothing baseline.")
        # Holt-Winters / Exponential Smoothing fallback
        alpha = 0.3
        y_train = train_df["y"].values
        smoothed = [y_train[0]]
        for val in y_train[1:]:
            smoothed.append(alpha * val + (1 - alpha) * smoothed[-1])

        last_val = smoothed[-1]
        y_pred = np.full(len(test_df), last_val)
        model_type = "exponential_smoothing_baseline"

    baseline_wmape = wmape(test_df["y"].values, y_pred)

    return {
        "model_type": model_type,
        "horizon_minutes": horizon_minutes,
        "test_samples": len(test_df),
        "baseline_wmape": round(baseline_wmape, 4),
        "y_pred_mean": round(float(np.mean(y_pred)), 4),
    }

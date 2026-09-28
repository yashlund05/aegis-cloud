"""
Prophet baseline model training module.
This is the baseline model for comparison against the LightGBM quantile regression.
"""

import logging
import pandas as pd
from typing import Dict, Any

logger = logging.getLogger(__name__)

def train_prophet_baseline(df: pd.DataFrame, horizon_minutes: int,
                           target_col: str = "cpu_usage") -> Dict[str, Any]:
    """
    Train a Prophet baseline model for workload demand forecasting.
    Returns a dict with the fitted model and evaluation metrics.
    """
    try:
        from prophet import Prophet
    except ImportError:
        logger.warning("Prophet not installed. Install via: pip install prophet")
        return {"error": "prophet not installed", "model": None}

    # Prophet requires columns 'ds' (datetime) and 'y' (value)
    prophet_df = pd.DataFrame()

    if isinstance(df.index, pd.DatetimeIndex):
        prophet_df['ds'] = df.index
        prophet_df['y'] = df[target_col].values
    elif 'timestamp' in df.columns:
        prophet_df['ds'] = pd.to_datetime(df['timestamp'])
        prophet_df['y'] = df[target_col].values
    else:
        raise ValueError("DataFrame must have a DatetimeIndex or 'timestamp' column")

    prophet_df = prophet_df.dropna()

    # Split: last horizon_minutes for validation
    cutoff = prophet_df['ds'].max() - pd.Timedelta(minutes=horizon_minutes)
    train = prophet_df[prophet_df['ds'] <= cutoff]
    test = prophet_df[prophet_df['ds'] > cutoff]

    # Fit model
    model = Prophet(
        daily_seasonality=True,
        weekly_seasonality=True,
        changepoint_prior_scale=0.05,
        interval_width=0.80
    )
    model.fit(train)

    # Predict
    future = model.make_future_dataframe(periods=len(test), freq='min')
    forecast = model.predict(future)

    # Evaluate on test set
    forecast_test = forecast[forecast['ds'] > cutoff].head(len(test))

    if len(forecast_test) > 0 and len(test) > 0:
        import numpy as np
        y_true = test['y'].values[:len(forecast_test)]
        y_pred = forecast_test['yhat'].values[:len(y_true)]

        mae = float(np.mean(np.abs(y_true - y_pred)))
        wmape = float(np.sum(np.abs(y_true - y_pred)) / np.sum(np.abs(y_true))) if np.sum(np.abs(y_true)) > 0 else 0.0

        return {
            "model": model,
            "metrics": {
                "mae": mae,
                "wmape": wmape,
                "test_size": len(y_true),
                "horizon_minutes": horizon_minutes,
            }
        }
    else:
        return {"model": model, "metrics": {"error": "insufficient test data"}}

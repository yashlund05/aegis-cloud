"""
Unit tests for LightGBM / Gradient Boosting Quantile Regression training and registry.
"""

import os
import pytest
import pandas as pd
import numpy as np
from ml.training.train_lightgbm import train_quantile_model, train_all_models
from ml.models.registry import ModelRegistry


class TestQuantileTraining:
    @pytest.fixture
    def sample_features_df(self):
        np.random.seed(42)
        n = 300
        # Create synthetic feature dataset
        t = np.linspace(0, 10, n)
        cpu = 0.4 + 0.3 * np.sin(t) + np.random.normal(0, 0.05, n)
        cpu = np.clip(cpu, 0.05, 1.2)
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=n, freq="1min"),
                "cpu_usage": cpu,
                "memory_usage": 0.5 + np.random.normal(0, 0.02, n),
                "rolling_mean_15min": pd.Series(cpu).rolling(15, min_periods=1).mean(),
                "lag_1": pd.Series(cpu).shift(1).fillna(0.4),
                "lag_2": pd.Series(cpu).shift(2).fillna(0.4),
                "hour_of_day": np.random.randint(0, 24, n),
                "day_of_week": np.random.randint(0, 7, n),
                "is_weekend": np.random.randint(0, 2, n),
            }
        )

    def test_single_quantile_training(self, sample_features_df):
        feature_cols = ["memory_usage", "rolling_mean_15min", "lag_1", "hour_of_day"]
        X = sample_features_df[feature_cols]
        y = sample_features_df["cpu_usage"]

        # Train p10, p50, p90
        wrapper_10 = train_quantile_model(
            X[:200], y[:200], X[200:], y[200:], quantile=0.1
        )
        wrapper_50 = train_quantile_model(
            X[:200], y[:200], X[200:], y[200:], quantile=0.5
        )
        wrapper_90 = train_quantile_model(
            X[:200], y[:200], X[200:], y[200:], quantile=0.9
        )

        preds_10 = wrapper_10.predict(X[200:])
        preds_50 = wrapper_50.predict(X[200:])
        preds_90 = wrapper_90.predict(X[200:])

        assert len(preds_10) == len(X[200:])
        assert len(preds_50) == len(X[200:])
        assert len(preds_90) == len(X[200:])

        # Quantile ordering property: mean(p10) <= mean(p50) <= mean(p90)
        assert np.mean(preds_10) <= np.mean(preds_50)
        assert np.mean(preds_50) <= np.mean(preds_90)

    def test_train_all_models_and_artifacts(self, sample_features_df, tmp_path):
        out_dir = str(tmp_path / "test_artifacts")
        results = train_all_models(
            sample_features_df,
            horizons=[5, 10],
            quantiles=[0.1, 0.5, 0.9],
            output_dir=out_dir,
            target_col="cpu_usage",
        )

        # 2 horizons * 3 quantiles = 6 models
        assert len(results) == 6
        for name, info in results.items():
            assert os.path.exists(info["model_path"])
            assert "metadata" in info
            assert info["metadata"]["metrics"]["wmape"] >= 0.0

        # Verify registry registration
        registry = ModelRegistry()
        active_models = registry.list_models(status="active")
        assert len(active_models) >= 6

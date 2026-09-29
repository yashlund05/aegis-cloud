"""
Unit tests for walk-forward temporal validation and metrics.
"""

import os
import pytest
import pandas as pd
import numpy as np
from ml.evaluation.evaluate import (
    wmape,
    pinball_loss,
    interval_coverage,
    walk_forward_validation,
    generate_evaluation_report,
)


class TestWalkForwardEvaluation:
    def test_wmape_metric(self):
        y_true = np.array([10.0, 20.0, 30.0])
        y_pred = np.array([11.0, 19.0, 33.0])  # diffs: 1, 1, 3 -> sum=5, sum(true)=60
        assert wmape(y_true, y_pred) == pytest.approx(5.0 / 60.0)

        # Perfect prediction
        assert wmape(y_true, y_true) == 0.0

    def test_pinball_loss_metric(self):
        y_true = np.array([10.0, 20.0])
        # Underprediction (y_true > y_pred): diff > 0 -> tau * diff
        y_pred_under = np.array([8.0, 18.0])  # diffs: 2, 2
        loss_90 = pinball_loss(y_true, y_pred_under, quantile=0.9)
        assert loss_90 == pytest.approx(0.9 * 2.0)

        # Overprediction (y_true < y_pred): diff < 0 -> (tau - 1) * diff
        y_pred_over = np.array([12.0, 22.0])  # diffs: -2, -2
        loss_10 = pinball_loss(y_true, y_pred_over, quantile=0.1)
        assert loss_10 == pytest.approx((0.1 - 1.0) * (-2.0))

    def test_interval_coverage_metric(self):
        y_true = np.array([10.0, 15.0, 20.0, 25.0, 30.0])
        y_lower = np.array([8.0, 12.0, 18.0, 26.0, 28.0])  # 25 is outside [26, 32]
        y_upper = np.array([12.0, 18.0, 22.0, 32.0, 35.0])
        # 4 out of 5 covered -> 0.80
        cov = interval_coverage(y_true, y_lower, y_upper)
        assert cov == pytest.approx(0.80)

    def test_walk_forward_validation_execution(self, tmp_path):
        np.random.seed(42)
        n = 250
        df = pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=n, freq="1min"),
                "cpu_usage": 0.4 + 0.2 * np.sin(np.linspace(0, 10, n)) + np.random.normal(0, 0.02, n),
                "memory_usage": 0.5 + np.random.normal(0, 0.01, n),
                "lag_1": np.random.uniform(0.2, 0.6, n),
                "rolling_mean_15min": np.random.uniform(0.3, 0.5, n),
                "hour_of_day": np.random.randint(0, 24, n),
            }
        )

        report = walk_forward_validation(df, horizon=5, quantiles=[0.1, 0.5, 0.9], n_splits=3)

        assert "average_metrics" in report
        assert "folds" in report
        assert len(report["folds"]) == 3
        assert report["average_metrics"]["mean_wmape_p50"] >= 0.0
        assert 0.0 <= report["average_metrics"]["mean_coverage_p10_p90"] <= 1.0

        # Test report saving
        report_path = str(tmp_path / "eval_report.json")
        generate_evaluation_report(report, report_path)
        assert os.path.exists(report_path)

"""
Unit tests for AegisPredictor inference pipeline and fallback.
"""

import pytest
from ml.inference.predict import AegisPredictor


class TestAegisPredictor:
    @pytest.fixture
    def predictor(self):
        return AegisPredictor(
            model_dir="ml/models/artifacts",
            horizons=[5, 10, 15],
            quantiles=[0.1, 0.5, 0.9],
        )

    def test_predictor_fallback_when_models_unloaded(self, predictor):
        features = {
            "workload_id": "test-app",
            "cpu_usage": 0.50,
            "memory_usage": 0.40,
            "rolling_mean_15min": 0.48,
        }

        preds = predictor.predict(features)

        assert 5 in preds
        assert 10 in preds
        assert 15 in preds
        for h in [5, 10, 15]:
            assert 0.1 in preds[h]
            assert 0.5 in preds[h]
            assert 0.9 in preds[h]
            # Fallback should respect quantile margins
            assert preds[h][0.1] <= preds[h][0.5] <= preds[h][0.9]

    def test_predict_batch(self, predictor):
        features_list = [
            {"workload_id": "app-1", "cpu_usage": 0.20},
            {"workload_id": "app-2", "cpu_usage": 0.80},
        ]
        results = predictor.predict_batch(features_list)
        assert len(results) == 2
        assert results[0][10][0.5] < results[1][10][0.5]

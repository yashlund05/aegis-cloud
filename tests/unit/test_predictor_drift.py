"""
Unit tests for Kolmogorov-Smirnov concept drift detection in Predictor Service.
"""

import numpy as np
import asyncio
from services.predictor.drift import DriftDetector, ks_drift_test


class TestPredictorDrift:
    def test_ks_drift_math(self):
        np.random.seed(42)
        ref = np.random.normal(0, 0.05, 100)
        cur_identical = np.random.normal(0, 0.05, 50)
        cur_shifted = np.random.normal(0.20, 0.05, 50)  # Systematic error shift

        is_drift_no, p_val_no = ks_drift_test(ref, cur_identical, significance=0.05)
        assert not is_drift_no
        assert p_val_no > 0.05

        is_drift_yes, p_val_yes = ks_drift_test(ref, cur_shifted, significance=0.05)
        assert is_drift_yes
        assert p_val_yes < 0.05

    def test_streaming_drift_detector_lifecycle(self):
        detector = DriftDetector(reference_window=50, test_window=25, significance=0.05)
        w_id = "payment-gateway"

        # 1. Warm-up phase
        for _ in range(50):
            detector.add_observation(
                w_id, y_true=0.50, y_pred=0.50 + np.random.normal(0, 0.02)
            )

        # Check drift before enough current samples
        report_warmup = asyncio.run(detector.check_drift(w_id))
        assert report_warmup["status"] == "warming_up"
        assert not report_warmup["drift_detected"]

        # 2. Add stable current observations
        for _ in range(30):
            detector.add_observation(
                w_id, y_true=0.50, y_pred=0.50 + np.random.normal(0, 0.02)
            )

        report_stable = asyncio.run(detector.check_drift(w_id))
        assert report_stable["status"] == "stable"
        assert not report_stable["drift_detected"]
        assert not report_stable["should_retrain"]

        # 3. Simulate sudden traffic shift / model degradation (large residuals)
        for _ in range(30):
            detector.add_observation(
                w_id, y_true=0.90, y_pred=0.45
            )  # Underforecasting by 0.45

        report_drift = asyncio.run(detector.check_drift(w_id))
        assert report_drift["drift_detected"]
        assert report_drift["should_retrain"]
        assert report_drift["status"] == "drift_detected"

        # 4. Reset reference after retrain
        detector.reset_reference(w_id)
        report_reset = asyncio.run(detector.check_drift(w_id))
        assert report_reset["status"] == "warming_up"

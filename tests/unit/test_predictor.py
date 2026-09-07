import pytest
from ml.inference.predict import AegisPredictor
from ml.drift.drift_detection import ks_drift_test, DriftMonitor
import numpy as np

class TestDriftDetection:
    def test_no_drift_same_distribution(self):
        np.random.seed(42)
        ref = np.random.normal(0, 1, 1000)
        cur = np.random.normal(0, 1, 100)
        is_drift, p_value = ks_drift_test(ref, cur)
        assert not is_drift
        assert p_value > 0.05

    def test_drift_different_distribution(self):
        np.random.seed(42)
        ref = np.random.normal(0, 1, 1000)
        cur = np.random.normal(3, 1, 100)  # shifted mean
        is_drift, p_value = ks_drift_test(ref, cur)
        assert is_drift
        assert p_value < 0.05

    def test_drift_monitor(self):
        monitor = DriftMonitor(reference_window=100, test_window=50, significance=0.05)
        np.random.seed(42)
        # Add reference observations (no drift)
        for _ in range(100):
            pred = np.random.normal(10, 1)
            actual = pred + np.random.normal(0, 0.5)
            monitor.add_observation(pred, actual)
        # Should not detect drift initially
        result = monitor.check_drift()
        assert not result['drift_detected']

    def test_drift_monitor_detects_shift(self):
        monitor = DriftMonitor(reference_window=100, test_window=50, significance=0.05)
        np.random.seed(42)
        # Add reference (normal errors)
        for _ in range(100):
            monitor.add_observation(10.0, 10.0 + np.random.normal(0, 0.5))
        # Add drifted observations (large systematic error)
        for _ in range(50):
            monitor.add_observation(10.0, 15.0 + np.random.normal(0, 0.5))
        result = monitor.check_drift()
        assert result['drift_detected']

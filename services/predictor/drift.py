"""
Concept Drift Detection module for Aegis Predictor Service.
Monitors forecast errors in real-time using Kolmogorov-Smirnov (KS) two-sample test
and triggers alerts or retraining when workload dynamics shift.
"""

from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import logging
from scipy import stats

from services.shared.redis_client import redis_client

logger = logging.getLogger(__name__)


def ks_drift_test(
    reference_errors: np.ndarray, current_errors: np.ndarray, significance: float = 0.05
) -> Tuple[bool, float]:
    """
    Two-sample Kolmogorov-Smirnov test to detect distribution drift between
    reference forecast errors (from validation) and current production errors.
    Returns: (is_drift_detected, p_value)
    """
    if len(reference_errors) < 20 or len(current_errors) < 20:
        return False, 1.0

    stat, p_value = stats.ks_2samp(reference_errors, current_errors)
    is_drift = bool(p_value < significance)
    return is_drift, float(p_value)


class DriftDetector:
    """
    Tracks streaming forecast errors per workload, performs KS statistical testing,
    and publishes alerts over Redis Pub/Sub when concept drift is identified.
    """

    def __init__(
        self,
        reference_window: int = 500,
        test_window: int = 60,
        significance: float = 0.05,
        wmape_threshold: float = 0.35,
    ):
        self.reference_window = reference_window
        self.test_window = test_window
        self.significance = significance
        self.wmape_threshold = wmape_threshold

        # workload_id -> list of error residuals (y_true - y_pred)
        self.reference_errors: Dict[str, List[float]] = {}
        self.current_errors: Dict[str, List[float]] = {}
        self.recent_actuals: Dict[str, List[float]] = {}
        self.recent_preds: Dict[str, List[float]] = {}

    def add_observation(self, workload_id: str, y_true: float, y_pred: float):
        """
        Record an observed actual value and corresponding p50 prediction.
        """
        err = float(y_true - y_pred)

        if workload_id not in self.reference_errors:
            self.reference_errors[workload_id] = []
            self.current_errors[workload_id] = []
            self.recent_actuals[workload_id] = []
            self.recent_preds[workload_id] = []

        ref = self.reference_errors[workload_id]
        cur = self.current_errors[workload_id]
        actuals = self.recent_actuals[workload_id]
        preds = self.recent_preds[workload_id]

        actuals.append(y_true)
        preds.append(y_pred)
        if len(actuals) > self.test_window:
            actuals.pop(0)
            preds.pop(0)

        # Build initial reference distribution first
        if len(ref) < self.reference_window:
            ref.append(err)
        else:
            cur.append(err)
            if len(cur) > self.test_window:
                cur.pop(0)

    async def check_drift(self, workload_id: str) -> Dict[str, Any]:
        """
        Executes KS test and computes rolling WMAPE for the workload.
        """
        ref = self.reference_errors.get(workload_id, [])
        cur = self.current_errors.get(workload_id, [])
        actuals = self.recent_actuals.get(workload_id, [])
        preds = self.recent_preds.get(workload_id, [])

        # Calculate rolling WMAPE if observations exist
        rolling_wmape = 0.0
        if actuals and preds:
            denom = sum(abs(a) for a in actuals)
            diff_sum = sum(abs(a - p) for a, p in zip(actuals, preds))
            rolling_wmape = (diff_sum / denom) if denom > 0 else 0.0

        if len(ref) < 20 or len(cur) < 20:
            return {
                "workload_id": workload_id,
                "status": "warming_up",
                "drift_detected": False,
                "p_value": 1.0,
                "rolling_wmape": round(rolling_wmape, 4),
                "should_retrain": False,
                "reference_samples": len(ref),
                "current_samples": len(cur),
            }

        ref_arr = np.array(ref)
        cur_arr = np.array(cur)
        is_drift, p_val = ks_drift_test(ref_arr, cur_arr, self.significance)
        should_retrain = is_drift or (rolling_wmape > self.wmape_threshold)

        result = {
            "workload_id": workload_id,
            "status": "drift_detected" if is_drift else "stable",
            "drift_detected": is_drift,
            "p_value": round(p_val, 5),
            "rolling_wmape": round(rolling_wmape, 4),
            "should_retrain": should_retrain,
            "reference_samples": len(ref),
            "current_samples": len(cur),
        }

        # If drift detected, emit alert on Redis pub/sub
        if is_drift:
            logger.warning(
                f"Concept drift detected for workload '{workload_id}' (p-value={p_val:.5f}, wmape={rolling_wmape:.4f})"
            )
            try:
                await redis_client.publish(
                    "aegis.events.alerts",
                    {
                        "alert_type": "drift",
                        "severity": "warning",
                        "workload_id": workload_id,
                        "message": f"Statistical concept drift detected via KS test (p={p_val:.5f})",
                        "metadata": result,
                    },
                )
            except Exception as e:
                logger.debug(f"Redis alert publishing deferred: {e}")

        return result

    def reset_reference(self, workload_id: str):
        """
        Resets reference error distribution after a model retrain.
        """
        if workload_id in self.reference_errors:
            self.reference_errors[workload_id] = []
            self.current_errors[workload_id] = []
            logger.info(f"Reset drift reference distribution for '{workload_id}'.")


drift_detector = DriftDetector()

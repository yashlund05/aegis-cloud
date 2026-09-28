"""
Drift detection module for Aegis.
"""
import numpy as np
from scipy import stats
from typing import Tuple, List, Dict

def ks_drift_test(reference_errors: np.ndarray, current_errors: np.ndarray, significance: float = 0.05) -> Tuple[bool, float]:
    """
    Two-sample Kolmogorov-Smirnov test.
    Returns (is_drift_detected, p_value).
    """
    if len(reference_errors) == 0 or len(current_errors) == 0:
        return False, 1.0
        
    statistic, p_value = stats.ks_2samp(reference_errors, current_errors)
    return p_value < significance, float(p_value)

def rolling_error_monitor(predictions: List[float], actuals: List[float], window_size: int = 100) -> Dict:
    """
    Compute rolling WMAPE and check for drift.
    """
    if len(predictions) < window_size or len(actuals) < window_size:
        return {"drift": False, "p_value": 1.0, "rolling_wmape": 0.0}
        
    recent_preds = np.array(predictions[-window_size:])
    recent_actuals = np.array(actuals[-window_size:])
    
    sum_abs_diff = np.sum(np.abs(recent_preds - recent_actuals))
    sum_abs_actual = np.sum(np.abs(recent_actuals))
    wmape = sum_abs_diff / sum_abs_actual if sum_abs_actual != 0 else 0.0
    
    half = window_size // 2
    err_ref = np.abs(recent_preds[:half] - recent_actuals[:half])
    err_cur = np.abs(recent_preds[half:] - recent_actuals[half:])
    
    is_drift, p_val = ks_drift_test(err_ref, err_cur)
    
    return {
        "drift": is_drift,
        "p_value": p_val,
        "rolling_wmape": wmape
    }

class DriftMonitor:
    def __init__(self, reference_window: int = 1000, test_window: int = 100, significance: float = 0.05):
        self.reference_window = reference_window
        self.test_window = test_window
        self.significance = significance
        self.reference_errors = []
        self.current_errors = []
        
    def add_observation(self, predicted: float, actual: float):
        error = abs(predicted - actual)
        if len(self.reference_errors) < self.reference_window:
            self.reference_errors.append(error)
        else:
            self.current_errors.append(error)
            if len(self.current_errors) > self.test_window:
                self.current_errors.pop(0)
                
    def check_drift(self) -> Dict:
        if len(self.current_errors) < self.test_window:
            return {"drift_detected": False, "p_value": 1.0}
            
        ref = np.array(self.reference_errors)
        cur = np.array(self.current_errors)
        is_drift, p_val = ks_drift_test(ref, cur, self.significance)
        
        return {
            "drift_detected": is_drift,
            "p_value": p_val
        }
        
    def should_retrain(self) -> bool:
        return self.check_drift().get("drift_detected", False)
        
    def reset_reference(self):
        """Reset reference distribution after retraining."""
        self.reference_errors = []
        self.current_errors = []

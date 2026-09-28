import numpy as np
from scipy import stats

class DriftDetector:
    def detect_drift(self, recent_errors: list, baseline_errors: list = None) -> bool:
        if len(recent_errors) < 30:
            return False
            
        if baseline_errors is None or len(baseline_errors) < 30:
            baseline_errors = np.zeros(len(recent_errors))
            
        # Perform Kolmogorov-Smirnov test for drift detection
        statistic, p_value = stats.ks_2samp(recent_errors, baseline_errors)
        
        return p_value < 0.05

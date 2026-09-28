import numpy as np
from typing import List, Dict, Any

class RightSizer:
    def __init__(self, target_quantile: float = 0.95, safety_margin: float = 1.15):
        self.target_quantile = target_quantile
        self.safety_margin = safety_margin

    def compute_suggestion(self, historical_usage: List[Dict[str, float]]) -> Dict[str, Any]:
        """
        Computes right-sizing recommendations based on historical usage quantiles.
        """
        if not historical_usage:
            return {
                "cpu_requests": 0.0,
                "memory_requests": 0.0,
                "cpu_limits": 0.0,
                "memory_limits": 0.0,
                "confidence": 0.0
            }
             
        cpu_usage = [obs.get('cpu', 0.0) for obs in historical_usage]
        mem_usage = [obs.get('mem', 0.0) for obs in historical_usage]
        
        q_cpu = float(np.percentile(cpu_usage, self.target_quantile * 100))
        q_mem = float(np.percentile(mem_usage, self.target_quantile * 100))
        
        # Add safety margin
        rec_cpu = q_cpu * self.safety_margin
        rec_mem = q_mem * self.safety_margin
        
        return {
            "cpu_requests": round(rec_cpu, 3),
            "memory_requests": round(rec_mem, 2),
            "cpu_limits": round(rec_cpu * 1.5, 3), # Allow 50% CPU burst
            "memory_limits": round(rec_mem * 1.2, 2), # Allow 20% Mem burst
            "confidence": min(1.0, len(historical_usage) / 10080.0) # 10080 = 1 week of minutely data
        }

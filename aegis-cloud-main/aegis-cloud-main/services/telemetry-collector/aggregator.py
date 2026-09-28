import numpy as np
import pandas as pd
from typing import List, Dict, Any

class Aggregator:
    def __init__(self, outlier_percentile: float = 99.9):
        self.outlier_percentile = outlier_percentile

    def aggregate_workload(self, raw_metrics: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Dict[str, float]]:
        """
        Takes raw Prometheus query results, groups them by namespace,
        and computes sum/mean while clipping outliers.
        """
        aggregated = {}
        
        for metric_name, results in raw_metrics.items():
            for result in results:
                namespace = result.get("metric", {}).get("namespace", "unknown")
                if namespace == "unknown":
                    continue
                if namespace not in aggregated:
                    aggregated[namespace] = {}
                
                try:
                    value = float(result.get("value", [0, 0])[1])
                except (ValueError, TypeError, IndexError):
                    value = 0.0
                
                if metric_name not in aggregated[namespace]:
                    aggregated[namespace][metric_name] = []
                
                aggregated[namespace][metric_name].append(value)
                
        final_metrics = {}
        for namespace, metrics in aggregated.items():
            final_metrics[namespace] = {}
            for metric_name, values in metrics.items():
                if not values:
                    final_metrics[namespace][metric_name] = 0.0
                    continue
                    
                # Outlier clipping
                clip_val = np.percentile(values, self.outlier_percentile)
                clipped_values = np.clip(values, None, clip_val)
                
                final_metrics[namespace][metric_name] = float(np.sum(clipped_values))
                
        return final_metrics

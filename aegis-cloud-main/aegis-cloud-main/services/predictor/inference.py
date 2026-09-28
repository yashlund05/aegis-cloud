import logging
import os
import lightgbm as lgb
import numpy as np
from scipy.stats import ks_2samp

logger = logging.getLogger(__name__)

class InferenceEngine:
    def __init__(self, model_dir: str = "/var/lib/aegis/models"):
        self.model_dir = model_dir
        self.models = {}  # Cache models
        self.baseline_features = [] # For KS drift detection

    def _get_model(self, workload_id: str, horizon: int, quantile: float, is_shadow: bool = False):
        shadow_prefix = "shadow_" if is_shadow else ""
        key = f"{shadow_prefix}{workload_id}_{horizon}m_p{int(quantile*100)}"
        if key not in self.models:
            model_path = os.path.join(self.model_dir, f"{key}.txt")
            if os.path.exists(model_path):
                self.models[key] = lgb.Booster(model_file=model_path)
            else:
                return None
        return self.models[key]

    def _detect_drift(self, current_features: np.ndarray) -> bool:
        if len(self.baseline_features) < 100:
            self.baseline_features.append(current_features[0])
            return False
            
        baseline = np.array(self.baseline_features)
        drift_detected = False
        for i in range(current_features.shape[1]):
            stat, p_value = ks_2samp(baseline[:, i], [current_features[0, i]])
            if p_value < 0.05:
                drift_detected = True
                break
                
        # Update baseline (sliding window)
        self.baseline_features.pop(0)
        self.baseline_features.append(current_features[0])
        
        return drift_detected

    async def predict(self, workload_id: str, horizon: int, features: dict) -> dict:
        feature_vector = np.array([[
            features.get('cpu', 0.0),
            features.get('mem', 0.0),
            features.get('net_rx', 0.0),
            features.get('net_tx', 0.0)
        ]])
        
        # Drift Detection
        drift = self._detect_drift(feature_vector)
        if drift:
            logger.warning(f"Feature drift detected for workload {workload_id}")

        predictions = {}
        for q in [0.10, 0.50, 0.90]:
            model = self._get_model(workload_id, horizon, q)
            if model:
                try:
                    pred = model.predict(feature_vector)[0]
                    predictions[f"p{int(q*100)}"] = float(pred)
                except Exception as e:
                    logger.error(f"Prediction error: {e}")
                    predictions[f"p{int(q*100)}"] = self._fallback(features, q)
            else:
                predictions[f"p{int(q*100)}"] = self._fallback(features, q)
                
            # Shadow model inference
            shadow_model = self._get_model(workload_id, horizon, q, is_shadow=True)
            if shadow_model:
                try:
                    shadow_pred = shadow_model.predict(feature_vector)[0]
                    logger.info(f"Shadow prediction for p{int(q*100)}: {shadow_pred}")
                except Exception as e:
                    pass

        return predictions
        
    def _fallback(self, features: dict, q: float) -> float:
        current_cpu = features.get('cpu', 1.0)
        return float(current_cpu * (1.0 + (q - 0.5)))

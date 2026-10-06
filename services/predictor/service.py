"""
PredictorService serves real-time quantile demand forecasts for Kubernetes workloads.
Consumes feature vectors from Redis, executes model inference, and returns p10/p50/p90 predictions.
Target inference latency: < 100ms p99.
"""

import time
from typing import Dict, Any, Optional
import logging

from services.shared.redis_client import redis_client
from ml.inference.predict import AegisPredictor
from ml.models.registry import ModelRegistry

logger = logging.getLogger(__name__)


class PredictorService:
    """
    Coordinates model loading, inference, and prediction serving.
    """

    def __init__(self, model_dir: str = "ml/models/artifacts"):
        self.predictor = AegisPredictor(
            model_dir=model_dir,
            horizons=[5, 10, 15],
            quantiles=[0.1, 0.5, 0.9],
        )
        self.registry = ModelRegistry()

    def initialize(self):
        """Loads trained quantile models on startup."""
        self.predictor.load_models()
        logger.info(
            f"PredictorService initialized with {len(self.predictor.models)} horizon sets."
        )

    async def serve_prediction(
        self,
        workload_id: str,
        horizon: int = 10,
        features_override: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Serves quantile prediction (p10, p50, p90) for a given workload and horizon.
        Completes in < 100ms.
        """
        start_time = time.perf_counter()

        # 1. Fetch feature vector from Redis or use override
        features = features_override
        if not features:
            redis_key = f"workload:{workload_id}:features"
            try:
                features = await redis_client.get_features(redis_key)
            except Exception as e:
                logger.warning(
                    f"Error reading Redis feature store for '{workload_id}': {e}"
                )

        # Fallback to sensible defaults if features are missing
        if not features:
            features = {
                "workload_id": workload_id,
                "cpu_usage": 0.40,
                "memory_usage": 0.50,
                "rolling_mean_15min": 0.40,
            }

        # 2. Run model inference
        all_preds = self.predictor.predict(features)

        # Nearest available horizon
        valid_horizons = self.predictor.horizons
        target_h = (
            horizon
            if horizon in all_preds
            else min(valid_horizons, key=lambda x: abs(x - horizon))
        )
        horizon_preds = all_preds.get(target_h, {0.1: 0.35, 0.5: 0.40, 0.9: 0.55})

        p10 = float(horizon_preds.get(0.1, 0.0))
        p50 = float(horizon_preds.get(0.5, 0.0))
        p90 = float(horizon_preds.get(0.9, 0.0))

        # Enforce monotonicity: p10 <= p50 <= p90
        p10 = min(p10, p50)
        p90 = max(p90, p50)

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # 3. Cache prediction in Redis
        prediction_payload = {
            "workload_id": workload_id,
            "horizon_minutes": target_h,
            "p10": p10,
            "p50": p50,
            "p90": p90,
            "latency_ms": round(latency_ms, 2),
        }

        try:
            cache_key = f"workload:{workload_id}:predictions"
            await redis_client.set_features(cache_key, prediction_payload, expire=3600)
        except Exception as e:
            logger.debug(f"Redis prediction caching skipped: {e}")

        logger.info(
            f"Forecast served for '{workload_id}' (h={target_h}m): "
            f"p10={p10:.4f}, p50={p50:.4f}, p90={p90:.4f} (latency={latency_ms:.2f}ms)"
        )
        return prediction_payload


predictor_service = PredictorService()

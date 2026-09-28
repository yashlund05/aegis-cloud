import json
import logging
import time
from services.predictor.inference import InferenceEngine
from services.shared.redis_client import redis_client

logger = logging.getLogger(__name__)

class PredictorService:
    def __init__(self):
        self.inference_engine = InferenceEngine()

    async def serve_prediction(self, workload_id: str, horizon: int):
        start_time = time.time()
        redis = await redis_client.get_redis()
        
        # Check cache
        cache_key = f"prediction:{workload_id}:{horizon}"
        cached = await redis.get(cache_key)
        if cached:
            predictions = json.loads(cached)
            latency = (time.time() - start_time) * 1000
            logger.info(f"Cached prediction for {workload_id} took {latency:.2f}ms")
            return {
                "workload_id": workload_id,
                "horizon": horizon,
                "predictions": predictions,
                "latency_ms": latency
            }
        
        # 1. Fetch features from Redis
        key = f"telemetry:{workload_id}"
        features_data = await redis.get(key)
        
        if not features_data:
            logger.warning(f"No telemetry found for {workload_id}")
            features = {}
        else:
            features = json.loads(features_data)
            
        # 2. Run inference
        predictions = await self.inference_engine.predict(workload_id, horizon, features)
        
        # 3. Cache result
        await redis.setex(cache_key, 60, json.dumps(predictions))
        
        latency = (time.time() - start_time) * 1000
        logger.info(f"Prediction for {workload_id} took {latency:.2f}ms")
        
        return {
            "workload_id": workload_id,
            "horizon": horizon,
            "predictions": predictions,
            "latency_ms": latency
        }

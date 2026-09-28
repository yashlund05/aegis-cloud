import json
import logging
from services.shared.redis_client import redis_client
from services.recommendation_engine.rightsizing import RightSizer

logger = logging.getLogger(__name__)

class RecommendationService:
    def __init__(self):
        self.rightsizer = RightSizer(target_quantile=0.95, safety_margin=1.15)

    async def generate_recommendation(self, workload_id: str) -> dict:
        """Generate resource right-sizing recommendation for a workload."""
        redis = await redis_client.get_redis()

        # Fetch historical telemetry snapshots stored over time
        # In a full system, this would query TimescaleDB for 14 days of history
        # Here we read the latest telemetry as a simplified approach
        key = f"telemetry:{workload_id}"
        data = await redis.get(key)

        if not data:
            logger.warning(f"No telemetry data for workload {workload_id}")
            return {
                "workload_id": workload_id,
                "recommendation": None,
                "reason": "insufficient data"
            }

        current_metrics = json.loads(data)
        # Simulate historical usage from current snapshot
        # In production, this would be a list of observations over 14 days
        historical = [current_metrics]

        suggestion = self.rightsizer.compute_suggestion(historical)

        recommendation = {
            "workload_id": workload_id,
            "recommendation": suggestion,
            "current_metrics": current_metrics,
            "reason": "based on p95 historical usage with 15% safety margin"
        }

        # Cache the recommendation
        await redis.setex(
            f"recommendation:{workload_id}",
            3600,
            json.dumps(recommendation)
        )

        return recommendation

    async def get_all_recommendations(self) -> list:
        """Get all cached recommendations."""
        redis = await redis_client.get_redis()
        keys = []
        async for key in redis.scan_iter(match="recommendation:*"):
            keys.append(key)

        results = []
        for key in keys:
            data = await redis.get(key)
            if data:
                results.append(json.loads(data))
        return results

import json
import logging
from services.shared.redis_client import redis_client
from services.shared.database import db

logger = logging.getLogger(__name__)

class OrchestratorService:
    async def get_cycle_history(self, limit: int = 10):
        """Get recent orchestrator cycle history from the database."""
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, cycle_id, status, solver_type, objective_value,
                       solve_time_ms, created_at
                FROM decision_plans
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit
            )
            return [dict(r) for r in rows]

    async def get_current_status(self):
        """Get current orchestrator status from Redis."""
        redis = await redis_client.get_redis()
        status_data = await redis.get("orchestrator:status")
        if status_data:
            return json.loads(status_data)
        return {
            "state": "unknown",
            "last_cycle_id": None,
            "last_cycle_time": None
        }

    async def set_status(self, status: dict):
        """Update orchestrator status in Redis."""
        redis = await redis_client.get_redis()
        await redis.set("orchestrator:status", json.dumps(status))

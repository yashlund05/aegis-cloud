import logging
from services.shared.database import db

logger = logging.getLogger(__name__)

class ModelRegistry:
    """PostgreSQL-backed model registry for the predictor service."""

    async def list_models(self, status: str = None) -> list:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM model_registry WHERE status = $1 ORDER BY created_at DESC",
                    status
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM model_registry ORDER BY created_at DESC"
                )
            return [dict(r) for r in rows]

    async def load_model(self, model_id: str) -> dict:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM model_registry WHERE id = $1", model_id
            )
            return dict(row) if row else None

    async def get_active_model(self, workload_id: str, quantile: float) -> dict:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT * FROM model_registry
                   WHERE workload_id = $1 AND quantile = $2 AND status = 'active'
                   ORDER BY created_at DESC LIMIT 1""",
                workload_id, quantile
            )
            return dict(row) if row else None

    async def register_model(self, model_info: dict) -> str:
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO model_registry (workload_id, quantile, model_path, version, status, metrics)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING id""",
                model_info.get("workload_id"),
                model_info.get("quantile"),
                model_info.get("model_path"),
                model_info.get("version"),
                model_info.get("status", "training"),
                str(model_info.get("metrics", {}))
            )
            return str(row["id"])

    async def promote_model(self, model_id: str):
        pool = await db.get_pool()
        async with pool.acquire() as conn:
            # Retire current active
            model = await self.load_model(model_id)
            if model:
                await conn.execute(
                    """UPDATE model_registry SET status = 'retired'
                       WHERE workload_id = $1 AND quantile = $2 AND status = 'active'""",
                    model["workload_id"], model["quantile"]
                )
            # Promote new
            await conn.execute(
                "UPDATE model_registry SET status = 'active' WHERE id = $1",
                model_id
            )

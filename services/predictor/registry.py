"""
Model Registry service module for Aegis.
Manages model versions, shadow models, and active promotions across PostgreSQL and JSON fallback.
"""

from typing import Dict, Any, List, Optional
import uuid
import json
import logging
from datetime import datetime, timezone

from services.shared.database import db
from ml.models.registry import ModelRegistry as FileModelRegistry

logger = logging.getLogger(__name__)


class DatabaseModelRegistry:
    """
    Model Registry with dual-mode storage: PostgreSQL database when available,
    with automatic fallback to JSON file storage (ml/models/registry.json).
    """

    def __init__(self, json_path: str = "ml/models/registry.json"):
        self.file_registry = FileModelRegistry(registry_path=json_path)

    async def list_models(
        self, model_name: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List all models matching optional name and status filters.
        """
        pool = await db.get_pool()
        if pool:
            query = "SELECT * FROM model_registry WHERE 1=1"
            params = []
            if model_name:
                params.append(model_name)
                query += f" AND model_name = ${len(params)}"
            if status:
                params.append(status)
                query += f" AND status = ${len(params)}"
            query += " ORDER BY created_at DESC"

            try:
                rows = await db.execute_query(query, *params)
                if rows:
                    return [dict(r) for r in rows]
            except Exception as e:
                logger.debug(f"PostgreSQL model_registry query deferred to file: {e}")

        # Fallback to file registry
        return self.file_registry.list_models(model_name=model_name, status=status)

    async def register_model(self, model_info: Dict[str, Any]) -> str:
        """
        Registers a new model version with status 'training' or 'shadow'.
        """
        v_id = str(uuid.uuid4())
        model_info["id"] = v_id
        model_info["version_id"] = v_id
        if "status" not in model_info:
            model_info["status"] = "training"

        # Attempt to insert into PostgreSQL
        pool = await db.get_pool()
        if pool:
            query = """
                INSERT INTO model_registry (
                    id, model_name, version, training_dataset, training_timestamp,
                    features, quantile, horizon_minutes, metrics, status, artifact_path
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
                ON CONFLICT (model_name, version) DO UPDATE SET status = EXCLUDED.status;
            """
            try:
                await db.execute_query(
                    query,
                    uuid.UUID(v_id),
                    model_info.get("model_name", "aegis_quantile"),
                    model_info.get("version", v_id[:8]),
                    model_info.get("training_dataset", "sample_trace"),
                    datetime.now(timezone.utc),
                    json.dumps(model_info.get("features", [])),
                    float(model_info.get("quantile", 0.5)),
                    int(model_info.get("horizon_minutes", 10)),
                    json.dumps(model_info.get("metrics", {})),
                    model_info.get("status", "training"),
                    model_info.get("model_path", ""),
                )
            except Exception as e:
                logger.debug(f"DB model registration deferred to file: {e}")

        # Also persist to file registry
        self.file_registry.register_model(model_info)
        return v_id

    async def promote_model(self, version_id: str):
        """
        Promotes a model (from shadow or training) to 'active', and retires the previous active model.
        """
        pool = await db.get_pool()
        if pool:
            try:
                # Find target model's horizon and quantile
                row = await db.execute_query("SELECT * FROM model_registry WHERE id = $1", uuid.UUID(version_id))
                if row:
                    m = dict(row[0])
                    # Retire previous active
                    await db.execute_query(
                        """
                        UPDATE model_registry SET status = 'retired'
                        WHERE model_name = $1 AND horizon_minutes = $2 AND quantile = $3 AND status = 'active';
                    """,
                        m["model_name"],
                        m["horizon_minutes"],
                        m["quantile"],
                    )
                    # Activate new
                    await db.execute_query(
                        "UPDATE model_registry SET status = 'active' WHERE id = $1;", uuid.UUID(version_id)
                    )
            except Exception as e:
                logger.debug(f"DB model promotion deferred to file: {e}")

        self.file_registry.promote_model(version_id)
        logger.info(f"Model version '{version_id}' promoted to active.")

    async def get_active_model(self, model_name: str, quantile: float, horizon: int) -> Optional[Dict[str, Any]]:
        pool = await db.get_pool()
        if pool:
            try:
                row = await db.execute_query(
                    """
                    SELECT * FROM model_registry
                    WHERE model_name = $1 AND quantile = $2 AND horizon_minutes = $3 AND status = 'active'
                    LIMIT 1;
                """,
                    model_name,
                    quantile,
                    horizon,
                )
                if row:
                    return dict(row[0])
            except Exception:
                pass
        return self.file_registry.get_active_model(model_name=model_name, quantile=quantile, horizon=horizon)

    async def get_shadow_models(self) -> List[Dict[str, Any]]:
        """
        Returns all candidate models currently deployed in 'shadow' status.
        """
        return await self.list_models(status="shadow")


model_registry = DatabaseModelRegistry()

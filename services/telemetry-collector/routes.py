"""
API endpoints for Aegis Telemetry Collector.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, Optional
import logging

from services.shared.redis_client import redis_client
from services.telemetry_collector.service import telemetry_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics")
async def get_raw_metrics(workload_id: Optional[str] = Query(None)) -> Dict[str, Any]:
    """
    Returns current raw metrics snapshot for all workloads or a specific workload.
    """
    try:
        # Run an instant scrape or fetch cached snapshot
        features = await telemetry_service.collect_once()
        if workload_id:
            if workload_id not in features:
                raise HTTPException(
                    status_code=404, detail=f"Workload '{workload_id}' not found."
                )
            return {"status": "ok", "workload": features[workload_id]}
        return {"status": "ok", "count": len(features), "data": features}
    except Exception as e:
        logger.error(f"Error fetching metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/features/{workload_id}")
async def get_features(workload_id: str) -> Dict[str, Any]:
    """
    Fetches the latest aggregated feature vector for a workload from Redis Feature Store.
    """
    redis_key = f"workload:{workload_id}:features"
    try:
        features = await redis_client.get_features(redis_key)
        if not features:
            # Fallback to in-memory aggregator history if Redis key not populated yet
            if workload_id in telemetry_service.aggregator.workload_histories:
                hist = telemetry_service.aggregator.workload_histories[workload_id]
                latest_cpu = hist.cpu_history[-1] if hist.cpu_history else 0.0
                latest_mem = hist.mem_history[-1] if hist.mem_history else 0.0
                features = telemetry_service.aggregator.extract_features(
                    workload_id, {"cpu_usage": latest_cpu, "memory_usage": latest_mem}
                )
            else:
                raise HTTPException(
                    status_code=404,
                    detail=f"Features for workload '{workload_id}' not found in feature store.",
                )

        return {"workload_id": workload_id, "status": "ok", "features": features}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving features from Redis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/collect")
async def trigger_collection() -> Dict[str, Any]:
    """
    Triggers an immediate telemetry collection cycle across Prometheus.
    """
    try:
        result = await telemetry_service.collect_once()
        return {
            "status": "success",
            "message": "Telemetry collection cycle executed successfully.",
            "workloads_processed": list(result.keys()),
        }
    except Exception as e:
        logger.error(f"Error triggering telemetry collection: {e}")
        raise HTTPException(status_code=500, detail=str(e))

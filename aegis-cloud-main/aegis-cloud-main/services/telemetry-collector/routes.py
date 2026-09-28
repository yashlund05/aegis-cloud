import json
from fastapi import APIRouter, HTTPException, BackgroundTasks
from typing import Dict, Any
from services.shared.redis_client import redis_client
from services.telemetry_collector.service import TelemetryService

router = APIRouter()
telemetry_service = TelemetryService()

@router.post("/collect")
async def trigger_collection(background_tasks: BackgroundTasks) -> Dict[str, str]:
    """Manually trigger a collection cycle."""
    background_tasks.add_task(telemetry_service.collect_and_store)
    return {"status": "collection_started"}

@router.get("/metrics")
async def get_raw_metrics() -> Dict[str, Any]:
    # Placeholder for getting current raw data if needed
    return {"status": "ok", "data": []}

@router.get("/features/{workload_id}")
async def get_features(workload_id: str) -> Dict[str, Any]:
    redis = await redis_client.get_redis()
    key = f"telemetry:{workload_id}"
    data = await redis.get(key)
    
    if not data:
        raise HTTPException(status_code=404, detail="Features not found for workload")
        
    return {"workload_id": workload_id, "features": json.loads(data)}

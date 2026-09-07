from fastapi import APIRouter
from typing import Dict, Any

router = APIRouter()

@router.get("/metrics")
async def get_raw_metrics() -> Dict[str, Any]:
    # TODO: implement
    return {"status": "ok", "data": []}

@router.get("/features/{workload_id}")
async def get_features(workload_id: str) -> Dict[str, Any]:
    # TODO: fetch aggregated features from Redis
    return {"workload_id": workload_id, "features": {}}

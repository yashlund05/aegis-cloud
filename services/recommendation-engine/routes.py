from fastapi import APIRouter
from typing import Dict, Any, List

router = APIRouter()

@router.get("/recommendations")
async def get_recommendations() -> List[Dict[str, Any]]:
    # TODO: return all right-sizing recommendations
    return []

@router.get("/recommendations/{workload_id}")
async def get_recommendation(workload_id: str) -> Dict[str, Any]:
    # TODO: return specific recommendation
    return {"workload_id": workload_id, "recommendation": {}}

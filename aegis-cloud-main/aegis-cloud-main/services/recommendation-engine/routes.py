from fastapi import APIRouter
from typing import Dict, Any, List
from services.recommendation_engine.service import RecommendationService

router = APIRouter()
recommendation_service = RecommendationService()

@router.get("/recommendations")
async def get_recommendations() -> List[Dict[str, Any]]:
    return await recommendation_service.get_all_recommendations()

@router.get("/recommendations/{workload_id}")
async def get_recommendation(workload_id: str) -> Dict[str, Any]:
    return await recommendation_service.generate_recommendation(workload_id)

@router.post("/recommendations/{workload_id}/generate")
async def generate_recommendation(workload_id: str) -> Dict[str, Any]:
    return await recommendation_service.generate_recommendation(workload_id)

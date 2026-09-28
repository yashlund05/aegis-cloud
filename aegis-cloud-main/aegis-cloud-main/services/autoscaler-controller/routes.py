from fastapi import APIRouter
from pydantic import BaseModel
from typing import List
from services.shared.schemas import DecisionPlan, ActionResult
from services.autoscaler_controller.service import AutoscalerService

router = APIRouter()
autoscaler_service = AutoscalerService()

@router.post("/actions/scale", response_model=List[ActionResult])
async def execute_scaling_plan(plan: DecisionPlan):
    results = await autoscaler_service.process_plan(plan)
    return results

@router.get("/actions")
async def get_action_history() -> List[ActionResult]:
    # TODO: fetch history from DB
    return []

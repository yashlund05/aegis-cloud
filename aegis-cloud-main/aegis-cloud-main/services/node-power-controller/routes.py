from fastapi import APIRouter
from typing import List, Dict, Any
from services.shared.schemas import DecisionPlan, ActionResult
from services.node_power_controller.service import NodePowerService

router = APIRouter()
power_service = NodePowerService()

@router.post("/actions/power", response_model=List[ActionResult])
async def execute_power_plan(plan: DecisionPlan):
    results = await power_service.process_plan(plan)
    return results

@router.get("/nodes/power-state")
async def get_power_states() -> Dict[str, Any]:
    cluster_state = await power_service._get_cluster_state()
    return cluster_state

"""
API routes for Node Power Controller Service (Phase 7).
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict
import logging

from services.shared.schemas import DecisionPlan, ActionResult
from services.node_power_controller.service import node_power_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/actions/power", response_model=List[ActionResult])
async def execute_power_plan(plan: DecisionPlan):
    """
    Executes node power actions (cordon/uncordon/drain) with minimum active node safety guards.
    """
    try:
        return await node_power_service.process_plan(plan)
    except Exception as e:
        logger.error(f"Error executing power plan '{plan.id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/power-state")
async def get_power_states() -> Dict[str, str]:
    """
    Returns the cluster node schedulability and power states.
    """
    return await node_power_service.get_node_states()


@router.get("/actions", response_model=List[ActionResult])
async def get_action_history(
    limit: int = Query(50, ge=1, le=200),
) -> List[ActionResult]:
    """
    Returns audit logs of node power actions.
    """
    return await node_power_service.get_history(limit=limit)

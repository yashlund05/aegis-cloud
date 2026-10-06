"""
API routes for Autoscaler Controller Service (Phase 7).
"""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Dict, Any
import logging

from services.shared.schemas import DecisionPlan, ActionResult
from services.autoscaler_controller.service import autoscaler_service
from services.autoscaler_controller.config import config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/actions/scale", response_model=List[ActionResult])
async def execute_scaling_plan(plan: DecisionPlan):
    """
    Executes replica scaling mutations specified in a DecisionPlan,
    applying safety dead zone (+-10%) and cooldown checks.
    """
    try:
        return await autoscaler_service.process_plan(plan)
    except Exception as e:
        logger.error(f"Error executing scaling plan '{plan.id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/actions", response_model=List[ActionResult])
async def get_action_history(
    limit: int = Query(50, ge=1, le=200),
) -> List[ActionResult]:
    """
    Returns recent scaling action audit history.
    """
    return await autoscaler_service.get_history(limit=limit)


@router.get("/status")
async def get_controller_status() -> Dict[str, Any]:
    """
    Returns controller operational status including HPA fallback trigger state.
    """
    return {
        "hpa_fallback_active": autoscaler_service.hpa_fallback_active,
        "cooldown_seconds": config.cooldown_seconds,
        "dead_zone_percent": config.dead_zone_percent,
        "dry_run": config.dry_run,
    }


@router.post("/fallback/reset")
async def reset_fallback():
    """
    Resets HPA fallback state back to normal Aegis predictive autoscaling.
    """
    autoscaler_service.reset_hpa_fallback()
    return {"status": "reset", "hpa_fallback_active": False}

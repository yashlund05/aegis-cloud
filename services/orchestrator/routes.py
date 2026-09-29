"""
API routes for Aegis Orchestrator Service (Phase 8).
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

from services.orchestrator.loop import control_loop
from services.orchestrator.service import orchestrator_service

logger = logging.getLogger(__name__)

router = APIRouter()


class TriggerCycleRequest(BaseModel):
    workloads: Optional[List[Dict[str, Any]]] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    telemetry_timestamp: Optional[float] = None
    force_fail_predictor: bool = False
    force_fail_solver: bool = False


@router.post("/cycle/trigger")
async def trigger_cycle(req: Optional[TriggerCycleRequest] = None):
    """
    Manually triggers one complete closed-loop control cycle (Monitor -> Forecast -> Optimize -> Execute).
    Supports failure injection flags to test resilience.
    """
    try:
        r = req or TriggerCycleRequest()
        result = await control_loop.run_cycle(
            workloads=r.workloads,
            nodes=r.nodes,
            telemetry_timestamp=r.telemetry_timestamp,
            force_fail_predictor=r.force_fail_predictor,
            force_fail_solver=r.force_fail_solver,
        )
        return result
    except Exception as e:
        logger.error(f"Error executing manual cycle: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/cycle/status")
async def get_cycle_status():
    """
    Returns live status of the control loop.
    """
    return await orchestrator_service.get_current_status()


@router.get("/cycle/history")
async def get_cycle_history(limit: int = Query(20, ge=1, le=100)):
    """
    Returns recent control loop cycle execution logs.
    """
    return await orchestrator_service.get_cycle_history(limit=limit)

"""
API routes for Aegis Decision Engine Service (Phase 5).
Exposes endpoints for triggering optimization, retrieving decision audit history,
and querying solver health.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
import logging

try:
    from ortools.sat.python import cp_model
except ImportError:
    cp_model = None

from services.shared.schemas import DecisionPlan
from services.decision_engine.service import decision_service
from services.decision_engine.config import config

logger = logging.getLogger(__name__)

router = APIRouter()


class OptimizationRequest(BaseModel):
    cycle_id: Optional[str] = Field(None, description="Unique control cycle identifier")
    workloads: List[Dict[str, Any]] = Field(
        ..., description="List of active workloads with target_cpu and replica bounds"
    )
    nodes: List[Dict[str, Any]] = Field(
        ..., description="List of cluster nodes with cpu/mem capacities and power parameters"
    )
    predictions: Optional[List[Dict[str, Any]]] = Field(
        None, description="Quantile workload demand forecasts from Predictor service"
    )


@router.post("/decisions", response_model=DecisionPlan)
async def create_decision(req: OptimizationRequest):
    """
    Solves the joint autoscaling and pod placement optimization problem.
    Uses OR-Tools CP-SAT with automatic fallback to First-Fit-Decreasing (FFD) heuristic.
    """
    try:
        plan = await decision_service.optimize(
            workloads=req.workloads,
            nodes=req.nodes,
            predictions=req.predictions,
            cycle_id=req.cycle_id,
        )
        return plan
    except Exception as e:
        logger.error(f"Optimization error during cycle '{req.cycle_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions", response_model=List[DecisionPlan])
async def get_decisions(limit: int = Query(20, ge=1, le=100)) -> List[DecisionPlan]:
    """
    Returns historical decision plans produced during recent control cycles.
    """
    return await decision_service.get_history(limit=limit)


@router.get("/decisions/{id}", response_model=DecisionPlan)
async def get_decision(id: str):
    """
    Returns a specific decision plan by ID or cycle ID.
    """
    plan = await decision_service.get_decision_by_id(id)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Decision '{id}' not found.")
    return plan


@router.get("/info")
async def get_solver_info() -> Dict[str, Any]:
    """
    Returns solver engine capabilities, timeout settings, and active backend.
    """
    return {
        "cpsat_available": cp_model is not None,
        "ffd_fallback_enabled": config.enable_ffd_fallback,
        "timeout_ms": config.solver_timeout_ms,
        "utilization_max": config.utilization_max,
        "min_active_nodes": config.min_active_nodes,
    }

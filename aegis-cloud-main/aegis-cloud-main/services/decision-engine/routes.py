from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Dict, Any
from services.shared.schemas import DecisionPlan
from solver import CPSolver

router = APIRouter()
solver = CPSolver(timeout_ms=5000)

class OptimizationRequest(BaseModel):
    cycle_id: str
    workloads: List[Dict[str, Any]]
    nodes: List[Dict[str, Any]]
    predictions: List[Dict[str, Any]]

@router.post("/decisions", response_model=DecisionPlan)
async def create_decision(req: OptimizationRequest):
    plan = solver.solve(req.workloads, req.nodes, req.predictions, req.cycle_id)
    return plan

@router.get("/decisions")
async def get_decisions() -> List[DecisionPlan]:
    # TODO: return decision history
    return []

@router.get("/decisions/{id}")
async def get_decision(id: str):
    # TODO: return specific decision
    return {}

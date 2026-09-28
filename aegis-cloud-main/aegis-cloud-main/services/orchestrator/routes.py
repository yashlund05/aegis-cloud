from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any
from services.orchestrator.service import OrchestratorService
from services.orchestrator.loop import ControlLoop

router = APIRouter()
orchestrator_service = OrchestratorService()
# The control loop instance is shared with main.py via lifespan
_control_loop: ControlLoop = None

def set_control_loop(loop: ControlLoop):
    global _control_loop
    _control_loop = loop

class CycleStatus(BaseModel):
    is_running: bool
    last_run: str
    status: str

@router.post("/cycle/trigger")
async def trigger_cycle(background_tasks: BackgroundTasks):
    """Manually trigger a single orchestrator cycle."""
    if _control_loop:
        background_tasks.add_task(_control_loop.run_cycle)
        return {"message": "Cycle triggered manually"}
    return {"message": "Control loop not initialized", "error": True}

@router.get("/cycle/status", response_model=CycleStatus)
async def cycle_status():
    status = await orchestrator_service.get_current_status()
    return CycleStatus(
        is_running=_control_loop.running if _control_loop else False,
        last_run=status.get("last_cycle_time", "unknown"),
        status=status.get("state", "unknown")
    )

@router.get("/cycle/history")
async def cycle_history(limit: int = 10) -> List[Dict[str, Any]]:
    return await orchestrator_service.get_cycle_history(limit=limit)

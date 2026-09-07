from fastapi import APIRouter
from pydantic import BaseModel
from typing import List

router = APIRouter()

class CycleStatus(BaseModel):
    is_running: bool
    last_run: str
    status: str

@router.post("/cycle/trigger")
async def trigger_cycle():
    # TODO: Implement manual trigger logic via control_loop
    return {"message": "Cycle triggered manually"}

@router.get("/cycle/status", response_model=CycleStatus)
async def cycle_status():
    # TODO: Fetch real status from loop
    return CycleStatus(is_running=True, last_run="2023-01-01T00:00:00Z", status="idle")

@router.get("/cycle/history")
async def cycle_history():
    # TODO: Fetch from DB
    return []

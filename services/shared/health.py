from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict
from datetime import datetime

router = APIRouter()

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str
    dependencies: Dict[str, str]

# In a real scenario, this would be injected or configured per service
SERVICE_NAME = "unknown"
VERSION = "1.0.0"

@router.get("/health")
async def liveness() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
        timestamp=datetime.utcnow().isoformat(),
        dependencies={}
    )

@router.get("/ready")
async def readiness() -> HealthResponse:
    # TODO: Add dependency checks (DB, Redis)
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=VERSION,
        timestamp=datetime.utcnow().isoformat(),
        dependencies={"database": "ok", "redis": "ok"}
    )

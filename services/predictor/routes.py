"""
API routes for Aegis Predictor Service.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Dict, Any, List, Optional
import logging

from services.predictor.service import predictor_service

logger = logging.getLogger(__name__)

router = APIRouter()


class PredictRequest(BaseModel):
    workload_id: str
    horizon: int = 10
    features_override: Optional[Dict[str, Any]] = None


class PredictResponse(BaseModel):
    workload_id: str
    horizon_minutes: int
    p10: float
    p50: float
    p90: float
    latency_ms: float


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    Returns quantile demand predictions (p10, p50, p90) for a given workload and horizon.
    """
    try:
        res = await predictor_service.serve_prediction(
            workload_id=req.workload_id,
            horizon=req.horizon,
            features_override=req.features_override,
        )
        return PredictResponse(**res)
    except Exception as e:
        logger.error(f"Prediction error for '{req.workload_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def get_models(status: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """
    Returns list of all models registered in the ModelRegistry.
    """
    try:
        return predictor_service.registry.list_models(status=status)
    except Exception as e:
        logger.error(f"Error fetching model registry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info")
async def get_predictor_info() -> Dict[str, Any]:
    """
    Returns current predictor configuration, horizons, and loaded models.
    """
    return predictor_service.predictor.get_model_info()

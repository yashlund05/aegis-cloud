"""
API routes for Aegis Predictor Service (Phase 4).
Exposes endpoints for prediction, shadow model tracking, KS concept drift, and retraining.
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import logging

from services.predictor.service import predictor_service
from services.predictor.registry import model_registry
from services.predictor.drift import drift_detector
from services.predictor.retrain import trigger_model_retrain

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


class DriftObservationRequest(BaseModel):
    workload_id: str
    y_true: float = Field(..., description="Actual observed CPU or memory demand")
    y_pred: float = Field(..., description="Forecasted p50 demand")


class RetrainRequest(BaseModel):
    workload_id: str
    data_path: Optional[str] = "datasets/processed_sample_trace.parquet"
    output_dir: Optional[str] = "ml/models/artifacts"


@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    """
    Returns quantile demand predictions (p10, p50, p90) for a given workload and horizon.
    Guarantees latency < 100ms.
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


@router.post("/drift/observe")
async def observe_actual_metric(req: DriftObservationRequest):
    """
    Records an observed actual demand value alongside its forecast to update streaming error history.
    """
    drift_detector.add_observation(req.workload_id, req.y_true, req.y_pred)
    return {"status": "recorded", "workload_id": req.workload_id}


@router.post("/drift/check")
async def check_drift(workload_id: str = Query(...)):
    """
    Runs the Kolmogorov-Smirnov test and rolling WMAPE to evaluate concept drift.
    """
    try:
        return await drift_detector.check_drift(workload_id)
    except Exception as e:
        logger.error(f"Error checking drift for '{workload_id}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models")
async def get_models(status: Optional[str] = Query(None)) -> List[Dict[str, Any]]:
    """
    Returns list of all models registered in the ModelRegistry (active, shadow, retired).
    """
    try:
        return await model_registry.list_models(status=status)
    except Exception as e:
        logger.error(f"Error fetching model registry: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/shadow")
async def get_shadow_models() -> List[Dict[str, Any]]:
    """
    Returns candidate models currently evaluated in shadow mode.
    """
    try:
        return await model_registry.get_shadow_models()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/retrain")
async def trigger_retraining(req: RetrainRequest, background_tasks: BackgroundTasks):
    """
    Triggers model retraining job asynchronously.
    """
    try:
        # Run retraining in background or synchronously if requested
        result = await trigger_model_retrain(
            req.workload_id, data_path=req.data_path, output_dir=req.output_dir
        )
        return {
            "status": "success",
            "message": "Model retraining executed.",
            "details": result,
        }
    except Exception as e:
        logger.error(f"Retraining error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/info")
async def get_predictor_info() -> Dict[str, Any]:
    """
    Returns current predictor configuration, horizons, and loaded models.
    """
    return predictor_service.predictor.get_model_info()

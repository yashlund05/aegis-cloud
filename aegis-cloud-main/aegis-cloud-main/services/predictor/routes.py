from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Any, List
from services.predictor.service import PredictorService
from services.predictor.registry import ModelRegistry

router = APIRouter()
predictor_service = PredictorService()
registry = ModelRegistry()

class PredictRequest(BaseModel):
    workload_id: str = Field(..., min_length=1)
    horizon: int = Field(..., description="Forecast horizon in minutes", ge=5, le=60)

class PredictResponse(BaseModel):
    p10: float
    p50: float
    p90: float

@router.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    if req.horizon not in [5, 10, 15]:
        raise HTTPException(status_code=400, detail="Horizon must be 5, 10, or 15")
        
    try:
        result = await predictor_service.serve_prediction(req.workload_id, req.horizon)
        preds = result.get("predictions", {})
        return PredictResponse(
            p10=preds.get("p10", 0.0),
            p50=preds.get("p50", 0.0),
            p90=preds.get("p90", 0.0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/predictions")
async def get_predictions() -> List[Dict[str, Any]]:
    return []

@router.get("/models")
async def get_models(status: str = None) -> List[Dict[str, Any]]:
    return await registry.list_models(status=status)

@router.post("/models/retrain")
async def trigger_retrain(workload_id: str):
    return {"status": "retraining triggered for workload_id: " + workload_id}

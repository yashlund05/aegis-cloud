"""
Unit tests for Phase 4 Predictor endpoints: shadow routing, drift checking, and retraining.
"""

import os
import asyncio
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from services.predictor.main import app
from services.predictor.registry import model_registry
from ml.training.train_lightgbm import QuantileModelWrapper, export_to_onnx


def test_shadow_model_registration_and_endpoint():
    # Register a shadow model candidate synchronously via asyncio.run
    shadow_candidate = {
        "model_name": "aegis_h10m_q50_shadow",
        "version": "v2.0.0-candidate",
        "horizon_minutes": 10,
        "quantile": 0.5,
        "status": "shadow",
        "features": ["cpu_usage", "memory_usage"],
        "artifact_path": "ml/models/artifacts/aegis_h10m_q50.joblib",
    }
    v_id = asyncio.run(model_registry.register_model(shadow_candidate))
    assert v_id is not None

    with TestClient(app) as client:
        response = client.get("/v1/models/shadow")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        shadow_names = [m.get("model_name") for m in data]
        assert "aegis_h10m_q50_shadow" in shadow_names


def test_drift_observe_and_check_endpoints():
    with TestClient(app) as client:
        workload = "test-service-drift-api"
        # 1. Observe some streaming actual vs predicted points
        for i in range(15):
            obs_payload = {
                "workload_id": workload,
                "y_true": 0.50 + 0.01 * (i % 3),
                "y_pred": 0.50,
            }
            obs_res = client.post("/v1/drift/observe", json=obs_payload)
            assert obs_res.status_code == 200
            assert obs_res.json()["status"] == "recorded"

        # 2. Check drift endpoint
        check_res = client.post(f"/v1/drift/check?workload_id={workload}")
        assert check_res.status_code == 200
        check_data = check_res.json()
        assert "drift_detected" in check_data
        assert "rolling_wmape" in check_data
        assert check_data["workload_id"] == workload


def test_models_retrain_endpoint(tmp_path):
    # Create small temporary dataset to test retraining fast (< 2 seconds)
    full_df = pd.read_parquet("datasets/processed_sample_trace.parquet")
    small_df = full_df.iloc[:300].copy()
    small_data_path = os.path.join(tmp_path, "quick_retrain_sample.parquet")
    small_df.to_parquet(small_data_path)

    with TestClient(app) as client:
        payload = {
            "workload_id": "test-workload-retrain",
            "data_path": small_data_path,
        }
        response = client.post("/v1/models/retrain", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "details" in data
        assert data["details"]["quality_gate_passed"] is True
        assert data["details"]["status"] == "promoted"
        assert len(data["details"]["models_trained"]) > 0


def test_export_to_onnx_graceful_handling():
    # Verify export_to_onnx handles missing onnx gracefully without raising uncaught exceptions
    mock_wrapper = QuantileModelWrapper(model_obj=None, backend="sklearn_hist", feature_names=["cpu_usage"])
    res = export_to_onnx(mock_wrapper, ["cpu_usage"], "output.onnx")
    assert isinstance(res, bool)

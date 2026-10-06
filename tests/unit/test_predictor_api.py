"""
Unit tests for Predictor FastAPI endpoints.
"""

from fastapi.testclient import TestClient
from services.predictor.main import app


def test_predict_endpoint_response_structure():
    with TestClient(app) as client:
        payload = {
            "workload_id": "cart-service",
            "horizon": 10,
            "features_override": {
                "cpu_usage": 0.55,
                "memory_usage": 0.60,
                "rolling_mean_15min": 0.52,
            },
        }
        # Warm-up call (JIT / cold start)
        client.post("/v1/predict", json=payload)

        # Measured call
        response = client.post("/v1/predict", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["workload_id"] == "cart-service"
        assert data["horizon_minutes"] == 10
        assert "p10" in data
        assert "p50" in data
        assert "p90" in data
        assert data["p10"] <= data["p50"] <= data["p90"]
        assert data["latency_ms"] < 100.0  # Warm SLA < 100ms


def test_models_list_endpoint():
    with TestClient(app) as client:
        response = client.get("/v1/models")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


def test_predictor_info_endpoint():
    with TestClient(app) as client:
        response = client.get("/v1/info")
        assert response.status_code == 200
        data = response.json()
        assert "horizons" in data
        assert "quantiles" in data

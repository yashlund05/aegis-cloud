# Aegis Orchestrator

Responsibility: Control loop orchestration — coordinates the Monitor→Forecast→Optimize→Execute cycle.

## Endpoints
- `POST /v1/cycle/trigger` (manual trigger)
- `GET /v1/cycle/status`
- `GET /v1/cycle/history`

## Config
See `config.py`

## Running Locally
```bash
uvicorn main:app --reload
```

# Phase 4: Prediction Service

## Purpose
Expose ML models via FastAPI to serve predictions to the Decision Engine.

## Prerequisites
- Python 3.10+
- Models from Phase 3

## Files
- verify.sh
- load_test.sh

## Implementation
FastAPI endpoint with drift detection, fallback mechanisms, caching, and shadow inference.

## How to run
\uvicorn services.predictor.main:app --host 0.0.0.0 --port 8000\

## How to test
\ash verify.sh\

## Expected output
JSON prediction responses under 100ms.

## Verification
Returns PASS.

## Definition of Done
Service reliably serves P10, P50, P90 predictions for 5, 10, 15 min horizons.

## Known limitations
Shadow model deployment requires manual registration in registry.

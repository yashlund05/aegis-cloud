# Phase 5: Decision Engine

## Purpose
Determine optimal replica counts, placements, and node power states to minimize energy while meeting SLAs.

## Prerequisites
- Python 3.10+
- OR-Tools

## Files
- schemas/decision_plan.json
- verify.sh

## Implementation
Implements a CP-SAT solver prioritizing energy reduction with a strict SLA/SLO penalty, and falls back to FFD bin packing upon timeout. 

## How to run
\uvicorn services.decision_engine.main:app --host 0.0.0.0 --port 8000\

## How to test
\ash verify.sh\

## Expected output
Decision Plan JSON response.

## Verification
Returns PASS.

## Definition of Done
Decision engine produces valid multi-objective optimization plans under the specified timeout.

## Known limitations
None.

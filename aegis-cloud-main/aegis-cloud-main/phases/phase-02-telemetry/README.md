# Phase 2: Telemetry

## Purpose
Collect metrics from Prometheus and Kepler, process them, and store in Redis.

## Prerequisites
- Phase 1 completed

## Files
- setup.sh
- verify.sh

## Implementation
Completes the telemetry collector service.

## How to run
\ash setup.sh\

## How to test
\pytest tests/\

## Expected output
Data in Redis.

## Verification
Returns PASS for telemetry tests.

## Definition of Done
Telemetry is successfully collected and stored in Redis.

## Known limitations
None.

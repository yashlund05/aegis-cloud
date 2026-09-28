# Phase 6: Custom Kubernetes Scheduler

## Purpose
Schedule pods based on ML predictions of workload demand and node energy efficiency.

## Prerequisites
- Go 1.21+
- Docker
- kind cluster

## Files
- deploy.sh
- verify.sh

## Implementation
Implements Filter and Score plugins for the Kubernetes scheduler framework, utilizing prediction caching and energy profiling.

## How to run
\ash deploy.sh\

## How to test
\ash verify.sh\

## Expected output
Scheduler pod running in kube-system namespace, actively scheduling Aegis workloads.

## Verification
Returns PASS.

## Definition of Done
Custom scheduler is built, deployed, and successfully schedules pods using the scoring logic.

## Known limitations
None.

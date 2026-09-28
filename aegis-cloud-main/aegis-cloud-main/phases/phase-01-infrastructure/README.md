# Phase 1: Infrastructure

## Purpose
Setup the base Kubernetes cluster and required backing services.

## Prerequisites
- Docker
- kind
- kubectl

## Files
- setup.sh
- verify.sh
- namespace.yaml

## Implementation
Sets up a kind cluster with 1 control plane and 3 workers.
Deploys PostgreSQL, Redis, Prometheus, Grafana, and Kepler.

## How to run
\ash setup.sh\

## How to test
\ash verify.sh\

## Expected output
All services running.

## Verification
Returns PASS for all services.

## Definition of Done
Cluster is accessible and all backing services are deployed.

## Known limitations
Simulated in this environment.

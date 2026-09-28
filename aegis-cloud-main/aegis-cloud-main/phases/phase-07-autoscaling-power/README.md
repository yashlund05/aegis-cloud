# Phase 7: Autoscaling & Node Power Control

## Purpose
Execute replica scaling and node power state transitions safely on the cluster.

## Prerequisites
- K8s cluster
- Decision Engine running

## Files
- verify.sh

## Implementation
Implements secure execution of autoscaling and node power management with retries, a 10% dead-zone, 5-minute cooldown, eviction API for drains, and control-plane protection.

## How to run
Deploy the controllers via Helm or standard YAML manifests.

## How to test
\ash verify.sh\

## Expected output
Controllers respond to Decision Plans and adjust resources within safe bounds.

## Verification
Returns PASS.

## Definition of Done
Scaling and power state controllers operate safely without breaking the cluster.

## Known limitations
Node power states (standby) are simulated via cordoning/draining in standard kind cluster. 

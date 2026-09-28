# Phase 9: A/B and Ablation Evaluation

## Purpose
Quantify the benefits of the Aegis architecture against baseline HPA and partial implementations.

## Prerequisites
- Full cluster environment
- Load generator (e.g. locust or wrk)

## Files
- run_ablation.sh
- configs/
- verify.sh

## Implementation
Defines 4 configurations and runs workload testing to measure latency, SLO, energy, and cycle times.

## How to run
\ash run_ablation.sh\

## How to test
\ash verify.sh\

## Expected output
Reproducible Markdown/CSV reports in eports/ and esults/.

## Verification
Returns PASS if report generation works.

## Definition of Done
Automated execution of 4 configurations and report generation is implemented.

## Known limitations
Real cluster execution takes hours. Verification uses SYNTHETIC TEST DATA if cluster is missing.

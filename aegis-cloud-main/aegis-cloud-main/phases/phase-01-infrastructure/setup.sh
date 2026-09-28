#!/bin/bash
set -e

echo "Setting up Phase 1: Infrastructure..."
kubectl apply -f namespace.yaml
# Here we'd call existing infrastructure setup scripts or apply them
# For now, it's just a mock that sets up the required mock state or invokes kind.
# In a real environment we would do:
# bash ../../infrastructure/kind/setup.sh
# kubectl apply -f ../../infrastructure/postgres/deployment.yaml
# kubectl apply -f ../../infrastructure/redis/deployment.yaml
# kubectl apply -f ../../infrastructure/prometheus/deployment.yaml
# kubectl apply -f ../../infrastructure/grafana/deployment.yaml
# kubectl apply -f ../../infrastructure/kepler/deployment.yaml

echo "Phase 1 Infrastructure setup complete."

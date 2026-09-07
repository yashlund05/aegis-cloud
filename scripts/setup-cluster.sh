#!/bin/bash
set -euo pipefail
# Aegis local development setup
echo "=== Aegis Local Development Setup ==="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "Docker required"; exit 1; }
command -v kind >/dev/null 2>&1 || { echo "kind required"; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl required"; exit 1; }
command -v helm >/dev/null 2>&1 || { echo "helm required"; exit 1; }

echo "Step 1: Creating kind cluster..."
kind create cluster --config infrastructure/kind/kind-config.yaml --name aegis

echo "Step 2: Creating namespaces..."
kubectl apply -f infrastructure/kubernetes/namespaces.yaml

echo "Step 3: Applying RBAC..."
kubectl apply -f infrastructure/kubernetes/rbac.yaml

echo "Step 4: Deploying PostgreSQL..."
kubectl apply -f infrastructure/postgres/deployment.yaml

echo "Step 5: Deploying Redis..."
kubectl apply -f infrastructure/redis/deployment.yaml

echo "Step 6: Deploying Prometheus..."
kubectl apply -f infrastructure/prometheus/deployment.yaml

echo "Step 7: Deploying Grafana..."
kubectl apply -f infrastructure/grafana/deployment.yaml

echo "Step 8: Waiting for infrastructure pods..."
kubectl wait --for=condition=ready pod -l app.kubernetes.io/part-of=aegis -n aegis-data --timeout=120s || true
kubectl wait --for=condition=ready pod -l app.kubernetes.io/part-of=aegis -n aegis-monitoring --timeout=120s || true

echo "=== Aegis cluster ready ==="
kubectl get pods -A | grep aegis

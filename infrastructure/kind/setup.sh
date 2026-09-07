#!/bin/bash
set -euo pipefail

echo "Checking prerequisites..."
command -v kind >/dev/null 2>&1 || { echo >&2 "kind is required but not installed.  Aborting."; exit 1; }
command -v kubectl >/dev/null 2>&1 || { echo >&2 "kubectl is required but not installed.  Aborting."; exit 1; }
command -v helm >/dev/null 2>&1 || { echo >&2 "helm is required but not installed.  Aborting."; exit 1; }
command -v docker >/dev/null 2>&1 || { echo >&2 "docker is required but not installed.  Aborting."; exit 1; }

echo "Creating Kind cluster from config..."
kind create cluster --name aegis --config ./kind-config.yaml

echo "Waiting for cluster to be ready..."
kubectl wait --for=condition=Ready nodes --all --timeout=300s

echo "Creating namespaces..."
kubectl create namespace aegis-system || true
kubectl create namespace aegis-monitoring || true
kubectl create namespace aegis-data || true

echo "Applying RBAC..."
kubectl apply -f ../kubernetes/rbac.yaml

echo "Cluster info:"
kubectl cluster-info
kubectl get nodes -o wide

echo "Aegis cluster setup complete."

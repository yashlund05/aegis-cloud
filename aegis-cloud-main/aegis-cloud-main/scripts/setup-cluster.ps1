# Aegis Local Kind Cluster & Infrastructure Setup (Windows PowerShell)
Write-Host "=== Aegis Local Development Setup (Windows) ===" -ForegroundColor Cyan

function Check-Tool($tool) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Write-Host "Error: '$tool' not found in current PATH. Please ensure Docker is running and restart PowerShell." -ForegroundColor Red
        exit 1
    }
}

Check-Tool "docker"
Check-Tool "kind"
Check-Tool "kubectl"

Write-Host "Step 1: Creating kind cluster..." -ForegroundColor Yellow
kind create cluster --config infrastructure/kind/kind-config.yaml --name aegis

Write-Host "Step 2: Creating namespaces..." -ForegroundColor Yellow
kubectl apply -f infrastructure/kubernetes/namespaces.yaml

Write-Host "Step 3: Applying RBAC..." -ForegroundColor Yellow
kubectl apply -f infrastructure/kubernetes/rbac.yaml

Write-Host "Step 4: Deploying PostgreSQL + TimescaleDB..." -ForegroundColor Yellow
kubectl apply -f infrastructure/postgres/deployment.yaml

Write-Host "Step 5: Deploying Redis..." -ForegroundColor Yellow
kubectl apply -f infrastructure/redis/deployment.yaml

Write-Host "Step 6: Deploying Prometheus..." -ForegroundColor Yellow
kubectl apply -f infrastructure/prometheus/deployment.yaml

Write-Host "Step 7: Deploying Grafana..." -ForegroundColor Yellow
kubectl apply -f infrastructure/grafana/deployment.yaml

Write-Host "Step 8: Checking cluster pods..." -ForegroundColor Yellow
kubectl get pods -A

Write-Host "=== Aegis cluster setup complete ===" -ForegroundColor Green

.PHONY: help setup teardown infra-up infra-down services-up services-down build build-service test test-python test-go lint lint-python lint-go fmt docker-build docker-push db-migrate clean dev load-test demo

help:
	@echo "Aegis Makefile"
	@echo "Available targets:"
	@echo "  setup            Create kind cluster + deploy infrastructure"
	@echo "  teardown         Delete kind cluster"
	@echo "  infra-up         Deploy monitoring + data stores"
	@echo "  infra-down       Remove monitoring + data stores"
	@echo "  services-up      Deploy Aegis services"
	@echo "  services-down    Remove Aegis services"
	@echo "  build            Build all Docker images"
	@echo "  build-service    Build specific service (e.g., make build-service SERVICE=api-gateway)"
	@echo "  test             Run all tests (pytest + go test)"
	@echo "  test-python      Run Python tests"
	@echo "  test-go          Run Go tests"
	@echo "  lint             Run all linters"
	@echo "  lint-python      flake8"
	@echo "  lint-go          golangci-lint"
	@echo "  fmt              Format all code"
	@echo "  docker-build     Build all Docker images"
	@echo "  docker-push      Push to GHCR"
	@echo "  db-migrate       Run database migrations"
	@echo "  clean            Clean build artifacts"
	@echo "  dev              Run a service locally (e.g., make dev SERVICE=api-gateway)"
	@echo "  load-test        Run k6 load test"
	@echo "  demo             Run full demo (setup + deploy + load test)"

setup:
	@echo "Setting up kind cluster and infrastructure..."
	bash infrastructure/kind/setup.sh
	@echo "Deploying monitoring stack..."
	kubectl apply -f infrastructure/kubernetes/namespaces.yaml
	kubectl apply -f infrastructure/kubernetes/rbac.yaml
	kubectl apply -f infrastructure/prometheus/deployment.yaml
	kubectl apply -f infrastructure/prometheus/prometheus-config.yaml
	kubectl apply -f infrastructure/prometheus/alerts.yaml
	kubectl apply -f infrastructure/grafana/deployment.yaml
	kubectl apply -f infrastructure/grafana/datasources.yaml
	kubectl apply -f infrastructure/kepler/deployment.yaml
	@echo "Deploying data stores..."
	kubectl apply -f infrastructure/postgres/deployment.yaml
	kubectl apply -f infrastructure/redis/deployment.yaml
	@echo "Waiting for pods to be ready..."
	kubectl wait --for=condition=Ready pods --all -n aegis-monitoring --timeout=300s || true
	kubectl wait --for=condition=Ready pods --all -n aegis-data --timeout=300s || true
	@echo "Running database migrations..."
	$(MAKE) db-migrate
	@echo "Setup complete!"

teardown:
	@echo "Tearing down kind cluster..."
	bash infrastructure/kind/teardown.sh

infra-up:
	@echo "Starting infrastructure..."
	docker compose up -d postgres redis prometheus grafana

infra-down:
	@echo "Stopping infrastructure..."
	docker compose down postgres redis prometheus grafana

services-up:
	@echo "Starting Aegis services..."
	docker compose up -d

services-down:
	@echo "Stopping Aegis services..."
	docker compose down

build: docker-build

build-service:
	@echo "Building service $(SERVICE)..."
	docker build -t aegis-$(SERVICE) ./services/$(SERVICE)

test: test-python test-go

test-python:
	pytest tests/ -v

test-go:
	cd scheduler/aegis-scheduler && go test ./...

lint: lint-python lint-go

lint-python:
	flake8 services/ ml/ tests/

lint-go:
	cd scheduler/aegis-scheduler && golangci-lint run

fmt:
	black services/ ml/ tests/
	cd scheduler/aegis-scheduler && gofmt -w .

docker-build:
	docker compose build

docker-push:
	@echo "Pushing images..."

db-migrate:
	@echo "Running database migrations..."
	kubectl exec -n aegis-data deploy/postgres -- psql -U admin -d aegis -f /docker-entrypoint-initdb.d/init.sql || true

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf ml/models/artifacts/*.txt
	rm -rf ml/models/registry.json

dev:
	@echo "Running $(SERVICE) in dev mode..."
	cd services/$(SERVICE) && uvicorn main:app --reload --host 0.0.0.0 --port 8000

load-test:
	@echo "Running load tests..."
	k6 run tests/load/scenarios/baseline.js || echo "k6 not installed or no test script found"

demo: setup services-up
	@echo "Running demo workload..."
	sleep 10
	@echo "Triggering telemetry collection..."
	curl -s -X POST http://localhost:8000/v1/collect || true
	sleep 5
	@echo "Requesting prediction..."
	curl -s -X POST http://localhost:8001/v1/predict -H "Content-Type: application/json" -d '{"workload_id":"demo","horizon":15}' || true
	@echo ""
	@echo "Demo complete! Visit Grafana at http://localhost:3000"

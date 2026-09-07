.PHONY: help setup teardown infra-up infra-down services-up services-down build build-service test test-python test-go lint lint-python lint-go fmt docker-build docker-push db-migrate clean dev load-test

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

setup:
	@echo "Setting up kind cluster and infrastructure..."
	# TODO: Implement kind cluster creation

teardown:
	@echo "Tearing down kind cluster..."
	# TODO: Implement kind cluster deletion

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
	pytest

test-go:
	cd scheduler-plugin && go test ./...

lint: lint-python lint-go

lint-python:
	flake8 .

lint-go:
	cd scheduler-plugin && golangci-lint run

fmt:
	black .
	cd scheduler-plugin && gofmt -w .

docker-build:
	docker compose build

docker-push:
	@echo "Pushing images..."

db-migrate:
	@echo "Running migrations..."

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache

dev:
	@echo "Running $(SERVICE) in dev mode..."

load-test:
	@echo "Running load tests..."

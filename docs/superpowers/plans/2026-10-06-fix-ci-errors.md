# Fix CI Errors and Docker Build Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all failing CI checks (Python lint, Go lint timeout) and Docker container builds across Aegis Cloud repository.

**Architecture:** 
1. Fix all 203 flake8 lint errors (unused imports `F401`, blank lines `E302`/`E305`/`E303`, trailing whitespace `W293`/`W391`) across `services/`, `ml/`, and `tests/`.
2. Update `.github/workflows/ci.yml` to pass `--timeout=5m` to `golangci-lint` to prevent package loading timeouts on large k8s dependencies.
3. Fix Docker build contexts in `.github/workflows/docker.yml` and `docker-compose.yml` so that `-r ../shared/requirements.txt` and shared service packages resolve properly during build.

**Tech Stack:** Python 3.11, Flake8, Ruff, Go 1.21, GolangCI-Lint, Docker Buildx, GitHub Actions.

---

### Task 1: Fix Python Lint (Flake8) Errors

**Files:**
- Modify: `services/`, `ml/`, `tests/` Python files

- [ ] **Step 1: Remove unused imports (`F401`) and format blank lines (`E302`, `E305`, `E303`, `W293`, `W391`)**
- [ ] **Step 2: Run flake8 check to verify zero errors remain**
  Run: `python -m flake8 services/ ml/ tests/ --max-line-length=120 --ignore=E501,W503`
  Expected: Exit code 0 (no output).
- [ ] **Step 3: Run existing unit test suite to ensure no regressions**
  Run: `python -m pytest tests/unit/ -v`
  Expected: All passing.
- [ ] **Step 4: Commit changes**
  `git commit -m "fix(lint): resolve flake8 unused imports and whitespace errors across services, ml, and tests"`

---

### Task 2: Fix Go Linter Timeout in CI

**Files:**
- Modify: `.github/workflows/ci.yml:24-27`

- [ ] **Step 1: Add `--timeout=5m` to `golangci/golangci-lint-action` in `.github/workflows/ci.yml`**
- [ ] **Step 2: Verify `ci.yml` syntax**
- [ ] **Step 3: Commit changes**
  `git commit -m "ci: increase golangci-lint timeout to 5m in Aegis CI workflow"`

---

### Task 3: Fix Docker Build Context and Shared Requirements Resolution

**Files:**
- Modify: `.github/workflows/docker.yml`
- Modify: `docker-compose.yml`
- Modify: `services/*/Dockerfile`

- [ ] **Step 1: Standardize Docker build context in `.github/workflows/docker.yml` to repo root and point `file:` to service Dockerfile**
- [ ] **Step 2: Update service Dockerfiles to copy requirements from repository structure (`services/shared/requirements.txt` and `services/<service>/requirements.txt`)**
- [ ] **Step 3: Update `docker-compose.yml` to align build context with repo root**
- [ ] **Step 4: Commit changes**
  `git commit -m "build(docker): fix build context and shared requirements resolution for all microservices"`

---

### Task 4: Full Verification

- [ ] **Step 1: Run `python -m flake8 services/ ml/ tests/ --max-line-length=120 --ignore=E501,W503`**
- [ ] **Step 2: Run `python -m pytest tests/unit/`**
- [ ] **Step 3: Check git status and diff**

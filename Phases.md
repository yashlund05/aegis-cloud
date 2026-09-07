# Implementation Roadmap (10 Phases)

## Phase 1: Foundations (Cluster + Monitoring + Storage)
- **Objective:** Provision a running kind cluster with Prometheus, Grafana, Kepler, PostgreSQL+TimescaleDB, and Redis.
- **Prerequisites:** Docker, kind, helm, kubectl installed.
- **Tasks:**
  - Create kind configuration (1 CP, 3 Workers).
  - Setup Kubernetes namespaces (`aegis-system`, `monitoring`).
  - Deploy Prometheus and Grafana via Helm.
  - Deploy Kepler daemonset for energy metrics.
  - Deploy PostgreSQL (with TimescaleDB) and apply initial schema migrations.
  - Deploy Redis instance.
  - Implement health verification script.
- **Deliverables:** Infrastructure as Code scripts (Makefile/shell), baseline K8s manifests.
- **Files Affected:** `deploy/kind-config.yaml`, `deploy/helm/`, `db/migrations/001_init.sql`.
- **Testing:** Unit (none), Integration (Infrastructure readiness checks).
- **Validation Metric:** All pods Running, Prometheus scraping Kepler metrics, PostgreSQL and Redis accessible.
- **Definition of Done:** `make infra-up` yields a fully observable local cluster.

## Phase 2: Data Pipeline (Telemetry + Traces + Preprocessing)
- **Objective:** Build telemetry collector to pull metrics, extract features, and populate the Redis feature store.
- **Prerequisites:** Phase 1.
- **Tasks:**
  - Implement Telemetry Collector service (Python).
  - Create PromQL query library for metric extraction.
  - Define Redis schema mapping for features.
  - Implement trace preprocessing pipeline (handling Google cluster traces for simulation).
  - Validate data integrity in Redis.
- **Deliverables:** `telemetry-collector` service.
- **Files Affected:** `src/telemetry/collector.py`, `src/telemetry/promql.py`, `src/common/redis_client.py`.
- **Testing:** Unit tests for feature aggregation logic. Integration tests for PromQL fetching.
- **Validation Metric:** Features written to Redis with correct 1h TTL and expected format.
- **Definition of Done:** Collector runs continuously without memory leaks and DB reflects accurate state.

## Phase 3: Forecasting (LightGBM + Quantile + Evaluation)
- **Objective:** Train LightGBM quantile models and establish walk-forward evaluation harness.
- **Prerequisites:** Phase 2, Historical dataset available.
- **Tasks:**
  - Build feature engineering module (AR lags, rolling stats, time features).
  - Implement LightGBM quantile regression training scripts.
  - Create walk-forward validation harness.
  - Establish Prophet baseline for comparison.
  - Compute WMAPE and Pinball loss metrics.
- **Deliverables:** ML training pipeline, model artifacts.
- **Files Affected:** `src/ml/train.py`, `src/ml/features.py`, `src/ml/evaluate.py`.
- **Testing:** Unit tests for feature transforms.
- **Validation Metric:** WMAPE < target threshold, p90 coverage > 85%.
- **Definition of Done:** Training pipeline successfully outputs valid model artifacts with evaluation reports.

## Phase 4: Prediction Service (MLServer/API/Model Registry/Drift)
- **Objective:** Serve predictions via FastAPI with model versioning and KS drift detection.
- **Prerequisites:** Phase 3.
- **Tasks:**
  - Build Predictor service API using FastAPI.
  - Implement basic model registry in PostgreSQL.
  - Export LightGBM models to ONNX.
  - Implement KS test for drift detection.
  - Set up shadow deployment routing.
  - Create nightly retraining job stub.
- **Deliverables:** `predictor` microservice Docker image.
- **Files Affected:** `src/predictor/main.py`, `src/predictor/inference.py`, `src/predictor/drift.py`.
- **Testing:** Unit tests for API endpoints and drift math. Load tests for latency.
- **Validation Metric:** `POST /v1/predict` latency < 100ms.
- **Definition of Done:** Predictor responds accurately in real-time with loaded ONNX models.

## Phase 5: Decision Engine (CP-SAT + FFD Fallback)
- **Objective:** Build optimization solver that produces valid scheduling and scaling plans.
- **Prerequisites:** Phase 4.
- **Tasks:**
  - Formulate decision constraints in OR-Tools CP-SAT.
  - Implement First-Fit Decreasing (FFD) fallback logic.
  - Define JSON schema for decision plans.
  - Implement solver wall-clock timeout handling.
- **Deliverables:** `decision-engine` microservice.
- **Files Affected:** `src/decision/solver.py`, `src/decision/fallback.py`, `src/decision/models.py`.
- **Testing:** Unit tests for constraint models, solver timeout behavior, and fallback activation.
- **Validation Metric:** CP-SAT produces valid plan within timeout; FFD activates upon failure.
- **Definition of Done:** Engine accepts mock forecasts and returns a structurally valid `plan`.

## Phase 6: Scheduler (Go K8s Scheduler Plugin)
- **Objective:** Develop a custom Go scheduler plugin to score nodes by energy and predicted utilization.
- **Prerequisites:** Phase 5, Go environment.
- **Tasks:**
  - Scaffold K8s Scheduler Plugin (Filter & Score extension points).
  - Implement caching layer to read prediction scores.
  - Implement scoring function: `w1*(1-util) + w2*(-energy) + w3*balance`.
  - Compile and deploy as alternate scheduler in kind.
- **Deliverables:** `aegis-scheduler` Go binary and Docker image.
- **Files Affected:** `src/scheduler/main.go`, `src/scheduler/plugin.go`.
- **Testing:** Unit tests for scoring math. Integration with mock K8s api.
- **Validation Metric:** Scheduling latency ≤ 50ms; pods route to correct nodes.
- **Definition of Done:** Scheduler successfully binds a pod to a node based on custom logic.

## Phase 7: Execution (Autoscaler + Node Power Controller)
- **Objective:** Execute decision plans safely against the K8s API.
- **Prerequisites:** Phase 5.
- **Tasks:**
  - Implement Autoscaler Controller applying replica plans.
  - Add dead-zone (±10%) and cooldown (≥5m) safety logic.
  - Implement Node Power Controller (cordon/drain/power).
  - Implement HPA fallback logic trigger.
- **Deliverables:** `execution-controller` service.
- **Files Affected:** `src/executor/autoscaler.py`, `src/executor/power.py`, `src/executor/safety.py`.
- **Testing:** Unit tests for safety thresholds. Dry-run integration tests.
- **Validation Metric:** Replicas change correctly without thrashing; fallback activates on error.
- **Definition of Done:** Controller successfully mutates cluster state matching the decision plan safely.

## Phase 8: Closed-Loop Integration
- **Objective:** Connect all components into a running 30-60s control loop on kind.
- **Prerequisites:** Phases 1-7.
- **Tasks:**
  - Implement Orchestrator service to drive the cycle.
  - Setup load generation tool (k6/hey) to simulate workload spikes.
  - Connect full end-to-end flow.
  - Inject failures to test HPA fallback, FFD fallback, and stale telemetry handling.
- **Deliverables:** Unified Helm chart deploying all Aegis components.
- **Files Affected:** `src/orchestrator/main.py`, `deploy/helm/aegis/`.
- **Testing:** End-to-end integration tests.
- **Validation Metric:** Full cycle completes in ≤60s. Decisions logged correctly.
- **Definition of Done:** The system autonomously manages load variations on the kind cluster.

## Phase 9: Evaluation (HPA vs Aegis + Ablation)
- **Objective:** Conduct rigorous A/B and ablation testing to gather quantitative results.
- **Prerequisites:** Phase 8.
- **Tasks:**
  - Build evaluation framework script.
  - Run baseline: stock Kubernetes HPA.
  - Run ablation 1: Forecast-only (no optimal placement).
  - Run ablation 2: Forecast + placement (no power mgmt).
  - Run full Aegis system.
  - Collect and analyze Prometheus metrics for all runs.
- **Deliverables:** Jupyter notebooks with metric analysis and charts.
- **Files Affected:** `eval/run_experiments.sh`, `eval/analysis.ipynb`.
- **Testing:** Validation of metric collection completeness.
- **Validation Metric:** Results table populated with Energy consumed and SLO violations.
- **Definition of Done:** Reproducible dataset comparing HPA to Aegis generated.

## Phase 10: Finalization (Documentation + Dashboards + Reproducibility + Demo)
- **Objective:** Polish the system for demonstration and open-source release.
- **Prerequisites:** Phase 9.
- **Tasks:**
  - Finalize Grafana dashboards (Forecast, Energy, Timeline views).
  - Complete README, API documentation, and architecture diagrams.
  - Create automated demo script (`make demo`).
  - Verify clean reproducibility (clone -> install -> run).
- **Deliverables:** Polished repository, demo video/script.
- **Files Affected:** `README.md`, `docs/`, `deploy/grafana/dashboards/`.
- **Testing:** Manual walkthrough from a fresh environment.
- **Validation Metric:** Demo script executes flawlessly in under 5 minutes.
- **Definition of Done:** Repository is publication-ready and meets all project specification criteria.

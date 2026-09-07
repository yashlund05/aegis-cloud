# Product Requirements Document (PRD)

## 1. Product Overview
- **Product Name:** Aegis
- **Problem:** Existing autoscaling (HPA) in Kubernetes is reactive, leading to lag in scaling up during demand spikes (causing SLO violations) and delayed scaling down (causing energy waste from idle capacity).
- **Why it Matters:** Inefficient resource allocation leads to high operational costs, unnecessary energy consumption (carbon footprint), and poor application performance due to SLO violations.
- **Proposed Solution:** A predictive, closed-loop AI-driven Kubernetes orchestration system coupling quantile workload forecasting with a joint optimization decision engine. It plans ahead to scale and schedule workloads in an energy-aware manner.
- **Target Users:** Cloud operators, SRE teams, DevOps engineers, cluster administrators, and system researchers.
- **Objectives:** 
  - *Functional:* Proactively scale workloads, place pods optimally, and manage node power states.
  - *Technical:* Achieve decision cycle ≤60s, prediction latency <100ms, and maintain system stability.
  - *Research/Industrial:* Demonstrate quantifiable energy savings and reduced SLO violations compared to standard reactive HPA.

## 2. Functional Requirements

### FR-TEL: Telemetry & Monitoring
- **FR-TEL-001:** The system shall continuously collect cluster and workload telemetry (CPU, memory, network, disk, HTTP rate, pod count, node utilization) via Prometheus and Kepler.
- **FR-TEL-002:** The system shall aggregate and preprocess metrics for feature generation.

### FR-PRED: Demand Forecasting
- **FR-PRED-001:** The system shall utilize LightGBM quantile regression models to forecast future workload demand.
- **FR-PRED-002:** The predictor shall output predictions for the 10th (p10), 50th (p50), and 90th (p90) percentiles.
- **FR-PRED-003:** Forecasts shall be provided for multiple horizons: 5, 10, and 15 minutes.
- **FR-PRED-004:** The system shall perform model drift detection using Kolmogorov-Smirnov (KS) tests and trigger retraining when necessary.

### FR-DEC: Decision Engine
- **FR-DEC-001:** The decision engine shall utilize an OR-Tools CP-SAT solver to formulate a joint optimization plan (replica count, pod placement, node power state).
- **FR-DEC-002:** The engine shall fallback to a First-Fit Decreasing (FFD) heuristic if the CP-SAT solver times out.
- **FR-DEC-003:** The engine shall calculate energy-aware scheduling scores and optimal replica counts based on the p90 forecast.

### FR-EXEC: Execution & Kubernetes Integration
- **FR-EXEC-001:** The autoscaler controller shall execute replica scaling plans (respecting a dead zone of ±10% and a cooldown of ≥5 min).
- **FR-EXEC-002:** The system shall employ a Go-based Kubernetes scheduler plugin for pod placement.
- **FR-EXEC-003:** The node power controller shall issue node state commands (e.g., cordon/drain/power off).
- **FR-EXEC-004:** The system shall fallback seamlessly to Kubernetes HPA if the Aegis control loop fails or telemetry goes stale.

### FR-OBS: Observability & Audit
- **FR-OBS-001:** The system shall maintain an immutable audit log of all decisions, actions, and prediction outputs.
- **FR-OBS-002:** The system shall provide a dashboard for system observability, A/B testing, and ablation testing results.

## 3. Non-Functional Requirements
- **NFR-REL-001 (Reliability):** The system must handle component failures gracefully (e.g., failing over to HPA).
- **NFR-PERF-001 (Performance):** ML inference latency must be <100ms.
- **NFR-PERF-002 (Performance):** The end-to-end decision control cycle must execute in ≤60 seconds.
- **NFR-SEC-001 (Security):** System APIs shall be secured using JWT and RBAC.
- **NFR-MNT-001 (Maintainability):** Code must be strongly typed, modular, and extensively tested.
- **NFR-TST-001 (Testability):** The system must support dry-run capabilities and automated integration testing.

## 4. MVP vs Future Scope
### Minimum Viable Product (MVP)
- Telemetry collection & Feature generation (Prometheus/Kepler to Redis)
- Forecasting Service (LightGBM p10/p50/p90)
- Decision Engine (CP-SAT + FFD fallback)
- Execution components (Autoscaler, Go Scheduler Plugin, Node Power Controller)
- Energy Monitoring Module
- Fallback-to-HPA mechanism
- Audit Logging & Basic Dashboard

### Future Scope
- LLM agent integration for conversational ops
- Reinforcement Learning (RL) based policies
- Self-healing mechanisms
- Multi-cloud and edge-cloud orchestration
- Carbon-aware geographical workload placement
- Full digital-twin simulation

# System Flow Document

## 1. Startup Flow

```mermaid
sequenceDiagram
    participant Infra as kind Cluster
    participant Mon as Monitoring (Prom, Kepler)
    participant Data as Data Stores (PG, Redis)
    participant Aegis as Aegis Services

    Infra->>Mon: Bootstrap monitoring
    Mon-->>Infra: Ready
    Infra->>Data: Start PostgreSQL & Redis
    Data-->>Infra: DBs Ready
    Infra->>Aegis: Start Telemetry Collector
    Infra->>Aegis: Start Predictor & MLServer
    Infra->>Aegis: Start Decision Engine
    Infra->>Aegis: Start Execution (Autoscaler, Scheduler)
    Infra->>Aegis: Start Orchestrator
    Aegis->>Aegis: Perform Health Checks
    Aegis-->>Infra: System Ready
```

## 2. Control-Loop Flow (30-60s Cycle)

```mermaid
sequenceDiagram
    participant Orch as Orchestrator
    participant Tel as Telemetry Collector
    participant Redis as Redis Feature Store
    participant Pred as Predictor
    participant Dec as Decision Engine
    participant Exec as Execution (K8s API)

    Orch->>Tel: Trigger Cycle
    Tel->>Tel: Scrape Prometheus/Kepler
    Tel->>Redis: Extract & write features
    Orch->>Pred: Request Forecast
    Pred->>Redis: Read features (last 60m)
    Pred->>Pred: LightGBM Inference
    Pred-->>Orch: p10/p50/p90 Forecasts
    Orch->>Dec: Send Forecasts
    Dec->>Dec: CP-SAT Optimization (or FFD)
    Dec-->>Orch: Decision Plan
    Orch->>Exec: Execute Plan (Safety/Cooldown checks)
    Exec->>Exec: Autoscale / Schedule
    Exec-->>Orch: Verification
    Orch->>Orch: Log to Audit DB
```

## 3. Failure Flows

- **Predictor Fails:** The orchestrator retrieves the last valid prediction from the cache and uses it.
- **Redis Unavailable:** System degrades gracefully; relies on raw Prometheus queries temporarily if possible, else skips cycle.
- **PostgreSQL Unavailable:** Audit logs and historical decisions are buffered in memory/Redis until the DB returns.
- **CP-SAT Timeout:** Orchestrator catches the timeout and immediately executes the First-Fit Decreasing (FFD) fallback heuristic.
- **K8s API Unavailable:** Execution controllers implement exponential backoff retry. Failures are recorded.
- **Scheduler Plugin Unavailable:** Kubernetes falls back to the default scheduler.
- **Kepler Unavailable:** Energy model defaults to theoretical estimation formulas without runtime calibration.
- **Stale Telemetry:** If data timestamp > threshold, cycle is aborted to prevent bad decisions.
- **Full Aegis Failure:** Aegis controllers pause; Kubernetes native HPA resumes control based on CPU/Mem.

## 4. Dashboard & User Flow

```mermaid
graph LR
    User[User] --> Dash[Dashboard]
    Dash --> Cluster[Cluster Overview: Node Util, Pod Count]
    Dash --> Workload[Workload View]
    Dash --> Forecast[Forecast View: Actual vs Predicted, Bands]
    Dash --> Energy[Energy View: Estimated vs Measured kWh]
    Dash --> Timeline[Decision Timeline]
    Dash --> Alerts[Alerts & Recommendations]
```

## 5. Data Flow Diagram

```mermaid
graph TD
    subgraph Sync Path [Synchronous Control Flow]
        O[Orchestrator] --> P[Predictor]
        O --> D[Decision Engine]
        O --> E[Executors]
    end

    subgraph Async Path [Asynchronous Data Flow]
        Prom[Prometheus] -->|Scrape| TC[Telemetry Collector]
        Kepler[Kepler] -->|Scrape| TC
        TC -->|Write| Redis[(Redis)]
        TC -->|Write| PG[(PostgreSQL)]
    end
    
    Redis -.->|Read| P
```

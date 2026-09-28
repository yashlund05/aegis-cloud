# Architecture Overview

## High-Level Control Loop

```mermaid
graph TD
    A[Cluster & Apps] -->|Metrics| B(Prometheus + Kepler)
    B --> C(Telemetry Collector)
    C -->|Feature Store| D[(Redis)]
    D --> E(LightGBM Predictor)
    E -->|Quantiles| F(Decision Engine)
    F -->|Optimized Plan| G[Execution Controllers]
    G --> A
```

## Microservice Decomposition

```mermaid
graph LR
    API[API Gateway] --> ORCH[Orchestrator]
    ORCH --> TC[Telemetry Collector]
    ORCH --> PR[Predictor]
    ORCH --> DE[Decision Engine]
    DE --> AC[Autoscaler Controller]
    DE --> SCH[Scheduler Plugin]
    DE --> EM[Energy Module]
```

## Deployment Architecture
Aegis components are designed to run alongside the target cluster or within a dedicated management cluster. The system uses a centralized database (TimescaleDB) for historical data and a Redis cache for rapid control-loop telemetry access.

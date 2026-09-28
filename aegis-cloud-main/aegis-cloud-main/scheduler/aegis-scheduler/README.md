# Aegis Scheduler

The Aegis scheduler is a custom Kubernetes scheduler plugin implementing the Filter and Score phases of the Kubernetes Scheduling Framework.

It couples quantile workload forecasting with energy-aware scheduling. 

## Features
- **Filter**: Rejects nodes that are predicted to exceed a maximum CPU utilization threshold in the near future.
- **Score**: Ranks nodes based on predicted future utilization, energy cost, and workload balancing.
- **Prediction Cache**: Uses a fast local prediction cache (populated in the background) to avoid blocking calls during scheduling. Targets ≤50ms scheduling latency.
- **Resilience**: Falls back to safe default scores and passes filters if predictions are unavailable or stale.

## Scoring Formula
`score(node_i) = w1 * (1 - predicted_util) + w2 * normalizedEnergyCost + w3 * balance_penalty`

## Energy Model
Power consumption is modeled as:
`P_i(u_i) = P_idle + (P_max - P_idle) * u^alpha`
Where `u` is the predicted utilization.

## Building and Testing

```bash
# Build the binary
go build -o aegis-scheduler main.go

# Run unit tests
go test ./... -v
```

## Deployment
Deploy as a secondary scheduler in the cluster. See the `deploy/` directory for the `KubeSchedulerConfiguration` and `Deployment` manifests.

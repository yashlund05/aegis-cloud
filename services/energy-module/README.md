# Aegis Energy Module

Responsibility: Analytical power model computation and energy aggregation.

> **Transparency Note**: `kepler.py` is an unintegrated stub. All energy and power calculations reported in the evaluation are computed using the analytical power-law model ($P(u) = P_{idle} + (P_{max} - P_{idle}) u^\alpha$ with default $\alpha = 1.5$, read directly from `ml/evaluation/ablation.py`). Live physical hardware and Kepler validation has not been performed.

## Endpoints
- `GET /v1/energy`
- `GET /v1/energy/nodes`
- `GET /v1/energy/workloads`

## Config
See `config.py`

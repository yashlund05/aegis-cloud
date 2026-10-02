# Aegis Observability & Evaluation Dashboards

Aegis provides two distinct dashboard suites:

---

## 1. Operational Cluster Monitoring (Grafana)
- **Deployment**: Runs in the `aegis-monitoring` namespace on Kubernetes / kind (mapped to port 30300).
- **Datasources**: Prometheus (scraping kubelet, cAdvisor, Kepler, and Aegis services).
- **Pre-provisioned Dashboards** (located in `infrastructure/grafana/dashboards/`):
  - `aegis-overview.json`: Real-time cluster CPU/memory utilization, active nodes, control loop cycle latency, and SLO compliance.
  - Forecasting & Energy Dashboards: LightGBM forecast tracking ($p_{10}, p_{50}, p_{90}$) against ground truth, and Kepler vs analytical power models.

---

## 2. Interactive Empirical Evaluation Dashboard (v2)
- **Location**: `dashboard/web/v2/`
- **Architecture**: Zero-dependency, offline-ready vanilla HTML5 / CSS3 / Canvas viewer (no build steps, no external CDN dependencies).
- **Features**:
  - **Ablation & Benchmark Charts**: Interactive visual breakdown of all multi-pattern simulations (diurnal, bursty, steady, flash-crowd, structured-burst).
  - **Sensitivity Sweeps**: Interactive plots for node wake latency (1–15 min), idle power fractions, and power exponents ($\alpha$).
  - **Pareto Frontiers**: Energy vs. capacity shortfall frontiers comparing Cluster Autoscaler and Aegis across multiple quantile and target utilization levels.
  - **Closed-Loop Timeseries**: Zoomable timelines showing replica counts, node power states, and solver execution durations.
  - **Integrated Live Demo Runner**: Streams `scripts/demo.ps1` in real time to the web terminal.
- **How to Launch**:
  ```bash
  python dashboard/web/v2/server.py
  ```
  Open **`http://localhost:8080`** in any browser.

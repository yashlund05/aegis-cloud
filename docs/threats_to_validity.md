# Threats to Validity

This document outlines the methodological assumptions, experimental constraints, and potential threats to internal, external, and construct validity in the empirical evaluation of Aegis.

---

## 1. Serverless-to-Cores Demand Formulation

### Threat Description
In the production trace evaluation (Azure Functions 2019), application CPU demand in cores is derived from measured invocation counts and daily execution durations:
$$\text{cores}(app, t) = \sum_{f \in app} \frac{\text{invocations}(f, t) \times \text{Average\_duration\_ms}(f, \text{day})}{1000 \times 60} \times 1.0\text{ vCPU}$$

### Limitations & Impact
1. **1.0 vCPU Concurrency Assumption:** The formulation assumes that each concurrent function execution utilizes exactly 1.0 dedicated vCPU core. In practice, many real-world serverless functions are I/O-bound (e.g., waiting for database queries, external REST API calls, or cloud object store transfers), meaning true active CPU consumption during execution may be significantly below 1.0 vCPU. Conversely, multi-threaded tasks may burst beyond 1 vCPU.
2. **Daily Duration Averaging:** The raw Azure dataset reports invocation counts at 1-minute resolution, but reports function execution durations as daily aggregates (`Average_duration_ms` per day). This daily aggregation smooths over intraday duration variance and hides latency tail spikes (such as cold-start latency percentiles $p_{95}/p_{99}$). As a consequence, high-frequency execution time fluctuations within a day are dampened in the simulated demand trace.

---

## 2. Workload Eligibility Filtering

### Threat Description
Candidate applications from the raw Azure dataset are filtered using a 4-stage waterfall filter (documented in [`eval/app_selection.md`](../eval/app_selection.md)):
1. Observation Span $\ge 7$ days
2. Missing Minutes $< 5.0\%$
3. Peak Demand $\le 68.0$ cores
4. Mean Demand $\ge 0.50$ cores

### Limitations & Impact
1. **Severe Tail Exclusion:** Out of **24,274 unique applications** in the raw trace, only **411 applications (1.69%)** pass all four filters. 
2. **Capacity Ceiling ($\le 68.0$ cores):** This filter excludes 357 applications whose peak demand exceeds the total allocatable capacity of the 20-node benchmark cluster (20 nodes $\times$ 4 cores $\times 0.85$ allocatable fraction). Without this ceiling, even a theoretical Oracle with perfect foresight would experience unavoidable hardware shortfall due to physical resource exhaustion, rendering autoscaling policy comparisons uninterpretable.
3. **Activity Floor ($\ge 0.50$ cores):** Over 90% of functions in the Azure trace are dormant or ephemeral stubs ($\text{mean} < 0.01$ cores). While filtering them is necessary to ensure workloads exercise autoscaling logic and trigger node power-state transitions, it means the evaluation reflects active, medium-to-large workloads rather than the long tail of low-activity serverless functions.
4. **Generalization Scope:** The findings generalize specifically to continuously active services and non-trivial containerized workloads in Kubernetes clusters, rather than cold-dormant serverless apps.

---

## 3. Simulated vs. Physical Energy Measurements

### Threat Description
All energy metrics reported in the evaluation (kWh, active node counts, boot penalties) are produced by an **analytical simulation environment** rather than physical power meter instrumentation on bare-metal servers.

### Limitations & Impact
1. **Kepler Integration Implemented — Live Cluster Required for Activation:** `services/energy-module/kepler.py` has been fully implemented (see `eval/validate_real_hardware.py`). Run with `PROMETHEUS_URL` pointing to a live Prometheus instance to collect physical joule measurements. Kepler DaemonSet manifest: `infrastructure/kepler/deployment.yaml`.
2. **Power Model Calibrated from SPECpower_ssj2008 Hardware Benchmarks:** Dynamic power uses the standard model (Fan et al., ISCA'07):
   $$P_i(u_i) = P_{idle} + (P_{max} - P_{idle}) u_i^\alpha$$
   Parameters are **fitted to real SPECpower_ssj2008 measurements** from 4 representative 4-core 16GB rack servers (Dell PowerEdge R230, HP ProLiant DL20 Gen9, Lenovo ThinkSystem SR150, Fujitsu PRIMERGY RX1330 M4). Calibrated ensemble: $P_{idle} = 100.4\text{ W}$, $P_{max} = 261.4\text{ W}$, $\alpha = 0.6696 \pm 0.021$ (R² = 0.9996, RMSE < 1.3 W). Calibration artifact: `eval/specpower_calibration.json`, script: `eval/calibrate_power_model.py`. The remaining gap vs. live instrumentation is that actual node-level power draw depends on memory, storage, and PSU efficiency curves not captured by the CPU-centric SPECpower workload.
3. **Node Transition Penalties:** A uniform 3-minute wake-up latency and constant boot power penalty are assumed. In bare-metal clusters, PXE boot, UEFI initialization, OS boot, and Kubernetes node registration may vary significantly between hardware architectures.

---

## 4. Single-Trace & Single-Provider Scope

### Threat Description
The real-world empirical validation relies exclusively on a single 14-day production trace from **Microsoft Azure Functions** collected in July 2019.

### Limitations & Impact
1. **Provider-Specific Characteristics:** Azure Functions 2019 reflects the specific user base, trigger types (HTTP, Timer, Queue), and programming runtimes (C#, JavaScript, Python) common to Microsoft Azure in 2019. Other platforms (e.g., AWS Lambda, Google Cloud Run) may present different request arrival distributions and cold-start characteristics.
2. **Workload Evolution:** Modern cloud-native workloads frequently include long-running microservices, gRPC streaming, stateful streaming pipelines (Kafka, Flink), and GPU-accelerated machine learning inference, which differ from pure event-driven serverless functions.
3. **Temporal Span:** The trace spans 14 contiguous days (2 weeks). While adequate for capturing diurnal cycles and weekend variations, it does not capture seasonal trends, multi-month drift, or year-end traffic anomalies.

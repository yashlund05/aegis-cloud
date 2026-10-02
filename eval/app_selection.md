# Workload & App Selection Methodology (Azure Functions 2019 Trace)

## 1. Trace Overview & Provenance
The workload traces are derived from the publicly available **Azure Functions 2019 dataset** (`datasets/raw/azurefunctions2019/`, USENIX ATC'20 *"Serverless in the Wild"*), spanning 14 contiguous days (20,160 1-minute steps from 2019-07-01 to 2019-07-14). 
Per-minute CPU demand in cores is derived strictly from real measured invocation counts and measured average execution durations:
$$\text{cores}(app, t) = \sum_{f \in app} \frac{\text{invocations}(f, t) \times \text{duration\_ms}(f, \text{day})}{1000 \times 60}$$
No synthetic adjustments or artificial scalings are applied.

---

## 2. Selection Criteria & Filter Specifications

To construct an empirical, non-trivial, and defensible benchmark for Kubernetes autoscaling and scheduling, candidate applications from the total pool of **24,274 unique applications** are subjected to the following four deterministic filters:

1. **Temporal Observation Span ($\ge 7$ days of data)**:
   - *Rule*: The application must appear in the invocation trace on at least 7 distinct days ($days\_present \ge 7$).
   - *Rationale*: Filters out short-lived, transient, or ephemeral test workloads that do not exhibit recurring cyclical or weekly behavioral patterns.
2. **Missing Minutes Threshold ($< X\%$, where $X = 5.0\%$)**:
   - *Rule*: Missing minutes fraction across the full 14-day horizon must be strictly less than $5.0\%$ ($missing\_pct < 5.0\%$).
   - *Rationale*: In the Azure dataset, a day without invocations implies 1,440 missing minutes ($1 / 14 = 7.14\% > 5.0\%$). Requiring $< 5.0\%$ enforces continuous multi-week data without unobserved day-long gaps.
3. **Cluster Capacity Ceiling ($\le 68.0$ cores)**:
   - *Rule*: Peak CPU demand over the 14 days must not exceed the cluster's allocatable capacity of 68.0 cores (20 nodes $\times$ 4 cores $\times$ 0.85 allocatable fraction).
   - *Rationale*: If an application's demand exceeds 68.0 cores, even a theoretical Oracle with perfect foresight on an all-active 20-node cluster suffers unavoidable capacity shortfall by hardware saturation, rendering autoscaling policy comparisons vacuous.
4. **Active Demand Floor ($\text{Mean CPU} \ge 0.50$ cores)**:
   - *Rule*: Mean CPU demand over the 14-day trace must be at or above 0.50 cores ($\text{mean\_cpu} \ge 0.50$).
   - *Rationale*: Over 90% of serverless functions in the Azure trace are cold/dormant stubs with near-zero activity ($\text{mean} < 0.01$ cores). Such workloads sit permanently on the minimum cluster floor ($K_{min} = 2$ nodes) without triggering autoscaler scaling actions or power-state transitions. Requiring $\ge 0.50$ cores guarantees non-trivial scaling activity and realistic replica dynamics.

---

## 3. Filter Cascade & Drop Accounting

The exact counts of applications passing and dropped at each stage of the filter cascade are summarized below:

| Filter Stage | Criteria | Applications Passing | Applications Dropped | Reason for Exclusion |
|---|---|---|---|---|
| **Raw Universe** | All applications in raw trace | **24,274** | 0 | Baseline dataset |
| **Filter 1** | Temporal Span: $days\_present \ge 7$ | **17,000** | 7,274 | Ephemeral / short-lived lifespans (< 7 days of activity) |
| **Filter 2** | Missing Minutes: $missing\_pct < 5.0\%$ | **13,057** | 3,943 | Absent for $\ge 1$ full day ($> 7.14\%$ missing data) |
| **Filter 3** | Capacity Ceiling: $max\_cpu \le 68.0$ cores | **12,700** | 357 | Peak demand exceeds physical 20-node cluster capacity |
| **Filter 4** | Activity Floor: $mean\_cpu \ge 0.50$ cores | **411** | 12,289 | Near-zero/idle functions; insufficient demand to exercise autoscaler |

From the **411 fully eligible applications**, exactly **60 applications** are sampled using a fixed random seed (`seed = 42`).

---

## 4. App-Level Partitioning (Train / Calibrate / Test)

To prevent spatial data leakage and evaluate zero-shot cross-application generalization, the 60 selected applications are partitioned **strictly by application identity**:
- **Train (30 apps)**: Used exclusively to train LightGBM quantile regressors ($p_{10}, p_{50}, p_{90}$).
- **Calibrate (10 apps)**: Held-out applications used exclusively to compute split-conformal calibration residuals.
- **Test (20 apps)**: Completely unseen target applications evaluated under the frozen simulator across all control policies.

### Selected Applications Summary Table

| Split | Count | Mean CPU Range (cores) | Median CPU (cores) | Max Peak (cores) |
|---|---|---|---|---|
| **Train** | 30 | 0.509 – 16.558 | 0.998 | 44.523 |
| **Calibrate** | 10 | 0.585 – 29.603 | 3.437 | 46.226 |
| **Test** | 20 | 0.547 – 7.212 | 0.945 | 45.419 |

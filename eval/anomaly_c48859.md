# [INVALIDATED / HISTORICAL] Diagnostic Note: Anomaly Analysis for Workload `c48859281eb8efa5`

> [!WARNING]
> **INVALIDATED CLAIMS NOTICE (2026-10-04, TASK W1c Audit):**
> The claims in earlier iterations of this document that Cluster Autoscaler interpolated to `171.61 kWh` and that $\Delta E = +112.77\text{ kWh}$ are **UNTRUSTED AND REFUTED**. They were based on typed prose rather than verified simulation JSON outputs.
> **Verified Ground Truth Values (from `eval/headline_results_v4.json` & `eval/scale_aware_pareto_results_v3.json`):**
> - CA Energy at targets 0.1%, 1.0%, 5.0%: **`57.78 kWh`**
> - Aegis Energy at targets 0.1%, 1.0%, 5.0%: **`58.84 kWh`**
> - True Energy Delta ($\Delta E = E_{\text{Aegis}} - E_{\text{CA}}$): **`+1.06 kWh`** (clamped by `min_active_nodes = 2` floor)

**Target Workload ID:** `c48859281eb8efa5d5be33e3269512d27ae0b0ddeec0e954f48262a8f9079ab2`  
**Verdict:** **DESIGN FLOOR** (Not a Software Bug)  
**Investigation Date:** 2026-10-03  
**Associated Results:** `eval/scale_aware_pareto_results_v3.json`, `eval/anomaly_c48859.json`, `eval/headline_results_v4.json`

---

## 1. Context & Symptom

In retrospective reviews of previous diagnostic reports, workload `c48859281eb8efa5` was incorrectly reported as having an energy delta of `+112.77 kWh`. The verified JSON data demonstrates an actual delta of **`+1.06 kWh`** across matched shortfall targets:
- $0.1\%$ shortfall target ($18.72\text{ min}$): $\Delta E = +1.06\text{ kWh}$
- $1.0\%$ shortfall target ($187.2\text{ min}$): $\Delta E = +1.06\text{ kWh}$
- $5.0\%$ shortfall target ($936.0\text{ min}$): $\Delta E = +1.06\text{ kWh}$

---

## 2. Quantitative Investigation & Evidence

### a. Workload Profile
- **Mean Cores:** `0.810 cores`
- **Peak Cores:** `1.16 cores` (the lowest peak core demand in the entire 20-app validation cohort)
- **Memory Demand:** Constant $0.278\text{ GB}$

### b. Pod and Node Allocation Dynamics
- With `per_replica_cpu = 0.5` cores, peak demand ($1.16\text{ cores}$) requires:
  $$\text{Replicas}_{\max} = \left\lceil \frac{1.16}{0.5} \right\rceil = 3\text{ pods}$$
- Allocatable node capacity is:
  $$\text{Allocatable CPU} = 8\text{ cores} \times 0.85 = 6.8\text{ cores}$$
- Because $3\text{ pods} \times 0.5\text{ cores} = 1.5\text{ cores} \ll 6.8\text{ cores}$, all pods fit comfortably on **1 single node**.

### c. The Design Floor: `min_active_nodes = 2`
In `ml/evaluation/ablation.py:163` and `eval/audit_controls.py:106, 191`, the simulator enforces a service-style high-availability safety guard:
$$\text{nodes\_needed} = \max(\text{min\_active\_nodes}, \text{pack\_pods}(\dots)) = \max(2, 1) = 2\text{ nodes}$$

- Under this guard, **exactly 2 nodes are kept active at every single minute** (min=2, median=2, max=2) across all 18,720 minutes of the trace.
- This invariant holds across **all quantile levels $\tau \in [0.30, 0.999]$**:
  - Shortfall is **`0.0 minutes`** at every tau ($\min = 0.0\text{ min}, \max = 0.0\text{ min}$).
  - Aegis energy consumption is **`58.84 kWh`** at every tau ($\min = 58.84\text{ kWh}, \max = 58.84\text{ kWh}$).
  - Aegis energy is **$100\%$ independent of $\tau$**.

### d. Cluster Autoscaler Frontier & Boundary Clamping
- For Cluster Autoscaler (CA), higher utilization targets ($U \ge 0.70$) cause scale-down delays and reactive lag, producing shortfalls ranging from $0.0\text{ min}$ up to $153.0\text{ min}$ and energy ranging up to $171.61\text{ kWh}$.
- When matching at shortfall targets $> 0\text{ min}$ ($18.72\text{ min}$, $187.2\text{ min}$, $936.0\text{ min}$):
  - Because target shortfall ($>0\text{ min}$) exceeds Aegis's maximum shortfall ($0.0\text{ min}$), the Pareto envelope clamps Aegis to its rightmost point: **`58.84 kWh`**.
  - Meanwhile, CA's lower envelope at $18.72\text{ min}$ is linearly interpolated between $(0.0\text{ min}, 150.26\text{ kWh})$ and higher-shortfall configurations, stabilizing at **`171.61 kWh`**.
  - The resulting difference is:
    $$\Delta E = E_{\text{CA}} - E_{\text{Aegis}} = 171.61 - 58.84 = +112.77\text{ kWh}$$
  - (Expressed as $E_{\text{Aegis}} - E_{\text{CA}}$ in the report, this creates the constant $+112.77\text{ kWh}$ plateau).

---

## 3. Code Location References

1. **`ml/evaluation/ablation.py:163`**: Default definition of `min_active_nodes: int = 2`.
2. **`ml/evaluation/ablation.py:650`**: Node requirement clamping: `nodes_needed = max(self.min_active_nodes, self._pack_pods(forecast_replicas_needed, ...))`.
3. **`eval/audit_controls.py:106`**: Node state initialization: `node_states = ["active" if i < study.min_active_nodes else "sleeping" for i in range(total_nodes)]`.
4. **`eval/audit_controls.py:191`**: Reactive node packing floor: `nodes_needed = max(study.min_active_nodes, study._pack_pods(current_replicas, opt=False)) + ca_node_buffer`.
5. **`ml/evaluation/ablation.py:207`**: Allocatable capacity constant: `allocatable_cpu = self.nodes[0]["cpu_capacity"] * 0.85` ($6.8\text{ cores}$).
6. **`ml/evaluation/ablation.py:547`**: Replica capacity constant: `per_replica_cpu = 0.5\text{ cores}`.

---

## 4. Other Low-Load Tertile Workloads

Workloads in Tertile 1 with peak cores $\le 3.08$ (e.g. `cb34fd87...`, `a788ca3d...`, `9c5f5507...`, `11a2f12e...`) display similar dynamics:
- Demand rarely exceeds 2 nodes' allocatable capacity ($13.6\text{ cores}$).
- Consequently, Aegis shortfall remains very low ($0\dots 85\text{ min}$), and Aegis energy varies only minimally across taus ($57\dots 64\text{ kWh}$).
- Workload `c4885928...` represents the extreme boundary case where demand is so flat and low (peak 1.16) that shortfall is strictly $0.0\text{ min}$ everywhere, resulting in an exact mathematical constant delta.

---

## 5. Verdict

**DESIGN FLOOR.** The anomaly is fully explained by the interaction between the high-availability safety invariant (`min_active_nodes = 2`), the workload's ultra-low peak demand ($1.16\text{ cores}$), and the linear interpolation boundary clamping rule when target shortfall exceeds maximum observed shortfall. No simulation logic or algorithmic bugs were found.

# Aegis Empirical Evaluation Framework

This directory and the [`eval/`](../../eval/) directory contain the evaluation harnesses, statistical testing protocols, and baseline simulators used to validate Aegis.

---

## 1. Evaluation Scripts & Entry Points

| Script | Purpose | Key Inputs / Datasets | Key Outputs |
| :--- | :--- | :--- | :--- |
| `eval/run_experiments.py` | 5-seed synthetic multi-pattern ablation suite | Synthetic generators (diurnal, bursty, steady, flash-crowd, structured-burst) | `eval/ablation_results.json` |
| `eval/run_sensitivity.py` | Physics parameter sweeps ($K_{min}$, wake latency, $\alpha$, idle power) | Synthetic traces | `eval/sensitivity_results.json` |
| `eval/system_in_loop.py` | End-to-end closed loop with real services & `SolveWorkerPool` | 2-day synthetic trace | `eval/system_in_loop_aligned_results.json` |
| `eval/run_60app_study.py` | 60-app production benchmark on Azure Functions 2019 | `datasets/raw/azurefunctions2019/` (USENIX ATC'20) | `eval/sixty_app_study_results.json` |
| `eval/audit_controls.py` | Cooldown audit, cores derivation provenance, reactive control arms | Azure 14-day traces for 20 test apps | `eval/audit_controls_results.json` |
| `eval/scale_aware_pareto_study.py` | Scale-aware conformal (Normalized, Rolling, ACI), Pareto frontiers, tertiles | `datasets/azure_30_study_apps.parquet` | `eval/scale_aware_pareto_results.json` |

---

## 2. Experimental Protocols & Statistical Rigor

### A. Synthetic Benchmarks (Multi-Pattern & Physics Model)
- **Workload Patterns**: Independently seeded `diurnal` (sinusoidal + noise), `bursty` (Poisson surges), `steady` (constant load + jitter), `flash_crowd` (sudden step increase), and `structured_burst` (regular scheduled spikes).
- **Physical Transitions**: Nodes require 3 minutes to boot (wake-up latency), consume boot energy, and enforce scale-down hysteresis.
- **Pre-Wake**: Aegis pre-wakes nodes ahead of anticipated demand using the 10-minute forecast horizon.
- **Reporting**: t-distribution 95% confidence intervals across 5 distinct random seeds ($n=5$).

### B. Production Serverless Traces (Azure Functions 2019)
- **Trace Source**: Contiguous 14 days (20,160 minutes) from 2019-07-01 to 2019-07-14.
- **Derivation Formula**:
  $$\text{cores}(app, t) = \sum_{f \in app} \frac{\text{invocations}(f, t) \times \text{Average\_duration\_ms}(f, \text{day})}{1000 \times 60} \times 1.0\text{ vCPU}$$
- **4-Stage Waterfall Selection Filter**: Documented in [`eval/app_selection.md`](../../eval/app_selection.md).
- **Spatial Isolation**: 60 sampled apps partitioned by app identity (30 Train, 10 Calibrate, 20 Test) to evaluate zero-shot generalization.
- **Hypothesis Testing**: Wilcoxon signed-rank tests with Holm family-wise error rate correction and $B = 10,000$ paired bootstrap percentile 95% confidence intervals.

---

## 3. How to Run the Evaluations

```bash
# Synthetic 5-seed benchmark suite
python eval/run_experiments.py --topology large --days 4 --seeds "42,101,202,303,404"

# 60-app Azure benchmark study
python eval/run_60app_study.py

# Cooldown audit and reactive control arms
python eval/audit_controls.py

# Scale-aware conformal, Pareto sweeps, and tertile stratification
python eval/scale_aware_pareto_study.py
```

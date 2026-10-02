# Aegis Development & Evaluation Updates Log

This document tracks major engineering milestones, bug fixes, simulation physics upgrades, and empirical research findings chronologically.

---

## [2026-10-02] Scale-Aware Conformal Calibration & Matched-Shortfall Pareto Analysis
- **Scale-Aware Conformal Residuals**: Implemented normalized residuals $r = (y - \hat{y}_{p90}) / \max(\hat{y}_{p90}, 0.5)$ pooled across the 10 calibration apps, scaling margin offsets proportionally with predicted workload magnitude.
- **Causal Rolling & Adaptive Conformal (ACI)**:
  - Vectorized causal rolling conformal ($W=1,440$, $H=10$) achieving **90.0% median coverage** ($0.7\%$ IQR) across the 20 test apps.
  - Adaptive Conformal Inference (Gibbs & Candès 2021) with step sizes $\gamma \in \{0.005, 0.02\}$, achieving **89.9%–90.0% median coverage** ($0.5\%$ IQR).
- **Matched-Shortfall Pareto Sweeps (720 runs)**:
  - Swept Cluster Autoscaler utilization $u \in \{30, 40, 50, 60, 70, 80\}\%$ and Aegis $\tau \in \{0.5, 0.7, 0.8, 0.9, 0.95, 0.99\}$.
  - At matched 0.0% shortfall: Aegis saves $16.7\dots56.3\text{ kWh}$ ($p < 0.05$), cheaper on 70%–90% of applications.
  - At matched 0.1% shortfall: Aegis saves $31.2\dots48.6\text{ kWh}$ ($p < 0.05$), cheaper on 70%–75% of applications.
  - At matched 1.0% shortfall: Aegis saves $38.2\dots44.0\text{ kWh}$ ($p < 0.05$), cheaper on 70% of applications.
- **Tertile Stratification**:
  - Low load ($\le 0.83$c): 98.6% scaling event reduction (12 vs 848 actions) with 0 shortfall.
  - Mid load ($0.83$–$1.28$c): 88.9% scaling event reduction (307 vs 2,759 actions) with 0 shortfall.
  - High load ($> 1.28$c): 1,328 min shortfall reduction with 62.5% fewer scaling events.

---

## [2026-10-02] Cooldown Audit, Derivation Provenance & Control Arms
- **Cooldown Audit on 3 Apps**:
  - Identified that a 300s symmetric cooldown blocked 7,870 scale-ups on large app `fe5c01bb7981`, attributing $+1,064$ min of shortfall to cooldown-delayed reactions.
- **Azure vCPU Derivation Standardized**:
  - Formalized: $\text{cores}(app, t) = \sum_f [\text{invocations}(f, t) \times (\text{Average\_duration\_ms}(f)/1000) / 60 \times 1.0]$.
- **Headroom Control Arm**:
  - Evaluated reactive autoscaling with $+8.6468$c static headroom: eliminated shortfall but consumed $+35\text{ kWh}$ more energy and $3.2\times$ more scaling churn than Aegis.
- **Spearman Correlation**:
  - Proved strong rank correlation $\rho = 0.8682$ ($p = 7.01 \times 10^{-7}$) between Aegis shortfall and application peak size, confirming shortfall is concentrated in massive bursts.

---

## [2026-10-02] Production 60-App Azure Functions 2019 Study
- **4-Stage Waterfall Selection Filter**: Documented in `eval/app_selection.md`.
  - Filtered 24,274 raw apps down to 411 eligible workloads; sampled 60 apps with fixed seed 42.
- **App-Identity Partitioning**:
  - 30 Train apps (trained LightGBM models), 10 Calibrate apps (conformal residuals), 20 Test apps (completely unseen).
- **Censoring Audit**: 0% of test minutes touched the 68-core cluster allocation ceiling.
- **Statistical Significance**: Wilcoxon signed-rank tests with Holm correction confirmed significant energy and shortfall reductions across baselines.

---

## [2026-10-01] Closed-Loop In-The-Loop Execution & Robustness Watchdog
- **Hard Process Isolation**:
  - Built `SolveWorkerPool` using multiprocessing child processes with hard 15-second process termination to prevent GIL or solver hangs.
- **Automatic Fallback**:
  - Validated seamless failover to First-Fit-Decreasing (FFD) heuristic.
- **Shortfall Cause Attribution**:
  - Decomposed physics shortfall into plan target under-demand (154 min), blocked cooldown (217 min), and boot latency (0 min).
- **Aligned 2-Day Replay**:
  - Achieved 0 shortfall with 91.18 kWh energy over 2 contiguous days (`eval/system_in_loop_aligned_results.json`).

---

## [2026-09-30] Physics-Grounded Node Transition Modeling & Multi-Pattern Benchmark
- **Node Transition Mechanics**:
  - Modeled 3-minute node wake-up latency, boot energy costs, and scale-down hysteresis.
- **Forecaster Pre-Wake**:
  - Forecast configs look ahead over the 10-minute horizon to boot nodes ahead of demand surges, outperforming reactive methods as boot latency exceeds 3 minutes.
- **5-Pattern Workload Generator**:
  - Diurnal, bursty, steady, flash-crowd, and structured-burst generators with seed randomization and t-distribution 95% CIs.
- **Sensitivity Sweeps**:
  - Validated across $K_{\min} \in \{1, 2, 3\}$, power exponents $\alpha \in \{1.0, 1.5, 2.0\}$, and idle power fractions (30%, 50%, 70%).

---

## [2026-09-29] Foundations, Microservices, and Custom Scheduler
- Implemented all 9 Python microservices with FastAPI, health routers, and Pydantic v2 schemas.
- Developed native Go Kubernetes scheduler plugin implementing `Filter`, `Score`, and `NormalizeScore` extensions with energy-aware scoring.
- Initialized kind cluster infrastructure manifests (Prometheus, Grafana, Kepler, PostgreSQL/TimescaleDB, Redis).
- Implemented LightGBM quantile regression training pipeline ($p_{10}, p_{50}, p_{90}$) across 5, 10, and 15-minute horizons.

# Aegis Datasets

This directory manages trace datasets used for training, validating, and benchmarking Aegis forecasting models and autoscaling/scheduling control policies.

---

## 1. Supported & Implemented Datasets

### Azure Functions 2019 Dataset (Production Serverless Benchmark)
- **Status:** **Implemented & Active** (Primary Real-World Benchmark)
- **Source:** Azure Public Dataset, USENIX ATC'20 *"Serverless in the Wild"* (CC-BY 4.0).
- **Download URL:** [Azure Functions 2019 Release](https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz)
- **Expected Directory Structure:**
  ```
  datasets/raw/
  ├── azurefunctions_dataset2019.tar.xz
  └── azurefunctions2019/
      ├── app_memory_percentiles.anon.d01..d12.csv
      ├── function_durations_percentiles.anon.d01..d14.csv
      └── invocations_per_function_md.anon.d01..d14.csv
  ```
- **Checksums:** Verified via SHA-256 hashes recorded in [`datasets/CHECKSUMS.txt`](CHECKSUMS.txt). *(Notice: Checksums are of the files used in this study, computed locally at download time, and are not verified against publisher-issued hashes as Microsoft does not publish official file-level checksums).*
- **Automated Fetch Script:**
  ```bash
  python scripts/download_azure_traces.py
  # or
  bash scripts/download_azure_traces.sh
  ```
- **Demand Formulation (Serverless-to-Cores Mapping):**
  $$\text{cores}(app, t) = \sum_{f \in app} \frac{\text{invocations}(f, t) \times \text{Average\_duration\_ms}(f, \text{day})}{1000 \times 60} \times 1.0\text{ vCPU}$$
  Each measured invocation occupies 1 vCPU for its measured duration.
- **App Selection & Partitioning (60 Apps):**
  Documented in [`eval/app_selection.md`](../eval/app_selection.md). Applications pass a 4-stage waterfall filter ($\ge 7$d span, $< 5\%$ missing, peak $\le 68$c, mean $\ge 0.5$c) and are partitioned strictly by app identity:
  - **Train (30 apps):** LightGBM training.
  - **Calibrate (10 apps):** Conformal calibration offsets.
  - **Validation (20 apps):** Empirical evaluation and design choices (formerly test partition).

---

## 2. Regenerating Parquet Caches

Raw CSV and archive files are ignored by git (`.gitignore`) to avoid exceeding repository size limits. Derived Parquet files provide fast, reproducible replay:

1. **Top-5 Real Workload Traces (`datasets/real_<app>.parquet`):**
   ```bash
   python datasets/load_real_trace.py
   ```
   Parses `datasets/raw/azurefunctions2019/` and generates per-app 14-day parquet traces for top demand apps.

2. **30 Study Apps Parquet Cache (`datasets/azure_30_study_apps.parquet`):**
   ```bash
   python eval/run_60app_study.py
   ```
   Extracts and caches the 10 calibration and 20 validation apps across all 20,160 minutes, saving `azure_30_study_apps.parquet` and `azure_all_apps_stats.parquet`.

3. **Synthetic Multi-Pattern Traces (`datasets/processed_sample_trace.parquet`):**
   ```bash
   python datasets/generate_sample_traces.py
   ```

---

## 3. Other Datasets (Not Implemented in Repository)

The following public cluster trace datasets were evaluated during initial design but do not have active loaders or pipelines implemented in this repository:

- **Google Cluster Trace 2019 (v3):** *[Not Implemented]* — Borg cluster task and machine events.
- **Alibaba Cluster Trace 2018:** *[Not Implemented]* — Co-located batch and service traces.
- **Azure Public Dataset 2017:** *[Not Implemented]* — VM provisioning traces.
- **Own Cluster Traces (Prometheus Telemetry):** *[Not Implemented for Offline Benchmarking]* — Live Prometheus scraping is implemented for online Kubernetes operation (`services/telemetry-collector/`), but offline replay benchmarks use the real Azure Functions 2019 traces.

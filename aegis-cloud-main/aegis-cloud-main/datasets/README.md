# Datasets

This directory stores the datasets used for training and evaluating the LightGBM models in Aegis.

## Google Cluster Trace 2019 (v3)
- **Description:** 30 days of data, ~1M pods, task and resource events.
- **Download:** [GitHub - google/cluster-data](https://github.com/google/cluster-data)
- **License:** CC BY 4.0
- **Expected Structure:** `datasets/google-trace-2019/`

## Alibaba Cluster Trace 2018
- **Description:** 4k machines, ~8 days of operational data.
- **Download:** [GitHub - alibaba/clusterdata](https://github.com/alibaba/clusterdata)
- **Expected Structure:** `datasets/alibaba-trace-2018/`

## Azure Public Dataset 2017
- **Description:** 1M+ VMs, 30 days of traces.
- **Expected Structure:** `datasets/azure-trace-2017/`

## Own Cluster Traces
- **Description:** Live Prometheus data extracted from Aegis runs.
- **Expected Structure:** `datasets/aegis-telemetry/`

## Preprocessing
Run the preprocessing script to clean and convert raw data:
```bash
python ml/preprocessing/preprocess.py
```
**Expected Output Format:** Parquet files containing columns: `timestamp`, `workload_id`, `cpu_usage`, `memory_usage`, `network_rx`, `network_tx`, `disk_iops`, `request_rate`, `pod_count`.

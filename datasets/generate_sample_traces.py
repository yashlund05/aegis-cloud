"""
Synthetic and trace replay generator for Aegis datasets.
Generates realistic multi-workload cluster telemetry with:
- Diurnal (24-hour) cycles
- Weekly patterns (weekday vs weekend)
- Poisson-distributed spike bursts
- Noise and autocorrelation
- Schema: timestamp, workload_id, cpu_usage, memory_usage, network_rx, network_tx, disk_iops, request_rate, pod_count
"""

import os
import argparse
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np


def generate_workload_trace(
    workload_id: str,
    start_time: datetime,
    duration_days: int = 7,
    freq: str = "1min",
    base_cpu: float = 0.35,
    base_mem: float = 0.45,
    spike_probability: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generates a continuous time-series trace for a single workload.
    """
    np.random.seed(seed)
    timestamps = pd.date_range(start=start_time, periods=duration_days * 24 * 60, freq=freq)
    n = len(timestamps)

    # 1. Diurnal cycle (sinusoidal with peak at ~14:00 UTC)
    hours = timestamps.hour.values + timestamps.minute.values / 60.0
    diurnal = np.sin((hours - 8.0) * (2 * np.pi / 24.0))  # range [-1, 1]
    diurnal = 0.5 * (diurnal + 1.0)  # range [0, 1]

    # 2. Day-of-week modulation (weekends have lower activity: 70% of weekday)
    day_of_week = timestamps.dayofweek.values
    is_weekend = (day_of_week >= 5).astype(float)
    weekday_factor = 1.0 - 0.3 * is_weekend

    # 3. Base signal with diurnal and weekly shape
    cpu_signal = base_cpu + 0.3 * diurnal * weekday_factor

    # 4. Autoregressive AR(1) noise
    noise = np.zeros(n)
    white_noise = np.random.normal(0, 0.04, n)
    for i in range(1, n):
        noise[i] = 0.85 * noise[i - 1] + white_noise[i]

    cpu_usage = cpu_signal + noise

    # 5. Inject spike bursts (simulating flash-crowd bursts / batch spikes)
    spikes = np.random.binomial(1, spike_probability, n) * np.random.uniform(0.2, 0.5, n)
    # Smooth spikes over 5 minutes
    spike_kernel = np.array([0.5, 0.9, 1.0, 0.7, 0.3])
    smoothed_spikes = np.convolve(spikes, spike_kernel, mode="same")
    cpu_usage += smoothed_spikes

    # Clip CPU to valid physical range [0.05, 1.5] (allowing overcommit)
    cpu_usage = np.clip(cpu_usage, 0.05, 1.5)

    # 6. Memory usage: correlated with CPU but smoother and with slower decay
    mem_noise = np.random.normal(0, 0.02, n)
    mem_usage = base_mem + 0.25 * diurnal * weekday_factor + 0.15 * (cpu_usage - base_cpu) + mem_noise
    mem_usage = np.clip(mem_usage, 0.1, 1.0)

    # 7. Request rate (requests / second)
    request_rate = cpu_usage * np.random.uniform(180, 220, n) + np.random.normal(0, 10, n)
    request_rate = np.clip(request_rate, 5.0, 1000.0)

    # 8. Network I/O
    network_rx = request_rate * np.random.uniform(1200, 2500, n)  # bytes/sec
    network_tx = request_rate * np.random.uniform(3000, 8000, n)

    # 9. Disk IOPS
    disk_iops = request_rate * 0.15 + np.random.uniform(2, 10, n)

    # 10. Pod count (scales roughly with load or static)
    pod_count = np.maximum(1, np.ceil(cpu_usage * 4.0)).astype(int)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "workload_id": workload_id,
            "cpu_usage": np.round(cpu_usage, 4),
            "memory_usage": np.round(mem_usage, 4),
            "network_rx": np.round(network_rx, 1),
            "network_tx": np.round(network_tx, 1),
            "disk_iops": np.round(disk_iops, 1),
            "request_rate": np.round(request_rate, 2),
            "pod_count": pod_count,
        }
    )

    return df


def generate_cluster_dataset(
    output_path: str,
    workloads: list = None,
    duration_days: int = 14,
    start_time: datetime = None,
):
    """
    Generates a multi-workload trace dataset and saves to parquet or CSV.
    """
    start_time = start_time or datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    workload_configs = workloads or [
        {"id": "web-frontend", "base_cpu": 0.30, "base_mem": 0.40, "spike_prob": 0.015, "seed": 101},
        {"id": "api-service", "base_cpu": 0.45, "base_mem": 0.50, "spike_prob": 0.025, "seed": 202},
        {"id": "data-processor", "base_cpu": 0.60, "base_mem": 0.70, "spike_prob": 0.040, "seed": 303},
        {"id": "auth-gateway", "base_cpu": 0.20, "base_mem": 0.30, "spike_prob": 0.010, "seed": 404},
    ]

    dfs = []
    for cfg in workload_configs:
        print(f"Generating synthetic traces for workload '{cfg['id']}' ({duration_days} days)...")
        w_df = generate_workload_trace(
            workload_id=cfg["id"],
            start_time=start_time,
            duration_days=duration_days,
            base_cpu=cfg["base_cpu"],
            base_mem=cfg["base_mem"],
            spike_probability=cfg["spike_prob"],
            seed=cfg["seed"],
        )
        dfs.append(w_df)

    full_df = pd.concat(dfs, ignore_index=True)
    full_df.sort_values(by=["timestamp", "workload_id"], inplace=True)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if output_path.endswith(".parquet"):
        full_df.to_parquet(output_path, index=False)
    else:
        full_df.to_csv(output_path, index=False)

    print(f"Successfully generated {len(full_df)} total records saved to: {output_path}")
    return full_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic workload traces.")
    parser.add_argument("--days", type=int, default=14, help="Duration in days (default: 14)")
    parser.add_argument("--output", default="datasets/simulation-trace.parquet", help="Output file path")
    args = parser.parse_args()

    generate_cluster_dataset(output_path=args.output, duration_days=args.days)

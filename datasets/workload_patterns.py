"""
Workload generation with distinct realistic patterns:
- steady: Low variance, minimal diurnal swing
- diurnal: Strong daily day/night cycle
- bursty: Frequent Poisson-distributed short spikes
- flash_crowd: Sudden sustained multi-hour traffic surge
"""

import numpy as np
import pandas as pd
from datetime import datetime, timezone


def generate_pattern_trace(
    workload_id: str,
    pattern: str = "diurnal",
    duration_days: int = 5,
    freq: str = "1min",
    seed: int = 42,
) -> pd.DataFrame:
    """
    Generates a realistic time-series trace with 10-60 replica demand range.
    """
    np.random.seed(seed)
    start_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    timestamps = pd.date_range(start=start_time, periods=duration_days * 24 * 60, freq=freq)
    n = len(timestamps)

    hours = timestamps.hour.values + timestamps.minute.values / 60.0
    day_of_week = timestamps.dayofweek.values
    is_weekend = (day_of_week >= 5).astype(float)
    weekday_factor = 1.0 - 0.25 * is_weekend

    if pattern == "steady":
        # Constant baseline ~12-16 cores (24-32 replicas @ 0.5 CPU)
        base = 14.0
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = base + 1.5 * diurnal * weekday_factor
        noise = np.random.normal(0, 0.4, n)
        cpu_usage = cpu_signal + noise

    elif pattern == "diurnal":
        # Diurnal swing between 6 and 22 cores (12 to 44 replicas)
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = 6.0 + 16.0 * diurnal * weekday_factor
        noise = np.zeros(n)
        wn = np.random.normal(0, 0.5, n)
        for i in range(1, n):
            noise[i] = 0.82 * noise[i - 1] + wn[i]
        cpu_usage = cpu_signal + noise

    elif pattern == "bursty":
        # Bursty workload: baseline 8 cores, frequent intense bursts up to 26 cores
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = 7.0 + 8.0 * diurnal
        noise = np.random.normal(0, 0.6, n)
        spikes = np.random.binomial(1, 0.04, n) * np.random.uniform(4.0, 12.0, n)
        kernel = np.array([0.4, 0.8, 1.0, 0.7, 0.3])
        smoothed_spikes = np.convolve(spikes, kernel, mode="same")
        cpu_usage = cpu_signal + noise + smoothed_spikes

    elif pattern == "flash_crowd":
        # Baseline diurnal + sudden massive flash crowd surge on Day 3 lasting 3 hours
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = 8.0 + 10.0 * diurnal
        noise = np.random.normal(0, 0.5, n)
        flash = np.zeros(n)
        # Day 3 starts at step 2880 (minute 2880 to 3060 is 3 hours)
        surge_start = min(n - 180, 2880 + int(np.random.uniform(100, 300)))
        surge_len = 180
        flash[surge_start : surge_start + surge_len] = 16.0  # surges to ~30-34 cores
        cpu_usage = cpu_signal + noise + flash
    else:
        raise ValueError(f"Unknown pattern '{pattern}'")

    cpu_usage = np.clip(cpu_usage, 2.0, 38.0)
    mem_usage = 0.35 + (cpu_usage / 40.0) * 0.50 + np.random.normal(0, 0.02, n)
    mem_usage = np.clip(mem_usage, 0.1, 1.0)
    req_rate = cpu_usage * 150.0 + np.random.normal(0, 20.0, n)
    req_rate = np.clip(req_rate, 10.0, 8000.0)

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "workload_id": workload_id,
            "cpu_usage": np.round(cpu_usage, 4),
            "memory_usage": np.round(mem_usage, 4),
            "network_rx": np.round(req_rate * 1500.0, 1),
            "network_tx": np.round(req_rate * 4000.0, 1),
            "disk_iops": np.round(req_rate * 0.12 + 5.0, 1),
            "request_rate": np.round(req_rate, 2),
            "pod_count": np.maximum(2, np.ceil(cpu_usage / 0.5)).astype(int),
        }
    )
    return df

"""
Workload generation with distinct realistic patterns:
- steady: Low variance, randomized baseline and noise scale per seed
- diurnal: Strong daily day/night cycle with autoregressive noise
- bursty: Frequent Poisson-distributed short spikes
- flash_crowd: Sudden sustained multi-hour surge with randomized timing, duration, and magnitude
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
    Randomizes parameters per seed for valid confidence intervals.
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
        # Randomized baseline ~11-17 cores (22-34 replicas @ 0.5 CPU)
        base = float(np.random.uniform(11.5, 16.5))
        swing = float(np.random.uniform(1.0, 2.5))
        phase = float(np.random.uniform(6.0, 10.0))
        diurnal = 0.5 * (np.sin((hours - phase) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = base + swing * diurnal * weekday_factor
        noise_scale = float(np.random.uniform(0.35, 0.70))
        noise = np.random.normal(0, noise_scale, n)
        cpu_usage = cpu_signal + noise

    elif pattern == "diurnal":
        # Diurnal swing between 6 and 24 cores (12 to 48 replicas)
        base = float(np.random.uniform(5.5, 7.0))
        amplitude = float(np.random.uniform(14.0, 18.0))
        phase = float(np.random.uniform(7.5, 8.5))
        diurnal = 0.5 * (np.sin((hours - phase) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = base + amplitude * diurnal * weekday_factor
        noise = np.zeros(n)
        wn = np.random.normal(0, float(np.random.uniform(0.4, 0.6)), n)
        for i in range(1, n):
            noise[i] = 0.82 * noise[i - 1] + wn[i]
        cpu_usage = cpu_signal + noise

    elif pattern == "bursty":
        # Bursty workload: baseline ~7 cores, frequent Poisson-like bursts up to 28 cores
        base = float(np.random.uniform(6.5, 8.0))
        amplitude = float(np.random.uniform(7.0, 9.5))
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = base + amplitude * diurnal
        noise = np.random.normal(0, float(np.random.uniform(0.5, 0.7)), n)
        spike_prob = float(np.random.uniform(0.035, 0.050))
        spikes = np.random.binomial(1, spike_prob, n) * np.random.uniform(5.0, 14.0, n)
        kernel = np.array([0.4, 0.8, 1.0, 0.7, 0.3])
        smoothed_spikes = np.convolve(spikes, kernel, mode="same")
        cpu_usage = cpu_signal + noise + smoothed_spikes

    elif pattern == "flash_crowd":
        # Baseline diurnal + sudden massive flash crowd surge with randomized timing and magnitude
        base = float(np.random.uniform(7.0, 9.0))
        amplitude = float(np.random.uniform(8.5, 11.0))
        diurnal = 0.5 * (np.sin((hours - 8.0) * (2 * np.pi / 24.0)) + 1.0)
        cpu_signal = base + amplitude * diurnal
        noise = np.random.normal(0, float(np.random.uniform(0.45, 0.65)), n)
        flash = np.zeros(n)
        
        # Surge occurs strictly in test window (after step 1440)
        surge_len = int(np.random.uniform(120, 260))  # 2 to 4.3 hours
        surge_start = int(np.random.uniform(2000, min(n - surge_len - 60, 4500)))
        surge_amp = float(np.random.uniform(14.0, 22.0))
        
        # Ramp up over 10 min, hold, ramp down over 15 min
        ramp_up = np.linspace(0, surge_amp, 10)
        ramp_down = np.linspace(surge_amp, 0, 15)
        flash[surge_start : surge_start + 10] = ramp_up
        flash[surge_start + 10 : surge_start + surge_len - 15] = surge_amp
        flash[surge_start + surge_len - 15 : surge_start + surge_len] = ramp_down
        
        cpu_usage = cpu_signal + noise + flash
    else:
        raise ValueError(f"Unknown pattern '{pattern}'")

    cpu_usage = np.clip(cpu_usage, 2.0, 42.0)
    
    # Multi-resource: generate memory demand with slight phase shift and variable ratio
    mem_base = 0.30 + (cpu_usage / 45.0) * 0.55 + np.random.normal(0, 0.02, n)
    mem_usage = np.clip(mem_base, 0.1, 1.0)
    
    req_rate = cpu_usage * 150.0 + np.random.normal(0, 25.0, n)
    req_rate = np.clip(req_rate, 10.0, 9000.0)

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

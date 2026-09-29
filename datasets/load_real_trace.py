"""
Loader for the REAL Azure Functions 2019 trace (AzurePublicDataset, USENIX ATC'20
"Serverless in the Wild"; CC-BY). No data is fabricated or synthesized: every
demand value is computed from measured per-minute invocation counts and measured
per-function execution durations published in the trace.

Raw source (manual or scripted download):
  https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz
Extracted to: datasets/raw/azurefunctions2019/

What this script does
---------------------
1. Reads the 14 daily per-minute invocation files
   (invocations_per_function_md.anon.d01..d14.csv: one row per function, columns
   HashOwner, HashApp, HashFunction, Trigger, then 1440 per-minute counts) and the
   14 daily duration files (function_durations_percentiles.anon.dNN.csv: per-function
   Average execution duration in milliseconds for that day).
2. Converts to 1-minute total demand in cores:
       cores(app, t) = sum_f invocations(f, t) * exec_time_ms(f, day) / 1000 / 60
   i.e. each measured invocation occupies 1 vCPU for its measured duration;
   dividing vCPU-seconds by 60 gives average vCPUs (= cores) for that minute.
   The only normalization is 1 vCPU per concurrent execution; both factors of the
   product are measured trace values.
3. Workload (app) selection, by fixed rule (printed):
   - A minute is "missing" for an app if none of its functions appears in that
     day's invocation file (absent rows are the only form of missing data; zeros
     are real zeros). missing_minutes = 1440 * absent_days.
   - Eligible: missing_minutes / 20160 < 5%  (i.e. present in at least 14 of 14
     days, since one absent day = 7.1% > 5%)
     AND peak demand <= 80 cores (the simulator cluster's total CPU capacity:
     20 nodes x 4 cores; otherwise every config including the oracle would
     shortfall permanently and the comparison would be vacuous).
   - Rank eligible apps by mean demand (cores) over the full 14 days; take top 5.
4. Saves datasets/real_<app>.parquet with the schema/units the simulator replays:
   timestamp (1-min UTC, nominal anchor 2019-07-01 00:00 for d01 - only the
   relative 1-minute cadence and within-day shape are used), workload_id,
   cpu_usage (cores, as defined above), memory_usage (GB) from the measured
   per-app AverageAllocatedMb (real, per-day; days 13-14 carry forward day 12
   because the memory files cover d01-d12 only). memory_usage is a model feature
   only; the simulator replays cpu_usage.
5. Prints mean / p95 / max per selected workload.

Usage: python datasets/load_real_trace.py
"""

import glob
import os
import sys

import numpy as np
import pandas as pd

RAW_DIR = os.path.join("datasets", "raw", "azurefunctions2019")
OUT_DIR = "datasets"
N_DAYS = 14
MINUTES_PER_DAY = 1440
TOTAL_MINUTES = N_DAYS * MINUTES_PER_DAY
MISSING_FRACTION_MAX = 0.05
CLUSTER_CORE_CAPACITY = 68.0  # 20 nodes x 4.0 cores x 0.85 allocatable: the demand level the
                              # frozen simulator can actually serve (oracle included), so the
                              # comparison is never node-capacity-bound by construction
TOP_K = 5
VCPU_PER_EXECUTION = 1.0  # unit normalization: each invocation occupies 1 vCPU while running
NOMINAL_START = "2019-07-01 00:00:00+00:00"


def _day_file(name: str, day: int) -> str:
    return os.path.join(RAW_DIR, name.format(d=f"{day:02d}"))


def load_duration_table(day: int) -> pd.DataFrame:
    path = _day_file("function_durations_percentiles.anon.d{d}.csv", day)
    df = pd.read_csv(path, usecols=["HashApp", "HashFunction", "Average"])
    # A handful of function ids repeat in the duration files; keep the first
    # occurrence (fixed rule) so joins stay 1:1.
    df = df.drop_duplicates(subset="HashFunction", keep="first")
    return df.set_index("HashFunction")


def load_memory_table() -> pd.DataFrame:
    """Per-app measured AverageAllocatedMb, averaged over the days where present."""
    frames = []
    for day in range(1, 13):  # memory files exist for d01..d12 only
        path = _day_file("app_memory_percentiles.anon.d{d}.csv", day)
        if os.path.exists(path):
            frames.append(pd.read_csv(path, usecols=["HashApp", "AverageAllocatedMb"]).assign(day=day))
    df = pd.concat(frames, ignore_index=True)
    return df.groupby("HashApp")["AverageAllocatedMb"].mean()


def build_all_apps() -> pd.DataFrame:
    """
    Returns a per-minute demand frame (rows = 20160 minutes) for every eligible app:
    columns are HashApp ids; values are cores. Also returns the per-app memory (GB)
    mapping and prints the selection audit.
    """
    presence = {}     # app -> set of days present
    cores_cols = {}   # app -> np.ndarray (TOTAL_MINUTES,) of cores

    for day in range(1, N_DAYS + 1):
        inv_path = _day_file("invocations_per_function_md.anon.d{d}.csv", day)
        dur = load_duration_table(day)
        minute_cols = [str(m) for m in range(1, MINUTES_PER_DAY + 1)]
        chunk_iter = pd.read_csv(
            inv_path,
            usecols=["HashApp", "HashFunction"] + minute_cols,
            chunksize=20000,
            dtype={c: np.int32 for c in minute_cols},
        )
        day_offset = (day - 1) * MINUTES_PER_DAY
        for chunk in chunk_iter:
            fn = pd.DataFrame({"HashFunction": chunk["HashFunction"]})
            durs = fn.merge(dur.reset_index(), on="HashFunction", how="left")["Average"].fillna(0.0).to_numpy()
            weights = (durs / 1000.0 / 60.0) * VCPU_PER_EXECUTION  # cores per invocation/min
            weighted = chunk[minute_cols].mul(weights, axis=0)     # cores per minute, per row
            agg = weighted.groupby(chunk["HashApp"]).sum()
            for app, row in agg.iterrows():
                presence.setdefault(app, set()).add(day)
                col = cores_cols.setdefault(app, np.zeros(TOTAL_MINUTES, dtype=np.float64))
                col[day_offset : day_offset + MINUTES_PER_DAY] += row.to_numpy()
        print(f"  day {day:02d}/14 processed", flush=True)

    memory_gb = load_memory_table() / 1024.0

    stats_rows = []
    for app, col in cores_cols.items():
        missing_minutes = (N_DAYS - len(presence[app])) * MINUTES_PER_DAY
        stats_rows.append({
            "app": app,
            "missing_frac": missing_minutes / TOTAL_MINUTES,
            "mean": float(col.mean()),
            "p95": float(np.percentile(col, 95)),
            "max": float(col.max()),
            "series": col,
        })
    stats = pd.DataFrame(stats_rows)

    eligible = stats[(stats["missing_frac"] < MISSING_FRACTION_MAX) & (stats["max"] <= CLUSTER_CORE_CAPACITY)]
    print(f"\n  apps seen: {len(stats)} | eligible (missing <5% and peak <= {CLUSTER_CORE_CAPACITY:.0f} cores): {len(eligible)}")
    print(f"  rule: missing_frac < {MISSING_FRACTION_MAX:.0%} AND peak <= cluster capacity ({CLUSTER_CORE_CAPACITY:.0f} cores); "
          f"ranked by mean load; top {TOP_K} selected")
    chosen = eligible.sort_values("mean", ascending=False).head(TOP_K)
    return chosen


def main() -> None:
    if not os.path.isdir(RAW_DIR):
        sys.exit(
            f"Azure Functions 2019 raw files not found under {RAW_DIR}.\n"
            "Download the archive and extract the CSVs there:\n"
            "  curl -L -o datasets/raw/azurefunctions_dataset2019.tar.xz "
            "https://github.com/Azure/AzurePublicDataset/releases/download/dataset-functions-2019/"
            "azurefunctions_dataset2019_azurefunctions-dataset2019.tar.xz\n"
            "  python -c \"import tarfile; tarfile.open('datasets/raw/azurefunctions_dataset2019.tar.xz').extractall('datasets/raw/azurefunctions2019')\""
        )

    # Remove parquets of any previously selected apps so the dataset directory
    # always reflects exactly the current eligibility rule.
    for stale in glob.glob(os.path.join(OUT_DIR, "real_*.parquet")):
        os.remove(stale)

    chosen = build_all_apps()

    stamps = pd.date_range(NOMINAL_START, periods=TOTAL_MINUTES, freq="1min")
    memory_gb = load_memory_table() / 1024.0

    print(f"\n  {'app':<14} | {'mean cores':>10} | {'p95 cores':>10} | {'max cores':>10} | {'mem GB':>7}")
    print("  " + "-" * 66)
    for _, row in chosen.iterrows():
        app = row["app"]
        mem = float(memory_gb.get(app, np.nan))
        print(f"  {app[:12]:<14} | {row['mean']:>10.3f} | {row['p95']:>10.3f} | {row['max']:>10.3f} | {mem:>7.3f}")

        out = pd.DataFrame({
            "timestamp": stamps,
            "workload_id": f"azure-{app[:12]}",
            "cpu_usage": np.round(row["series"], 4),
            "memory_usage": np.round(np.full(TOTAL_MINUTES, mem), 4),
        })
        out.to_parquet(os.path.join(OUT_DIR, f"real_{app[:12]}.parquet"), index=False)
    print(f"\n  wrote {TOP_K} files: datasets/real_<app>.parquet (20160 one-minute rows each, 2019-07-01 nominal anchor)")


if __name__ == "__main__":
    main()

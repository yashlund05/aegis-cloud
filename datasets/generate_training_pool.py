"""
Generates the forecaster training dataset used by the IEEE benchmark.

The training pool is drawn from the SAME workload generator family and the SAME
units (total cluster CPU cores) as the traces replayed by the simulator, but uses
an independent training seed (9999) that shares nothing with the evaluation seeds
(42, 101, 202, 303, 404). One contiguous 7-day block is generated per workload
pattern; blocks are concatenated on a contiguous timeline.

Usage:
    python datasets/generate_training_pool.py --seed 9999 --days-per-pattern 7
"""

import argparse
from datetime import datetime, timedelta, timezone

import pandas as pd

from datasets.workload_patterns import generate_pattern_trace

PATTERNS = ["diurnal", "steady", "bursty", "structured_burst", "flash_crowd", "low_load"]


def generate_training_pool(seed: int = 9999, days_per_pattern: int = 7) -> pd.DataFrame:
    blocks = []
    for i, pattern in enumerate(PATTERNS):
        df = generate_pattern_trace(
            workload_id=f"train-{pattern}",
            pattern=pattern,
            duration_days=days_per_pattern,
            seed=seed,
        )
        # Shift each block onto a contiguous timeline so rolling/lag features
        # stay within-block except for one boundary minute per pair.
        offset = pd.Timedelta(days=i * days_per_pattern)
        df["timestamp"] = pd.to_datetime(df["timestamp"]) + offset
        blocks.append(df)

    pool = pd.concat(blocks, ignore_index=True)
    pool.sort_values(by="timestamp", inplace=True)
    pool.reset_index(drop=True, inplace=True)
    return pool


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate pooled forecaster training dataset.")
    parser.add_argument("--seed", type=int, default=9999)
    parser.add_argument("--days-per-pattern", type=int, default=7)
    parser.add_argument("--output", default="datasets/training_trace.parquet")
    args = parser.parse_args()

    pool = generate_training_pool(seed=args.seed, days_per_pattern=args.days_per_pattern)
    pool.to_parquet(args.output, index=False)
    print(f"Wrote {len(pool)} rows across {len(PATTERNS)} patterns (seed={args.seed}) to {args.output}")
    print(pool.groupby("workload_id")["cpu_usage"].agg(["min", "mean", "max"]))

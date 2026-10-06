"""
Preprocessing module for Aegis ML pipeline.
Handles raw trace data processing (Google, Alibaba, and simulated cluster traces)
and temporal train/val/test splitting.
"""

import argparse
import logging
import os
import pandas as pd
import numpy as np

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def preprocess_trace_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Core trace preprocessing:
    - Filters failed tasks (if status column present)
    - Converts timestamps to datetime
    - Resamples to 60-second buckets per workload
    - Forward-fills short gaps (<5 min)
    - Drops residual NaNs
    - Clips outliers at 99.9th percentile
    """
    if "status" in df.columns:
        df = df[df["status"].isin(["success", "Running", "COMPLETED", 0])].copy()

    if "timestamp" not in df.columns:
        raise ValueError("Missing 'timestamp' column in trace data.")

    # Convert timestamps if numeric
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        # Check if Unix seconds, ms, or string
        sample_val = df["timestamp"].iloc[0]
        if isinstance(sample_val, (int, float, np.integer, np.floating)):
            unit = "ms" if sample_val > 1e11 else "s"
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit=unit, utc=True)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Process by workload if workload_id is present
    if "workload_id" in df.columns:
        processed_dfs = []
        for w_id, w_group in df.groupby("workload_id"):
            w_df = w_group.copy().sort_values("timestamp")
            w_df.set_index("timestamp", inplace=True)

            num_cols = w_df.select_dtypes(include=[np.number]).columns
            resampled = w_df[num_cols].resample("60s").mean()
            resampled = resampled.ffill(limit=5).dropna(how="all")

            for col in ["cpu_usage", "memory_usage"]:
                if col in resampled.columns and len(resampled) > 10:
                    upper_bound = resampled[col].quantile(0.999)
                    resampled[col] = resampled[col].clip(upper=upper_bound)

            resampled["workload_id"] = w_id
            processed_dfs.append(resampled.reset_index())

        if not processed_dfs:
            return pd.DataFrame()
        result_df = pd.concat(processed_dfs, ignore_index=True)
        result_df.sort_values(by=["timestamp", "workload_id"], inplace=True)
        return result_df
    else:
        df = df.sort_values("timestamp").set_index("timestamp")
        num_cols = df.select_dtypes(include=[np.number]).columns
        resampled = df[num_cols].resample("60s").mean()
        resampled = resampled.ffill(limit=5).dropna(how="all")

        for col in ["cpu_usage", "memory_usage"]:
            if col in resampled.columns and len(resampled) > 10:
                upper_bound = resampled[col].quantile(0.999)
                resampled[col] = resampled[col].clip(upper=upper_bound)

        return resampled.reset_index()


def preprocess_google_trace(input_path: str, output_path: str) -> pd.DataFrame:
    """
    Reads Google Cluster Trace CSV/parquet, cleans, aligns to 60-second buckets, and saves output.
    """
    logger.info(f"Preprocessing Google trace from {input_path}")
    if input_path.endswith(".parquet"):
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(input_path)

    processed = preprocess_trace_data(df)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if output_path.endswith(".parquet"):
        processed.to_parquet(output_path, index=False)
    else:
        processed.to_csv(output_path, index=False)

    logger.info(
        f"Saved {len(processed)} preprocessed Google trace records to {output_path}"
    )
    return processed


def preprocess_alibaba_trace(input_path: str, output_path: str) -> pd.DataFrame:
    """
    Reads Alibaba Cluster Trace, cleans, aligns to 60-second buckets, and saves output.
    """
    logger.info(f"Preprocessing Alibaba trace from {input_path}")
    if input_path.endswith(".parquet"):
        df = pd.read_parquet(input_path)
    else:
        df = pd.read_csv(input_path)

    processed = preprocess_trace_data(df)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if output_path.endswith(".parquet"):
        processed.to_parquet(output_path, index=False)
    else:
        processed.to_csv(output_path, index=False)

    logger.info(
        f"Saved {len(processed)} preprocessed Alibaba trace records to {output_path}"
    )
    return processed


def create_temporal_split(
    df: pd.DataFrame,
    train_ratio: float = 0.7,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split time series strictly by time (walk-forward chronological order), NEVER shuffle.
    Preserves 70% train, 15% validation, 15% test.
    """
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError(
            f"Split ratios must sum to 1.0, got {train_ratio + val_ratio + test_ratio}"
        )

    if "timestamp" in df.columns:
        df_sorted = df.sort_values("timestamp").copy()
    else:
        df_sorted = df.copy()

    n = len(df_sorted)
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * val_ratio)

    train_df = df_sorted.iloc[:train_end].copy()
    val_df = df_sorted.iloc[train_end:val_end].copy()
    test_df = df_sorted.iloc[val_end:].copy()

    return train_df, val_df, test_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess workload traces.")
    parser.add_argument(
        "--trace-type", choices=["google", "alibaba", "generic"], default="generic"
    )
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output", required=True, help="Output file path")

    args = parser.parse_args()

    if args.trace_type == "google":
        preprocess_google_trace(args.input, args.output)
    elif args.trace_type == "alibaba":
        preprocess_alibaba_trace(args.input, args.output)
    else:
        preprocess_google_trace(args.input, args.output)

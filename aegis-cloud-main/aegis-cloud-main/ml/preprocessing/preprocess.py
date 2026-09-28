"""
Preprocessing module for Aegis ML pipeline.
Handles raw trace data processing (Google, Alibaba) and temporal splitting.
"""

import argparse
import logging
import os
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def preprocess_google_trace(input_path: str, output_path: str) -> None:
    """
    Reads Google Cluster Trace CSV/parquet, filters failed/empty tasks, aligns to 60-second buckets,
    forward-fills gaps <5 min (drops longer), clips outliers at 99.9 percentile, per-workload normalization.
    """
    logger.info(f"Preprocessing Google trace from {input_path}")
    try:
        if input_path.endswith('.parquet'):
            df = pd.read_parquet(input_path)
        else:
            df = pd.read_csv(input_path)
            
        if 'status' in df.columns:
            df = df[df['status'] == 'success']
            
        if 'timestamp' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            df.set_index('timestamp', inplace=True)
            df = df.resample('60s').mean()
            df = df.ffill(limit=5)
            df.dropna(inplace=True)
            
            for col in ['cpu_usage', 'memory_usage']:
                if col in df.columns:
                    upper_bound = df[col].quantile(0.999)
                    df[col] = df[col].clip(upper=upper_bound)
                    
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            if output_path.endswith('.parquet'):
                df.to_parquet(output_path)
            else:
                df.to_csv(output_path)
            logger.info(f"Successfully saved to {output_path}")
        else:
            logger.error("Missing timestamp column in input data.")
            
    except Exception as e:
        logger.error(f"Error processing Google trace: {e}")
        raise


def preprocess_alibaba_trace(input_path: str, output_path: str) -> None:
    """
    Similar preprocessing for Alibaba format traces.
    """
    logger.info(f"Preprocessing Alibaba trace from {input_path}")
    try:
        if input_path.endswith('.parquet'):
            df = pd.read_parquet(input_path)
        else:
            df = pd.read_csv(input_path)
            
        if 'timestamp' in df.columns:
            if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('timestamp', inplace=True)
            df = df.resample('60s').mean()
            df = df.ffill(limit=5)
            df.dropna(inplace=True)
            
            for col in ['cpu_usage', 'memory_usage']:
                if col in df.columns:
                    upper_bound = df[col].quantile(0.999)
                    df[col] = df[col].clip(upper=upper_bound)
            
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            if output_path.endswith('.parquet'):
                df.to_parquet(output_path)
            else:
                df.to_csv(output_path)
            logger.info(f"Successfully saved to {output_path}")
        else:
            logger.error("Missing timestamp column.")
    except Exception as e:
        logger.error(f"Error processing Alibaba trace: {e}")
        raise


def create_temporal_split(df: pd.DataFrame, train_ratio: float = 0.7, val_ratio: float = 0.15, test_ratio: float = 0.15) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split BY TIME, never shuffle.
    """
    if abs(train_ratio + val_ratio + test_ratio - 1.0) > 1e-6:
        raise ValueError("Ratios must sum to 1.0")
        
    n = len(df)
    train_end = int(n * train_ratio)
    val_end = train_end + int(n * val_ratio)
    
    train_df = df.iloc[:train_end].copy()
    val_df = df.iloc[train_end:val_end].copy()
    test_df = df.iloc[val_end:].copy()
    
    return train_df, val_df, test_df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Preprocess workload traces.")
    parser.add_argument("--trace-type", choices=["google", "alibaba"], required=True, help="Type of trace")
    parser.add_argument("--input", required=True, help="Input file path")
    parser.add_argument("--output", required=True, help="Output file path")
    
    args = parser.parse_args()
    
    if args.trace_type == "google":
        preprocess_google_trace(args.input, args.output)
    elif args.trace_type == "alibaba":
        preprocess_alibaba_trace(args.input, args.output)

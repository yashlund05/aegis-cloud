"""
Unit tests for trace preprocessing and temporal splitting.
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from ml.preprocessing.preprocess import preprocess_trace_data, create_temporal_split


class TestTracePreprocessing:
    @pytest.fixture
    def raw_trace_df(self):
        start = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        timestamps = [start + timedelta(seconds=15 * i) for i in range(200)]
        return pd.DataFrame(
            {
                "timestamp": timestamps,
                "workload_id": ["app-a"] * 100 + ["app-b"] * 100,
                "cpu_usage": np.random.uniform(0.1, 0.9, 200),
                "memory_usage": np.random.uniform(0.2, 0.7, 200),
                "status": ["success"] * 200,
            }
        )

    def test_preprocess_trace_resampling(self, raw_trace_df):
        processed = preprocess_trace_data(raw_trace_df)

        assert isinstance(processed, pd.DataFrame)
        assert len(processed) > 0
        assert "timestamp" in processed.columns
        assert "workload_id" in processed.columns
        assert "cpu_usage" in processed.columns
        assert "memory_usage" in processed.columns

        # Verify time alignment
        workloads = set(processed["workload_id"].unique())
        assert workloads == {"app-a", "app-b"}

    def test_create_temporal_split(self, raw_trace_df):
        train_df, val_df, test_df = create_temporal_split(
            raw_trace_df, train_ratio=0.7, val_ratio=0.15, test_ratio=0.15
        )

        n = len(raw_trace_df)
        assert len(train_df) == int(n * 0.7)
        assert len(val_df) == int(n * 0.15)
        assert len(test_df) == n - len(train_df) - len(val_df)

        # Check temporal order: train timestamps must precede val timestamps, which precede test
        assert train_df["timestamp"].max() <= val_df["timestamp"].min()
        assert val_df["timestamp"].max() <= test_df["timestamp"].min()

    def test_invalid_split_ratios_raise(self, raw_trace_df):
        with pytest.raises(ValueError):
            create_temporal_split(
                raw_trace_df, train_ratio=0.5, val_ratio=0.5, test_ratio=0.5
            )

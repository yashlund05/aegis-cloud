import pytest
import pandas as pd
import numpy as np
from ml.features.feature_engineering import build_features, get_feature_columns

class TestFeatureEngineering:
    @pytest.fixture
    def sample_df(self):
        """Create sample telemetry dataframe."""
        np.random.seed(42)
        n = 200
        timestamps = pd.date_range('2024-01-01', periods=n, freq='1min')
        return pd.DataFrame({
            'timestamp': timestamps,
            'workload_id': 'test-workload',
            'cpu_usage': np.random.uniform(0.1, 0.9, n),
            'memory_usage': np.random.uniform(0.2, 0.8, n),
            'network_rx': np.random.uniform(1000, 10000, n),
            'network_tx': np.random.uniform(500, 5000, n),
            'disk_iops': np.random.uniform(10, 100, n),
            'request_rate': np.random.uniform(10, 500, n),
            'pod_count': np.random.randint(1, 10, n),
        })

    def test_build_features_returns_dataframe(self, sample_df):
        result = build_features(sample_df)
        assert isinstance(result, pd.DataFrame)
        assert len(result) > 0

    def test_time_features_created(self, sample_df):
        result = build_features(sample_df)
        assert 'hour_of_day' in result.columns
        assert 'day_of_week' in result.columns
        assert 'is_weekend' in result.columns

    def test_rolling_features_created(self, sample_df):
        result = build_features(sample_df)
        assert 'cpu_rolling_mean_15' in result.columns
        assert 'cpu_rolling_std_15' in result.columns
        assert 'cpu_rolling_mean_60' in result.columns

    def test_lag_features_created(self, sample_df):
        result = build_features(sample_df)
        for i in range(1, 11):
            assert f'cpu_lag_{i}' in result.columns

    def test_no_nan_in_output(self, sample_df):
        result = build_features(sample_df)
        # After dropping NaN rows from rolling/lag operations
        assert not result[get_feature_columns()].isnull().any().any()

    def test_feature_columns_list(self):
        cols = get_feature_columns()
        assert isinstance(cols, list)
        assert len(cols) > 0
        assert 'hour_of_day' in cols

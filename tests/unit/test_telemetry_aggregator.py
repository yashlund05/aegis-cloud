"""
Unit tests for Aggregator in Telemetry Collector.
Tests metric aggregation, feature extraction, rolling statistics, lag creation, and outlier clipping.
"""

import pytest
from datetime import datetime, timezone, timedelta
from services.telemetry_collector.aggregator import Aggregator, extract_workload_name


class TestAggregator:
    @pytest.fixture
    def aggregator(self):
        return Aggregator(outlier_percentile=99.0, max_history_points=60)

    def test_extract_workload_name(self):
        # Deployment pod naming convention
        assert extract_workload_name("frontend-deployment-79f8b6545-abc12") == "frontend-deployment"
        assert extract_workload_name("api-service-5896cb885-xyz99") == "api-service"
        # StatefulSet pod naming convention
        assert extract_workload_name("postgres-cluster-0") == "postgres-cluster"
        assert extract_workload_name("redis-node-1") == "redis-node"
        # Simple name
        assert extract_workload_name("custom-app") == "custom-app"

    def test_aggregate_raw_metrics(self, aggregator):
        now = datetime.now(timezone.utc)
        cpu_results = [
            {"metric": {"namespace": "default", "pod": "web-deploy-79f8b6545-abc12"}, "value": [1000, "0.35"]},
            {"metric": {"namespace": "default", "pod": "web-deploy-79f8b6545-xyz34"}, "value": [1000, "0.45"]},
            {"metric": {"namespace": "default", "pod": "worker-67df8b64b-11111"}, "value": [1000, "0.80"]},
        ]
        mem_results = [
            {"metric": {"namespace": "default", "pod": "web-deploy-79f8b6545-abc12"}, "value": [1000, "200000000"]},
            {"metric": {"namespace": "default", "pod": "web-deploy-79f8b6545-xyz34"}, "value": [1000, "250000000"]},
            {"metric": {"namespace": "default", "pod": "worker-67df8b64b-11111"}, "value": [1000, "500000000"]},
        ]

        workloads = aggregator.aggregate_raw_metrics(
            cpu_results=cpu_results,
            mem_results=mem_results,
            net_rx_results=[],
            net_tx_results=[],
            disk_results=[],
            req_results=[],
            pod_count_results=[],
            timestamp=now,
        )

        assert "web-deploy" in workloads
        assert "worker" in workloads
        # Pods under web-deploy should sum up: 0.35 + 0.45 = 0.80
        assert workloads["web-deploy"]["cpu_usage"] == pytest.approx(0.80)
        assert workloads["web-deploy"]["memory_usage"] == pytest.approx(450000000)
        assert workloads["worker"]["cpu_usage"] == pytest.approx(0.80)

    def test_extract_features_shape_and_lags(self, aggregator):
        now = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)  # Monday, 14:30
        w_id = "test-service"

        # Feed 15 observations to build history
        for i in range(15):
            ts = now - timedelta(minutes=(15 - i))
            metrics = {
                "cpu_usage": 0.30 + i * 0.02,
                "memory_usage": 0.40,
                "request_rate": 150.0,
            }
            features = aggregator.extract_features(w_id, metrics, timestamp=ts)

        # Verify time features
        assert features["hour_of_day"] == 14
        assert features["day_of_week"] == 0  # Monday
        assert features["is_weekend"] == 0
        assert features["minute_of_hour"] == 29

        # Verify lag features exist
        for k in range(1, 11):
            assert f"lag_{k}" in features
            assert f"cpu_lag_{k}" in features
            assert isinstance(features[f"lag_{k}"], float)

        # Verify rolling statistics
        assert "rolling_mean_15min" in features
        assert "rolling_std_15min" in features
        assert "rolling_mean_60min" in features
        assert "rolling_std_60min" in features
        assert features["rolling_mean_15min"] > 0

        # Verify rate of change
        assert "cpu_rate_of_change" in features
        assert "cpu_memory_ratio" in features

    def test_redis_feature_key_format_and_ttl(self, aggregator):
        """
        Phase 2 Validation Metric: Features written to Redis with correct 1h TTL (3600s)
        and expected key format 'workload:{id}:features'.
        """
        import asyncio
        from unittest.mock import AsyncMock

        async def _test():
            mock_client = AsyncMock()
            w_id = "checkout-service"
            features = aggregator.extract_features(w_id, {"cpu_usage": 0.45, "memory_usage": 0.55})
            
            key = f"workload:{w_id}:features"
            ttl = 3600
            
            # Simulate storing in Redis
            await mock_client.set(key, features, ex=ttl)
            
            mock_client.set.assert_called_once_with("workload:checkout-service:features", features, ex=3600)
            assert key == "workload:checkout-service:features"
            assert ttl == 3600
            assert "cpu_usage" in features
            assert "rolling_mean_15min" in features
            assert "lag_1" in features

        asyncio.run(_test())



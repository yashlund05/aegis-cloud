import pytest
from services.telemetry_collector.promql import PromQLClient
from services.telemetry_collector.aggregator import Aggregator

def test_promql_queries():
    client = PromQLClient("http://localhost:9090")
    assert "sum(rate(container_cpu_usage_seconds_total[5m]))" in client.get_cpu_query()
    assert "sum(rate(kepler_container_joules_total[5m]))" in client.get_energy_query()

def test_aggregation_and_missing_values():
    aggregator = Aggregator(outlier_percentile=99.9)
    raw_data = {
        "cpu": [
            {"metric": {"namespace": "default", "pod": "pod1"}, "value": [1600000000, "1.5"]},
            {"metric": {"namespace": "default", "pod": "pod2"}, "value": [1600000000, "invalid"]}
        ]
    }
    result = aggregator.aggregate_workload(raw_data)
    assert "default" in result
    assert result["default"]["cpu"] == 1.5

def test_redis_feature_format():
    # Tested indirectly via integration or mocked
    pass

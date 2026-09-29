"""
Unit tests for PromQLClient and query template library.
"""

import pytest
from services.telemetry_collector.promql import PromQLClient


class TestPromQLClient:
    @pytest.fixture
    def client(self):
        return PromQLClient(url="http://prometheus.mock:9090")

    def test_cpu_query_generation(self, client):
        q = client.get_cpu_query()
        assert "container_cpu_usage_seconds_total" in q
        assert "by (namespace, pod)" in q

        q_ns = client.get_cpu_query(namespace="aegis-workload")
        assert 'namespace="aegis-workload"' in q_ns

    def test_memory_query_generation(self, client):
        q = client.get_memory_query()
        assert "container_memory_working_set_bytes" in q
        assert "by (namespace, pod)" in q

    def test_network_queries(self, client):
        q_rx = client.get_network_rx_query(namespace="default")
        q_tx = client.get_network_tx_query(namespace="default")
        assert "container_network_receive_bytes_total" in q_rx
        assert "container_network_transmit_bytes_total" in q_tx

    def test_disk_iops_query(self, client):
        q = client.get_disk_iops_query()
        assert "container_fs_reads_total" in q
        assert "container_fs_writes_total" in q

    def test_request_rate_query(self, client):
        q = client.get_request_rate_query()
        assert "http_requests_total" in q

    def test_node_util_queries(self, client):
        q_cpu = client.get_node_cpu_util_query()
        q_mem = client.get_node_mem_util_query()
        assert "node_cpu_seconds_total" in q_cpu
        assert "node_memory_MemTotal_bytes" in q_mem

    def test_kepler_energy_query(self, client):
        q = client.get_kepler_energy_query()
        assert "kepler_container_joules_total" in q

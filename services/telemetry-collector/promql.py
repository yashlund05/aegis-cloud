"""
PromQL query library and HTTP client for Aegis Telemetry Collector.
Queries Prometheus to extract container, workload, node, and Kepler energy metrics.
"""

from typing import Dict, Any, List, Optional
import httpx
import logging

logger = logging.getLogger(__name__)


class PromQLClient:
    """
    Client for executing PromQL queries against Prometheus API.
    """

    def __init__(self, url: str = "http://localhost:9090", timeout: float = 10.0):
        self.url = url.rstrip("/")
        self.query_endpoint = f"{self.url}/api/v1/query"
        self.query_range_endpoint = f"{self.url}/api/v1/query_range"
        self.timeout = timeout

    async def query(
        self, promql_query: str, time: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute an instant query against Prometheus.
        """
        params: Dict[str, Any] = {"query": promql_query}
        if time is not None:
            params["time"] = time

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.query_endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("data", {}).get("result", [])
                else:
                    logger.warning(f"PromQL query returned non-success status: {data}")
                    return []
        except httpx.RequestError as e:
            logger.error(f"Prometheus connection error querying '{promql_query}': {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error executing PromQL query: {e}")
            return []

    async def query_range(
        self, promql_query: str, start: float, end: float, step: str = "15s"
    ) -> List[Dict[str, Any]]:
        """
        Execute a range query against Prometheus.
        """
        params = {
            "query": promql_query,
            "start": start,
            "end": end,
            "step": step,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(self.query_range_endpoint, params=params)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "success":
                    return data.get("data", {}).get("result", [])
                return []
        except Exception as e:
            logger.error(f"Error querying range '{promql_query}': {e}")
            return []

    # -------------------------------------------------------------
    # Query Templates for Telemetry
    # -------------------------------------------------------------

    @staticmethod
    def get_cpu_query(namespace: Optional[str] = None) -> str:
        """CPU rate in cores per pod/workload."""
        ns_filter = f', namespace="{namespace}"' if namespace else ""
        return (
            f'sum(rate(container_cpu_usage_seconds_total{{container!="", container!="POD"{ns_filter}}}[1m])) '
            f"by (namespace, pod)"
        )

    @staticmethod
    def get_memory_query(namespace: Optional[str] = None) -> str:
        """Memory working set bytes per pod/workload."""
        ns_filter = f', namespace="{namespace}"' if namespace else ""
        return (
            f'sum(container_memory_working_set_bytes{{container!="", container!="POD"{ns_filter}}}) '
            f"by (namespace, pod)"
        )

    @staticmethod
    def get_network_rx_query(namespace: Optional[str] = None) -> str:
        """Network receive rate in bytes/sec."""
        ns_filter = f'namespace="{namespace}"' if namespace else 'namespace!=""'
        return f"sum(rate(container_network_receive_bytes_total{{{ns_filter}}}[1m])) by (namespace, pod)"

    @staticmethod
    def get_network_tx_query(namespace: Optional[str] = None) -> str:
        """Network transmit rate in bytes/sec."""
        ns_filter = f'namespace="{namespace}"' if namespace else 'namespace!=""'
        return f"sum(rate(container_network_transmit_bytes_total{{{ns_filter}}}[1m])) by (namespace, pod)"

    @staticmethod
    def get_disk_iops_query(namespace: Optional[str] = None) -> str:
        """Disk read + write IOPS."""
        ns_filter = f', namespace="{namespace}"' if namespace else ""
        return (
            f'sum(rate(container_fs_reads_total{{container!=""{ns_filter}}}[1m]) + '
            f'rate(container_fs_writes_total{{container!=""{ns_filter}}}[1m])) by (namespace, pod)'
        )

    @staticmethod
    def get_request_rate_query(namespace: Optional[str] = None) -> str:
        """Incoming HTTP request rate."""
        ns_filter = f'namespace="{namespace}"' if namespace else 'namespace!=""'
        return f"sum(rate(http_requests_total{{{ns_filter}}}[1m])) by (namespace, pod, service)"

    @staticmethod
    def get_pod_count_query(namespace: Optional[str] = None) -> str:
        """Active running pods per namespace/workload."""
        ns_filter = f', namespace="{namespace}"' if namespace else ""
        return (
            f'count(kube_pod_status_phase{{phase="Running"{ns_filter}}}) by (namespace)'
        )

    @staticmethod
    def get_node_cpu_util_query() -> str:
        """Node CPU utilization fraction [0, 1]."""
        return "1 - avg(rate(node_cpu_seconds_total{mode='idle'}[1m])) by (instance)"

    @staticmethod
    def get_node_mem_util_query() -> str:
        """Node Memory utilization fraction [0, 1]."""
        return "(node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes"

    @staticmethod
    def get_kepler_energy_query(namespace: Optional[str] = None) -> str:
        """Kepler container energy in Joules/sec (Watts)."""
        ns_filter = (
            f'container_namespace="{namespace}"'
            if namespace
            else 'container_namespace!=""'
        )
        return f"sum(rate(kepler_container_joules_total{{{ns_filter}}}[1m])) by (pod_name, container_namespace)"

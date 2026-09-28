import httpx
import logging

logger = logging.getLogger(__name__)

class PromQLClient:
    def __init__(self, url: str):
        self.url = url
        self.client = httpx.AsyncClient(base_url=url)

    async def query(self, query: str):
        try:
            response = await self.client.get("/api/v1/query", params={"query": query})
            response.raise_for_status()
            data = response.json()
            if data.get("status") == "success":
                return data.get("data", {}).get("result", [])
            else:
                logger.error(f"Prometheus query failed: {data}")
                return []
        except Exception as e:
            logger.error(f"Error executing query {query}: {e}")
            return []
            
    async def close(self):
        await self.client.aclose()
    
    def get_cpu_query(self) -> str:
        return 'sum(rate(container_cpu_usage_seconds_total[5m])) by (pod, namespace)'

    def get_mem_query(self) -> str:
        return 'sum(container_memory_working_set_bytes) by (pod, namespace)'
        
    def get_network_rx_query(self) -> str:
        return 'sum(rate(container_network_receive_bytes_total[5m])) by (pod, namespace)'
        
    def get_network_tx_query(self) -> str:
        return 'sum(rate(container_network_transmit_bytes_total[5m])) by (pod, namespace)'
        
    def get_disk_iops_query(self) -> str:
        # Simplified IOPS query, assumes sum of reads and writes
        return 'sum(rate(container_fs_reads_total[5m]) + rate(container_fs_writes_total[5m])) by (pod, namespace)'
        
    def get_pod_count_query(self) -> str:
        return 'count(kube_pod_info) by (namespace)'
        
    def get_node_util_query(self) -> str:
        return 'sum(rate(node_cpu_seconds_total{mode!="idle"}[5m])) by (instance) / sum(instance:node_cpu:ratio) by (instance)'

    def get_http_request_rate_query(self) -> str:
        return 'sum(rate(http_requests_total[5m])) by (pod, namespace)'
        
    def get_energy_query(self) -> str:
        return 'sum(rate(kepler_container_joules_total[5m])) by (pod, namespace)'
        
    def get_workload_utilization_query(self) -> str:
        return 'sum(rate(container_cpu_usage_seconds_total[5m])) by (namespace)'


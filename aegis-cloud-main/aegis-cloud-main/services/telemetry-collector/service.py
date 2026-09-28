import json
import logging
from services.telemetry_collector.promql import PromQLClient
from services.telemetry_collector.aggregator import Aggregator
from services.telemetry_collector.config import config
from services.shared.redis_client import redis_client

logger = logging.getLogger(__name__)

class TelemetryService:
    def __init__(self):
        self.prom_client = PromQLClient(config.prometheus_url)
        self.aggregator = Aggregator(outlier_percentile=config.outlier_percentile)

    async def collect_and_store(self):
        logger.info("Starting telemetry collection cycle...")
        try:
            # 1. Execute queries
            queries = {
                "cpu": self.prom_client.get_cpu_query(),
                "mem": self.prom_client.get_mem_query(),
                "net_rx": self.prom_client.get_network_rx_query(),
                "net_tx": self.prom_client.get_network_tx_query(),
                "disk_iops": self.prom_client.get_disk_iops_query(),
                "http_rate": self.prom_client.get_http_request_rate_query(),
                "energy": self.prom_client.get_energy_query(),
                "pod_count": self.prom_client.get_pod_count_query(),
                "node_util": self.prom_client.get_node_util_query(),
                "workload_util": self.prom_client.get_workload_utilization_query(),
            }
            
            raw_results = {}
            for name, q in queries.items():
                raw_results[name] = await self.prom_client.query(q)
                
            # 2. Aggregate
            aggregated_data = self.aggregator.aggregate_workload(raw_results)
            
            # 3. Store in Redis
            redis = await redis_client.get_redis()
            
            for namespace, metrics in aggregated_data.items():
                key = f"telemetry:{namespace}"
                # Store with TTL (default 1h) as per Phase 2
                await redis.setex(key, config.feature_store_ttl, json.dumps(metrics))
                
            logger.info(f"Successfully stored telemetry for {len(aggregated_data)} namespaces.")
            return aggregated_data
            
        except Exception as e:
            logger.error(f"Error in collect_and_store: {e}")
            raise

    async def close(self):
        await self.prom_client.close()


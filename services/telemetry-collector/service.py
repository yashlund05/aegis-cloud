"""
TelemetryService orchestrates scraping Prometheus, aggregating features,
and publishing them to Redis and TimescaleDB.
"""

import asyncio
from typing import Dict, Any
from datetime import datetime, timezone
import logging

from services.shared.config import config
from services.shared.redis_client import redis_client
from services.shared.database import db
from services.telemetry_collector.promql import PromQLClient
from services.telemetry_collector.aggregator import Aggregator

logger = logging.getLogger(__name__)


class TelemetryService:
    """
    Coordinates metrics scraping, aggregation, and storage in Redis and TimescaleDB.
    """

    def __init__(self, prom_client: PromQLClient = None, aggregator: Aggregator = None):
        self.prom_client = prom_client or PromQLClient(url=config.prometheus_url)
        self.aggregator = aggregator or Aggregator()
        self.is_running = False
        self._scrape_task: asyncio.Task = None

    async def collect_once(self) -> Dict[str, Dict[str, Any]]:
        """
        Executes a single cycle of scraping, aggregating, and caching telemetry.
        Returns the dictionary of workload features.
        """
        now = datetime.now(timezone.utc)
        logger.info(f"Executing telemetry collection cycle at {now.isoformat()}...")

        # 1. Fetch raw metrics concurrently from Prometheus
        (
            cpu_res,
            mem_res,
            net_rx_res,
            net_tx_res,
            disk_res,
            req_res,
            pod_res,
        ) = await asyncio.gather(
            self.prom_client.query(self.prom_client.get_cpu_query()),
            self.prom_client.query(self.prom_client.get_memory_query()),
            self.prom_client.query(self.prom_client.get_network_rx_query()),
            self.prom_client.query(self.prom_client.get_network_tx_query()),
            self.prom_client.query(self.prom_client.get_disk_iops_query()),
            self.prom_client.query(self.prom_client.get_request_rate_query()),
            self.prom_client.query(self.prom_client.get_pod_count_query()),
            return_exceptions=True,
        )

        # Handle potential query failures gracefully
        def safe_result(res):
            if isinstance(res, Exception):
                logger.warning(f"Error fetching metric in collection cycle: {res}")
                return []
            return res or []

        # 2. Aggregate raw container metrics by workload
        workload_metrics = self.aggregator.aggregate_raw_metrics(
            cpu_results=safe_result(cpu_res),
            mem_results=safe_result(mem_res),
            net_rx_results=safe_result(net_rx_res),
            net_tx_results=safe_result(net_tx_res),
            disk_results=safe_result(disk_res),
            req_results=safe_result(req_res),
            pod_count_results=safe_result(pod_res),
            timestamp=now,
        )

        workload_features: Dict[str, Dict[str, Any]] = {}

        # 3. For each workload, extract features and push to Redis & PostgreSQL
        for w_id, raw_m in workload_metrics.items():
            features = self.aggregator.extract_features(w_id, raw_m, timestamp=now)
            workload_features[w_id] = features

            # Write to Redis Feature Store: key format workload:{id}:features with 1h TTL (3600s)
            redis_key = f"workload:{w_id}:features"
            try:
                await redis_client.set_features(redis_key, features, expire=3600)
            except Exception as e:
                logger.warning(f"Failed to write features to Redis for {w_id}: {e}")

            # Publish telemetry event on Redis pub/sub channel
            try:
                await redis_client.publish(
                    "aegis.events.telemetry",
                    {
                        "workload_id": w_id,
                        "timestamp": now.isoformat(),
                        "cpu_usage": raw_m["cpu_usage"],
                        "memory_usage": raw_m["memory_usage"],
                    },
                )
            except Exception as e:
                logger.debug(f"Redis pub/sub publish skipped: {e}")

            # Write raw metric point to TimescaleDB if pool is active
            await self._persist_metric_point(raw_m, now)

        logger.info(
            f"Telemetry cycle completed. Processed {len(workload_features)} workloads."
        )
        return workload_features

    async def _persist_metric_point(self, raw_m: Dict[str, Any], ts: datetime):
        """
        Inserts raw metric snapshot into PostgreSQL / TimescaleDB metrics_raw table.
        """
        pool = await db.get_pool()
        if not pool:
            return

        query = """
            INSERT INTO metrics_raw (
                ts, workload_id, cpu_usage, memory_usage,
                network_rx, network_tx, disk_iops, request_rate, pod_count
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT DO NOTHING;
        """
        try:
            # If workload_id is a valid UUID, persist directly; otherwise skip foreign-key error
            await db.execute_query(
                query,
                ts,
                raw_m["workload_id"],
                raw_m["cpu_usage"],
                raw_m["memory_usage"],
                raw_m["network_rx"],
                raw_m["network_tx"],
                raw_m["disk_iops"],
                raw_m["request_rate"],
                raw_m["pod_count"],
            )
        except Exception as e:
            logger.debug(f"DB persistence deferred or skipped: {e}")

    async def start_periodic_scrape(self, interval_seconds: int = 30):
        """
        Background loop executing collect_once periodically.
        """
        self.is_running = True
        logger.info(
            f"Starting continuous telemetry scraper loop (interval={interval_seconds}s)..."
        )
        while self.is_running:
            try:
                await self.collect_once()
            except Exception as e:
                logger.error(f"Error in telemetry collection loop: {e}", exc_info=True)
            await asyncio.sleep(interval_seconds)

    def stop_periodic_scrape(self):
        self.is_running = False
        if self._scrape_task:
            self._scrape_task.cancel()
        logger.info("Telemetry scraper loop stopped.")


telemetry_service = TelemetryService()

import logging
import httpx
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class KeplerClient:
    def __init__(self, url: str):
        self.url = url

    async def get_pod_energy(self) -> Dict[str, float]:
        """
        Query Kepler Prometheus metrics for pod-level energy consumption.
        Returns a dict mapping pod names to their power in watts.
        """
        try:
            async with httpx.AsyncClient() as client:
                # Query Kepler's per-pod energy metric
                resp = await client.get(
                    f"{self.url}/api/v1/query",
                    params={"query": "sum(kepler_container_joules_total) by (pod_name)"}
                )
                resp.raise_for_status()
                data = resp.json()

                pod_energy = {}
                if data.get("status") == "success":
                    for result in data.get("data", {}).get("result", []):
                        pod_name = result.get("metric", {}).get("pod_name", "unknown")
                        value = float(result.get("value", [0, 0])[1])
                        pod_energy[pod_name] = value

                return pod_energy
        except Exception as e:
            logger.error(f"Failed to fetch Kepler pod energy: {e}")
            return {}

    async def get_node_energy(self) -> Dict[str, float]:
        """
        Query Kepler Prometheus metrics for node-level energy consumption.
        Returns a dict mapping node names to their power in watts.
        """
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"{self.url}/api/v1/query",
                    params={"query": "sum(kepler_node_core_joules_total + kepler_node_dram_joules_total) by (instance)"}
                )
                resp.raise_for_status()
                data = resp.json()

                node_energy = {}
                if data.get("status") == "success":
                    for result in data.get("data", {}).get("result", []):
                        node_name = result.get("metric", {}).get("instance", "unknown")
                        value = float(result.get("value", [0, 0])[1])
                        node_energy[node_name] = value

                return node_energy
        except Exception as e:
            logger.error(f"Failed to fetch Kepler node energy: {e}")
            return {}

    async def get_cluster_total_power(self) -> float:
        """Returns total cluster power in watts from Kepler."""
        node_energy = await self.get_node_energy()
        return sum(node_energy.values())

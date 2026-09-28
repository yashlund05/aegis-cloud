import logging
import math
import httpx
from services.energy_module.config import config
from services.shared.redis_client import redis_client

logger = logging.getLogger(__name__)

class EnergyService:
    def __init__(self):
        self.kepler_url = config.kepler_url
        self.default_p_idle = config.default_p_idle
        self.default_p_max = config.default_p_max
        self.default_alpha = config.default_alpha

    def compute_power(self, utilization: float, p_idle: float = None,
                      p_max: float = None, alpha: float = None) -> float:
        """P(u) = P_idle + (P_max - P_idle) * u^alpha"""
        p_idle = p_idle or self.default_p_idle
        p_max = p_max or self.default_p_max
        alpha = alpha or self.default_alpha
        return p_idle + (p_max - p_idle) * math.pow(max(0.0, min(1.0, utilization)), alpha)

    async def _fetch_kepler_metrics(self) -> list:
        """Fetch per-node energy metrics from Kepler."""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self.kepler_url}/metrics")
                if resp.status_code == 200:
                    # Parse Prometheus exposition format (simplified)
                    lines = resp.text.strip().split("\n")
                    metrics = []
                    for line in lines:
                        if line.startswith("#") or not line.strip():
                            continue
                        parts = line.split()
                        if len(parts) >= 2:
                            metrics.append({"metric": parts[0], "value": float(parts[1])})
                    return metrics
        except Exception as e:
            logger.error(f"Failed to fetch Kepler metrics: {e}")
        return []

    async def get_cluster_summary(self) -> dict:
        """Calculate cluster-wide energy summary."""
        kepler_metrics = await self._fetch_kepler_metrics()

        # Extract node-level power from Kepler (kepler_node_core_joules_total, etc.)
        total_power_watts = 0.0
        node_powers = {}

        for m in kepler_metrics:
            metric_name = m.get("metric", "")
            value = m.get("value", 0.0)
            if "kepler_node" in metric_name and "joules" in metric_name:
                # Simplified: treat the value as current power draw
                node_id = metric_name.split("{")[0] if "{" in metric_name else "unknown"
                node_powers[node_id] = node_powers.get(node_id, 0.0) + value
                total_power_watts += value

        return {
            "total_power_watts": round(total_power_watts, 2),
            "total_energy_kwh": round(total_power_watts / 1000.0, 4),  # Instantaneous approx
            "node_count": len(node_powers),
            "nodes": node_powers
        }

    async def get_node_energy(self, node_name: str, utilization: float) -> dict:
        """Get estimated energy for a specific node."""
        power = self.compute_power(utilization)
        return {
            "node": node_name,
            "utilization": utilization,
            "estimated_power_watts": round(power, 2),
            "p_idle": self.default_p_idle,
            "p_max": self.default_p_max
        }

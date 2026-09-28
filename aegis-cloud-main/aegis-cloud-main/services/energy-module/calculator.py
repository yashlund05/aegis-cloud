import logging
from typing import List, Dict, Any
from services.energy_module.power_model import PowerModel, compute_energy_kwh

logger = logging.getLogger(__name__)

class EnergyCalculator:
    """Calculates energy consumed over time intervals for nodes and workloads."""

    def __init__(self, default_p_idle: float = 50.0, default_p_max: float = 200.0,
                 default_alpha: float = 1.5):
        self.default_model = PowerModel(p_idle=default_p_idle, p_max=default_p_max, alpha=default_alpha)

    def compute_kwh(self, power_watts: float, duration_hours: float) -> float:
        """Simple energy computation: E(kWh) = P(W) / 1000 * t(h)."""
        return (power_watts / 1000.0) * duration_hours

    def compute_node_energy(self, utilization_samples: List[float],
                            sample_interval_seconds: float = 60.0,
                            power_model: PowerModel = None) -> Dict[str, float]:
        """
        Given a time series of utilization samples for a node, compute total energy.

        Args:
            utilization_samples: List of utilization values (0.0 to 1.0).
            sample_interval_seconds: Time between samples in seconds.
            power_model: Optional custom power model for the node.

        Returns:
            Dict with total_kwh, avg_power_watts, peak_power_watts.
        """
        model = power_model or self.default_model

        if not utilization_samples:
            return {"total_kwh": 0.0, "avg_power_watts": 0.0, "peak_power_watts": 0.0}

        powers = []
        for u in utilization_samples:
            clamped = max(0.0, min(1.0, u))
            powers.append(model.compute_power(clamped))

        avg_power = sum(powers) / len(powers)
        peak_power = max(powers)
        total_duration_seconds = len(utilization_samples) * sample_interval_seconds
        total_kwh = compute_energy_kwh(avg_power, total_duration_seconds)

        return {
            "total_kwh": round(total_kwh, 6),
            "avg_power_watts": round(avg_power, 2),
            "peak_power_watts": round(peak_power, 2),
            "samples": len(utilization_samples),
            "duration_hours": round(total_duration_seconds / 3600.0, 4)
        }

    def compute_cluster_energy(self, nodes: List[Dict[str, Any]],
                                sample_interval_seconds: float = 60.0) -> Dict[str, Any]:
        """
        Compute total cluster energy from multiple nodes.

        Args:
            nodes: List of dicts, each with 'name' and 'utilization_samples' keys.
            sample_interval_seconds: Time between samples.

        Returns:
            Dict with per-node breakdown and cluster totals.
        """
        node_results = {}
        cluster_kwh = 0.0
        cluster_peak = 0.0

        for node in nodes:
            name = node.get("name", "unknown")
            samples = node.get("utilization_samples", [])

            p_idle = node.get("p_idle", self.default_model.p_idle)
            p_max = node.get("p_max", self.default_model.p_max)
            alpha = node.get("alpha", self.default_model.alpha)
            model = PowerModel(p_idle=p_idle, p_max=p_max, alpha=alpha)

            result = self.compute_node_energy(samples, sample_interval_seconds, model)
            node_results[name] = result
            cluster_kwh += result["total_kwh"]
            cluster_peak = max(cluster_peak, result["peak_power_watts"])

        return {
            "cluster_total_kwh": round(cluster_kwh, 6),
            "cluster_peak_power_watts": round(cluster_peak, 2),
            "node_count": len(nodes),
            "nodes": node_results
        }

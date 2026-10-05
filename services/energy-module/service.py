import os
from .kepler import KeplerClient
from typing import Dict, Any

class EnergyService:
    def __init__(self):
        prometheus_url = os.environ.get("PROMETHEUS_URL", "http://prometheus.aegis-monitoring:9090")
        self.kepler = KeplerClient(prometheus_url)

    async def get_cluster_summary(self) -> Dict[str, Any]:
        """
        Calculate cluster energy summary using live Kepler data.
        """
        pod_energy = await self.kepler.get_pod_energy()
        
        total_joules = sum(pod_energy.values())
        total_kwh = total_joules / (3600.0 * 1000.0)
        
        return {
            "total_energy_joules": total_joules,
            "total_energy_kwh": total_kwh,
            "pod_breakdown": pod_energy
        }

import aiohttp
from typing import Dict


class KeplerClient:
    def __init__(self, url: str):
        self.url = url

    async def get_pod_energy(self) -> Dict[str, float]:
        """
        Query Kepler Prometheus metrics for pod energy (kepler_container_joules_total).
        """
        energy_dict = {}
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.url}/api/v1/query",
                    params={"query": "kepler_container_joules_total"},
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "success":
                            for result in data["data"]["result"]:
                                pod_name = result["metric"].get("pod_name", "unknown")
                                value = float(result["value"][1])
                                energy_dict[pod_name] = value
            except Exception as e:
                print(f"Error querying Kepler: {e}")
        return energy_dict

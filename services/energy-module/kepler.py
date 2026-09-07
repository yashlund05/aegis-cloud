class KeplerClient:
    def __init__(self, url: str):
        self.url = url

    async def get_pod_energy(self) -> dict:
        # TODO: Query Kepler Prometheus metrics for pod energy
        return {}

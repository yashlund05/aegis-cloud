class PromQLClient:
    def __init__(self, url: str):
        self.url = url

    async def query(self, query: str):
        # TODO: Execute query against Prometheus API
        pass
    
    def get_cpu_query(self) -> str:
        return 'sum(rate(container_cpu_usage_seconds_total[5m])) by (pod)'

    def get_mem_query(self) -> str:
        return 'sum(container_memory_working_set_bytes) by (pod)'
    
    # TODO: add queries for network rx/tx, disk IOPS, request rate, pod count, node util

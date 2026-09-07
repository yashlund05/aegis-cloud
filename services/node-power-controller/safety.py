class PowerSafetyChecker:
    def __init__(self, min_active_nodes: int, buffer_capacity_percent: float):
        self.min_active_nodes = min_active_nodes
        self.buffer_capacity_percent = buffer_capacity_percent

    def can_drain(self, node_name: str, cluster_state: dict) -> bool:
        # TODO: ensure never drain last node and minimum capacity is maintained
        return True

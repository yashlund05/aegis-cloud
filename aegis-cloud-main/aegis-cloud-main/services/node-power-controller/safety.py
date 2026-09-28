import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

class PowerSafetyChecker:
    def __init__(self, min_active_nodes: int = 2, buffer_capacity_percent: float = 0.20):
        self.min_active_nodes = min_active_nodes
        self.buffer_capacity_percent = buffer_capacity_percent

    def validate_power_action(self, action: str, node_id: str, cluster_state: Dict[str, Any]) -> bool:
        """
        Validates if a power action is safe to execute.
        - Cannot turn off/drain if it drops active nodes below min_active_nodes.
        - Cannot turn off/drain control plane nodes.
        - Cannot turn off/drain if it violates buffer capacity.
        """
        if action not in ["drain", "standby", "power-off"]:
            return True

        nodes = cluster_state.get("nodes", [])
        
        # Control plane check
        for n in nodes:
            if n["name"] == node_id and n.get("is_control_plane"):
                logger.warning(f"Safety violation: cannot drain/power-off control plane node {node_id}")
                return False

        active_nodes = [n for n in nodes if n["status"] == "active" and n["name"] != node_id]

        if len(active_nodes) < self.min_active_nodes:
            logger.warning(
                f"Safety violation: action {action} on {node_id} would leave "
                f"only {len(active_nodes)} active nodes (min: {self.min_active_nodes})"
            )
            return False

        total_active_capacity = sum(n.get("cpu_capacity", 0) for n in active_nodes)
        total_used = sum(n.get("cpu_used", 0) for n in nodes)

        if total_active_capacity == 0:
            return False

        projected_util = total_used / total_active_capacity
        if projected_util > (1.0 - self.buffer_capacity_percent):
            logger.warning(
                f"Safety violation: action {action} on {node_id} would push "
                f"cluster utilization to {projected_util*100:.1f}% "
                f"(max allowed: {(1.0-self.buffer_capacity_percent)*100:.1f}%)"
            )
            return False

        return True

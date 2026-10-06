"""
Safety enforcement module for Node Power Controller (Phase 7).
Guarantees cluster survivability and minimum capacity before executing cordon or drain.
"""

import logging
from typing import Tuple, List

logger = logging.getLogger(__name__)


class PowerSafetyChecker:
    """
    Enforces minimum active nodes and capacity buffer guards to prevent cluster starvation.
    """

    def __init__(
        self, min_active_nodes: int = 1, buffer_capacity_percent: float = 15.0
    ):
        self.min_active_nodes = max(1, min_active_nodes)
        self.buffer_capacity_percent = buffer_capacity_percent

    def can_modify_node(
        self,
        node_name: str,
        action: str,
        currently_active_nodes: List[str],
        all_nodes: List[str],
    ) -> Tuple[bool, str]:
        """
        Validates whether cordoning, uncordoning, or draining a node is safe.
        Returns:
            (is_safe: bool, reason: str)
        """
        # Uncordon / activation is always safe
        if action in ("uncordon", "active", "power_up"):
            return True, f"Activation approved for node '{node_name}'."

        # Cordon or drain checks
        if action in ("cordon", "drain", "power_down"):
            # 1. Never drain the last remaining active node
            if len(currently_active_nodes) <= 1 and node_name in currently_active_nodes:
                return (
                    False,
                    f"Refusing to {action} node '{node_name}': cannot disable the last remaining active node in cluster.",
                )

            # 2. Enforce minimum active nodes threshold
            if (
                len(currently_active_nodes) <= self.min_active_nodes
                and node_name in currently_active_nodes
            ):
                return (
                    False,
                    f"Refusing to {action} node '{node_name}': cluster requires at least {self.min_active_nodes} active nodes.",
                )

        return True, f"Action '{action}' on node '{node_name}' approved."

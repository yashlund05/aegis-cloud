"""
Node Power Service orchestrating safety validation and power state mutations (Phase 7).
"""

import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any

from services.node_power_controller.config import config
from services.node_power_controller.safety import PowerSafetyChecker
from services.node_power_controller.power import PowerManager
from services.shared.schemas import DecisionPlan, ActionResult

logger = logging.getLogger(__name__)


class NodePowerService:
    """
    Applies node power state transitions from DecisionPlan with strict minimum capacity guards.
    """

    def __init__(self):
        self.safety = PowerSafetyChecker(
            min_active_nodes=config.min_active_nodes,
            buffer_capacity_percent=config.buffer_capacity_percent,
        )
        self.manager = PowerManager(dry_run=getattr(config, "dry_run", False))
        self.action_history: List[ActionResult] = []

    async def process_plan(self, plan: DecisionPlan) -> List[ActionResult]:
        results: List[ActionResult] = []

        all_nodes = [c.node_id for c in plan.node_power_changes]
        # Active nodes in plan
        active_nodes = [
            c.node_id for c in plan.node_power_changes if c.action.lower() in ("active", "uncordon")
        ]

        for change in plan.node_power_changes:
            n_id = str(change.node_id)
            act = change.action.lower()
            action_id = f"act-pwr-{uuid.uuid4().hex[:8]}"

            is_safe, reason = self.safety.can_modify_node(
                node_name=n_id,
                action=act,
                currently_active_nodes=active_nodes,
                all_nodes=all_nodes,
            )

            if not is_safe:
                logger.warning(f"Safety guard rejected node action '{act}' for '{n_id}': {reason}")
                res = ActionResult(
                    id=action_id,
                    decision_id=str(plan.id),
                    action_type="power",
                    target=n_id,
                    status="rejected",
                    error_message=reason,
                    completed_at=datetime.utcnow(),
                )
            else:
                try:
                    if act in ("cordon", "power_down"):
                        await self.manager.cordon_node(n_id)
                    elif act in ("drain",):
                        await self.manager.drain_node(n_id)
                    else:
                        await self.manager.uncordon_node(n_id)

                    res = ActionResult(
                        id=action_id,
                        decision_id=str(plan.id),
                        action_type="power",
                        target=n_id,
                        status="executed",
                        error_message=None,
                        completed_at=datetime.utcnow(),
                    )
                except Exception as e:
                    logger.error(f"Error applying power action on '{n_id}': {e}")
                    res = ActionResult(
                        id=action_id,
                        decision_id=str(plan.id),
                        action_type="power",
                        target=n_id,
                        status="failed",
                        error_message=str(e),
                        completed_at=datetime.utcnow(),
                    )

            results.append(res)
            self.action_history.insert(0, res)
            if len(self.action_history) > 200:
                self.action_history.pop()

        return results

    async def get_node_states(self) -> Dict[str, str]:
        return self.manager.simulated_node_states

    async def get_history(self, limit: int = 50) -> List[ActionResult]:
        return self.action_history[:limit]


node_power_service = NodePowerService()

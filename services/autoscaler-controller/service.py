"""
Autoscaler Service managing safety validation, execution, and HPA fallback (Phase 7).
"""

import time
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from services.autoscaler_controller.config import config
from services.autoscaler_controller.safety import SafetyChecker
from services.autoscaler_controller.executor import K8sExecutor
from services.shared.schemas import DecisionPlan, ActionResult, ReplicaChange

logger = logging.getLogger(__name__)


class AutoscalerService:
    """
    Coordinates decision plan replica mutations, enforcing dead zones, cooldowns,
    and automatic fallback to stock Kubernetes HPA on failure.
    """

    def __init__(self):
        self.safety = SafetyChecker(
            dead_zone_percent=config.dead_zone_percent,
            cooldown_seconds=config.cooldown_seconds,
        )
        self.executor = K8sExecutor(dry_run=config.dry_run)
        self.last_scaled_at: Dict[str, float] = {}
        self.action_history: List[ActionResult] = []
        self.hpa_fallback_active: bool = False

    async def process_plan(self, plan: DecisionPlan) -> List[ActionResult]:
        """
        Processes replica changes from a DecisionPlan through safety gates and executes them.
        """
        results: List[ActionResult] = []

        for change in plan.replica_changes:
            w_id = str(change.workload_id)
            curr = change.current_replicas
            target = change.target_replicas
            last_ts = self.last_scaled_at.get(w_id)

            can_scale, reason, approved_target = self.safety.should_scale(
                current_replicas=curr,
                target_replicas=target,
                last_scaled_at=last_ts,
            )

            action_id = f"act-scale-{uuid.uuid4().hex[:8]}"

            if not can_scale:
                logger.info(f"Skipping scale for workload '{w_id}': {reason}")
                res = ActionResult(
                    id=action_id,
                    decision_id=str(plan.id),
                    action_type="scale",
                    target=w_id,
                    status="skipped",
                    error_message=reason,
                    completed_at=datetime.utcnow(),
                )
            else:
                try:
                    await self.executor.scale_deployment(
                        deployment_name=w_id,
                        replicas=approved_target,
                    )
                    self.last_scaled_at[w_id] = time.time()
                    res = ActionResult(
                        id=action_id,
                        decision_id=str(plan.id),
                        action_type="scale",
                        target=w_id,
                        status="executed",
                        error_message=None,
                        completed_at=datetime.utcnow(),
                    )
                    logger.info(
                        f"Successfully applied scale for '{w_id}': {curr} -> {approved_target}"
                    )
                except Exception as e:
                    logger.error(f"Execution error scaling '{w_id}': {e}. Triggering HPA fallback.")
                    self.trigger_hpa_fallback(f"Scale execution error on '{w_id}': {e}")
                    res = ActionResult(
                        id=action_id,
                        decision_id=str(plan.id),
                        action_type="scale",
                        target=w_id,
                        status="failed",
                        error_message=str(e),
                        completed_at=datetime.utcnow(),
                    )

            results.append(res)
            self.action_history.insert(0, res)
            if len(self.action_history) > 200:
                self.action_history.pop()

        return results

    def trigger_hpa_fallback(self, reason: str):
        """
        Activates fallback to standard Kubernetes HPA behavior upon execution failure.
        """
        self.hpa_fallback_active = True
        logger.warning(f"=== HPA FALLBACK ACTIVATED === Reason: {reason}")

    def reset_hpa_fallback(self):
        """Resets the HPA fallback status."""
        self.hpa_fallback_active = False

    async def get_history(self, limit: int = 50) -> List[ActionResult]:
        return self.action_history[:limit]


autoscaler_service = AutoscalerService()

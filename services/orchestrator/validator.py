"""
Decision plan safety validator for Aegis Orchestrator (Phase 8).
Validates plans before execution to protect cluster stability and prevent invalid mutations.
"""

import logging
from services.shared.schemas import DecisionPlan
from services.shared.errors import ValidationError

logger = logging.getLogger(__name__)


def validate_decision_plan(
    plan: DecisionPlan,
    min_active_nodes: int = 1,
    max_replicas_limit: int = 100,
) -> bool:
    """
    Validates a DecisionPlan before execution.
    Raises ValidationError if any constraint or safety invariant is breached.
    """
    if not plan:
        raise ValidationError("DecisionPlan cannot be null or empty.")

    if plan.status in ("infeasible", "failed", "rejected"):
        raise ValidationError(f"Cannot execute plan with status '{plan.status}'.")

    # 1. Validate replica changes
    for change in plan.replica_changes:
        if change.target_replicas < 0:
            raise ValidationError(
                f"Invalid negative target replicas for workload '{change.workload_id}': {change.target_replicas}"
            )
        if change.target_replicas > max_replicas_limit:
            raise ValidationError(
                f"Target replicas for '{change.workload_id}' ({change.target_replicas}) exceeds safety ceiling ({max_replicas_limit})."
            )

    # 2. Validate node power state invariants
    if plan.node_power_changes:
        active_nodes = [
            c.node_id
            for c in plan.node_power_changes
            if c.action.lower() in ("active", "uncordon")
        ]
        # Only check if all nodes in cluster were evaluated
        if len(plan.node_power_changes) >= min_active_nodes and len(active_nodes) < min_active_nodes:
            raise ValidationError(
                f"Plan would leave {len(active_nodes)} active nodes, violating minimum threshold of {min_active_nodes}."
            )

    logger.info(f"DecisionPlan '{plan.id}' passed all safety validations.")
    return True

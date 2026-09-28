import logging
from services.shared.schemas import DecisionPlan
from services.shared.errors import ValidationError

logger = logging.getLogger(__name__)

MAX_REPLICA_CHANGE_PER_CYCLE = 10
MAX_NODE_POWER_CHANGES_PER_CYCLE = 2

def validate_decision_plan(plan) -> bool:
    """
    Validates a decision plan before execution.
    Raises ValidationError if the plan is unsafe or invalid.
    """
    if not plan:
        raise ValidationError("Plan cannot be empty")

    # If plan is a dict (from JSON), access via dict keys
    if isinstance(plan, dict):
        replica_changes = plan.get("replica_changes", [])
        node_power_changes = plan.get("node_power_changes", [])
        placement_decisions = plan.get("placement_decisions", [])
        status = plan.get("status", "")
    else:
        replica_changes = plan.replica_changes
        node_power_changes = plan.node_power_changes
        placement_decisions = plan.placement_decisions
        status = plan.status

    # 1. Check plan status
    if status not in ("success", "feasible"):
        logger.warning(f"Plan status is '{status}', may not be optimal")

    # 2. Guard against too many replica changes in a single cycle
    if len(replica_changes) > MAX_REPLICA_CHANGE_PER_CYCLE:
        logger.error(
            f"Plan has {len(replica_changes)} replica changes, "
            f"exceeding max {MAX_REPLICA_CHANGE_PER_CYCLE}"
        )
        return False

    # 3. Guard against too many node power changes (prevent mass drain)
    if len(node_power_changes) > MAX_NODE_POWER_CHANGES_PER_CYCLE:
        logger.error(
            f"Plan has {len(node_power_changes)} node power changes, "
            f"exceeding max {MAX_NODE_POWER_CHANGES_PER_CYCLE}"
        )
        return False

    # 4. Validate replica change bounds
    for rc in replica_changes:
        if isinstance(rc, dict):
            target = rc.get("target_replicas", 0)
            current = rc.get("current_replicas", 0)
        else:
            target = rc.target_replicas
            current = rc.current_replicas

        if target < 0:
            logger.error(f"Negative target_replicas: {target}")
            return False
        if target > 200:
            logger.error(f"Excessive target_replicas: {target}")
            return False

    logger.info("Decision plan validated successfully")
    return True

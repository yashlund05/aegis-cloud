from services.shared.schemas import DecisionPlan
from services.shared.errors import ValidationError

def validate_decision_plan(plan: DecisionPlan) -> bool:
    """
    Validates a decision plan before execution.
    Raises ValidationError if the plan is unsafe or invalid.
    """
    # TODO: Implement safety constraints (e.g., max replica changes per cycle, 
    # preventing draining all nodes, etc.)
    if not plan:
        raise ValidationError("Plan cannot be empty")
        
    return True

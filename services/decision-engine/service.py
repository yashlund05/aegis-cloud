"""
Decision Service managing lifecycle, optimization requests, and audit history.
"""

import logging
from typing import List, Dict, Any, Optional
from services.decision_engine.config import config
from services.decision_engine.solver import CPSolver
from services.shared.schemas import DecisionPlan
from services.shared.database import db

logger = logging.getLogger(__name__)


class DecisionService:
    """
    High-level orchestrator for decision optimization.
    Maintains decision audit logs in PostgreSQL/memory and routes requests to the solver.
    """

    def __init__(self):
        self.solver = CPSolver(
            timeout_ms=config.solver_timeout_ms,
            utilization_max=config.utilization_max,
            ha_max_ratio=config.ha_max_pods_per_node_ratio,
            weight_energy=config.weight_energy,
            weight_churn=config.weight_scaling_churn,
        )
        self.in_memory_history: List[DecisionPlan] = []

    async def optimize(
        self,
        workloads: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        predictions: Optional[List[Dict[str, Any]]] = None,
        cycle_id: Optional[str] = None,
    ) -> DecisionPlan:
        """
        Executes CP-SAT joint optimization or FFD fallback to generate a DecisionPlan.
        """
        plan = self.solver.solve(
            workloads=workloads,
            nodes=nodes,
            predictions=predictions,
            cycle_id=cycle_id,
        )

        # Store in audit history
        self.in_memory_history.insert(0, plan)
        if len(self.in_memory_history) > 100:
            self.in_memory_history.pop()

        # Try persisting asynchronously to database if available
        try:
            pool = await db.get_pool()
            if pool:
                # Query placeholder for database persistence
                pass
        except Exception as e:
            logger.debug(f"Could not persist decision to DB: {e}")

        return plan

    async def get_history(self, limit: int = 20) -> List[DecisionPlan]:
        """
        Returns latest decision plans from audit history.
        """
        return self.in_memory_history[:limit]

    async def get_decision_by_id(self, decision_id: str) -> Optional[DecisionPlan]:
        """
        Fetches a specific decision plan by its ID or cycle ID.
        """
        for plan in self.in_memory_history:
            if str(plan.id) == decision_id or str(plan.cycle_id) == decision_id:
                return plan
        return None


decision_service = DecisionService()

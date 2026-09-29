"""
Orchestrator Service providing cycle history and status queries.
"""

from typing import List, Dict, Any
from services.orchestrator.loop import control_loop


class OrchestratorService:
    async def get_cycle_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return control_loop.cycle_history[:limit]

    async def get_current_status(self) -> Dict[str, Any]:
        return control_loop.last_cycle_info


orchestrator_service = OrchestratorService()

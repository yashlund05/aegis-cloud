from fastapi import APIRouter
from typing import Dict, Any, List

router = APIRouter()

@router.get("/energy")
async def get_cluster_energy() -> Dict[str, Any]:
    # TODO: return cluster energy summary
    return {"total_power_watts": 0.0, "total_energy_kwh": 0.0}

@router.get("/energy/nodes")
async def get_nodes_energy() -> List[Dict[str, Any]]:
    # TODO: return per-node power
    return []

@router.get("/energy/workloads")
async def get_workloads_energy() -> List[Dict[str, Any]]:
    # TODO: return per-workload energy attribution
    return []

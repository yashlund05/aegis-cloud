from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List
from services.energy_module.service import EnergyService

router = APIRouter()
energy_service = EnergyService()

@router.get("/energy")
async def get_cluster_energy() -> Dict[str, Any]:
    summary = await energy_service.get_cluster_summary()
    return summary

@router.get("/energy/nodes")
async def get_nodes_energy() -> List[Dict[str, Any]]:
    summary = await energy_service.get_cluster_summary()
    nodes = summary.get("nodes", {})
    return [{"node": k, "power_watts": v} for k, v in nodes.items()]

@router.get("/energy/nodes/{node_name}")
async def get_node_energy(node_name: str, utilization: float = 0.5) -> Dict[str, Any]:
    return await energy_service.get_node_energy(node_name, utilization)

@router.get("/energy/workloads")
async def get_workloads_energy() -> List[Dict[str, Any]]:
    # Genuine Dependency: Per-workload energy attribution requires Kepler pod-level metrics exported to Redis.
    # Currently only node-level metrics are queried and cached.
    raise HTTPException(status_code=501, detail="Per-workload energy attribution not available. Requires Kepler pod-level metrics pipeline.")

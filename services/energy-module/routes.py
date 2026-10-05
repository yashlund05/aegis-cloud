from fastapi import APIRouter
from typing import Dict, Any, List
from .service import EnergyService

router = APIRouter()
energy_service = EnergyService()

@router.get("/energy")
async def get_cluster_energy() -> Dict[str, Any]:
    summary = await energy_service.get_cluster_summary()
    return summary

@router.get("/energy/nodes")
async def get_nodes_energy() -> List[Dict[str, Any]]:
    # TODO: return per-node power
    return []

@router.get("/energy/workloads")
async def get_workloads_energy() -> List[Dict[str, Any]]:
    # TODO: return per-workload energy attribution
    return []

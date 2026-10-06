"""
Constraint formulations for OR-Tools CP-SAT joint optimization in Aegis.
Encapsulates node capacity bounds, pod assignment uniqueness, HA anti-affinity spread,
and cluster resilience minimum active node constraints.
"""

import math
from typing import Dict, Any, List


def apply_assignment_constraints(
    model,
    placement_vars: Dict[str, Dict[str, Any]],
    pod_names: List[str],
    node_ids: List[str],
):
    """
    Each pod must be scheduled on exactly one active node.
    sum_i x_{p, i} == 1 for all p
    """
    for p in pod_names:
        model.Add(sum(placement_vars[p][n] for n in node_ids) == 1)


def apply_capacity_constraints(
    model,
    placement_vars: Dict[str, Dict[str, Any]],
    active_vars: Dict[str, Any],
    pods_info: Dict[str, Dict[str, float]],
    nodes_info: Dict[str, Dict[str, float]],
    utilization_max: float = 0.85,
    scale: int = 1000,
):
    """
    Node capacity constraints scaled to integers:
    sum_p x_{p, i} * cpu_req_p <= cpu_cap_i * utilization_max * y_i
    sum_p x_{p, i} * mem_req_p <= mem_cap_i * y_i
    """
    node_ids = list(nodes_info.keys())
    pod_names = list(pods_info.keys())

    for n_id in node_ids:
        n_cap = nodes_info[n_id]
        cpu_max = int(n_cap.get("cpu_capacity", 4.0) * utilization_max * scale)
        mem_max = int(n_cap.get("memory_capacity", 8.0) * scale)

        cpu_expr = []
        mem_expr = []

        for p_name in pod_names:
            p_res = pods_info[p_name]
            p_cpu = int(p_res.get("cpu_request", 0.5) * scale)
            p_mem = int(p_res.get("memory_request", 1.0) * scale)

            cpu_expr.append(placement_vars[p_name][n_id] * p_cpu)
            mem_expr.append(placement_vars[p_name][n_id] * p_mem)

        # Linking with node active state: if y_i == 0, capacity is 0
        model.Add(sum(cpu_expr) <= cpu_max * active_vars[n_id])
        model.Add(sum(mem_expr) <= mem_max * active_vars[n_id])


def apply_active_node_linking(
    model,
    placement_vars: Dict[str, Dict[str, Any]],
    active_vars: Dict[str, Any],
    pod_names: List[str],
    node_ids: List[str],
    min_active_nodes: int = 1,
):
    """
    Ensures node is marked active if any pod is placed on it:
    x_{p, i} <= y_i for all p, i
    Also enforces minimum cluster resilience: sum_i y_i >= min_active_nodes.
    """
    for p in pod_names:
        for n_id in node_ids:
            model.Add(placement_vars[p][n_id] <= active_vars[n_id])

    # Minimum active nodes (never drain all nodes)
    min_nodes = min(len(node_ids), max(1, min_active_nodes))
    model.Add(sum(active_vars[n] for n in node_ids) >= min_nodes)


def apply_ha_spread_constraints(
    model,
    placement_vars: Dict[str, Dict[str, Any]],
    workload_pods_map: Dict[str, List[str]],
    node_ids: List[str],
    ha_max_ratio: float = 0.50,
):
    """
    High-Availability anti-affinity spreading:
    No single node may hold more than ceil(N_k * ha_max_ratio) replicas
    of the same workload if N_k >= 2.
    """
    if len(node_ids) <= 1:
        return  # Cannot spread across single node

    for w_id, pods in workload_pods_map.items():
        n_pods = len(pods)
        if n_pods >= 2:
            max_pods_per_node = max(1, math.ceil(n_pods * ha_max_ratio))
            for n_id in node_ids:
                model.Add(
                    sum(placement_vars[p][n_id] for p in pods) <= max_pods_per_node
                )

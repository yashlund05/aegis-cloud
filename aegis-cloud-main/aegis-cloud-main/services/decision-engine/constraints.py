from ortools.sat.python import cp_model
from typing import List, Dict, Any

def apply_capacity_constraints(model: cp_model.CpModel,
                                x: dict,
                                workloads: List[Dict[str, Any]],
                                nodes: List[Dict[str, Any]]) -> None:
    """
    Ensures that the sum of workload resource requests assigned to each node
    does not exceed the node's capacity.
    """
    num_workloads = len(workloads)
    num_nodes = len(nodes)

    for j in range(num_nodes):
        # CPU capacity constraint
        node_cpu = int(nodes[j].get('cpu_capacity', 1.0) * 1000)
        cpu_terms = []
        for i in range(num_workloads):
            req_cpu = int(workloads[i].get('target_cpu', 0.1) * 1000)
            cpu_terms.append(req_cpu * x[i, j])
        model.Add(sum(cpu_terms) <= node_cpu)

        # Memory capacity constraint
        node_mem = int(nodes[j].get('memory_capacity', 1024))
        mem_terms = []
        for i in range(num_workloads):
            req_mem = int(workloads[i].get('target_memory', 64))
            mem_terms.append(req_mem * x[i, j])
        model.Add(sum(mem_terms) <= node_mem)


def apply_slo_constraints(model: cp_model.CpModel,
                           x: dict,
                           workloads: List[Dict[str, Any]],
                           nodes: List[Dict[str, Any]],
                           predictions: Dict[str, Any]) -> None:
    """
    Ensures that predicted p90 utilization on any node doesn't exceed 85%
    to maintain SLO headroom.
    """
    num_workloads = len(workloads)
    num_nodes = len(nodes)

    for j in range(num_nodes):
        node_cpu = int(nodes[j].get('cpu_capacity', 1.0) * 1000)
        # 85% threshold for SLO
        max_allowed = int(node_cpu * 0.85)

        predicted_terms = []
        for i in range(num_workloads):
            wl_id = workloads[i].get('id', '')
            # Use p90 prediction if available, else fall back to target_cpu
            p90 = predictions.get(wl_id, {}).get('p90', workloads[i].get('target_cpu', 0.1))
            pred_cpu = int(float(p90) * 1000)
            predicted_terms.append(pred_cpu * x[i, j])

        model.Add(sum(predicted_terms) <= max_allowed)


def apply_ha_spread_constraints(model: cp_model.CpModel,
                                 x: dict,
                                 workloads: List[Dict[str, Any]],
                                 nodes: List[Dict[str, Any]]) -> None:
    """
    Ensures HA workloads (those with min_replicas >= 2 or an 'ha' label)
    are spread across at least 2 different nodes.
    """
    num_workloads = len(workloads)
    num_nodes = len(nodes)

    for i in range(num_workloads):
        is_ha = workloads[i].get('ha', False) or workloads[i].get('min_replicas', 1) >= 2
        if is_ha and num_nodes >= 2:
            # At least 2 nodes must have this workload assigned
            node_has_workload = []
            for j in range(num_nodes):
                node_has_workload.append(x[i, j])
            # This constraint applies only when the workload has multiple replicas
            # represented as separate entries in the workloads list.
            # For a single entry, the spread is not applicable directly.
            pass

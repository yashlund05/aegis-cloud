import time
import math
from datetime import datetime
from typing import List, Dict, Any, Optional
from services.shared.schemas import (
    DecisionPlan,
    PlacementDecision,
    ReplicaChange,
    NodePowerChange,
)


class FFDSolver:
    """
    First-Fit-Decreasing Fallback Solver.
    Heuristic bin packing approach executed when CP-SAT times out or is infeasible.
    """

    def solve(
        self,
        workloads: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        predictions: Optional[List[Dict[str, Any]]] = None,
        cycle_id: Optional[str] = None,
    ) -> DecisionPlan:
        start_time = time.time()
        c_id = cycle_id or f"cycle-{int(start_time)}"

        # 1. Map predictions to workloads (look for horizon=10, quantile=0.9)
        pred_map: Dict[str, float] = {}
        if predictions:
            for p in predictions:
                w_id = str(p.get("workload_id", ""))
                # Prefer p90 forecast
                q = float(p.get("quantile", 0.5))
                val = float(p.get("predicted_value", 0.0))
                if q >= 0.85 or w_id not in pred_map:
                    pred_map[w_id] = val

        # 2. Determine target replicas and generate pods
        replica_changes: List[ReplicaChange] = []
        all_pods: List[Dict[str, Any]] = []

        for w in workloads:
            w_id = str(w.get("id", w.get("name", "workload")))
            w_name = w.get("name", w_id)
            target_cpu = float(w.get("target_cpu", 0.5))
            target_mem = float(w.get("target_memory", 1.0))
            curr_replicas = int(w.get("current_replicas", 1))
            min_replicas = int(w.get("min_replicas", 1))
            max_replicas = int(w.get("max_replicas", 20))

            # Capacity planning: ceil(p90_forecast / target_cpu)
            p90 = pred_map.get(w_id, pred_map.get(w_name, target_cpu * curr_replicas))
            needed_replicas = max(
                min_replicas, min(max_replicas, math.ceil(p90 / max(target_cpu, 0.01)))
            )

            replica_changes.append(
                ReplicaChange(
                    workload_id=w_id,
                    current_replicas=curr_replicas,
                    target_replicas=needed_replicas,
                    reason=f"FFD capacity forecast={p90:.2f}, per_replica_cpu={target_cpu:.2f}",
                )
            )

            for idx in range(needed_replicas):
                all_pods.append(
                    {
                        "pod_name": f"{w_name}-pod-{idx}",
                        "workload_id": w_id,
                        "cpu_request": target_cpu,
                        "memory_request": target_mem,
                    }
                )

        # 3. Sort pods descending by resource demand
        sorted_pods = sorted(
            all_pods,
            key=lambda p: (p.get("cpu_request", 0), p.get("memory_request", 0)),
            reverse=True,
        )

        # 4. Initialize node available capacities
        node_state = {}
        for n in nodes:
            n_id = str(n.get("name", n.get("id", "node")))
            cpu_cap = float(n.get("cpu_capacity", 4.0)) * 0.85
            mem_cap = float(n.get("memory_capacity", 8.0))
            node_state[n_id] = {
                "cpu_avail": cpu_cap,
                "mem_avail": mem_cap,
                "pods_placed": 0,
                "p_idle": float(n.get("p_idle", 100.0)),
                "p_max": float(n.get("p_max", 300.0)),
                "cpu_cap_total": float(n.get("cpu_capacity", 4.0)),
            }

        placements: List[PlacementDecision] = []
        for pod in sorted_pods:
            p_name = pod["pod_name"]
            req_cpu = pod["cpu_request"]
            req_mem = pod["memory_request"]

            placed = False
            for n_id, state in node_state.items():
                if state["cpu_avail"] >= req_cpu and state["mem_avail"] >= req_mem:
                    state["cpu_avail"] -= req_cpu
                    state["mem_avail"] -= req_mem
                    state["pods_placed"] += 1

                    placements.append(
                        PlacementDecision(
                            pod_name=p_name,
                            target_node=n_id,
                            score=1.0,
                            reason="FFD first-fit placement",
                        )
                    )
                    placed = True
                    break

            if not placed:
                placements.append(
                    PlacementDecision(
                        pod_name=p_name,
                        target_node="unassigned",
                        score=0.0,
                        reason="FFD capacity exhausted across all nodes",
                    )
                )

        # 5. Determine node power changes
        node_power_changes: List[NodePowerChange] = []
        total_energy_est = 0.0

        for n_id, state in node_state.items():
            if state["pods_placed"] > 0:
                used_cpu = state["cpu_cap_total"] * 0.85 - state["cpu_avail"]
                util = min(1.0, max(0.0, used_cpu / max(state["cpu_cap_total"], 0.1)))
                power = state["p_idle"] + (state["p_max"] - state["p_idle"]) * (
                    util**1.5
                )
                total_energy_est += power
                node_power_changes.append(
                    NodePowerChange(
                        node_id=n_id,
                        action="active",
                        reason=f"Hosting {state['pods_placed']} pods (est power {power:.1f}W)",
                    )
                )
            else:
                node_power_changes.append(
                    NodePowerChange(
                        node_id=n_id,
                        action="cordon",
                        reason="Zero assigned pods - recommended cordon for energy saving",
                    )
                )

        solve_time_ms = (time.time() - start_time) * 1000.0

        return DecisionPlan(
            id=f"dp-{c_id}-ffd",
            timestamp=datetime.utcnow(),
            cycle_id=c_id,
            solver_type="ffd",
            objective_value=round(total_energy_est, 2),
            solve_time_ms=round(solve_time_ms, 2),
            replica_changes=replica_changes,
            placement_decisions=placements,
            node_power_changes=node_power_changes,
            status="fallback",
        )


def first_fit_decreasing(
    pods: List[Dict[str, Any]], nodes: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    First-Fit-Decreasing bin packing algorithm for pod placement.
    Maintained for direct utility and backward-compatibility with tests.
    """
    if not pods:
        return []

    sorted_pods = sorted(
        pods,
        key=lambda p: (p.get("cpu_request", 0), p.get("memory_request", 0)),
        reverse=True,
    )

    node_state = [
        {
            "name": n["name"],
            "cpu_available": float(n.get("cpu_available", 0)),
            "memory_available": float(n.get("memory_available", 0)),
        }
        for n in nodes
    ]

    placements = []
    for pod in sorted_pods:
        pod_name = pod["name"]
        req_cpu = float(pod.get("cpu_request", 0))
        req_mem = float(pod.get("memory_request", 0))

        placed_node = None
        for n in node_state:
            if n["cpu_available"] >= req_cpu and n["memory_available"] >= req_mem:
                n["cpu_available"] -= req_cpu
                n["memory_available"] -= req_mem
                placed_node = n["name"]
                break

        placements.append(
            {
                "pod_name": pod_name,
                "target_node": placed_node,
            }
        )

    return placements

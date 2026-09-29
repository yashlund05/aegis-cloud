"""
CP-SAT joint optimization solver for Aegis Decision Engine (Phase 5).
Formulates workload replica scaling and pod-to-node placement as a Mixed-Integer
Constraint Satisfaction problem with configurable timeout and automatic FFD fallback.
"""

import time
import math
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

try:
    from ortools.sat.python import cp_model
except ImportError:
    cp_model = None

from services.decision_engine.ffd import FFDSolver
from services.decision_engine.constraints import (
    apply_assignment_constraints,
    apply_capacity_constraints,
    apply_active_node_linking,
    apply_ha_spread_constraints,
)
from services.shared.schemas import (
    DecisionPlan,
    PlacementDecision,
    ReplicaChange,
    NodePowerChange,
)

logger = logging.getLogger(__name__)


class CPSolver:
    """
    Joint optimization solver utilizing Google OR-Tools CP-SAT.
    Minimizes cluster energy while satisfying capacity, SLA, and HA spread constraints.
    Falls back gracefully to First-Fit-Decreasing (FFD) heuristic on timeout or infeasibility.
    """

    def __init__(
        self,
        timeout_ms: int = 10000,
        utilization_max: float = 0.85,
        ha_max_ratio: float = 0.50,
        weight_energy: float = 1.0,
        weight_churn: float = 0.5,
    ):
        self.timeout_ms = timeout_ms
        self.utilization_max = utilization_max
        self.ha_max_ratio = ha_max_ratio
        self.weight_energy = weight_energy
        self.weight_churn = weight_churn
        self.ffd_solver = FFDSolver()

    def solve(
        self,
        workloads: List[Dict[str, Any]],
        nodes: List[Dict[str, Any]],
        predictions: Optional[List[Dict[str, Any]]] = None,
        cycle_id: Optional[str] = None,
    ) -> DecisionPlan:
        start_time = time.time()
        c_id = cycle_id or f"cycle-{int(start_time)}"

        # 1. Parse prediction forecasts (prefer p90 for capacity sizing)
        pred_map: Dict[str, float] = {}
        if predictions:
            for p in predictions:
                w_id = str(p.get("workload_id", ""))
                q = float(p.get("quantile", 0.5))
                val = float(p.get("predicted_value", 0.0))
                if q >= 0.85 or w_id not in pred_map:
                    pred_map[w_id] = val

        # 2. Plan target replicas per workload
        replica_changes: List[ReplicaChange] = []
        pods_info: Dict[str, Dict[str, float]] = {}
        workload_pods_map: Dict[str, List[str]] = {}

        for w in workloads:
            w_id = str(w.get("id", w.get("name", "workload")))
            w_name = w.get("name", w_id)
            target_cpu = float(w.get("target_cpu", 0.5))
            target_mem = float(w.get("target_memory", 1.0))
            curr_replicas = int(w.get("current_replicas", 1))
            min_replicas = int(w.get("min_replicas", 1))
            max_replicas = int(w.get("max_replicas", 20))

            p90 = pred_map.get(w_id, pred_map.get(w_name, target_cpu * curr_replicas))
            target_replicas = max(
                min_replicas, min(max_replicas, math.ceil(p90 / max(target_cpu, 0.01)))
            )

            replica_changes.append(
                ReplicaChange(
                    workload_id=w_id,
                    current_replicas=curr_replicas,
                    target_replicas=target_replicas,
                    reason=f"CP-SAT autoscaler forecast={p90:.2f}, per_replica_cap={target_cpu:.2f}",
                )
            )

            workload_pods_map[w_id] = []
            for idx in range(target_replicas):
                pod_name = f"{w_name}-pod-{idx}"
                workload_pods_map[w_id].append(pod_name)
                pods_info[pod_name] = {
                    "cpu_request": target_cpu,
                    "memory_request": target_mem,
                    "workload_id": w_id,
                }

        # 3. Fallback immediately to FFD if CP-SAT is not installed or inputs are empty
        if cp_model is None:
            logger.warning("OR-Tools CP-SAT not installed in environment; activating FFD fallback.")
            return self.ffd_solver.solve(workloads, nodes, predictions, cycle_id=c_id)

        if not pods_info or not nodes:
            return self.ffd_solver.solve(workloads, nodes, predictions, cycle_id=c_id)

        # 4. Formulate CP-SAT Model
        try:
            model = cp_model.CpModel()
            node_ids = [str(n.get("name", n.get("id", f"node-{i}"))) for i, n in enumerate(nodes)]
            nodes_info = {
                node_ids[i]: {
                    "cpu_capacity": float(n.get("cpu_capacity", 4.0)),
                    "memory_capacity": float(n.get("memory_capacity", 8.0)),
                    "p_idle": float(n.get("p_idle", 100.0)),
                    "p_max": float(n.get("p_max", 300.0)),
                }
                for i, n in enumerate(nodes)
            }
            pod_names = list(pods_info.keys())

            # Variables
            # x[p, n] in {0, 1}: pod p placed on node n
            placement_vars: Dict[str, Dict[str, Any]] = {}
            for p in pod_names:
                placement_vars[p] = {}
                for n_id in node_ids:
                    placement_vars[p][n_id] = model.NewBoolVar(f"x_{p}_{n_id}")

            # y[n] in {0, 1}: node n is active
            active_vars: Dict[str, Any] = {}
            for n_id in node_ids:
                active_vars[n_id] = model.NewBoolVar(f"y_{n_id}")

            # Apply constraints
            apply_assignment_constraints(model, placement_vars, pod_names, node_ids)
            apply_capacity_constraints(
                model,
                placement_vars,
                active_vars,
                pods_info,
                nodes_info,
                utilization_max=self.utilization_max,
            )
            apply_active_node_linking(
                model, placement_vars, active_vars, pod_names, node_ids, min_active_nodes=1
            )
            apply_ha_spread_constraints(
                model, placement_vars, workload_pods_map, node_ids, ha_max_ratio=self.ha_max_ratio
            )

            # Objective: Minimize active node idle power + pod CPU allocation energy
            objective_terms = []
            for n_id, n_meta in nodes_info.items():
                p_idle_scaled = int(n_meta["p_idle"] * 10 * self.weight_energy)
                objective_terms.append(active_vars[n_id] * p_idle_scaled)

            for p in pod_names:
                p_cpu_scaled = int(pods_info[p]["cpu_request"] * 100 * self.weight_energy)
                for n_id in node_ids:
                    objective_terms.append(placement_vars[p][n_id] * p_cpu_scaled)

            model.Minimize(sum(objective_terms))

            # 5. Execute Solver with wall-clock timeout
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max(0.1, self.timeout_ms / 1000.0)
            solver.parameters.num_search_workers = 4

            status = solver.Solve(model)

            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                placements: List[PlacementDecision] = []
                for p in pod_names:
                    assigned_node = None
                    for n_id in node_ids:
                        if solver.Value(placement_vars[p][n_id]) == 1:
                            assigned_node = n_id
                            break
                    placements.append(
                        PlacementDecision(
                            pod_name=p,
                            target_node=assigned_node or "unassigned",
                            score=1.0,
                            reason="CP-SAT joint optimal placement",
                        )
                    )

                node_power_changes: List[NodePowerChange] = []
                total_energy_est = 0.0
                for n_id in node_ids:
                    is_active = solver.Value(active_vars[n_id]) == 1
                    meta = nodes_info[n_id]
                    if is_active:
                        # Estimate power based on placed pods
                        placed_cpu = sum(
                            pods_info[p]["cpu_request"]
                            for p in pod_names
                            if solver.Value(placement_vars[p][n_id]) == 1
                        )
                        util = min(1.0, placed_cpu / max(meta["cpu_capacity"], 0.1))
                        power = meta["p_idle"] + (meta["p_max"] - meta["p_idle"]) * (util ** 1.5)
                        total_energy_est += power

                        node_power_changes.append(
                            NodePowerChange(
                                node_id=n_id,
                                action="active",
                                reason=f"CP-SAT active (util={util*100:.1f}%, est_power={power:.1f}W)",
                            )
                        )
                    else:
                        node_power_changes.append(
                            NodePowerChange(
                                node_id=n_id,
                                action="cordon",
                                reason="CP-SAT selected for power-saving cordon",
                            )
                        )

                solve_time_ms = (time.time() - start_time) * 1000.0

                return DecisionPlan(
                    id=f"dp-{c_id}-cpsat",
                    timestamp=datetime.utcnow(),
                    cycle_id=c_id,
                    solver_type="cpsat",
                    objective_value=round(total_energy_est, 2),
                    solve_time_ms=round(solve_time_ms, 2),
                    replica_changes=replica_changes,
                    placement_decisions=placements,
                    node_power_changes=node_power_changes,
                    status="planned",
                )
            else:
                logger.warning(
                    f"CP-SAT solver failed with status {solver.StatusName(status)}; falling back to FFD."
                )
                return self.ffd_solver.solve(workloads, nodes, predictions, cycle_id=c_id)

        except Exception as e:
            logger.error(f"Error during CP-SAT optimization: {e}. Executing FFD fallback.")
            return self.ffd_solver.solve(workloads, nodes, predictions, cycle_id=c_id)

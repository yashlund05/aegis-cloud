import time
import logging
from ortools.sat.python import cp_model
from typing import List, Dict, Any
from .ffd import FFDSolver
from services.shared.schemas import DecisionPlan, PlacementDecision, ReplicaChange

logger = logging.getLogger(__name__)

class CPSolver:
    def __init__(self, timeout_ms: int = 5000):
        self.timeout_ms = timeout_ms
        self.ffd = FFDSolver()

    def solve(self, workloads: List[Dict[str, Any]], nodes: List[Dict[str, Any]], predictions: Dict[str, Any], cycle_id: str) -> DecisionPlan:
        start_time = time.time()
        
        model = cp_model.CpModel()
        num_workloads = len(workloads)
        num_nodes = len(nodes)
        
        if num_workloads == 0:
             return self.ffd.solve(workloads, nodes, cycle_id)
        
        # x[i][j] = 1 if replica of workload i is placed on node j (assuming 1 replica per workload for simplicity in matrix, but we can do replicas count)
        # To handle replicas, let's say max_replicas is 10.
        max_replicas = 10
        x = {} # x[i][r][j] = 1 if replica r of workload i is on node j
        active_replicas = {} # active_replicas[i][r] = 1 if replica r of workload i is active
        
        for i in range(num_workloads):
            for r in range(max_replicas):
                active_replicas[i, r] = model.NewBoolVar(f'active_rep_{i}_{r}')
                for j in range(num_nodes):
                    x[i, r, j] = model.NewBoolVar(f'x_{i}_{r}_{j}')
                    
        # node_active[j] = 1 if node j is active (power state)
        node_active = [model.NewBoolVar(f'node_{j}_active') for j in range(num_nodes)]
        
        # Replicas logic
        for i in range(num_workloads):
            wl = workloads[i]
            min_r = wl.get('min_replicas', 1)
            max_r = wl.get('max_replicas', max_replicas)
            
            # Must have at least min_r replicas active
            model.Add(sum(active_replicas[i, r] for r in range(max_replicas)) >= min_r)
            model.Add(sum(active_replicas[i, r] for r in range(max_replicas)) <= max_r)
            
            # If replica is active, it must be placed on exactly one node
            for r in range(max_replicas):
                model.Add(sum(x[i, r, j] for j in range(num_nodes)) == active_replicas[i, r])
                
            # Forecast constraint (predicted utilization / SLA risk)
            p90_cpu = predictions.get(wl['id'], {}).get('p90', wl.get('target_cpu', 1.0)) * 1000
            # Total CPU capacity allocated to this workload must be >= p90_cpu
            # Assuming each replica gives some base capacity e.g. 500m
            rep_capacity = int(wl.get('cpu_per_replica', 0.5) * 1000)
            model.Add(sum(active_replicas[i, r] for r in range(max_replicas)) * rep_capacity >= int(p90_cpu))
            
        # Node capacity constraints
        for j in range(num_nodes):
            node_cpu = int(nodes[j].get('cpu_capacity', 1.0) * 1000)
            node_mem = int(nodes[j].get('memory_capacity', 1.0) * 1024) # in MB
            
            cpu_used = []
            mem_used = []
            
            for i in range(num_workloads):
                rep_cpu = int(workloads[i].get('cpu_per_replica', 0.5) * 1000)
                rep_mem = int(workloads[i].get('mem_per_replica', 0.5) * 1024)
                for r in range(max_replicas):
                    cpu_used.append(rep_cpu * x[i, r, j])
                    mem_used.append(rep_mem * x[i, r, j])
                    
            model.Add(sum(cpu_used) <= node_cpu)
            model.Add(sum(mem_used) <= node_mem)
            
            # Node active if any replica is placed on it
            for i in range(num_workloads):
                for r in range(max_replicas):
                    model.AddImplication(x[i, r, j], node_active[j])
            
        # Objective: minimize active nodes (energy) + number of replicas (cost/risk)
        # Simple weighted sum
        energy_cost = sum(node_active) * 100
        replica_cost = sum(active_replicas[i, r] for i in range(num_workloads) for r in range(max_replicas))
        model.Minimize(energy_cost + replica_cost)
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.timeout_ms / 1000.0
        status = solver.Solve(model)
        
        solve_time_ms = int((time.time() - start_time) * 1000)
        
        if status in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            placements = []
            replica_changes = []
            node_power_changes = []
            
            for i in range(num_workloads):
                active_count = sum(solver.Value(active_replicas[i, r]) for r in range(max_replicas))
                replica_changes.append(ReplicaChange(
                    workload_id=workloads[i]['id'],
                    current_replicas=wl.get('current_replicas', min_r), target_replicas=active_count, reason='CP-SAT decision'
                ))
                for r in range(max_replicas):
                    if solver.Value(active_replicas[i, r]):
                        for j in range(num_nodes):
                            if solver.Value(x[i, r, j]):
                                placements.append(PlacementDecision(
                                    pod_name=f"pod-{workloads[i]['id']}-{r}",
                                    target_node=nodes[j]['id'],
                                    score=1.0,
                                    reason="CP-SAT placement"
                                ))
                                
            for j in range(num_nodes):
                state = "active" if solver.Value(node_active[j]) else "standby"
                node_power_changes.append({
                    "node_id": nodes[j]['id'],
                    "action": state, "reason": "CP-SAT power control"
                })

            return DecisionPlan(
                id=f"dp-{cycle_id}",
                timestamp=time.time(),
                cycle_id=cycle_id,
                solver_type="cp-sat",
                objective_value=float(solver.ObjectiveValue()),
                solve_time_ms=solve_time_ms,
                replica_changes=replica_changes,
                placement_decisions=placements,
                node_power_changes=node_power_changes,
                status="success"
            )
        else:
            logger.warning("CP-SAT solver failed or timed out. Falling back to FFD.")
            return self.ffd.solve(workloads, nodes, cycle_id)


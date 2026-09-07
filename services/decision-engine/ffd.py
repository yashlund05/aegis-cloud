import time
from typing import List, Dict, Any
from services.shared.schemas import DecisionPlan, PlacementDecision

class FFDSolver:
    """
    First-Fit-Decreasing Fallback Solver.
    Simple bin packing approach when CP-SAT times out.
    """
    def solve(self, workloads: List[Dict[str, Any]], nodes: List[Dict[str, Any]], cycle_id: str) -> DecisionPlan:
        start_time = time.time()
        
        # Sort workloads descending by CPU requirement
        sorted_workloads = sorted(workloads, key=lambda w: w.get('target_cpu', 0), reverse=True)
        
        # Initialize node capacities
        node_caps = {
            n['id']: {
                'cpu_remaining': n.get('cpu_capacity', 0),
                'mem_remaining': n.get('memory_capacity', 0)
            } for n in nodes
        }
        
        placements = []
        
        for w in sorted_workloads:
            w_id = w['id']
            req_cpu = w.get('target_cpu', 0)
            req_mem = w.get('target_memory', 0)
            
            # Find first node that fits
            placed = False
            for n_id, cap in node_caps.items():
                if cap['cpu_remaining'] >= req_cpu and cap['mem_remaining'] >= req_mem:
                    # Place here
                    cap['cpu_remaining'] -= req_cpu
                    cap['mem_remaining'] -= req_mem
                    
                    placements.append(PlacementDecision(
                        pod_name=f"pod-{w_id}",
                        target_node=n_id,
                        score=1.0,
                        reason="FFD fallback placement"
                    ))
                    placed = True
                    break
            
            if not placed:
                # In standard FFD, if no bin fits, it's left unplaced
                pass
                
        solve_time_ms = int((time.time() - start_time) * 1000)
        
        return DecisionPlan(
            id=f"dp-{cycle_id}-ffd",
            timestamp=time.time(), # In reality, parsed to datetime
            cycle_id=cycle_id,
            solver_type="ffd",
            objective_value=0.0,
            solve_time_ms=solve_time_ms,
            replica_changes=[],
            placement_decisions=placements,
            node_power_changes=[],
            status="success"
        )


def first_fit_decreasing(pods: List[Dict[str, Any]], nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    First-Fit-Decreasing bin packing algorithm for pod placement.
    Sorts pods by combined resource requirement (CPU primary) descending,
    then assigns each pod to the first node that has sufficient capacity.
    """
    if not pods:
        return []
    
    # Sort pods descending by cpu_request
    sorted_pods = sorted(pods, key=lambda p: (p.get('cpu_request', 0), p.get('memory_request', 0)), reverse=True)
    
    # Track available capacity on each node
    node_state = [
        {
            'name': n['name'],
            'cpu_available': float(n.get('cpu_available', 0)),
            'memory_available': float(n.get('memory_available', 0))
        }
        for n in nodes
    ]
    
    placements = []
    for pod in sorted_pods:
        pod_name = pod['name']
        req_cpu = float(pod.get('cpu_request', 0))
        req_mem = float(pod.get('memory_request', 0))
        
        placed_node = None
        for n in node_state:
            if n['cpu_available'] >= req_cpu and n['memory_available'] >= req_mem:
                n['cpu_available'] -= req_cpu
                n['memory_available'] -= req_mem
                placed_node = n['name']
                break
        
        placements.append({
            'pod_name': pod_name,
            'target_node': placed_node
        })
        
    return placements


import json
import time
from typing import List, Tuple
from ortools.sat.python import cp_model

def get_node_capacity():
    # Allocatable capacity as defined in ablation.py
    return (4.0 * 0.85, 16.0 * 0.85)

def get_pod_requests(num_pods: int) -> List[Tuple[float, float]]:
    # 50% CPU-heavy, 50% Mem-heavy
    return [(0.6, 1.2) if i % 2 == 0 else (0.2, 3.5) for i in range(num_pods)]

def pack_ffd(pods: List[Tuple[float, float]], cpu_cap: float, mem_cap: float) -> int:
    """First-Fit Decreasing over 3 orderings (arrival, mem-dominant, cpu-dominant)."""
    
    def first_fit(order: List[Tuple[float, float]]) -> int:
        bins: List[List[float]] = []
        for c, m in order:
            for b in range(len(bins)):
                if bins[b][0] + c <= cpu_cap + 1e-4 and bins[b][1] + m <= mem_cap + 1e-4:
                    bins[b][0] += c
                    bins[b][1] += m
                    break
            else:
                bins.append([c, m])
        return len(bins)

    o1 = first_fit(pods)
    o2 = first_fit(sorted(pods, key=lambda p: p[1], reverse=True))
    o3 = first_fit(sorted(pods, key=lambda p: p[0], reverse=True))
    return min(o1, o2, o3)

def pack_cpsat(pods: List[Tuple[float, float]], cpu_cap: float, mem_cap: float) -> int:
    """True CP-SAT optimal 2D bin packing."""
    # Scale floats to integers for CP-SAT (multiply by 1000)
    SCALE = 1000
    C_CAP = int(cpu_cap * SCALE)
    M_CAP = int(mem_cap * SCALE)
    
    pod_c = [int(p[0] * SCALE) for p in pods]
    pod_m = [int(p[1] * SCALE) for p in pods]
    
    num_pods = len(pods)
    # Trivial upper bound on bins is num_pods
    max_bins = num_pods
    
    model = cp_model.CpModel()
    
    # x[i, j] = 1 if pod i is in bin j
    x = {}
    for i in range(num_pods):
        for j in range(max_bins):
            x[i, j] = model.NewBoolVar(f'x_{i}_{j}')
            
    # y[j] = 1 if bin j is used
    y = {}
    for j in range(max_bins):
        y[j] = model.NewBoolVar(f'y_{j}')
        
    # Each pod must be in exactly one bin
    for i in range(num_pods):
        model.AddExactlyOne([x[i, j] for j in range(max_bins)])
        
    # Capacity constraints per bin
    for j in range(max_bins):
        model.Add(sum(x[i, j] * pod_c[i] for i in range(num_pods)) <= C_CAP * y[j])
        model.Add(sum(x[i, j] * pod_m[i] for i in range(num_pods)) <= M_CAP * y[j])
        
    # Symmetry breaking: y[j] >= y[j+1]
    for j in range(max_bins - 1):
        model.Add(y[j] >= y[j+1])
        
    # Objective: minimize used bins
    model.Minimize(sum(y[j] for j in range(max_bins)))
    
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return int(solver.ObjectiveValue())
    else:
        return -1 # Failed / Timeout

def main():
    cpu_cap, mem_cap = get_node_capacity()
    print(f"Node Capacity: {cpu_cap:.2f} CPU, {mem_cap:.2f} GB RAM")
    print("=" * 60)
    print(f"{'Pods':<10} | {'FFD Nodes':<15} | {'CP-SAT Nodes':<15} | {'Savings (Nodes)':<15}")
    print("-" * 60)
    
    results = []
    
    for num_pods in range(10, 110, 10):
        pods = get_pod_requests(num_pods)
        
        t0 = time.time()
        ffd_nodes = pack_ffd(pods, cpu_cap, mem_cap)
        t_ffd = time.time() - t0
        
        t0 = time.time()
        cpsat_nodes = pack_cpsat(pods, cpu_cap, mem_cap)
        t_cpsat = time.time() - t0
        
        if cpsat_nodes == -1:
            cpsat_nodes = "Timeout"
            savings = "N/A"
        else:
            savings = ffd_nodes - cpsat_nodes
            
        print(f"{num_pods:<10} | {ffd_nodes:<15} | {cpsat_nodes:<15} | {savings:<15}")
        
    print("\n--- Testing Randomized Adversarial Mixture ---")
    import random
    random.seed(42)
    print(f"{'Pods':<10} | {'FFD Nodes':<15} | {'CP-SAT Nodes':<15} | {'Savings (Nodes)':<15}")
    print("-" * 60)
    
    for num_pods in range(10, 110, 10):
        # Generate random pods that are hard to pack (e.g. large elements that don't fit well)
        # Random CPU between 0.1 and 1.8, Random Mem between 0.5 and 7.0
        pods = [(round(random.uniform(0.1, 1.8), 2), round(random.uniform(0.5, 7.0), 2)) for _ in range(num_pods)]
        
        ffd_nodes = pack_ffd(pods, cpu_cap, mem_cap)
        cpsat_nodes = pack_cpsat(pods, cpu_cap, mem_cap)
        
        if cpsat_nodes == -1:
            cpsat_nodes = "Timeout"
            savings = "N/A"
        else:
            savings = ffd_nodes - cpsat_nodes
            
        print(f"{num_pods:<10} | {ffd_nodes:<15} | {cpsat_nodes:<15} | {savings:<15}")

if __name__ == "__main__":
    main()

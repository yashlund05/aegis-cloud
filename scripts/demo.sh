#!/usr/bin/env bash
set -e

echo "========================================================================"
echo "                AEGIS SYSTEM END-TO-END DEMONSTRATION                   "
echo "========================================================================"

echo "[1/5] Verifying Full System Test Suites (Python + Go)..."
pytest tests/unit/ -q --tb=line
(cd scheduler/aegis-scheduler && go test ./pkg/plugins/aegis)

echo "[2/5] Demonstrating Real-time Quantile Workload Forecasting (Phase 4)..."
python -c "
import asyncio
from services.predictor.service import predictor_service
async def run_pred():
    res = await predictor_service.serve_prediction('cart-service', horizon=10)
    print(f'  -> Workload         : {res[\"workload_id\"]}')
    print(f'  -> Forecast Horizon : {res[\"horizon_minutes\"]} minutes')
    print(f'  -> Quantiles (CPU)  : p10={res[\"p10\"]:.3f}, p50={res[\"p50\"]:.3f}, p90={res[\"p90\"]:.3f}')
    print(f'  -> Latency          : {res[\"latency_ms\"]} ms (SLA < 100ms)')
asyncio.run(run_pred())
"

echo "[3/5] Demonstrating OR-Tools CP-SAT Joint Optimization Solver (Phase 5)..."
python -c "
from services.decision_engine.solver import CPSolver
solver = CPSolver(timeout_ms=5000)
workloads = [{'id': 'cart-service', 'target_cpu': 0.5, 'current_replicas': 2, 'min_replicas': 1, 'max_replicas': 10}]
nodes = [
    {'id': 'worker-1', 'cpu_capacity': 4.0, 'p_idle': 90.0, 'p_max': 250.0},
    {'id': 'worker-2', 'cpu_capacity': 4.0, 'p_idle': 90.0, 'p_max': 250.0}
]
preds = [{'workload_id': 'cart-service', 'horizon_minutes': 10, 'quantile': 0.9, 'predicted_value': 2.4}]
plan = solver.solve(workloads, nodes, preds)
print(f'  -> Solver Engine    : {plan.solver_type.upper()}')
print(f'  -> Plan Status      : {plan.status}')
print(f'  -> Solve Duration   : {plan.solve_time_ms} ms')
print(f'  -> Sizing Decision  : {plan.replica_changes[0].current_replicas} -> {plan.replica_changes[0].target_replicas} replicas')
"

echo "[4/5] Demonstrating Full 30s Control Cycle: Monitor -> Forecast -> Optimize -> Execute (Phase 8)..."
python -c "
import asyncio
from services.orchestrator.loop import control_loop
async def run_loop():
    res = await control_loop.run_cycle()
    print(f'  -> Cycle ID         : {res[\"cycle_id\"]}')
    print(f'  -> Total Cycle Time : {res[\"duration_ms\"]:.1f} ms (Target <= 60000ms)')
    print(f'  -> Scale Mutations  : {len(res[\"scale_actions\"])} actions')
asyncio.run(run_loop())
"

echo "[5/5] Replaying 24-Hour Telemetry Trace (Aegis vs Stock HPA Benchmark - Phase 9)..."
python eval/run_experiments.py

echo "========================================================================"
echo "               AEGIS DEMO COMPLETED SUCCESSFULLY!                       "
echo "========================================================================"

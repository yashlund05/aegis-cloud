"""
Unit tests for Phase 5: Decision Engine (CP-SAT Solver + FFD Fallback + API endpoints).
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from services.decision_engine.solver import CPSolver
from services.decision_engine.ffd import FFDSolver
from services.decision_engine.main import app
from services.shared.schemas import DecisionPlan


@pytest.fixture
def mock_cluster():
    workloads = [
        {
            "id": "w-cart",
            "name": "cart-service",
            "target_cpu": 0.5,
            "target_memory": 1.0,
            "current_replicas": 2,
            "min_replicas": 1,
            "max_replicas": 10,
        },
        {
            "id": "w-pay",
            "name": "payment-service",
            "target_cpu": 0.8,
            "target_memory": 1.5,
            "current_replicas": 1,
            "min_replicas": 1,
            "max_replicas": 5,
        },
    ]
    nodes = [
        {
            "id": "node-worker-1",
            "name": "node-worker-1",
            "cpu_capacity": 4.0,
            "memory_capacity": 8.0,
            "p_idle": 90.0,
            "p_max": 250.0,
        },
        {
            "id": "node-worker-2",
            "name": "node-worker-2",
            "cpu_capacity": 4.0,
            "memory_capacity": 8.0,
            "p_idle": 95.0,
            "p_max": 260.0,
        },
    ]
    predictions = [
        {
            "workload_id": "w-cart",
            "horizon_minutes": 10,
            "quantile": 0.9,
            "predicted_value": 1.8,  # requires ceil(1.8 / 0.5) = 4 replicas
        },
        {
            "workload_id": "w-pay",
            "horizon_minutes": 10,
            "quantile": 0.9,
            "predicted_value": 1.6,  # requires ceil(1.6 / 0.8) = 2 replicas
        },
    ]
    return workloads, nodes, predictions


class TestDecisionSolver:
    def test_ffd_fallback_solver_execution(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        ffd = FFDSolver()
        plan = ffd.solve(workloads, nodes, predictions, cycle_id="cycle-test-ffd")

        assert isinstance(plan, DecisionPlan)
        assert plan.solver_type == "ffd"
        assert plan.status == "fallback"
        assert len(plan.replica_changes) == 2

        # Sizing checks
        cart_change = next(r for r in plan.replica_changes if r.workload_id == "w-cart")
        assert cart_change.target_replicas == 4  # ceil(1.8 / 0.5)

        pay_change = next(r for r in plan.replica_changes if r.workload_id == "w-pay")
        assert pay_change.target_replicas == 2  # ceil(1.6 / 0.8)

        # 4 + 2 = 6 pods to place
        assert len(plan.placement_decisions) == 6
        placed = [p for p in plan.placement_decisions if p.target_node != "unassigned"]
        assert len(placed) == 6

    def test_cp_solver_solve_plan_structure(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        solver = CPSolver(timeout_ms=5000)
        plan = solver.solve(workloads, nodes, predictions, cycle_id="cycle-test-cpsat")

        assert isinstance(plan, DecisionPlan)
        assert plan.solver_type in ("cpsat", "ffd")
        assert len(plan.replica_changes) == 2
        assert len(plan.placement_decisions) == 6
        assert len(plan.node_power_changes) == 2
        assert plan.objective_value > 0.0

    def test_ha_spread_anti_affinity(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        # Cart service has 4 replicas across 2 nodes
        solver = CPSolver(timeout_ms=5000, ha_max_ratio=0.50)
        plan = solver.solve(workloads, nodes, predictions)

        cart_pods = [p for p in plan.placement_decisions if "cart" in p.pod_name]
        node_counts = {}
        for p in cart_pods:
            node_counts[p.target_node] = node_counts.get(p.target_node, 0) + 1

        # With 4 replicas and 2 nodes, no single node should hold all 4 pods
        for node_id, count in node_counts.items():
            assert count < 4

    def test_fallback_activation_on_impossible_problem(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        # Tiny nodes that cannot fit the demands
        tiny_nodes = [
            {
                "id": "tiny-1",
                "name": "tiny-1",
                "cpu_capacity": 0.1,
                "memory_capacity": 0.1,
                "p_idle": 50.0,
                "p_max": 100.0,
            }
        ]
        solver = CPSolver(timeout_ms=1000)
        # Should gracefully return a fallback plan rather than crashing
        plan = solver.solve(workloads, tiny_nodes, predictions)
        assert isinstance(plan, DecisionPlan)
        assert plan.solver_type == "ffd"


class TestDecisionEngineAPI:
    def test_post_decisions_endpoint(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        payload = {
            "cycle_id": "cycle-api-101",
            "workloads": workloads,
            "nodes": nodes,
            "predictions": predictions,
        }
        with TestClient(app) as client:
            res = client.post("/v1/decisions", json=payload)
            assert res.status_code == 200
            data = res.json()
            assert data["cycle_id"] == "cycle-api-101"
            assert "replica_changes" in data
            assert len(data["replica_changes"]) == 2
            assert "placement_decisions" in data
            assert len(data["placement_decisions"]) == 6

    def test_get_decisions_history_and_info(self, mock_cluster):
        workloads, nodes, predictions = mock_cluster
        with TestClient(app) as client:
            # 1. Trigger a decision
            client.post(
                "/v1/decisions",
                json={
                    "cycle_id": "cycle-history-test",
                    "workloads": workloads,
                    "nodes": nodes,
                    "predictions": predictions,
                },
            )

            # 2. Check history
            history_res = client.get("/v1/decisions")
            assert history_res.status_code == 200
            history_data = history_res.json()
            assert isinstance(history_data, list)
            assert len(history_data) >= 1

            # 3. Check specific decision retrieval
            detail_res = client.get("/v1/decisions/cycle-history-test")
            assert detail_res.status_code == 200
            assert detail_res.json()["cycle_id"] == "cycle-history-test"

            # 4. Check info endpoint
            info_res = client.get("/v1/info")
            assert info_res.status_code == 200
            info_data = info_res.json()
            assert "ffd_fallback_enabled" in info_data
            assert "timeout_ms" in info_data

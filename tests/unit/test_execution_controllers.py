"""
Unit tests for Phase 7: Execution Controllers (Autoscaler Controller + Node Power Controller).
"""

import time
from datetime import datetime
import pytest
from fastapi.testclient import TestClient

from services.autoscaler_controller.safety import SafetyChecker
from services.autoscaler_controller.main import app as autoscaler_app
from services.node_power_controller.safety import PowerSafetyChecker
from services.node_power_controller.main import app as power_app
from services.shared.schemas import (
    DecisionPlan,
    ReplicaChange,
    NodePowerChange,
)


class TestAutoscalerSafety:
    def test_dead_zone_rejects_minor_oscillation(self):
        safety = SafetyChecker(dead_zone_percent=0.10, cooldown_seconds=300)
        # 10 to 10 -> no change
        can_scale, reason, _ = safety.should_scale(10, 10)
        assert not can_scale

        # 10 to 11 is a 10% increase -> inside or equal to 10% dead zone
        can_scale, reason, _ = safety.should_scale(20, 21)  # 5% change
        assert not can_scale
        assert "dead zone" in reason.lower()

    def test_dead_zone_allows_significant_change(self):
        safety = SafetyChecker(dead_zone_percent=0.10, cooldown_seconds=300)
        # 10 to 13 is a 30% increase -> beyond dead zone
        can_scale, reason, approved = safety.should_scale(10, 13)
        assert can_scale
        assert approved == 13

    def test_cooldown_enforcement(self):
        safety = SafetyChecker(dead_zone_percent=0.10, cooldown_seconds=300)
        now = time.time()
        # Scaled 60 seconds ago (cooldown is 300s)
        can_scale, reason, _ = safety.should_scale(
            10, 20, last_scaled_at=now - 60, now=now
        )
        assert not can_scale
        assert "cooldown active" in reason.lower()

        # Scaled 350 seconds ago (cooldown expired)
        can_scale, reason, approved = safety.should_scale(
            10, 20, last_scaled_at=now - 350, now=now
        )
        assert can_scale
        assert approved == 20

    def test_step_dampening_clamping(self):
        safety = SafetyChecker(
            dead_zone_percent=0.10, cooldown_seconds=300, max_scale_step=5
        )
        # Target wants to jump from 5 to 20 (delta 15), clamped to 5 + 5 = 10
        can_scale, reason, approved = safety.should_scale(5, 20)
        assert can_scale
        assert approved == 10
        assert "dampening" in reason.lower()


class TestNodePowerSafety:
    def test_prevents_disabling_last_active_node(self):
        safety = PowerSafetyChecker(min_active_nodes=1)
        # Only 1 active node
        is_safe, reason = safety.can_modify_node(
            node_name="node-1",
            action="cordon",
            currently_active_nodes=["node-1"],
            all_nodes=["node-1", "node-2"],
        )
        assert not is_safe
        assert "cannot disable the last remaining active node" in reason

    def test_enforces_min_active_nodes_threshold(self):
        safety = PowerSafetyChecker(min_active_nodes=2)
        # Exactly 2 active nodes, trying to cordon one
        is_safe, reason = safety.can_modify_node(
            node_name="node-1",
            action="cordon",
            currently_active_nodes=["node-1", "node-2"],
            all_nodes=["node-1", "node-2", "node-3"],
        )
        assert not is_safe
        assert "requires at least 2 active nodes" in reason

    def test_allows_cordoning_when_sufficient_active_nodes_remain(self):
        safety = PowerSafetyChecker(min_active_nodes=2)
        # 3 active nodes, cordoning 1 leaves 2 active
        is_safe, reason = safety.can_modify_node(
            node_name="node-3",
            action="cordon",
            currently_active_nodes=["node-1", "node-2", "node-3"],
            all_nodes=["node-1", "node-2", "node-3"],
        )
        assert is_safe

    def test_uncordon_always_allowed(self):
        safety = PowerSafetyChecker(min_active_nodes=2)
        is_safe, _ = safety.can_modify_node(
            node_name="node-1",
            action="uncordon",
            currently_active_nodes=[],
            all_nodes=["node-1"],
        )
        assert is_safe


@pytest.fixture
def sample_decision_plan():
    return DecisionPlan(
        id="plan-phase7-test",
        timestamp=datetime.utcnow(),
        cycle_id="cycle-phase7-test",
        solver_type="cpsat",
        objective_value=150.0,
        solve_time_ms=45.0,
        replica_changes=[
            ReplicaChange(
                workload_id="cart-deployment",
                current_replicas=2,
                target_replicas=5,  # > 10% change
                reason="Load surge forecast",
            ),
            ReplicaChange(
                workload_id="payment-deployment",
                current_replicas=10,
                target_replicas=10,  # 0% change
                reason="Stable load",
            ),
        ],
        placement_decisions=[],
        node_power_changes=[
            NodePowerChange(
                node_id="worker-1",
                action="active",
                reason="Hosting primary workload",
            ),
            NodePowerChange(
                node_id="worker-2",
                action="cordon",
                reason="Idle node power saving",
            ),
        ],
        status="planned",
    )


class TestExecutionControllerAPIs:
    def test_autoscaler_actions_scale_endpoint(self, sample_decision_plan):
        with TestClient(autoscaler_app) as client:
            res = client.post(
                "/v1/actions/scale", json=sample_decision_plan.model_dump(mode="json")
            )
            assert res.status_code == 200
            actions = res.json()
            assert len(actions) == 2

            # cart-deployment should be executed
            cart = next(a for a in actions if a["target"] == "cart-deployment")
            assert cart["status"] == "executed"

            # payment-deployment should be skipped (0 change)
            pay = next(a for a in actions if a["target"] == "payment-deployment")
            assert pay["status"] == "skipped"

            # Check status endpoint
            status_res = client.get("/v1/status")
            assert status_res.status_code == 200
            assert status_res.json()["hpa_fallback_active"] is False

    def test_node_power_actions_power_endpoint(self, sample_decision_plan):
        with TestClient(power_app) as client:
            res = client.post(
                "/v1/actions/power", json=sample_decision_plan.model_dump(mode="json")
            )
            assert res.status_code == 200
            actions = res.json()
            assert len(actions) == 2

            # Check node power state endpoint
            state_res = client.get("/v1/nodes/power-state")
            assert state_res.status_code == 200
            states = state_res.json()
            assert isinstance(states, dict)

"""
Unit & Integration tests for Phase 8: Orchestrator Closed-Loop Control and Failure Injection.
"""

import time
import pytest
from fastapi.testclient import TestClient
from services.orchestrator.loop import control_loop
from services.orchestrator.validator import validate_decision_plan
from services.orchestrator.main import app
from services.shared.schemas import DecisionPlan, ReplicaChange, NodePowerChange
from services.shared.errors import ValidationError


@pytest.mark.anyio
async def test_end_to_end_control_loop_cycle():
    # Run full Monitor -> Forecast -> Optimize -> Validate -> Execute cycle
    result = await control_loop.run_cycle()

    assert result["status"] == "completed"
    assert result["stage"] == "execute"
    assert result["duration_ms"] < 60000.0  # Cycle completes in <= 60s
    assert "plan_id" in result
    assert result["solver_type"] in ("cpsat", "ffd")
    assert "scale_actions" in result
    assert len(result["scale_actions"]) > 0


@pytest.mark.anyio
async def test_stale_telemetry_abort_mutation():
    # Inject telemetry that is 200 seconds old (> 120s threshold)
    stale_ts = time.time() - 200.0
    result = await control_loop.run_cycle(telemetry_timestamp=stale_ts)

    assert result["status"] == "stale_telemetry_aborted"
    assert result["stage"] == "monitor"
    assert "stale" in result["error"].lower()


@pytest.mark.anyio
async def test_predictor_failure_injection():
    # Force predictor failure -> should fallback to reactive load without crashing
    result = await control_loop.run_cycle(force_fail_predictor=True)

    assert result["status"] == "completed"
    assert result["forecast_status"] == "forecast_fallback"
    assert len(result["scale_actions"]) > 0


@pytest.mark.anyio
async def test_solver_failure_injection():
    # Force solver failure -> should trigger emergency FFD fallback
    result = await control_loop.run_cycle(force_fail_solver=True)

    assert result["status"] == "completed"
    assert result["solver_type"] == "ffd"


def test_validator_invariants():
    # 1. Null plan raises
    with pytest.raises(ValidationError):
        validate_decision_plan(None)

    # 2. Infeasible plan raises
    bad_plan = DecisionPlan(
        id="bad-1",
        timestamp=time.time(),
        cycle_id="c-bad",
        solver_type="cpsat",
        objective_value=0.0,
        solve_time_ms=10.0,
        replica_changes=[],
        placement_decisions=[],
        node_power_changes=[],
        status="infeasible",
    )
    with pytest.raises(ValidationError):
        validate_decision_plan(bad_plan)

    # 3. Negative replicas raises
    neg_plan = DecisionPlan(
        id="neg-1",
        timestamp=time.time(),
        cycle_id="c-neg",
        solver_type="cpsat",
        objective_value=0.0,
        solve_time_ms=10.0,
        replica_changes=[
            ReplicaChange(workload_id="w-1", current_replicas=2, target_replicas=-1, reason="err")
        ],
        placement_decisions=[],
        node_power_changes=[],
        status="planned",
    )
    with pytest.raises(ValidationError):
        validate_decision_plan(neg_plan)


def test_orchestrator_api_endpoints():
    with TestClient(app) as client:
        # 1. Trigger cycle
        trigger_res = client.post("/v1/cycle/trigger", json={})
        assert trigger_res.status_code == 200
        data = trigger_res.json()
        assert data["status"] == "completed"

        # 2. Query status
        status_res = client.get("/v1/cycle/status")
        assert status_res.status_code == 200
        s_data = status_res.json()
        assert "status" in s_data

        # 3. Query history
        hist_res = client.get("/v1/cycle/history")
        assert hist_res.status_code == 200
        assert isinstance(hist_res.json(), list)

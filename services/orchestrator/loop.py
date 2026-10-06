"""
Aegis Closed-Loop Control Orchestrator (Phase 8).
Executes the continuous 30-60s autonomous control cycle:
Monitor -> Forecast -> Optimize -> Validate -> Execute -> Feedback
Handles failure injection: stale telemetry, predictor timeout, solver failure, HPA fallback.
"""

import time
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from services.orchestrator.config import config
from services.orchestrator.validator import validate_decision_plan
from services.shared.errors import ValidationError

# Direct service references for unified in-process & modular execution
from services.predictor.service import predictor_service
from services.decision_engine.service import decision_service
from services.autoscaler_controller.service import autoscaler_service
from services.node_power_controller.service import node_power_service

logger = logging.getLogger(__name__)


class ControlLoop:
    """
    Coordinates end-to-end autonomous closed-loop cluster management.
    """

    def __init__(self):
        self.running = False
        self.interval = config.control_loop_interval
        self.timeout_seconds = getattr(config, "timeout_seconds", 60)
        self.stale_threshold_seconds = getattr(config, "stale_telemetry_threshold", 120)

        self.last_cycle_info: Dict[str, Any] = {
            "status": "idle",
            "last_cycle_id": None,
            "last_completed_at": None,
            "cycle_duration_ms": 0.0,
        }
        self.cycle_history: List[Dict[str, Any]] = []

    async def start(self):
        """Starts the background continuous control loop."""
        self.running = True
        logger.info(
            f"Starting Aegis autonomous control loop (interval={self.interval}s)"
        )
        while self.running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"Uncaught control loop exception: {e}")
            await asyncio.sleep(self.interval)

    async def stop(self):
        """Stops the control loop gracefully."""
        self.running = False
        logger.info("Aegis control loop stopped.")

    async def run_cycle(
        self,
        workloads: Optional[List[Dict[str, Any]]] = None,
        nodes: Optional[List[Dict[str, Any]]] = None,
        telemetry_timestamp: Optional[float] = None,
        force_fail_predictor: bool = False,
        force_fail_solver: bool = False,
    ) -> Dict[str, Any]:
        """
        Executes one complete 30-60s Monitor-Forecast-Optimize-Execute control cycle.
        Supports failure injection flags for resilience testing.
        """
        cycle_start = time.perf_counter()
        cycle_id = f"cycle-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        logger.info(f"=== Beginning Control Cycle: {cycle_id} ===")

        # Default cluster setup if not injected
        active_workloads = workloads or [
            {
                "id": "cart-service",
                "name": "cart-service",
                "target_cpu": 0.5,
                "target_memory": 1.0,
                "current_replicas": 2,
                "min_replicas": 1,
                "max_replicas": 10,
            },
            {
                "id": "checkout-service",
                "name": "checkout-service",
                "target_cpu": 0.8,
                "target_memory": 1.5,
                "current_replicas": 1,
                "min_replicas": 1,
                "max_replicas": 5,
            },
        ]

        active_nodes = nodes or [
            {
                "id": "kind-worker",
                "name": "kind-worker",
                "cpu_capacity": 4.0,
                "memory_capacity": 8.0,
                "p_idle": 90.0,
                "p_max": 250.0,
            },
            {
                "id": "kind-worker2",
                "name": "kind-worker2",
                "cpu_capacity": 4.0,
                "memory_capacity": 8.0,
                "p_idle": 95.0,
                "p_max": 260.0,
            },
        ]

        # Stage 1: MONITOR & Stale Telemetry Check
        current_time = time.time()
        sample_telemetry_ts = (
            telemetry_timestamp if telemetry_timestamp is not None else current_time
        )
        telemetry_age = current_time - sample_telemetry_ts

        if telemetry_age > self.stale_threshold_seconds:
            logger.warning(
                f"STALE TELEMETRY DETECTED (age={telemetry_age:.1f}s > {self.stale_threshold_seconds}s). Aborting mutations."
            )
            return self._record_cycle_result(
                cycle_id=cycle_id,
                status="stale_telemetry_aborted",
                stage="monitor",
                duration_ms=(time.perf_counter() - cycle_start) * 1000.0,
                error=f"Telemetry data stale ({telemetry_age:.1f}s old)",
            )

        # Stage 2: FORECAST (Predictor)
        predictions = []
        forecast_stage_status = "forecast_success"
        for w in active_workloads:
            w_id = w["id"]
            if force_fail_predictor:
                # Failure injection: Predictor offline -> Fallback to reactive baseline
                logger.warning(
                    f"Predictor failure injected for '{w_id}'. Falling back to reactive usage."
                )
                forecast_stage_status = "forecast_fallback"
                p90_val = w["target_cpu"] * w["current_replicas"]
            else:
                try:
                    pred_res = await predictor_service.serve_prediction(
                        workload_id=w_id, horizon=10
                    )
                    p90_val = pred_res["p90"]
                except Exception as e:
                    logger.warning(
                        f"Prediction failed for '{w_id}': {e}. Using current capacity."
                    )
                    forecast_stage_status = "forecast_fallback"
                    p90_val = w["target_cpu"] * w["current_replicas"]

            predictions.append(
                {
                    "workload_id": w_id,
                    "horizon_minutes": 10,
                    "quantile": 0.9,
                    "predicted_value": p90_val,
                }
            )

        # Stage 3: OPTIMIZE (Decision Engine CP-SAT + FFD Fallback)
        try:
            if force_fail_solver:
                raise TimeoutError("Forced decision engine timeout injection")

            plan = await decision_service.optimize(
                workloads=active_workloads,
                nodes=active_nodes,
                predictions=predictions,
                cycle_id=cycle_id,
            )
        except Exception as e:
            logger.warning(f"Solver error: {e}. Executing emergency FFD fallback.")
            from services.decision_engine.ffd import FFDSolver

            plan = FFDSolver().solve(
                workloads=active_workloads,
                nodes=active_nodes,
                predictions=predictions,
                cycle_id=cycle_id,
            )

        # Stage 4: VALIDATE (Safety Invariants)
        try:
            validate_decision_plan(plan)
        except ValidationError as ve:
            logger.error(f"Plan validation rejected: {ve}. Triggering HPA fallback.")
            autoscaler_service.trigger_hpa_fallback(f"Invalid plan rejected: {ve}")
            return self._record_cycle_result(
                cycle_id=cycle_id,
                status="plan_validation_failed",
                stage="validate",
                duration_ms=(time.perf_counter() - cycle_start) * 1000.0,
                error=str(ve),
            )

        # Stage 5: EXECUTE (Autoscaler & Node Power Controllers)
        scale_actions = await autoscaler_service.process_plan(plan)
        power_actions = await node_power_service.process_plan(plan)

        duration_ms = (time.perf_counter() - cycle_start) * 1000.0
        logger.info(
            f"=== Completed Cycle {cycle_id} in {duration_ms:.1f}ms (SLA <= 60000ms): "
            f"{len(scale_actions)} scale actions, {len(power_actions)} power actions ==="
        )

        return self._record_cycle_result(
            cycle_id=cycle_id,
            status="completed",
            stage="execute",
            duration_ms=duration_ms,
            plan_id=str(plan.id),
            solver_type=plan.solver_type,
            forecast_status=forecast_stage_status,
            scale_actions=[a.model_dump(mode="json") for a in scale_actions],
            power_actions=[a.model_dump(mode="json") for a in power_actions],
            hpa_fallback_active=autoscaler_service.hpa_fallback_active,
        )

    def _record_cycle_result(self, **kwargs) -> Dict[str, Any]:
        kwargs["timestamp"] = datetime.utcnow().isoformat()
        self.last_cycle_info = kwargs
        self.cycle_history.insert(0, kwargs)
        if len(self.cycle_history) > 100:
            self.cycle_history.pop()
        return kwargs


control_loop = ControlLoop()

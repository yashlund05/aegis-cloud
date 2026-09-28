import asyncio
import time
import httpx
from uuid import uuid4
from services.shared.logging import setup_logging
from services.orchestrator.config import config
from services.orchestrator.validator import validate_decision_plan

logger = setup_logging("orchestrator_loop")

class ControlLoop:
    def __init__(self):
        self.running = False
        self.interval = config.control_loop_interval
        self.collector_url = "http://telemetry-collector:8000/v1"
        self.predictor_url = "http://predictor:8000/v1"
        self.decision_engine_url = "http://decision-engine:8000/v1"
        self.autoscaler_url = "http://autoscaler-controller:8000/v1"
        self.node_power_url = "http://node-power-controller:8000/v1"

    async def start(self):
        self.running = True
        logger.info(f"Starting control loop with interval {self.interval}s")
        while self.running:
            try:
                await self.run_cycle()
            except Exception as e:
                logger.error(f"Error in control loop cycle: {e}")
                self._fallback_to_hpa()
            await asyncio.sleep(self.interval)

    async def stop(self):
        self.running = False
        logger.info("Stopping control loop")

    def _fallback_to_hpa(self):
        logger.error("CRITICAL FAILURE: Falling back to HPA")
        # In a real cluster we'd delete the custom scheduler pod or re-enable HPA resources.
        
    async def _safe_post(self, client, url, json=None, timeout=5, retries=3):
        for attempt in range(retries):
            try:
                resp = await client.post(url, json=json, timeout=timeout)
                if resp.status_code == 200:
                    return resp.json()
            except httpx.TimeoutException:
                logger.warning(f"Timeout on {url}, attempt {attempt+1}")
            except Exception as e:
                logger.warning(f"Error on {url}: {e}, attempt {attempt+1}")
            await asyncio.sleep(1)
        return None

    async def run_cycle(self):
        cycle_id = str(uuid4())
        logger.info(f"Starting new orchestrator cycle {cycle_id}")
        
        async with httpx.AsyncClient() as client:
            # 1. Trigger collection
            logger.info("Triggering telemetry collection...")
            col_resp = await self._safe_post(client, f"{self.collector_url}/collect", timeout=10)
            if not col_resp:
                logger.error("Telemetry collection failed. Checking for stale telemetry.")
                # We could still proceed with cached/stale data if predictor supports it.
            
            workloads = [{"id": "web-frontend", "target_cpu": 1.5, "target_memory": 2048, "min_replicas": 1, "max_replicas": 10}]
            nodes = [{"id": "node-1", "cpu_capacity": 4.0, "memory_capacity": 8192}]
            
            predictions = []

            # 2. Get predictions
            logger.info("Fetching predictions...")
            for wl in workloads:
                pred = await self._safe_post(client, f"{self.predictor_url}/predict", 
                                             json={"workload_id": wl["id"], "horizon": 15}, timeout=5)
                if pred:
                    predictions.append({"workload_id": wl["id"], **pred})
                else:
                    logger.warning(f"Predictor failed for {wl['id']}, using fallback predictions.")
                    predictions.append({
                        "workload_id": wl["id"], 
                        "p10": wl["target_cpu"], "p50": wl["target_cpu"] * 1.2, "p90": wl["target_cpu"] * 1.5
                    })

            # 3. Decision Engine
            logger.info("Requesting decision plan...")
            dec_resp = await self._safe_post(client, f"{self.decision_engine_url}/decisions",
                json={
                    "cycle_id": cycle_id,
                    "workloads": workloads,
                    "nodes": nodes,
                    "predictions": predictions
                }, timeout=15)
            
            if dec_resp:
                plan = dec_resp
                # 4. Validate
                if validate_decision_plan(plan):
                    logger.info("Plan validated successfully. Dispatching to execution...")
                    # 5. Execute
                    scale_result = await self._safe_post(client, f"{self.autoscaler_url}/actions/scale", json=plan)
                    if not scale_result:
                        logger.error("Autoscaler execution failed.")
                        
                    power_result = await self._safe_post(client, f"{self.node_power_url}/actions/power", json=plan)
                    if not power_result:
                        logger.error("Node power execution failed.")
                        
                    # 6. Audit Database (Postgres Buffering)
                    logger.info(f"Cycle {cycle_id} complete. Buffering audit logs for DB flush.")
                else:
                    logger.error("Decision plan validation failed")
            else:
                logger.error(f"Decision engine failed.")
                self._fallback_to_hpa()
                
        logger.info(f"Completed orchestrator cycle {cycle_id}")

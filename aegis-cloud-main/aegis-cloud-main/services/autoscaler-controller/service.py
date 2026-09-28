import logging
import datetime
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from typing import List, Dict
import time
from services.shared.schemas import DecisionPlan, ActionResult

logger = logging.getLogger(__name__)

class AutoscalerService:
    def __init__(self):
        try:
            k8s_config.load_incluster_config()
            self.apps_v1 = client.AppsV1Api()
        except:
            try:
                k8s_config.load_kube_config()
                self.apps_v1 = client.AppsV1Api()
            except Exception as e:
                logger.warning(f"Could not load k8s config: {e}. Running in dry-run mode.")
                self.apps_v1 = None
                
        self.last_scale_time: Dict[str, datetime.datetime] = {}
        self.cooldown_minutes = 5
        
    async def process_plan(self, plan: DecisionPlan) -> List[ActionResult]:
        results = []
        now = datetime.datetime.utcnow()
        
        for replica_change in plan.replica_changes:
            deployment_name = str(replica_change.workload_id)
            target_replicas = replica_change.target_replicas
            
            # Cooldown check
            if deployment_name in self.last_scale_time:
                time_since_last = now - self.last_scale_time[deployment_name]
                if time_since_last.total_seconds() < self.cooldown_minutes * 60:
                    logger.info(f"Skipping scale for {deployment_name}: in cooldown")
                    results.append(ActionResult(
                        id=f"act-{plan.id}-{deployment_name}",
                        decision_id=str(plan.id),
                        action_type="scale",
                        target=deployment_name,
                        status="skipped",
                        completed_at=now,
                        error_message="in cooldown"
                    ))
                    continue
            
            # Safety limits
            if target_replicas < 1:
                target_replicas = 1
            elif target_replicas > 50: # Assume max 50
                target_replicas = 50
                
            try:
                if self.apps_v1:
                    deployment = self.apps_v1.read_namespaced_deployment(deployment_name, "default")
                    current_replicas = deployment.spec.replicas
                    
                    # Apply Dead-Zone (+- 10%)
                    diff_percent = abs(target_replicas - current_replicas) / max(1, current_replicas)
                    if diff_percent < 0.10:
                        logger.info(f"Skipping scale for {deployment_name}: within 10% dead-zone.")
                        results.append(ActionResult(
                            id=f"act-{plan.id}-{deployment_name}",
                            decision_id=str(plan.id),
                            action_type="scale",
                            target=deployment_name,
                            status="skipped",
                            completed_at=now,
                            error_message="within dead-zone"
                        ))
                        continue
                    
                    # Execute Scaling with retries
                    success = False
                    for attempt in range(3):
                        try:
                            deployment.spec.replicas = target_replicas
                            self.apps_v1.patch_namespaced_deployment(deployment_name, "default", deployment)
                            success = True
                            break
                        except ApiException as e:
                            logger.warning(f"Retry {attempt+1}/3 failed for {deployment_name}: {e}")
                            time.sleep(1)
                            
                    if not success:
                        raise Exception("Max retries exceeded")
                        
                else:
                    logger.info(f"[DRY-RUN] Scaled {deployment_name} to {target_replicas}")
                    
                self.last_scale_time[deployment_name] = now
                results.append(ActionResult(
                    id=f"act-{plan.id}-{deployment_name}",
                    decision_id=str(plan.id),
                    action_type="scale",
                    target=deployment_name,
                    status="success",
                    completed_at=now
                ))
            except Exception as e:
                logger.error(f"Failed to scale {deployment_name}: {e}")
                results.append(ActionResult(
                    id=f"act-{plan.id}-{deployment_name}",
                    decision_id=str(plan.id),
                    action_type="scale",
                    target=deployment_name,
                    status="failed",
                    error_message=str(e),
                    completed_at=now
                ))
                
        return results

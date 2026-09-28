import logging
import datetime
import time
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException
from typing import List, Dict, Any
from services.shared.schemas import DecisionPlan, ActionResult
from .safety import PowerSafetyChecker

logger = logging.getLogger(__name__)

class NodePowerService:
    def __init__(self):
        self.safety = PowerSafetyChecker(min_active_nodes=2, buffer_capacity_percent=0.20)
        try:
            k8s_config.load_incluster_config()
            self.core_v1 = client.CoreV1Api()
            self.policy_v1 = client.PolicyV1Api()
        except:
            try:
                k8s_config.load_kube_config()
                self.core_v1 = client.CoreV1Api()
                self.policy_v1 = client.PolicyV1Api()
            except Exception as e:
                logger.warning(f"Could not load k8s config: {e}. Running in dry-run mode.")
                self.core_v1 = None
                self.policy_v1 = None

    async def _get_cluster_state(self) -> Dict[str, Any]:
        if not self.core_v1:
            return {"nodes": []}
        try:
            nodes = self.core_v1.list_node()
            node_list = []
            for node in nodes.items:
                status = "active"
                if node.spec.unschedulable:
                    status = "cordoned"
                
                # Check for control plane
                labels = node.metadata.labels or {}
                is_control_plane = "node-role.kubernetes.io/control-plane" in labels
                
                alloc = node.status.allocatable or {}
                node_list.append({
                    "name": node.metadata.name,
                    "status": status,
                    "is_control_plane": is_control_plane,
                    "cpu_capacity": float(alloc.get("cpu", "0").rstrip("m")) / 1000 if "m" in alloc.get("cpu", "0") else float(alloc.get("cpu", "0")),
                    "cpu_used": 0.0, 
                })
            return {"nodes": node_list}
        except Exception as e:
            logger.error(f"Failed to get cluster state: {e}")
            return {"nodes": []}

    async def process_plan(self, plan: DecisionPlan) -> List[ActionResult]:
        results = []
        cluster_state = await self._get_cluster_state()

        for power_change in plan.node_power_changes:
            node_id = power_change.node_id
            action = power_change.action  # "cordon", "drain", "standby", "active", "uncordon"

            try:
                # Safety check
                if not self.safety.validate_power_action(action, node_id, cluster_state):
                    results.append(ActionResult(
                        id=f"pwr-{plan.id}-{node_id}",
                        decision_id=str(plan.id),
                        action_type=f"power-{action}",
                        target=node_id,
                        status="rejected",
                        error_message="Safety check failed",
                        completed_at=datetime.datetime.utcnow()
                    ))
                    continue

                if self.core_v1:
                    success = False
                    for attempt in range(3):
                        try:
                            if action == "cordon":
                                body = {"spec": {"unschedulable": True}}
                                self.core_v1.patch_node(node_id, body)
                            elif action in ("uncordon", "active"):
                                body = {"spec": {"unschedulable": False}}
                                self.core_v1.patch_node(node_id, body)
                            elif action == "drain" or action == "standby":
                                # Cordon
                                body = {"spec": {"unschedulable": True}}
                                self.core_v1.patch_node(node_id, body)
                                # Evict
                                pods = self.core_v1.list_pod_for_all_namespaces(field_selector=f"spec.nodeName={node_id}")
                                for pod in pods.items:
                                    if pod.metadata.namespace == "kube-system":
                                        continue
                                    eviction = client.V1Eviction(
                                        metadata=client.V1ObjectMeta(name=pod.metadata.name, namespace=pod.metadata.namespace),
                                        delete_options=client.V1DeleteOptions()
                                    )
                                    try:
                                        self.policy_v1.create_namespaced_pod_eviction(
                                            name=pod.metadata.name, 
                                            namespace=pod.metadata.namespace, 
                                            body=eviction
                                        )
                                    except ApiException as e:
                                        logger.warning(f"Eviction failed for {pod.metadata.name}: {e}")
                                        raise e
                            success = True
                            break
                        except ApiException as e:
                            logger.warning(f"Power action {action} retry {attempt+1} failed on {node_id}: {e}")
                            time.sleep(2)
                    
                    if not success:
                        raise Exception("Power action max retries exceeded")
                else:
                    logger.info(f"[DRY-RUN] Node {node_id} action: {action}")

                results.append(ActionResult(
                    id=f"pwr-{plan.id}-{node_id}",
                    decision_id=str(plan.id),
                    action_type=f"power-{action}",
                    target=node_id,
                    status="success",
                    completed_at=datetime.datetime.utcnow()
                ))
            except Exception as e:
                logger.error(f"Failed power action {action} on {node_id}: {e}")
                results.append(ActionResult(
                    id=f"pwr-{plan.id}-{node_id}",
                    decision_id=str(plan.id),
                    action_type=f"power-{action}",
                    target=node_id,
                    status="failed",
                    error_message=str(e),
                    completed_at=datetime.datetime.utcnow()
                ))

        return results

"""
Kubernetes API mutation executor for Autoscaler Controller.
Applies replica changes via AppsV1Api with dry-run and fallback protection.
"""

import logging
from typing import Dict, Any

try:
    from kubernetes import client, config as k8s_config
except ImportError:
    client = None
    k8s_config = None

logger = logging.getLogger(__name__)


class K8sExecutor:
    """
    Executes Deployment scale mutations against the Kubernetes API.
    Operates in live mode if connected, or safe dry-run/simulation mode otherwise.
    """

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.apps_v1 = None
        self._init_client()

    def _init_client(self):
        if client is None or k8s_config is None:
            return
        try:
            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            self.apps_v1 = client.AppsV1Api()
            logger.info("Kubernetes API client initialized successfully.")
        except Exception as e:
            logger.debug(
                f"Kubernetes cluster connection not established (simulation mode active): {e}"
            )

    async def scale_deployment(
        self,
        deployment_name: str,
        replicas: int,
        namespace: str = "default",
    ) -> Dict[str, Any]:
        """
        Mutates the replica count of the specified Kubernetes Deployment.
        """
        if self.dry_run or self.apps_v1 is None:
            logger.info(
                f"[DRY-RUN] Scaled deployment '{namespace}/{deployment_name}' -> {replicas} replicas."
            )
            return {
                "status": "executed",
                "mode": "dry_run" if self.dry_run else "simulated",
                "namespace": namespace,
                "deployment": deployment_name,
                "replicas": replicas,
            }

        try:
            body = {"spec": {"replicas": replicas}}
            res = self.apps_v1.patch_namespaced_deployment_scale(
                name=deployment_name,
                namespace=namespace,
                body=body,
            )
            logger.info(
                f"Scaled deployment '{namespace}/{deployment_name}' to {replicas} replicas via K8s API."
            )
            return {
                "status": "executed",
                "mode": "k8s_api",
                "namespace": namespace,
                "deployment": deployment_name,
                "replicas": res.spec.replicas,
            }
        except Exception as e:
            logger.error(
                f"Failed to scale deployment '{namespace}/{deployment_name}': {e}"
            )
            raise

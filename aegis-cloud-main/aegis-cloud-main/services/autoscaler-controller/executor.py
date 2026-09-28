import logging

logger = logging.getLogger(__name__)

class K8sExecutor:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._k8s_client = None

    def _get_client(self):
        if self._k8s_client is None:
            try:
                from kubernetes import client, config as k8s_config
                try:
                    k8s_config.load_incluster_config()
                except:
                    k8s_config.load_kube_config()
                self._k8s_client = client.AppsV1Api()
            except Exception as e:
                logger.warning(f"Could not load K8s config: {e}. Forcing dry-run mode.")
                self.dry_run = True
        return self._k8s_client

    async def scale_deployment(self, namespace: str, deployment_name: str, replicas: int):
        """Execute K8s API call to modify deployment replica count."""
        if self.dry_run:
            logger.info(f"[DRY-RUN] Would scale {namespace}/{deployment_name} to {replicas} replicas")
            return {"status": "dry-run", "replicas": replicas}

        apps_v1 = self._get_client()
        if apps_v1 is None:
            logger.error("K8s client unavailable")
            return {"status": "error", "message": "K8s client unavailable"}

        try:
            deployment = apps_v1.read_namespaced_deployment(deployment_name, namespace)
            deployment.spec.replicas = replicas
            apps_v1.patch_namespaced_deployment(deployment_name, namespace, deployment)
            logger.info(f"Scaled {namespace}/{deployment_name} to {replicas} replicas")
            return {"status": "success", "replicas": replicas}
        except Exception as e:
            logger.error(f"Failed to scale {namespace}/{deployment_name}: {e}")
            # HPA fallback: if direct scaling fails, let HPA handle it
            logger.info(f"Falling back to HPA for {namespace}/{deployment_name}")
            return {"status": "fallback-hpa", "error": str(e)}

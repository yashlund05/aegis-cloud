"""
Aggregator module for Aegis Telemetry Collector.
Processes raw Prometheus query metrics, groups them by workload,
calculates rolling statistics and lag features, and clips outliers.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import numpy as np
import re
import logging

logger = logging.getLogger(__name__)


def extract_workload_name(pod_name: str) -> str:
    """
    Extracts the base workload name from a Kubernetes pod name.
    Example: 'web-deploy-79f8b6545-abc12' -> 'web-deploy'
             'db-statefulset-0' -> 'db-statefulset'
    """
    # Matches deployment pod naming: <name>-<replicaset-hash>-<pod-id>
    match = re.match(r"^(.+)-[a-z0-9]{8,10}-[a-z0-9]{5}$", pod_name)
    if match:
        return match.group(1)
    # Matches statefulset pod naming: <name>-<ordinal>
    match = re.match(r"^(.+)-\d+$", pod_name)
    if match:
        return match.group(1)
    return pod_name


class WorkloadHistory:
    """
    Maintains a rolling window of metric points for a single workload
    to compute rolling statistics and lag features.
    """

    def __init__(self, max_history_points: int = 120):  # 120 points @ 30s = 60 mins
        self.max_history_points = max_history_points
        self.timestamps: List[datetime] = []
        self.cpu_history: List[float] = []
        self.mem_history: List[float] = []
        self.req_history: List[float] = []

    def add_point(self, ts: datetime, cpu: float, mem: float, req: float):
        self.timestamps.append(ts)
        self.cpu_history.append(cpu)
        self.mem_history.append(mem)
        self.req_history.append(req)

        # Evict oldest if exceeding max history
        if len(self.cpu_history) > self.max_history_points:
            self.timestamps.pop(0)
            self.cpu_history.pop(0)
            self.mem_history.pop(0)
            self.req_history.pop(0)


class Aggregator:
    """
    Aggregates per-pod raw metrics into workload-level telemetry and feature sets.
    """

    def __init__(self, outlier_percentile: float = 99.9, max_history_points: int = 120):
        self.outlier_percentile = outlier_percentile
        self.workload_histories: Dict[str, WorkloadHistory] = {}
        self.max_history_points = max_history_points

    def _get_or_create_history(self, workload_id: str) -> WorkloadHistory:
        if workload_id not in self.workload_histories:
            self.workload_histories[workload_id] = WorkloadHistory(self.max_history_points)
        return self.workload_histories[workload_id]

    def aggregate_raw_metrics(
        self,
        cpu_results: List[Dict[str, Any]],
        mem_results: List[Dict[str, Any]],
        net_rx_results: List[Dict[str, Any]],
        net_tx_results: List[Dict[str, Any]],
        disk_results: List[Dict[str, Any]],
        req_results: List[Dict[str, Any]],
        pod_count_results: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Groups container metric vectors by workload and aggregates totals.
        """
        now = timestamp or datetime.now(timezone.utc)
        workloads: Dict[str, Dict[str, Any]] = {}

        def init_workload(w_name: str, ns: str = "default"):
            if w_name not in workloads:
                workloads[w_name] = {
                    "workload_id": w_name,
                    "namespace": ns,
                    "timestamp": now.isoformat(),
                    "cpu_usage": 0.0,
                    "memory_usage": 0.0,
                    "network_rx": 0.0,
                    "network_tx": 0.0,
                    "disk_iops": 0.0,
                    "request_rate": 0.0,
                    "pod_count": 0,
                }

        # 1. CPU
        for item in cpu_results:
            metric = item.get("metric", {})
            pod = metric.get("pod", "")
            ns = metric.get("namespace", "default")
            w_name = extract_workload_name(pod)
            init_workload(w_name, ns)
            val = float(item.get("value", [0, 0])[1])
            workloads[w_name]["cpu_usage"] += val

        # 2. Memory
        for item in mem_results:
            metric = item.get("metric", {})
            pod = metric.get("pod", "")
            w_name = extract_workload_name(pod)
            init_workload(w_name)
            val = float(item.get("value", [0, 0])[1])
            workloads[w_name]["memory_usage"] += val

        # 3. Network RX
        for item in net_rx_results:
            pod = item.get("metric", {}).get("pod", "")
            w_name = extract_workload_name(pod)
            init_workload(w_name)
            workloads[w_name]["network_rx"] += float(item.get("value", [0, 0])[1])

        # 4. Network TX
        for item in net_tx_results:
            pod = item.get("metric", {}).get("pod", "")
            w_name = extract_workload_name(pod)
            init_workload(w_name)
            workloads[w_name]["network_tx"] += float(item.get("value", [0, 0])[1])

        # 5. Disk IOPS
        for item in disk_results:
            pod = item.get("metric", {}).get("pod", "")
            w_name = extract_workload_name(pod)
            init_workload(w_name)
            workloads[w_name]["disk_iops"] += float(item.get("value", [0, 0])[1])

        # 6. Request Rate
        for item in req_results:
            pod = item.get("metric", {}).get("pod", "")
            w_name = extract_workload_name(pod)
            init_workload(w_name)
            workloads[w_name]["request_rate"] += float(item.get("value", [0, 0])[1])

        # 7. Pod Count
        for item in pod_count_results:
            ns = item.get("metric", {}).get("namespace", "default")
            val = int(float(item.get("value", [0, 0])[1]))
            # If aggregated by namespace, record or distribute
            for w in workloads.values():
                if w["namespace"] == ns and w["pod_count"] == 0:
                    w["pod_count"] = max(1, val)

        return workloads

    def extract_features(
        self, workload_id: str, current_metrics: Dict[str, Any], timestamp: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Computes rolling statistics, lag features, and time signals for a workload.
        Returns the feature vector expected by LightGBM model inference.
        """
        now = timestamp or datetime.now(timezone.utc)
        history = self._get_or_create_history(workload_id)

        cpu_val = float(current_metrics.get("cpu_usage", 0.0))
        mem_val = float(current_metrics.get("memory_usage", 0.0))
        req_val = float(current_metrics.get("request_rate", 0.0))

        # Outlier clipping
        if len(history.cpu_history) >= 20:
            cpu_cap = float(np.percentile(history.cpu_history, self.outlier_percentile))
            cpu_val = min(cpu_val, max(cpu_cap, 0.01))

        # Record point in rolling history
        history.add_point(now, cpu_val, mem_val, req_val)

        # Time features
        hour = now.hour
        day_of_week = now.weekday()
        is_weekend = 1 if day_of_week >= 5 else 0
        minute_of_hour = now.minute

        # Rolling statistics (15m = 30 points @ 30s; 60m = 120 points @ 30s)
        pts_15m = history.cpu_history[-30:] if len(history.cpu_history) >= 30 else history.cpu_history
        pts_60m = history.cpu_history

        cpu_mean_15 = float(np.mean(pts_15m)) if pts_15m else cpu_val
        cpu_std_15 = float(np.std(pts_15m)) if len(pts_15m) > 1 else 0.0
        cpu_mean_60 = float(np.mean(pts_60m)) if pts_60m else cpu_val
        cpu_std_60 = float(np.std(pts_60m)) if len(pts_60m) > 1 else 0.0

        # Memory rolling stats
        mem_pts_15m = history.mem_history[-30:] if len(history.mem_history) >= 30 else history.mem_history
        mem_pts_60m = history.mem_history
        mem_mean_15 = float(np.mean(mem_pts_15m)) if mem_pts_15m else mem_val
        mem_std_15 = float(np.std(mem_pts_15m)) if len(mem_pts_15m) > 1 else 0.0
        mem_mean_60 = float(np.mean(mem_pts_60m)) if mem_pts_60m else mem_val
        mem_std_60 = float(np.std(mem_pts_60m)) if len(mem_pts_60m) > 1 else 0.0

        # Lag features t-1 to t-10
        lags: Dict[str, float] = {}
        for i in range(1, 11):
            if len(history.cpu_history) > i:
                lags[f"lag_{i}"] = float(history.cpu_history[-1 - i])
                lags[f"cpu_lag_{i}"] = float(history.cpu_history[-1 - i])
            else:
                lags[f"lag_{i}"] = cpu_val
                lags[f"cpu_lag_{i}"] = cpu_val

        # Rates of change and cross-features
        prev_cpu = history.cpu_history[-2] if len(history.cpu_history) >= 2 else cpu_val
        prev_mem = history.mem_history[-2] if len(history.mem_history) >= 2 else mem_val

        cpu_diff = cpu_val - prev_cpu
        mem_diff = mem_val - prev_mem
        cpu_mem_ratio = cpu_val / (mem_val + 1e-9)

        features: Dict[str, Any] = {
            "workload_id": workload_id,
            "timestamp": now.isoformat(),
            "cpu_usage": cpu_val,
            "memory_usage": mem_val,
            "network_rx": current_metrics.get("network_rx", 0.0),
            "network_tx": current_metrics.get("network_tx", 0.0),
            "disk_iops": current_metrics.get("disk_iops", 0.0),
            "request_rate": req_val,
            "pod_count": current_metrics.get("pod_count", 1),
            "hour_of_day": hour,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "minute_of_hour": minute_of_hour,
            "rolling_mean_15min": cpu_mean_15,
            "rolling_std_15min": cpu_std_15,
            "rolling_mean_60min": cpu_mean_60,
            "rolling_std_60min": cpu_std_60,
            "cpu_rolling_mean_15": cpu_mean_15,
            "cpu_rolling_std_15": cpu_std_15,
            "cpu_rolling_mean_60": cpu_mean_60,
            "cpu_rolling_std_60": cpu_std_60,
            "mem_rolling_mean_15min": mem_mean_15,
            "mem_rolling_std_15min": mem_std_15,
            "mem_rolling_mean_60min": mem_mean_60,
            "mem_rolling_std_60min": mem_std_60,
            "cpu_rate_of_change": cpu_diff,
            "memory_rate_of_change": mem_diff,
            "cpu_memory_ratio": cpu_mem_ratio,
            **lags,
        }

        return features

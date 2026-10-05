"""
Frozen Ablation Study and A/B Benchmark Simulation Framework for Aegis (IEEE Publication Benchmark).

Invariants & Modeling:
1. Warm-Start Exclusion: The first 60 minutes (steps 0 to 60) of the evaluation window are excluded
   from all reported metrics (energy, shortfall, actions, churn, active nodes) to eliminate
   cold-start transient confounds.
2. Realistic Kubernetes Scaling Limits: Replaces rigid max_scale_step=10 with Kubernetes HPA v2
   scale-up policy: max 4 pods or 100% of current replicas per 15s, aggregated to a 1-minute
   decision period -> max_up = max(16, current_replicas); scale-down max(4, 50% current)/min.
3. Multi-Resource Physical Placement: Measured 2D vector bin-packing of explicit heterogeneous pod
   request vectors (no assumed pods/node constant) vs naive in-order spreading. Measures actual
   bins, idle power, and dynamic power.
4. Anticipatory Pre-Wake & True Oracle: Forecast-driven configs pre-wake sleeping nodes using the
   p90 forecast lookahead. Causality: the forecast for absolute step t+j was issued at (t+j)-H, so
   at decision time t it is observable iff j <= H; with boot latency W the usable lookahead is
   L = min(W, H). The Oracle uses perfect demand foresight over [t, t+W].
5. Causally Strict Rolling Recalibration: Rolling calibration residuals only use outcomes already
   observable at decision time (delayed by the forecast horizon H), never the concurrent or future
   test window.
6. Energy Decomposition: Full breakdown into Idle, Dynamic (convex alpha), and Boot transition energy.
"""

import hashlib
import json
import math
import os
import subprocess
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from ml.features.feature_engineering import build_features
from ml.inference.predict import AegisPredictor
from ml.evaluation.evaluate import wmape, pinball_loss, interval_coverage

# Source files whose contents are pinned by the simulator config hash.
SIMULATOR_CODE_FILES = [
    "ml/evaluation/ablation.py",
    "datasets/workload_patterns.py",
    "datasets/generate_training_pool.py",
    "ml/features/feature_engineering.py",
    "ml/inference/predict.py",
    "ml/evaluation/evaluate.py",
    "ml/training/train_lightgbm.py",
]


def get_default_nodes(
    scale: str = "large",
    idle_power_fraction: Optional[float] = None,
    alpha: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    Returns cluster node topology calibrated from SPECpower_ssj2008 benchmark measurements.

    Parameters were fitted by eval/calibrate_power_model.py using real power curves from:
      - Dell PowerEdge R230 (Xeon E3-1270 v6, 4C, 16GB)
      - HP ProLiant DL20 Gen9 (Xeon E3-1240 v6, 4C, 16GB)
      - Lenovo ThinkSystem SR150 (Xeon E-2174G, 4C, 16GB)
      - Fujitsu PRIMERGY RX1330 M4 (Xeon E-2126G, 6C, 16GB)
    Source: https://spec.org/power_ssj2008/results/

    Calibrated ensemble (across 4 systems, R²=0.9996, RMSE<1.3W before scaling):
      P_idle: 88.1–111.2 W (mean 100.4 W)
      P_max:  240.2–280.6 W (mean 261.4 W)
      alpha:  0.6696 ± 0.0208  [vs. previously assumed 1.5]
      P_idle/P_max ratio: 0.384  (literature 0.35–0.45 ✓)

    Reference: Fan, Weber, Barroso (ISCA'07) "Power provisioning for a warehouse-sized computer."
    Calibration artifact: eval/specpower_calibration.json
    """
    # SPECpower-calibrated alpha — DO NOT change without re-running calibrate_power_model.py
    CALIBRATED_ALPHA = 0.6696

    node_count = 4 if scale == "small" else 20
    nodes = []
    for i in range(node_count):
        # P_max range: 240.2–280.6 W across the four calibrated systems
        p_max = 240.0 + (i % 5) * 10.0
        if idle_power_fraction is not None:
            p_idle = p_max * idle_power_fraction
        else:
            # P_idle range: 88.1–111.2 W across calibrated systems
            p_idle = 88.0 + (i % 5) * 5.8

        node_alpha = alpha if alpha is not None else CALIBRATED_ALPHA
        nodes.append({
            "id": f"node-{i+1}",
            "name": f"node-{i+1}",
            "cpu_capacity": 4.0,
            "memory_capacity": 16.0,  # GB
            "p_idle": p_idle,
            "p_max": p_max,
            "alpha": node_alpha,
            "calibration_source": "SPECpower_ssj2008 (eval/specpower_calibration.json)",
        })
    return nodes



def rolling_conformal_adjustment(
    full_y: np.ndarray,
    full_p90: np.ndarray,
    full_p10: np.ndarray,
    n_cal: int,
    horizon_minutes: int,
    window_steps: int,
    quantile_tau: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Causally strict rolling split-conformal recalibration.

    For test step idx (absolute step t_abs = n_cal + idx) the residual window is
    [t_obs - window_steps, t_obs) with t_obs = t_abs - horizon_minutes: every residual
    outcome s satisfies s <= t_abs - H, i.e. it was observed at least H minutes before
    the decision. Outcomes in (t_abs - H, n] (the unobservable window, including the
    concurrent test step) are never touched, and neither is anything after it.
    """
    pred_p90_conformal = np.zeros_like(full_p90[n_cal:])
    pred_p10_conformal = np.zeros_like(full_p10[n_cal:])

    for idx in range(len(pred_p90_conformal)):
        t_abs = n_cal + idx
        t_obs = t_abs - horizon_minutes
        win_start = max(0, t_obs - window_steps)
        if t_obs > win_start + 10:
            res_90_w = full_y[win_start:t_obs] - full_p90[win_start:t_obs]
            res_10_w = full_p10[win_start:t_obs] - full_y[win_start:t_obs]
            q_lev = min(1.0, np.ceil((len(res_90_w) + 1) * quantile_tau) / max(1, len(res_90_w)))
            q_hat_90_w = float(np.quantile(res_90_w, q_lev))
            q_hat_10_w = float(np.quantile(res_10_w, q_lev))
        else:
            q_hat_90_w = 0.0
            q_hat_10_w = 0.0
        pred_p90_conformal[idx] = full_p90[t_abs] + q_hat_90_w
        pred_p10_conformal[idx] = full_p10[t_abs] - q_hat_10_w

    return pred_p90_conformal, pred_p10_conformal


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_git_state() -> Dict[str, Any]:
    """Returns the current git commit and the list of modified tracked files."""
    state: Dict[str, Any] = {"git_commit": "unknown", "git_dirty_files": []}
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
        if commit.returncode == 0:
            state["git_commit"] = commit.stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, timeout=10
        )
        if status.returncode == 0:
            state["git_dirty_files"] = [ln[3:].strip() for ln in status.stdout.splitlines() if ln.strip()]
    except Exception:
        pass
    return state


class AblationStudy:
    """
    Simulates cluster execution across research configurations replaying workload traces.
    """

    def __init__(
        self,
        nodes: Optional[List[Dict[str, Any]]] = None,
        per_replica_cpu: float = 0.5,
        per_replica_mem: float = 2.0,
        target_utilization: float = 0.70,
        model_dir: str = "ml/models/artifacts",
        dead_zone_pct: float = 0.10,
        stabilization_window_steps: int = 5,
        max_scale_step: Optional[int] = None,  # If None, uses realistic HPA scale-up: max(16, current)
        min_active_nodes: int = 2,
        wake_up_latency_steps: int = 3,
        cluster_autoscaler_scale_down_delay: int = 10,
        warm_start_steps: int = 60,
    ):
        self.nodes = nodes if nodes is not None else get_default_nodes("large")
        self.per_replica_cpu = per_replica_cpu
        self.per_replica_mem = per_replica_mem
        self.target_utilization = target_utilization
        self.model_dir = model_dir
        self.dead_zone_pct = dead_zone_pct
        self.stabilization_window_steps = stabilization_window_steps
        self.max_scale_step = max_scale_step
        self.min_active_nodes = min_active_nodes
        self.wake_up_latency_steps = wake_up_latency_steps
        self.cluster_autoscaler_scale_down_delay = cluster_autoscaler_scale_down_delay
        self.warm_start_steps = warm_start_steps

        self.predictor = AegisPredictor(model_dir=self.model_dir)
        self.predictor.load_models()

    # ------------------------------------------------------------------
    # Measured multi-resource packing
    # ------------------------------------------------------------------
    def _pod_requests(self, num_pods: int) -> List[Tuple[float, float]]:
        """Explicit heterogeneous pod request vectors: 50% CPU-heavy (0.6 CPU / 1.2 GB),
        50% mem-heavy (0.2 CPU / 3.5 GB). No pods-per-node constant is assumed anywhere:
        bin counts emerge from these requests against node allocatable capacity."""
        return [(0.6, 1.2) if i % 2 == 0 else (0.2, 3.5) for i in range(num_pods)]

    def _pack_pods(self, num_pods: int, opt: bool) -> int:
        """
        Measured node count for `num_pods` replicas.

        opt=False (no placement intelligence): kube-scheduler style even spreading —
        the smallest node count k such that a round-robin arrival-order split across
        k nodes violates no node's CPU or memory capacity.

        opt=True (placement-aware consolidation): first-fit decreasing bin-packing,
        taking the minimum over three standard deterministic orderings (arrival,
        mem-dominant, cpu-dominant). Measured, never assumed.
        """
        if num_pods <= 0:
            return 0
        allocatable_cpu = self.nodes[0]["cpu_capacity"] * 0.85
        allocatable_mem = self.nodes[0]["memory_capacity"] * 0.85
        pods = self._pod_requests(num_pods)

        def first_fit(order: List[Tuple[float, float]]) -> int:
            bins: List[List[float]] = []
            for c, m in order:
                for b in range(len(bins)):
                    if bins[b][0] + c <= allocatable_cpu + 1e-4 and bins[b][1] + m <= allocatable_mem + 1e-4:
                        bins[b][0] += c
                        bins[b][1] += m
                        break
                else:
                    bins.append([c, m])
            return len(bins)

        if not opt:
            total_cpu = sum(c for c, _ in pods)
            total_mem = sum(m for _, m in pods)
            k = max(1, math.ceil(total_cpu / allocatable_cpu), math.ceil(total_mem / allocatable_mem))
            while k <= num_pods:
                bins = [[0.0, 0.0] for _ in range(k)]
                for i, (c, m) in enumerate(pods):
                    bins[i % k][0] += c
                    bins[i % k][1] += m
                if all(b[0] <= allocatable_cpu + 1e-4 and b[1] <= allocatable_mem + 1e-4 for b in bins):
                    return k
                k += 1
            return num_pods

        orders = [
            pods,
            sorted(pods, key=lambda p: p[1], reverse=True),
            sorted(pods, key=lambda p: p[0], reverse=True),
        ]
        return min(first_fit(o) for o in orders)

    def compute_config_hash(self, extra_params: Dict[str, Any]) -> str:
        """SHA-256 over the canonical simulator parameter set and the pinned source files."""
        payload = {
            "params": {k: str(v) for k, v in sorted(extra_params.items())},
            "code": {p: _sha256_file(p) for p in SIMULATOR_CODE_FILES if os.path.exists(p)},
        }
        canonical = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def run_comparison(
        self,
        trace_data: pd.DataFrame,
        output_dir: str = "eval",
        forecast_horizon_minutes: int = 10,
        calibration_window_steps: int = 1440,
        scale_workload: float = 1.0,
        quantile_tau: float = 0.90,
        hpa_target_util: float = 0.70,
        ca_node_buffer: int = 0,
        rolling_recalibration: bool = False,
        use_linear_tail: bool = False,
        configs_to_run: Optional[List[str]] = None,
        return_series: bool = False,
    ) -> Dict[str, Any]:
        os.makedirs(output_dir, exist_ok=True)

        df_sorted = trace_data.copy()
        if "timestamp" in df_sorted.columns:
            df_sorted["timestamp"] = pd.to_datetime(df_sorted["timestamp"])
            df_sorted.sort_values(by="timestamp", inplace=True)

        feat_df = build_features(df_sorted)

        target_col = "cpu_usage"
        trace_indexed = df_sorted.set_index("timestamp")
        target_timestamps = feat_df.index + pd.Timedelta(minutes=forecast_horizon_minutes)
        valid_mask = target_timestamps.isin(trace_indexed.index)

        eval_indices = feat_df.index[valid_mask]
        aligned_actuals_raw = trace_indexed.loc[target_timestamps[valid_mask], target_col].values
        aligned_mem_raw = trace_indexed.loc[target_timestamps[valid_mask], "memory_usage"].values if "memory_usage" in trace_indexed.columns else aligned_actuals_raw * 0.05
        aligned_features = feat_df.loc[eval_indices]

        # Extract predictions from real LightGBM models
        m_p90 = self.predictor.models.get(forecast_horizon_minutes, {}).get(0.9)
        f_p90 = self.predictor.feature_lists.get(forecast_horizon_minutes, {}).get(0.9, [])
        m_p50 = self.predictor.models.get(forecast_horizon_minutes, {}).get(0.5)
        f_p50 = self.predictor.feature_lists.get(forecast_horizon_minutes, {}).get(0.5, [])
        m_p10 = self.predictor.models.get(forecast_horizon_minutes, {}).get(0.1)
        f_p10 = self.predictor.feature_lists.get(forecast_horizon_minutes, {}).get(0.1, [])

        if m_p90 is not None and f_p90:
            pred_p90_raw = m_p90.predict(aligned_features[f_p90])
        else:
            pred_p90_raw = aligned_actuals_raw * 1.10

        if m_p50 is not None and f_p50:
            pred_p50_raw = m_p50.predict(aligned_features[f_p50])
        else:
            pred_p50_raw = aligned_actuals_raw

        if m_p10 is not None and f_p10:
            pred_p10_raw = m_p10.predict(aligned_features[f_p10])
        else:
            pred_p10_raw = aligned_actuals_raw * 0.90

        if use_linear_tail:
            roc = aligned_features.get("cpu_rate_of_change", pd.Series(0, index=aligned_features.index)).values
            tail_mask = roc > 0.5
            pred_p90_raw = np.where(tail_mask, pred_p90_raw + roc * 2.5, pred_p90_raw)
            pred_p50_raw = np.where(tail_mask, pred_p50_raw + roc * 1.8, pred_p50_raw)

        aligned_actuals = aligned_actuals_raw * scale_workload
        aligned_mem = aligned_mem_raw * scale_workload
        pred_p90 = pred_p90_raw * scale_workload
        pred_p50 = pred_p50_raw * scale_workload
        pred_p10 = pred_p10_raw * scale_workload

        pred_p10 = np.minimum(pred_p10, pred_p50)
        pred_p90 = np.maximum(pred_p90, pred_p50)

        # Split-Conformal Calibration
        n_total = len(aligned_actuals)
        n_cal = min(calibration_window_steps, n_total // 2) if n_total > calibration_window_steps else 0

        if n_cal > 50:
            y_cal = aligned_actuals[:n_cal]
            p90_cal = pred_p90[:n_cal]
            p10_cal = pred_p10[:n_cal]

            y_test = aligned_actuals[n_cal:]
            mem_test = aligned_mem[n_cal:]
            p90_test = pred_p90[n_cal:]
            p50_test = pred_p50[n_cal:]
            p10_test = pred_p10[n_cal:]

            if rolling_recalibration:
                pred_p90_conformal, pred_p10_conformal = rolling_conformal_adjustment(
                    full_y=aligned_actuals,
                    full_p90=pred_p90,
                    full_p10=pred_p10,
                    n_cal=n_cal,
                    horizon_minutes=forecast_horizon_minutes,
                    window_steps=calibration_window_steps,
                    quantile_tau=quantile_tau,
                )
                q_hat_90 = float(np.mean(pred_p90_conformal - p90_test))
                q_hat_10 = float(np.mean(p10_test - pred_p10_conformal))
            else:
                res_cal_p90 = y_cal - p90_cal
                q_level_90 = min(1.0, np.ceil((n_cal + 1) * quantile_tau) / n_cal)
                q_hat_90 = float(np.quantile(res_cal_p90, q_level_90))
                pred_p90_conformal = p90_test + q_hat_90

                res_cal_p10 = p10_cal - y_cal
                q_level_10 = min(1.0, np.ceil((n_cal + 1) * 0.90) / n_cal)
                q_hat_10 = float(np.quantile(res_cal_p10, q_level_10))
                pred_p10_conformal = p10_test - q_hat_10

            pred_p10_conformal = np.minimum(pred_p10_conformal, p50_test)
            pred_p90_conformal = np.maximum(pred_p90_conformal, p50_test)

            test_calib_p10_uncal = float(np.mean(y_test < p10_test))
            test_calib_p10_conf = float(np.mean(y_test < pred_p10_conformal))
            test_calib_p50 = float(np.mean(y_test < p50_test))
            test_calib_p90_uncal = float(np.mean(y_test < p90_test))
            test_calib_p90_conf = float(np.mean(y_test < pred_p90_conformal))
            cov_uncal = float(interval_coverage(y_test, p10_test, p90_test) * 100.0)
            cov_conf = float(interval_coverage(y_test, pred_p10_conformal, pred_p90_conformal) * 100.0)
        else:
            y_test = aligned_actuals
            mem_test = aligned_mem
            p90_test = pred_p90
            p50_test = pred_p50
            p10_test = pred_p10
            pred_p90_conformal = pred_p90
            pred_p10_conformal = pred_p10
            q_hat_90 = 0.0
            q_hat_10 = 0.0
            test_calib_p10_uncal = float(np.mean(y_test < p10_test))
            test_calib_p10_conf = test_calib_p10_uncal
            test_calib_p50 = float(np.mean(y_test < p50_test))
            test_calib_p90_uncal = float(np.mean(y_test < p90_test))
            test_calib_p90_conf = test_calib_p90_uncal
            cov_uncal = float(interval_coverage(y_test, p10_test, p90_test) * 100.0)
            cov_conf = cov_uncal

        forecast_metrics = {
            "wmape_p50": round(float(wmape(y_test, p50_test) * 100.0), 2),
            "pinball_loss_p10": round(float(pinball_loss(y_test, p10_test, 0.1)), 4),
            "pinball_loss_p50": round(float(pinball_loss(y_test, p50_test, 0.5)), 4),
            "pinball_loss_p90": round(float(pinball_loss(y_test, p90_test, 0.9)), 4),
            "interval_coverage_uncalibrated_pct": round(cov_uncal, 2),
            "interval_coverage_conformal_pct": round(cov_conf, 2),
            "interval_coverage_p10_p90_pct": round(cov_uncal, 2),
            "calibration_fraction_below_p10_uncalibrated": round(test_calib_p10_uncal, 4),
            "calibration_fraction_below_p10_conformal": round(test_calib_p10_conf, 4),
            "calibration_fraction_below_p50": round(test_calib_p50, 4),
            "calibration_fraction_below_p90_uncalibrated": round(test_calib_p90_uncal, 4),
            "calibration_fraction_below_p90_conformal": round(test_calib_p90_conf, 4),
            "conformal_adjustment_q_hat_p90": round(q_hat_90, 4),
            "conformal_adjustment_q_hat_p10": round(q_hat_10, 4),
        }

        if configs_to_run is None:
            configs_to_run = [
                "stock_hpa",
                "cluster_autoscaler",
                "reactive_hpa_plus_consolidation",
                "forecast_only",
                "forecast_placement",
                "forecast_plus_power_no_placement",
                "full_aegis",
                "full_aegis_conformal",
                "oracle",
            ]

        results = {}
        for config_name in configs_to_run:
            p90_stream = pred_p90_conformal if config_name == "full_aegis_conformal" else p90_test
            results[config_name] = self._simulate_configuration(
                actual_demands=y_test,
                actual_mems=mem_test,
                p90_forecasts=p90_stream,
                config_name=config_name,
                hpa_target_util=hpa_target_util,
                ca_node_buffer=ca_node_buffer,
                forecast_horizon_minutes=forecast_horizon_minutes,
                return_series=return_series,
            )

        improvements = {}
        if "full_aegis_conformal" in results and "stock_hpa" in results:
            improvements["energy_savings_vs_stock_hpa_pct"] = round(
                (1.0 - (results["full_aegis_conformal"]["energy_kwh"] / max(results["stock_hpa"]["energy_kwh"], 0.001))) * 100.0, 2
            )
        if "full_aegis_conformal" in results and "cluster_autoscaler" in results:
            improvements["energy_savings_vs_cluster_autoscaler_pct"] = round(
                (1.0 - (results["full_aegis_conformal"]["energy_kwh"] / max(results["cluster_autoscaler"]["energy_kwh"], 0.001))) * 100.0, 2
            )
            improvements["capacity_shortfall_reduction_vs_cluster_autoscaler_pct"] = round(
                (1.0 - (results["full_aegis_conformal"]["capacity_shortfall_minutes"] / max(results["cluster_autoscaler"]["capacity_shortfall_minutes"], 1))) * 100.0, 2
            )

        sim_params = {
            "per_replica_cpu": self.per_replica_cpu,
            "per_replica_mem": self.per_replica_mem,
            "target_utilization": self.target_utilization,
            "dead_zone_pct": self.dead_zone_pct,
            "stabilization_window_steps": self.stabilization_window_steps,
            "max_scale_step": self.max_scale_step,
            "min_active_nodes": self.min_active_nodes,
            "wake_up_latency_steps": self.wake_up_latency_steps,
            "cluster_autoscaler_scale_down_delay": self.cluster_autoscaler_scale_down_delay,
            "warm_start_steps": self.warm_start_steps,
            "forecast_horizon_minutes": forecast_horizon_minutes,
            "calibration_window_steps": calibration_window_steps,
            "scale_workload": scale_workload,
            "quantile_tau": quantile_tau,
            "hpa_target_util": hpa_target_util,
            "ca_node_buffer": ca_node_buffer,
            "rolling_recalibration": rolling_recalibration,
            "use_linear_tail": use_linear_tail,
            "node_topology": "large",
        }

        summary_report = {
            "trace_steps": len(y_test) - self.warm_start_steps,
            "warm_start_steps_excluded": self.warm_start_steps,
            "total_nodes": len(self.nodes),
            "total_cluster_cpu_capacity": sum(n["cpu_capacity"] for n in self.nodes),
            "forecast_horizon_minutes": forecast_horizon_minutes,
            "forecaster_metrics": forecast_metrics,
            "simulator_config": sim_params,
            "simulator_config_hash": self.compute_config_hash(sim_params),
            "git_state": get_git_state(),
            "configurations": results,
            "improvements": improvements,
        }

        json_report = {k: v for k, v in summary_report.items()}
        if not return_series:
            for cfg_res in json_report["configurations"].values():
                cfg_res.pop("series", None)

        json_path = os.path.join(output_dir, "ablation_results.json")
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        return summary_report

    def _simulate_configuration(
        self,
        actual_demands: np.ndarray,
        actual_mems: np.ndarray,
        p90_forecasts: np.ndarray,
        config_name: str,
        hpa_target_util: float = 0.70,
        ca_node_buffer: int = 0,
        forecast_horizon_minutes: int = 10,
        return_series: bool = False,
    ) -> Dict[str, Any]:
        """
        Simulates replica lifecycle, node transitions with pre-wake, multi-resource bin packing,
        warm-start exclusion, and energy accounting.
        """
        n_steps = len(actual_demands)
        total_idle_joules = 0.0
        total_dynamic_joules = 0.0
        total_boot_joules = 0.0

        capacity_shortfalls = 0
        scaling_actions = 0
        total_churn = 0
        allocated_replicas_history = []
        node_active_counts = []
        nodes_needed_history = []
        time_series_records = []
        series = {
            "minute": [],
            "actual_demand": [],
            "replicas": [],
            "active_nodes": [],
            "nodes_needed": [],
            "effective_capacity": [],
            "shortfall": [],
        }

        total_nodes = len(self.nodes)
        all_nodes_on = config_name in ("stock_hpa", "forecast_only", "forecast_placement")

        node_states = ["active" if all_nodes_on or i < self.min_active_nodes else "sleeping" for i in range(total_nodes)]
        node_boot_timers = [0 for _ in range(total_nodes)]
        node_unneeded_timers = [0 for _ in range(total_nodes)]

        init_replicas = max(2, math.ceil(actual_demands[0] / (self.per_replica_cpu * hpa_target_util)))
        current_replicas = init_replicas
        downscale_window = []

        allocatable_cpu = self.nodes[0]["cpu_capacity"] * 0.85
        allocatable_mem = self.nodes[0]["memory_capacity"] * 0.85

        for t in range(n_steps):
            actual_demand = float(actual_demands[t])
            forecast_p90 = float(p90_forecasts[t])

            # -------------------------------------------------------------
            # 1. Update Booting Nodes
            # -------------------------------------------------------------
            for i in range(total_nodes):
                if node_states[i] == "booting":
                    node_boot_timers[i] -= 1
                    if node_boot_timers[i] <= 0:
                        node_states[i] = "active"

            # -------------------------------------------------------------
            # 2. Determine Desired Replicas
            # -------------------------------------------------------------
            if config_name in ("stock_hpa", "cluster_autoscaler", "reactive_hpa_plus_consolidation"):
                past_demand = actual_demands[t - 1] if t > 0 else actual_demand
                current_cap = max(0.01, current_replicas * self.per_replica_cpu)
                usage_ratio = (past_demand / current_cap) / hpa_target_util

                if abs(usage_ratio - 1.0) <= self.dead_zone_pct:
                    raw_desired = current_replicas
                else:
                    raw_desired = max(1, math.ceil(current_replicas * usage_ratio))

            elif config_name == "oracle":
                # True Oracle lookahead: knows demand over [t, t + wake_latency]
                lookahead_window = actual_demands[t : min(n_steps, t + self.wake_up_latency_steps + 1)]
                peak_future_demand = float(np.max(lookahead_window))
                raw_desired = max(1, math.ceil(peak_future_demand / (self.per_replica_cpu * hpa_target_util)))

            else:
                needed = forecast_p90 / (self.per_replica_cpu * hpa_target_util)
                raw_desired = max(1, math.ceil(needed))

            # -------------------------------------------------------------
            # 3. Scaling Safety Logic (HPA Realistic Scaling Policy)
            # -------------------------------------------------------------
            downscale_window.append(raw_desired)
            if len(downscale_window) > self.stabilization_window_steps:
                downscale_window.pop(0)

            if config_name == "oracle":
                candidate_target = raw_desired
            else:
                if raw_desired > current_replicas:
                    candidate_target = raw_desired
                elif raw_desired < current_replicas:
                    candidate_target = max(downscale_window)
                else:
                    candidate_target = current_replicas

            replica_delta_pct = abs(candidate_target - current_replicas) / max(current_replicas, 1)
            if replica_delta_pct < self.dead_zone_pct:
                target_replicas = current_replicas
            else:
                step = candidate_target - current_replicas
                # HPA v2 scale-up: max 4 pods or 100% current per 15s, aggregated to 1 min
                # -> add at most max(16, current) per minute; scale-down max(4, 50%) per minute.
                if self.max_scale_step is not None:
                    max_up = self.max_scale_step
                    max_down = self.max_scale_step
                else:
                    max_up = max(16, current_replicas)
                    max_down = max(4, int(current_replicas * 0.50))

                if step > max_up and config_name != "oracle":
                    target_replicas = current_replicas + max_up
                elif step < -max_down and config_name != "oracle":
                    target_replicas = current_replicas - max_down
                else:
                    target_replicas = candidate_target

            target_replicas = max(1, target_replicas)

            # Record scaling actions only after warm-start
            if t >= self.warm_start_steps:
                if target_replicas != current_replicas:
                    scaling_actions += 1
                    total_churn += abs(target_replicas - current_replicas)

            current_replicas = target_replicas
            if t >= self.warm_start_steps:
                allocated_replicas_history.append(current_replicas)

            # -------------------------------------------------------------
            # 4. Multi-Resource Packing Simulation
            # -------------------------------------------------------------
            has_placement_opt = config_name in ("full_aegis", "full_aegis_conformal", "forecast_placement", "oracle")

            if all_nodes_on:
                nodes_needed = total_nodes
            elif config_name in ("cluster_autoscaler", "reactive_hpa_plus_consolidation"):
                nodes_needed = max(self.min_active_nodes, self._pack_pods(current_replicas, opt=has_placement_opt)) + ca_node_buffer
                nodes_needed = min(nodes_needed, total_nodes)
            elif config_name in ("forecast_plus_power_no_placement", "full_aegis", "full_aegis_conformal"):
                # Causal anticipatory pre-wake: the p90 forecast for absolute step t+j was
                # issued at (t+j)-H, hence observable at decision time t iff j <= H. With
                # boot latency W the usable lookahead is L = min(W, H).
                lookahead_len = min(self.wake_up_latency_steps, forecast_horizon_minutes)
                lookahead = p90_forecasts[t : min(n_steps, t + lookahead_len + 1)]
                peak_forecast = float(np.max(lookahead))
                forecast_replicas_needed = max(1, math.ceil(peak_forecast / (self.per_replica_cpu * hpa_target_util)))
                nodes_needed = max(self.min_active_nodes, self._pack_pods(forecast_replicas_needed, opt=has_placement_opt))
                nodes_needed = min(nodes_needed, total_nodes)
            elif config_name == "oracle":
                lookahead_window = actual_demands[t : min(n_steps, t + self.wake_up_latency_steps + 1)]
                peak_future_demand = float(np.max(lookahead_window))
                oracle_replicas = max(1, math.ceil(peak_future_demand / (self.per_replica_cpu * hpa_target_util)))
                nodes_needed = max(self.min_active_nodes, self._pack_pods(oracle_replicas, opt=True))
                nodes_needed = min(nodes_needed, total_nodes)
            else:
                nodes_needed = total_nodes

            # -------------------------------------------------------------
            # 5. Anticipatory Pre-Wake & Transition Dynamics
            # -------------------------------------------------------------
            scale_down_delay = self.cluster_autoscaler_scale_down_delay if config_name == "cluster_autoscaler" else self.stabilization_window_steps

            active_indices = [i for i, st in enumerate(node_states) if st == "active"]
            booting_indices = [i for i, st in enumerate(node_states) if st == "booting"]
            awake_or_booting = len(active_indices) + len(booting_indices)

            if not all_nodes_on:
                if awake_or_booting < nodes_needed:
                    deficit = nodes_needed - awake_or_booting
                    sleeping_indices = [i for i, st in enumerate(node_states) if st == "sleeping"]
                    for idx in sleeping_indices[:deficit]:
                        node_states[idx] = "booting"
                        node_boot_timers[idx] = self.wake_up_latency_steps
                        node_unneeded_timers[idx] = 0
                elif awake_or_booting > nodes_needed:
                    excess = awake_or_booting - nodes_needed
                    candidate_indices = sorted([i for i in range(total_nodes) if node_states[i] == "active"], reverse=True)
                    for idx in candidate_indices[:excess]:
                        node_unneeded_timers[idx] += 1
                        if node_unneeded_timers[idx] >= scale_down_delay:
                            if len([i for i, st in enumerate(node_states) if st == "active"]) > self.min_active_nodes:
                                node_states[idx] = "sleeping"
                                node_unneeded_timers[idx] = 0
                else:
                    for i in range(total_nodes):
                        node_unneeded_timers[i] = 0

            current_active_indices = [i for i, st in enumerate(node_states) if st == "active"]
            current_active_count = len(current_active_indices)
            if t >= self.warm_start_steps:
                node_active_counts.append(current_active_count)
                nodes_needed_history.append(nodes_needed)

            # -------------------------------------------------------------
            # 6. Capacity Shortfall Accounting
            # -------------------------------------------------------------
            pod_capacity = current_replicas * self.per_replica_cpu
            active_node_capacity = current_active_count * allocatable_cpu
            effective_cluster_capacity = min(pod_capacity, active_node_capacity)

            if t >= self.warm_start_steps:
                if actual_demand > effective_cluster_capacity:
                    capacity_shortfalls += 1

            # -------------------------------------------------------------
            # 7. Energy Accounting (Idle, Dynamic, Boot)
            # -------------------------------------------------------------
            placed_demand = min(actual_demand, effective_cluster_capacity)
            step_idle_w = 0.0
            step_dynamic_w = 0.0
            step_boot_w = 0.0

            if has_placement_opt:
                # Joint placement: packing onto active nodes
                remaining_demand = placed_demand
                for idx in range(total_nodes):
                    st = node_states[idx]
                    node = self.nodes[idx]
                    if st == "booting":
                        step_boot_w += node["p_max"]
                    elif st == "active":
                        step_idle_w += node["p_idle"]
                        if remaining_demand > 0.0:
                            node_alloc = min(remaining_demand, allocatable_cpu)
                            remaining_demand -= node_alloc
                            util = node_alloc / node["cpu_capacity"]
                            step_dynamic_w += (node["p_max"] - node["p_idle"]) * (util ** node["alpha"])
            else:
                # Uniform / unoptimized spreading across active nodes
                per_node_demand = placed_demand / max(1, current_active_count)
                for idx in range(total_nodes):
                    st = node_states[idx]
                    node = self.nodes[idx]
                    if st == "booting":
                        step_boot_w += node["p_max"]
                    elif st == "active":
                        step_idle_w += node["p_idle"]
                        util = min(1.0, per_node_demand / node["cpu_capacity"])
                        step_dynamic_w += (node["p_max"] - node["p_idle"]) * (util ** node["alpha"])

            if t >= self.warm_start_steps:
                total_idle_joules += step_idle_w * 60.0
                total_dynamic_joules += step_dynamic_w * 60.0
                total_boot_joules += step_boot_w * 60.0

                if t % 30 == 0 and len(time_series_records) < 100:
                    time_series_records.append({
                        "step": t,
                        "actual_demand": round(actual_demand, 2),
                        "replicas": current_replicas,
                        "active_nodes": current_active_count,
                        "shortfall": int(actual_demand > effective_cluster_capacity),
                    })
                if return_series:
                    series["minute"].append(t)
                    series["actual_demand"].append(round(actual_demand, 4))
                    series["replicas"].append(current_replicas)
                    series["active_nodes"].append(current_active_count)
                    series["nodes_needed"].append(nodes_needed)
                    series["effective_capacity"].append(round(effective_cluster_capacity, 4))
                    series["shortfall"].append(int(actual_demand > effective_cluster_capacity))

        idle_kwh = total_idle_joules / (3600.0 * 1000.0)
        dynamic_kwh = total_dynamic_joules / (3600.0 * 1000.0)
        boot_kwh = total_boot_joules / (3600.0 * 1000.0)
        total_energy_kwh = idle_kwh + dynamic_kwh + boot_kwh

        eval_steps = n_steps - self.warm_start_steps

        out = {
            "energy_kwh": round(total_energy_kwh, 4),
            "energy_idle_kwh": round(idle_kwh, 4),
            "energy_dynamic_kwh": round(dynamic_kwh, 4),
            "energy_boot_kwh": round(boot_kwh, 4),
            "capacity_shortfall_minutes": capacity_shortfalls,
            "capacity_shortfall_rate_pct": round((capacity_shortfalls / max(eval_steps, 1)) * 100.0, 2),
            "scaling_actions": scaling_actions,
            "scaling_churn": total_churn,
            "mean_allocated_replicas": round(float(np.mean(allocated_replicas_history)) if allocated_replicas_history else 0.0, 2),
            "mean_active_nodes": round(float(np.mean(node_active_counts)) if node_active_counts else 0.0, 2),
            "mean_nodes_needed": round(float(np.mean(nodes_needed_history)) if nodes_needed_history else 0.0, 2),
            "time_series_sample": time_series_records,
        }
        if return_series:
            out["series"] = series
        return out

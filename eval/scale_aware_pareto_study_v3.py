"""
eval/scale_aware_pareto_study_v3.py

Aegis Scale-Aware Conformal & Matched-Shortfall Pareto Study (v3)
With Widened Grids, 5% Shortfall Target, and Extrapolation Audit.

Key enhancements over v1:
  1. Widened CA utilization grid: 18 points [0.10, 0.15, ..., 0.95]
  2. Widened Aegis tau grid: 13 points [0.3, 0.4, ..., 0.999]
  3. Added 5.0% shortfall target (936.0 min) alongside 0%, 0.1%, 1.0%
  4. Per-app extrapolation tracking (is_extrapolated, extrapolation_side, min/max shortfall)
  5. Extrapolation sensitivity audit: recomputes paired DeltaE for non-extrapolated apps
  6. Per-app delta report: identifies losing apps (Aegis > CA energy) and checks overlap
     with poorly covered apps.
  7. Parallel simulation across CPU cores via multiprocessing.
  8. Provenance integration via eval.provenance.
"""

import argparse
import json
import logging
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.abspath("."))

from datasets.load_real_trace import TOTAL_MINUTES, load_memory_table
from eval.audit_controls import simulate_reactive_with_cooldown
from eval.provenance import compute_config_hash, get_provenance
from ml.evaluation.ablation import AblationStudy
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import QuantileModelWrapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("pareto_study_v3")

CACHE_FILE = "datasets/azure_30_study_apps.parquet"
MODELS_DIR = "ml/models/artifacts_60app"
OUTPUT_JSON = "eval/scale_aware_pareto_results_v3.json"
SENSITIVITY_JSON = "eval/extrapolation_sensitivity.json"

HORIZON_MINUTES = 10
BOOTSTRAP_B = 10000

# Full widened grids
DEFAULT_CA_UTILS = [round(float(x), 2) for x in np.arange(0.10, 0.96, 0.05)]  # 18 points: [0.1, 0.15, ..., 0.95]
DEFAULT_AEGIS_TAUS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999]  # 13 points
TARGET_PERCENTAGES = [0.0, 0.1, 1.0, 5.0]

# Original reference grid points (must be preserved in any subsampling)
ORIGINAL_CA_UTILS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
ORIGINAL_AEGIS_TAUS = [0.5, 0.7, 0.8, 0.9, 0.95, 0.99]

# Poorly covered reference apps noted in sixty-app audit
POORLY_COVERED_APPS = {
    "0e18802d31bf22abefa07cef938d2563cbba9a7155145618501ce2b447bc8e46",
    "fe5c01bb7981a5dcb7aebd13280cebe229cf6e04670b1ccf9442ed0bb0c87381",
}


def compute_target_minutes(target_pct: float, total_eval_minutes: int = 18720) -> float:
    """Converts shortfall target percentage of evaluation window to exact minutes."""
    return round((target_pct / 100.0) * total_eval_minutes, 2)


def paired_bootstrap_ci(a: np.ndarray, b: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 42) -> Tuple[float, float, float]:
    """Computes paired mean difference and 95% bootstrap percentile CI."""
    diff = a - b
    mean_diff = float(np.mean(diff))
    rng = np.random.RandomState(seed)
    n = len(diff)
    boot_means = np.empty(B, dtype=np.float64)
    for i in range(B):
        sample = rng.choice(diff, size=n, replace=True)
        boot_means[i] = np.mean(sample)
    ci_lower = float(np.percentile(boot_means, 2.5))
    ci_upper = float(np.percentile(boot_means, 97.5))
    return mean_diff, ci_lower, ci_upper


def load_study_data() -> Tuple[List[str], List[str], Dict[str, np.ndarray], Dict[str, float]]:
    with open("eval/sixty_app_study_results.json", "r", encoding="utf-8") as f:
        prior = json.load(f)

    calib_apps = prior["app_partition"]["calibrate_apps"]
    test_apps = prior["app_partition"]["test_apps"]
    all_needed = calib_apps + test_apps

    if os.path.exists(CACHE_FILE):
        logger.info(f"Loading cached time series from {CACHE_FILE}...")
        df_cached = pd.read_parquet(CACHE_FILE)
        cores_cols = {col: df_cached[col].to_numpy() for col in all_needed}
    else:
        logger.info(f"Extracting 14-day traces for {len(all_needed)} apps...")
        from eval.run_60app_study import extract_app_time_series
        cores_cols, app_mems = extract_app_time_series(all_needed)
        df_to_cache = pd.DataFrame(cores_cols)
        df_to_cache.to_parquet(CACHE_FILE, index=False)
        logger.info(f"Cached time series saved to {CACHE_FILE}")

    mem_table = load_memory_table() / 1024.0
    mean_mem = float(mem_table.mean())
    app_mems = {app: float(mem_table.get(app, mean_mem)) for app in all_needed}

    return calib_apps, test_apps, cores_cols, app_mems


def compute_rolling_conformal(
    y_test: np.ndarray,
    p90_raw: np.ndarray,
    tau: float,
    H: int = HORIZON_MINUTES,
    W: int = 1440,
) -> np.ndarray:
    residuals = pd.Series(y_test - p90_raw).shift(H)
    offset = residuals.rolling(window=W, min_periods=20).quantile(tau).bfill().fillna(0.0).to_numpy()
    return p90_raw + offset


def compute_adaptive_conformal(
    y_test: np.ndarray,
    p90_raw: np.ndarray,
    gamma: float,
    tau: float = 0.90,
    H: int = HORIZON_MINUTES,
) -> np.ndarray:
    n = len(y_test)
    alpha = 1.0 - tau
    scale = max(float(np.std(y_test - p90_raw)), 1.0)
    adj_p90 = np.zeros(n, dtype=np.float64)
    theta = 0.0

    for t in range(n):
        if t >= H:
            err = 1.0 if y_test[t - H] > adj_p90[t - H] else 0.0
            theta += gamma * (err - alpha) * scale
        adj_p90[t] = p90_raw[t] + theta

    return adj_p90


def interpolate_energy_at_shortfall_detailed(
    points: List[Tuple[float, float]], target_s: float
) -> Dict[str, Any]:
    """
    Computes linear interpolation of energy at target_s on the convex lower envelope.
    Returns:
      {
        'energy': float,
        'is_extrapolated': bool,
        'extrapolation_side': "below_min_shortfall" | "above_max_shortfall" | None,
        'min_shortfall': float,
        'max_shortfall': float
      }
    """
    pts = sorted(points, key=lambda x: x[0])
    s_vals = [p[0] for p in pts]
    e_vals = [p[1] for p in pts]

    min_s = float(s_vals[0])
    max_s = float(s_vals[-1])

    if target_s < min_s:
        return {
            "energy": float(e_vals[0]),
            "is_extrapolated": True,
            "extrapolation_side": "below_min_shortfall",
            "min_shortfall": min_s,
            "max_shortfall": max_s,
        }
    if target_s > max_s:
        return {
            "energy": float(e_vals[-1]),
            "is_extrapolated": True,
            "extrapolation_side": "above_max_shortfall",
            "min_shortfall": min_s,
            "max_shortfall": max_s,
        }

    for i in range(len(pts) - 1):
        s_low, e_low = pts[i]
        s_high, e_high = pts[i + 1]
        if s_low <= target_s <= s_high:
            if s_high == s_low:
                return {
                    "energy": float(e_low),
                    "is_extrapolated": False,
                    "extrapolation_side": None,
                    "min_shortfall": min_s,
                    "max_shortfall": max_s,
                }
            frac = (target_s - s_low) / (s_high - s_low)
            return {
                "energy": float(e_low + frac * (e_high - e_low)),
                "is_extrapolated": False,
                "extrapolation_side": None,
                "min_shortfall": min_s,
                "max_shortfall": max_s,
            }

    return {
        "energy": float(e_vals[-1]),
        "is_extrapolated": False,
        "extrapolation_side": None,
        "min_shortfall": min_s,
        "max_shortfall": max_s,
    }


def _simulate_single_app(args: Tuple) -> Tuple[str, List[Tuple[float, float]], Dict[str, List[Tuple[float, float]]]]:
    """Worker function for parallel per-app simulation."""
    (
        app_id,
        y_test,
        m_test,
        p90_raw,
        p50_raw,
        ca_utils,
        aegis_taus,
        static_q_offsets,
        norm_q_offsets,
    ) = args

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)

    # 1. CA simulations
    ca_pts = []
    for u in ca_utils:
        res_ca = simulate_reactive_with_cooldown(
            study, y_test, m_test, "cluster_autoscaler", enforce_cooldown=False, hpa_target_util=u
        )
        ca_pts.append((float(res_ca["capacity_shortfall_minutes"]), float(res_ca["energy_kwh"])))

    # 2. Aegis simulations
    methods = ["static", "scale_aware", "rolling", "aci_005", "aci_020"]
    aegis_pts = {m: [] for m in methods}

    for tau in aegis_taus:
        # Static
        p90_st = np.maximum(p90_raw + static_q_offsets[tau], p50_raw)
        res_st = study._simulate_configuration(y_test, m_test, p90_st, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        aegis_pts["static"].append((float(res_st["capacity_shortfall_minutes"]), float(res_st["energy_kwh"])))

        # Scale-aware
        p90_no = np.maximum(p90_raw + norm_q_offsets[tau] * np.maximum(p90_raw, 0.5), p50_raw)
        res_no = study._simulate_configuration(y_test, m_test, p90_no, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        aegis_pts["scale_aware"].append((float(res_no["capacity_shortfall_minutes"]), float(res_no["energy_kwh"])))

        # Rolling
        p90_ro = np.maximum(compute_rolling_conformal(y_test, p90_raw, tau=tau), p50_raw)
        res_ro = study._simulate_configuration(y_test, m_test, p90_ro, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        aegis_pts["rolling"].append((float(res_ro["capacity_shortfall_minutes"]), float(res_ro["energy_kwh"])))

        # ACI 005
        p90_a05 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.005, tau=tau), p50_raw)
        res_a05 = study._simulate_configuration(y_test, m_test, p90_a05, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        aegis_pts["aci_005"].append((float(res_a05["capacity_shortfall_minutes"]), float(res_a05["energy_kwh"])))

        # ACI 020
        p90_a20 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.020, tau=tau), p50_raw)
        res_a20 = study._simulate_configuration(y_test, m_test, p90_a20, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        aegis_pts["aci_020"].append((float(res_a20["capacity_shortfall_minutes"]), float(res_a20["energy_kwh"])))

    return app_id, ca_pts, aegis_pts


def run_study(
    ca_utils: List[float],
    aegis_taus: List[float],
    max_workers: int = 6,
    output_json: str = OUTPUT_JSON,
    sensitivity_json: str = SENSITIVITY_JSON,
    targets_pct: Optional[List[float]] = None,
):
    print("=" * 115)
    print("  AEGIS SCALE-AWARE CONFORMAL & MATCHED-SHORTFALL PARETO STUDY (v3 WIDENED GRIDS)")
    print("=" * 115)

    if targets_pct is None:
        targets_pct = TARGET_PERCENTAGES

    n_sims = len(ca_utils) * 20 + len(aegis_taus) * 5 * 20
    est_runtime_s = n_sims * 1.85 / max(1, max_workers)
    print(f"\n[ESTIMATED RUNTIME] Total simulations: {n_sims} across 20 validation apps.")
    print(f"Parallel workers: {max_workers} | Estimated wall-clock runtime: {est_runtime_s:.1f}s (~{est_runtime_s/60:.1f} minutes).")
    print(f"CA grid ({len(ca_utils)} points): {ca_utils}")
    print(f"Aegis tau grid ({len(aegis_taus)} points): {aegis_taus}")
    print(f"Targets: {targets_pct}\n")

    prov = get_provenance()
    config_dict = {
        "ca_utilizations": ca_utils,
        "aegis_taus": aegis_taus,
        "shortfall_targets_pct": targets_pct,
        "shortfall_targets_minutes": {f"{t:.1f}%": compute_target_minutes(t) for t in targets_pct},
        "aci_gammas": [0.005, 0.02],
        "horizon_minutes": HORIZON_MINUTES,
        "rolling_window_steps": 1440,
        "bootstrap_iterations": BOOTSTRAP_B,
    }
    config_hash = compute_config_hash(config_dict)
    prov["config_sha256"] = config_hash

    # Load data
    calib_apps, test_apps, cores_cols, app_mems = load_study_data()
    stamps = pd.date_range("2019-07-01 00:00:00+00:00", periods=TOTAL_MINUTES, freq="1min")

    # Load trained LightGBM models
    models = {}
    import lightgbm as lgb
    for q in (0.1, 0.5, 0.9):
        path = os.path.join(MODELS_DIR, f"aegis_h{HORIZON_MINUTES}m_q{int(q*100)}.txt")
        booster = lgb.Booster(model_file=path)
        models[q] = QuantileModelWrapper(booster, backend="lightgbm", feature_names=booster.feature_name())

    # 1. Calibration offsets
    logger.info("Computing pooled calibration residuals...")
    calib_raw_residuals = []
    calib_norm_residuals = []

    for app in calib_apps:
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": cores_cols[app],
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        valid = (target_idx < TOTAL_MINUTES) & (feat_idx >= 1440)

        feat_cols = [c for c in feat.columns if c not in ("cpu_usage", "timestamp", "workload_id") and pd.api.types.is_numeric_dtype(feat[c])]
        X_app = feat.reset_index(drop=True)[valid][feat_cols]
        y_app = df_app["cpu_usage"].to_numpy()[target_idx[valid]]

        p90 = models[0.9].predict(X_app)
        res_raw = y_app - p90
        res_norm = res_raw / np.maximum(p90, 0.5)

        calib_raw_residuals.extend(res_raw.tolist())
        calib_norm_residuals.extend(res_norm.tolist())

    m_cal = len(calib_norm_residuals)
    norm_q_offsets = {}
    static_q_offsets = {}
    for tau in aegis_taus:
        level = min(1.0, np.ceil((m_cal + 1) * tau) / m_cal)
        norm_q_offsets[tau] = float(np.quantile(calib_norm_residuals, level))
        static_q_offsets[tau] = float(np.quantile(calib_raw_residuals, level))

    # Pre-extract test streams
    logger.info("Extracting test streams for 20 validation apps...")
    test_streams = {}
    test_coverage_records = {"raw": [], "static": [], "scale_aware": [], "rolling": [], "aci_005": [], "aci_020": []}
    app_profiles = {}

    for app in test_apps:
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": cores_cols[app],
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        eval_mask = (target_idx < TOTAL_MINUTES) & (target_idx >= 1440)

        feat_cols = [c for c in feat.columns if c not in ("cpu_usage", "timestamp", "workload_id") and pd.api.types.is_numeric_dtype(feat[c])]
        X_app = feat.reset_index(drop=True)[eval_mask][feat_cols]
        y_test = df_app["cpu_usage"].to_numpy()[target_idx[eval_mask]]
        m_test = df_app["memory_usage"].to_numpy()[target_idx[eval_mask]]

        p90_raw = models[0.9].predict(X_app)
        p50_raw = models[0.5].predict(X_app)

        test_streams[app] = (y_test, m_test, p90_raw, p50_raw)
        app_profiles[app] = {
            "mean_cores": float(np.mean(y_test)),
            "peak_cores": float(np.max(y_test)),
            "is_poorly_covered": app in POORLY_COVERED_APPS,
        }

        # Coverage at nominal tau=0.90
        p90_st = np.maximum(p90_raw + static_q_offsets[0.90], p50_raw)
        p90_no = np.maximum(p90_raw + norm_q_offsets[0.90] * np.maximum(p90_raw, 0.5), p50_raw)
        p90_ro = np.maximum(compute_rolling_conformal(y_test, p90_raw, tau=0.90), p50_raw)
        p90_a05 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.005, tau=0.90), p50_raw)
        p90_a20 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.020, tau=0.90), p50_raw)

        test_coverage_records["raw"].append(float(np.mean(y_test <= p90_raw) * 100.0))
        test_coverage_records["static"].append(float(np.mean(y_test <= p90_st) * 100.0))
        test_coverage_records["scale_aware"].append(float(np.mean(y_test <= p90_no) * 100.0))
        test_coverage_records["rolling"].append(float(np.mean(y_test <= p90_ro) * 100.0))
        test_coverage_records["aci_005"].append(float(np.mean(y_test <= p90_a05) * 100.0))
        test_coverage_records["aci_020"].append(float(np.mean(y_test <= p90_a20) * 100.0))

    # Parallel simulation across test apps
    logger.info(f"Starting parallel simulation across 20 validation apps with {max_workers} processes...")
    sim_tasks = []
    for app in test_apps:
        y_test, m_test, p90_raw, p50_raw = test_streams[app]
        sim_tasks.append((app, y_test, m_test, p90_raw, p50_raw, ca_utils, aegis_taus, static_q_offsets, norm_q_offsets))

    ca_pareto_points = {}
    aegis_pareto_points = {m: {} for m in ["static", "scale_aware", "rolling", "aci_005", "aci_020"]}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_simulate_single_app, task): task[0] for task in sim_tasks}
        completed = 0
        for fut in as_completed(futures):
            app_id, ca_pts, ae_pts_dict = fut.result()
            ca_pareto_points[app_id] = ca_pts
            for m in ae_pts_dict:
                aegis_pareto_points[m][app_id] = ae_pts_dict[m]
            completed += 1
            logger.info(f"Completed app [{completed}/20]: {app_id[:16]}...")

    # Build Matched Shortfall Pareto Report & Extrapolation Audit
    logger.info("Computing matched-shortfall Pareto points and extrapolation statistics...")
    pareto_report = {}
    sensitivity_report = {}

    methods = ["static", "scale_aware", "rolling", "aci_005", "aci_020"]

    for target_pct in targets_pct:
        target_label = f"{target_pct:.1f}%"
        target_minutes = compute_target_minutes(target_pct)
        pareto_report[target_label] = {}
        sensitivity_report[target_label] = {}

        for m in methods:
            per_app_dict = {}
            ca_energies = []
            aegis_energies = []
            deltas = []
            ca_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}
            aegis_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}
            ca_extrap_count = 0
            aegis_extrap_count = 0

            interpolated_only_deltas = []
            interpolated_app_ids = []
            losing_apps = []

            for app in test_apps:
                ca_interp = interpolate_energy_at_shortfall_detailed(ca_pareto_points[app], target_minutes)
                ae_interp = interpolate_energy_at_shortfall_detailed(aegis_pareto_points[m][app], target_minutes)

                ca_e = ca_interp["energy"]
                ae_e = ae_interp["energy"]
                d_e = ae_e - ca_e

                ca_energies.append(ca_e)
                aegis_energies.append(ae_e)
                deltas.append(d_e)

                if ca_interp["is_extrapolated"]:
                    ca_extrap_count += 1
                    ca_extrap_sides[ca_interp["extrapolation_side"]] += 1
                else:
                    ca_extrap_sides["none"] += 1

                if ae_interp["is_extrapolated"]:
                    aegis_extrap_count += 1
                    aegis_extrap_sides[ae_interp["extrapolation_side"]] += 1
                else:
                    aegis_extrap_sides["none"] += 1

                # Extrapolation sensitivity: neither frontier extrapolated
                if not ca_interp["is_extrapolated"] and not ae_interp["is_extrapolated"]:
                    interpolated_only_deltas.append(d_e)
                    interpolated_app_ids.append(app)

                # Losing app tracking (Aegis > CA energy)
                if d_e > 0.0:
                    losing_apps.append({
                        "app_id": app,
                        "delta_energy_kwh": round(d_e, 3),
                        "mean_cores": round(app_profiles[app]["mean_cores"], 3),
                        "peak_cores": round(app_profiles[app]["peak_cores"], 2),
                        "is_poorly_covered": app_profiles[app]["is_poorly_covered"],
                    })

                per_app_dict[app] = {
                    "ca_energy": round(ca_e, 2),
                    "aegis_energy": round(ae_e, 2),
                    "delta_energy": round(d_e, 2),
                    "ca_is_extrapolated": ca_interp["is_extrapolated"],
                    "ca_extrapolation_side": ca_interp["extrapolation_side"],
                    "ca_min_shortfall": round(ca_interp["min_shortfall"], 2),
                    "ca_max_shortfall": round(ca_interp["max_shortfall"], 2),
                    "aegis_is_extrapolated": ae_interp["is_extrapolated"],
                    "aegis_extrapolation_side": ae_interp["extrapolation_side"],
                    "aegis_min_shortfall": round(ae_interp["min_shortfall"], 2),
                    "aegis_max_shortfall": round(ae_interp["max_shortfall"], 2),
                }

            # All-apps statistics
            m_delta, ci_l, ci_u = paired_bootstrap_ci(np.array(aegis_energies), np.array(ca_energies))
            ca_med = float(np.median(ca_energies))
            ae_med = float(np.median(aegis_energies))
            diff_of_meds = ae_med - ca_med
            cheaper_pct = float(np.mean(np.array(aegis_energies) < np.array(ca_energies)) * 100.0)

            # Interpolated-only sensitivity statistics
            n_interp = len(interpolated_only_deltas)
            if n_interp >= 8:
                interp_mean, interp_ci_l, interp_ci_u = paired_bootstrap_ci(
                    np.array(interpolated_only_deltas), np.zeros(n_interp)
                )
                interp_status = "valid"
                interp_res = {
                    "n_included": n_interp,
                    "status": interp_status,
                    "mean_delta_energy": round(interp_mean, 2),
                    "bootstrap_ci95": [round(interp_ci_l, 2), round(interp_ci_u, 2)],
                }
            else:
                interp_status = "underpowered"
                interp_res = {
                    "n_included": n_interp,
                    "status": interp_status,
                    "note": f"Fewer than 8 apps remain ({n_interp}/20) without extrapolation at this target",
                    "mean_delta_energy": round(float(np.mean(interpolated_only_deltas)), 2) if n_interp > 0 else None,
                    "bootstrap_ci95": None,
                }

            pareto_report[target_label][m] = {
                "target_shortfall_minutes": target_minutes,
                "ca_median_energy": round(ca_med, 2),
                "aegis_median_energy": round(ae_med, 2),
                "median_diff_energy": round(diff_of_meds, 2),
                "mean_delta_energy": round(m_delta, 3),
                "bootstrap_ci95": [round(ci_l, 3), round(ci_u, 3)],
                "cheaper_fraction_pct": round(cheaper_pct, 2),
                "ca_extrapolations": ca_extrap_count,
                "aegis_extrapolations": aegis_extrap_count,
                "ca_extrapolation_sides": ca_extrap_sides,
                "aegis_extrapolation_sides": aegis_extrap_sides,
                "interpolated_only": interp_res,
                "per_app_results": per_app_dict,
                "losing_apps": losing_apps,
            }

            sensitivity_report[target_label][m] = {
                "n_total": len(test_apps),
                "n_included": n_interp,
                "status": interp_status,
                "included_app_ids": interpolated_app_ids,
                "mean_delta_energy": interp_res.get("mean_delta_energy"),
                "bootstrap_ci95": interp_res.get("bootstrap_ci95"),
            }

    # Coverage summary
    cov_summary = {
        "test_apps_count": len(test_apps),
        "median_iqr": {
            k: [
                round(float(np.median(test_coverage_records[k])), 2),
                round(float(np.percentile(test_coverage_records[k], 75) - np.percentile(test_coverage_records[k], 25)), 2),
            ]
            for k in test_coverage_records
        },
    }

    # Final v3 payload
    final_payload = {
        "git_commit": prov["git_commit"],
        "dirty_flag": prov["dirty_flag"],
        "config_hash": prov["config_sha256"],
        "timestamp_utc": prov["timestamp_utc"],
        "seeds": [42],
        "configuration": config_dict,
        "coverage_summary": cov_summary,
        "matched_shortfall_pareto": pareto_report,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)
    logger.info(f"Results written to {output_json}")

    with open(sensitivity_json, "w", encoding="utf-8") as f:
        json.dump({"provenance": prov, "threshold_minimum_apps": 8, "sensitivity": sensitivity_report}, f, indent=2)
    logger.info(f"Extrapolation sensitivity written to {sensitivity_json}")


def main():
    parser = argparse.ArgumentParser(description="Run Aegis Pareto Study v3 with widened grids.")
    parser.add_argument("--max-ca-utils", type=int, default=None, help="Subsample CA utils grid to max points")
    parser.add_argument("--max-taus", type=int, default=None, help="Subsample Aegis taus grid to max points")
    parser.add_argument("--workers", type=int, default=6, help="Number of parallel worker processes")
    parser.add_argument("--output", "-o", default=OUTPUT_JSON, help="Output JSON path")
    parser.add_argument("--sensitivity-output", default=SENSITIVITY_JSON, help="Sensitivity JSON path")
    parser.add_argument("--targets", nargs="+", type=float, default=None, help="Target shortfall percentages")
    args = parser.parse_args()

    ca_utils = DEFAULT_CA_UTILS
    if args.max_ca_utils is not None and args.max_ca_utils < len(DEFAULT_CA_UTILS):
        # Always preserve original grid points
        extra_allowed = args.max_ca_utils - len(ORIGINAL_CA_UTILS)
        extra_points = [p for p in DEFAULT_CA_UTILS if p not in ORIGINAL_CA_UTILS]
        if extra_allowed > 0:
            step = max(1, len(extra_points) // extra_allowed)
            chosen_extras = extra_points[::step][:extra_allowed]
            ca_utils = sorted(ORIGINAL_CA_UTILS + chosen_extras)
        else:
            ca_utils = ORIGINAL_CA_UTILS

    aegis_taus = DEFAULT_AEGIS_TAUS
    if args.max_taus is not None and args.max_taus < len(DEFAULT_AEGIS_TAUS):
        extra_allowed = args.max_taus - len(ORIGINAL_AEGIS_TAUS)
        extra_points = [p for p in DEFAULT_AEGIS_TAUS if p not in ORIGINAL_AEGIS_TAUS]
        if extra_allowed > 0:
            step = max(1, len(extra_points) // extra_allowed)
            chosen_extras = extra_points[::step][:extra_allowed]
            aegis_taus = sorted(ORIGINAL_AEGIS_TAUS + chosen_extras)
        else:
            aegis_taus = ORIGINAL_AEGIS_TAUS

    run_study(
        ca_utils,
        aegis_taus,
        max_workers=args.workers,
        output_json=args.output,
        sensitivity_json=args.sensitivity_output,
        targets_pct=args.targets,
    )


if __name__ == "__main__":
    main()

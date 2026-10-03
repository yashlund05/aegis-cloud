"""
eval/headline_study_v4.py

Task W1: Headline results from one clean run.
Unified evaluation study producing eval/headline_results_v4.json.

Key features:
1. Provenance metadata tracking (git commit, clean dirty_flag=False, timestamp, config hash).
2. Protocol-compliant evaluation on 20 validation apps under Split Protocol.
3. Primary arm: Rolling Conformal (W=1440, H=10).
   Secondary / Ablation arms: ACI 0.005, ACI 0.020, Scale-Aware, Static Split Conformal.
4. Matched-shortfall Pareto frontiers across targets:
   - Primary: 1.0% (187.2 min)
   - Secondary: 0.1% (18.72 min)
   - Supplementary: 0.0% (0.0 min), 5.0% (936.0 min)
5. Degenerate frontier audit & sensitivity analysis (excluding extrapolated and degenerate apps).
6. Energy above floor metric (E_floor = 62.40 kWh for 2 nodes * 100W * 312h).
7. Natural Operating Point comparisons:
   - Aegis at tau=0.90 vs CA at U=0.50 and U=0.60.
   - Paired delta energy, delta shortfall, bootstrap 95% CIs.
   - Wilcoxon signed-rank test (two-sided and one-sided), Holm-Bonferroni correction, rank-biserial effect size.
   - Dominance counting (dominant, dominated, tradeoff, identical).
8. Stratification by mean-cores tertiles (Low, Mid, High load) embedded directly in JSON schema.
9. Equal-headroom reactive baseline integration from audit controls.
10. Correct sign convention throughout: Delta E = E_Aegis - E_CA (negative = Aegis cheaper).
"""

import argparse
import json
import logging
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import lightgbm as lgb
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
logger = logging.getLogger("headline_study_v4")

CACHE_FILE = "datasets/azure_30_study_apps.parquet"
MODELS_DIR = "ml/models/artifacts_60app"
OUTPUT_JSON = "eval/headline_results_v4.json"
AUDIT_CONTROLS_JSON = "eval/audit_controls_results.json"

HORIZON_MINUTES = 10
BOOTSTRAP_B = 10000
E_FLOOR_KWH = 62.40  # 2 nodes * 100W * 312 hours = 62.40 kWh

# Full widened grids (from Decision D-5)
DEFAULT_CA_UTILS = [round(float(x), 2) for x in np.arange(0.10, 0.96, 0.05)]  # 18 points: [0.1, 0.15, ..., 0.95]
DEFAULT_AEGIS_TAUS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999]  # 13 points
TARGET_PERCENTAGES = [0.0, 0.1, 1.0, 5.0]

PRIMARY_ARM = "rolling"
ALL_ARMS = ["rolling", "scale_aware", "aci_005", "aci_020", "static"]

POORLY_COVERED_APPS = {
    "0e18802d31bf22abefa07cef938d2563cbba9a7155145618501ce2b447bc8e46",
    "fe5c01bb7981a5dcb7aebd13280cebe229cf6e04670b1ccf9442ed0bb0c87381",
}


def compute_target_minutes(target_pct: float, total_eval_minutes: int = 18720) -> float:
    return round((target_pct / 100.0) * total_eval_minutes, 2)


def paired_bootstrap_ci(a: np.ndarray, b: np.ndarray, B: int = BOOTSTRAP_B, seed: int = 42) -> Tuple[float, float, float]:
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


def compute_rank_biserial(diff: np.ndarray) -> Tuple[float, float, float]:
    nonzero = diff[diff != 0]
    if len(nonzero) == 0:
        return 0.0, 1.0, 1.0
    try:
        res_two = wilcoxon(diff, alternative="two-sided")
        p_two = float(res_two.pvalue)
    except Exception:
        p_two = 1.0
    try:
        res_less = wilcoxon(diff, alternative="less")
        p_less = float(res_less.pvalue)
    except Exception:
        p_less = 1.0

    ranks = np.argsort(np.argsort(np.abs(nonzero))) + 1
    w_pos = float(np.sum(ranks[nonzero > 0]))
    w_neg = float(np.sum(ranks[nonzero < 0]))
    total = float(np.sum(ranks))
    r_rb = (w_pos - w_neg) / total if total > 0 else 0.0
    return float(r_rb), p_two, p_less


def holm_bonferroni(p_vals: List[float]) -> List[float]:
    m = len(p_vals)
    if m == 0:
        return []
    sorted_indices = np.argsort(p_vals)
    sorted_p = np.array(p_vals)[sorted_indices]
    adj_p = np.empty(m)
    for i in range(m):
        adj_p[i] = min(1.0, (m - i) * sorted_p[i])
    for i in range(1, m):
        adj_p[i] = max(adj_p[i], adj_p[i - 1])
    orig_adj_p = np.empty(m)
    orig_adj_p[sorted_indices] = adj_p
    return [float(x) for x in orig_adj_p]


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
    T = len(y_test)
    p90_rolling = np.empty(T, dtype=np.float64)
    calib_residuals = []

    for t in range(T):
        if t >= H:
            t_eval = t - H
            calib_residuals.append(y_test[t_eval] - p90_raw[t_eval])
            if len(calib_residuals) > W:
                calib_residuals.pop(0)

        if len(calib_residuals) < 10:
            p90_rolling[t] = p90_raw[t]
        else:
            n = len(calib_residuals)
            level = math.ceil((n + 1) * tau) / n
            level = min(1.0, max(0.0, level))
            q_offset = np.quantile(calib_residuals, level)
            p90_rolling[t] = p90_raw[t] + q_offset

    return p90_rolling


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


def interpolate_energy_at_shortfall(
    points: List[Tuple[float, float]],
    target_s: float,
) -> Dict[str, Any]:
    pts = sorted(points, key=lambda x: x[0])
    s_vals = [p[0] for p in pts]
    e_vals = [p[1] for p in pts]

    min_s = float(s_vals[0])
    max_s = float(s_vals[-1])

    is_degenerate = bool(len(np.unique(s_vals)) <= 1 or min_s == max_s)

    if target_s < min_s:
        return {
            "energy": float(e_vals[0]),
            "is_extrapolated": True,
            "extrapolation_side": "below_min_shortfall",
            "min_shortfall": min_s,
            "max_shortfall": max_s,
            "is_degenerate": is_degenerate,
        }
    if target_s > max_s:
        return {
            "energy": float(e_vals[-1]),
            "is_extrapolated": True,
            "extrapolation_side": "above_max_shortfall",
            "min_shortfall": min_s,
            "max_shortfall": max_s,
            "is_degenerate": is_degenerate,
        }

    for i in range(len(pts) - 1):
        s_low, e_low = pts[i]
        s_high, e_high = pts[i + 1]
        if s_low <= target_s <= s_high:
            if s_high == s_low:
                return {
                    "energy": float(e_low),
                    "is_extrapolated": False,
                    "extrapolation_side": "none",
                    "min_shortfall": min_s,
                    "max_shortfall": max_s,
                    "is_degenerate": is_degenerate,
                }
            frac = (target_s - s_low) / (s_high - s_low)
            return {
                "energy": float(e_low + frac * (e_high - e_low)),
                "is_extrapolated": False,
                "extrapolation_side": "none",
                "min_shortfall": min_s,
                "max_shortfall": max_s,
                "is_degenerate": is_degenerate,
            }

    return {
        "energy": float(e_vals[-1]),
        "is_extrapolated": False,
        "extrapolation_side": "none",
        "min_shortfall": min_s,
        "max_shortfall": max_s,
        "is_degenerate": is_degenerate,
    }


def _simulate_single_app(args: Tuple) -> Tuple[str, List[Tuple[float, float]], Dict[str, List[Tuple[float, float]]], Dict[str, Any]]:
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
    ca_operating_points = {}
    for u in ca_utils:
        res_ca = simulate_reactive_with_cooldown(
            study, y_test, m_test, "cluster_autoscaler", enforce_cooldown=False, hpa_target_util=u
        )
        s_ca = float(res_ca["capacity_shortfall_minutes"])
        e_ca = float(res_ca["energy_kwh"])
        ca_pts.append((s_ca, e_ca))
        ca_operating_points[round(u, 2)] = {"shortfall": s_ca, "energy": e_ca}

    # 2. Aegis simulations
    aegis_pts = {m: [] for m in ALL_ARMS}
    aegis_operating_points = {m: {} for m in ALL_ARMS}

    for tau in aegis_taus:
        tau_key = round(tau, 3)

        # Static
        p90_st = np.maximum(p90_raw + static_q_offsets[tau], p50_raw)
        res_st = study._simulate_configuration(y_test, m_test, p90_st, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        st_s, st_e = float(res_st["capacity_shortfall_minutes"]), float(res_st["energy_kwh"])
        aegis_pts["static"].append((st_s, st_e))
        aegis_operating_points["static"][tau_key] = {"shortfall": st_s, "energy": st_e}

        # Scale-aware
        p90_no = np.maximum(p90_raw + norm_q_offsets[tau] * np.maximum(p90_raw, 0.5), p50_raw)
        res_no = study._simulate_configuration(y_test, m_test, p90_no, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        sa_s, sa_e = float(res_no["capacity_shortfall_minutes"]), float(res_no["energy_kwh"])
        aegis_pts["scale_aware"].append((sa_s, sa_e))
        aegis_operating_points["scale_aware"][tau_key] = {"shortfall": sa_s, "energy": sa_e}

        # Rolling
        p90_ro = np.maximum(compute_rolling_conformal(y_test, p90_raw, tau=tau), p50_raw)
        res_ro = study._simulate_configuration(y_test, m_test, p90_ro, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        ro_s, ro_e = float(res_roll_s := res_ro["capacity_shortfall_minutes"]), float(res_ro["energy_kwh"])
        aegis_pts["rolling"].append((ro_s, ro_e))
        aegis_operating_points["rolling"][tau_key] = {"shortfall": ro_s, "energy": ro_e}

        # ACI 005
        p90_a05 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.005, tau=tau), p50_raw)
        res_a05 = study._simulate_configuration(y_test, m_test, p90_a05, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        a05_s, a05_e = float(res_a05["capacity_shortfall_minutes"]), float(res_a05["energy_kwh"])
        aegis_pts["aci_005"].append((a05_s, a05_e))
        aegis_operating_points["aci_005"][tau_key] = {"shortfall": a05_s, "energy": a05_e}

        # ACI 020
        p90_a20 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.020, tau=tau), p50_raw)
        res_a20 = study._simulate_configuration(y_test, m_test, p90_a20, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        a20_s, a20_e = float(res_a20["capacity_shortfall_minutes"]), float(res_a20["energy_kwh"])
        aegis_pts["aci_020"].append((a20_s, a20_e))
        aegis_operating_points["aci_020"][tau_key] = {"shortfall": a20_s, "energy": a20_e}

    raw_sim_results = {
        "ca_operating_points": ca_operating_points,
        "aegis_operating_points": aegis_operating_points,
    }

    return app_id, ca_pts, aegis_pts, raw_sim_results


def run_headline_study(
    ca_utils: List[float],
    aegis_taus: List[float],
    max_workers: int = 6,
    output_json: str = OUTPUT_JSON,
    targets_pct: Optional[List[float]] = None,
) -> None:
    targets_pct = targets_pct or TARGET_PERCENTAGES

    config_dict = {
        "protocol": "SPLIT_PROTOCOL",
        "primary_arm": PRIMARY_ARM,
        "secondary_arms": [a for a in ALL_ARMS if a != PRIMARY_ARM],
        "horizon_minutes": HORIZON_MINUTES,
        "bootstrap_b": BOOTSTRAP_B,
        "ca_utilizations": [round(float(x), 2) for x in ca_utils],
        "aegis_taus": [round(float(x), 3) for x in aegis_taus],
        "shortfall_targets_pct": targets_pct,
        "energy_floor_kwh": E_FLOOR_KWH,
        "natural_operating_points": {
            "aegis_tau": 0.90,
            "ca_utilizations": [0.50, 0.60],
        },
    }

    prov = get_provenance(config_dict)
    logger.info(f"Provenance initialized: commit={prov['git_commit']}, dirty={prov['dirty_flag']}")

    calib_apps, test_apps, cores_cols, app_mems = load_study_data()
    stamps = pd.date_range("2019-07-01 00:00:00+00:00", periods=TOTAL_MINUTES, freq="1min")
    logger.info(f"Loaded {len(calib_apps)} calibration apps and {len(test_apps)} validation apps.")

    # Sort validation apps by mean cores to establish tertiles
    app_mean_cores = {app: float(cores_cols[app].mean()) for app in test_apps}
    app_peak_cores = {app: float(np.percentile(cores_cols[app], 99.9)) for app in test_apps}
    sorted_test_apps = sorted(test_apps, key=lambda a: app_mean_cores[a])

    # Tertile assignment: Low (7 apps), Mid (7 apps), High (6 apps)
    tertiles = {
        "low_load": sorted_test_apps[:7],
        "mid_load": sorted_test_apps[7:14],
        "high_load": sorted_test_apps[14:],
    }

    app_profiles = {
        app: {
            "mean_cores": app_mean_cores[app],
            "peak_cores": app_peak_cores[app],
            "tertile": "low_load" if app in tertiles["low_load"] else ("mid_load" if app in tertiles["mid_load"] else "high_load"),
            "is_poorly_covered": app in POORLY_COVERED_APPS,
        }
        for app in test_apps
    }

    # Load LightGBM models
    models = {}
    for q in (0.1, 0.5, 0.9):
        path = os.path.join(MODELS_DIR, f"aegis_h{HORIZON_MINUTES}m_q{int(q*100)}.txt")
        booster = lgb.Booster(model_file=path)
        models[q] = QuantileModelWrapper(booster, backend="lightgbm", feature_names=booster.feature_name())

    # Step 1: Calibration phase
    logger.info("Computing pooled calibration residuals across 10 calibration apps...")
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

    # Step 2: Test phase stream extraction & coverage tracking
    logger.info(f"Extracting test streams and computing coverage on {len(test_apps)} validation apps...")
    test_streams = {}
    test_coverage_records = {"raw": [], "static": [], "scale_aware": [], "rolling": [], "aci_005": [], "aci_020": []}

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

    # Step 3: Run simulations in parallel
    logger.info(f"Starting parallel simulation across 20 validation apps with {max_workers} processes...")
    sim_tasks = []
    for app in test_apps:
        y_test, m_test, p90_raw, p50_raw = test_streams[app]
        sim_tasks.append((app, y_test, m_test, p90_raw, p50_raw, ca_utils, aegis_taus, static_q_offsets, norm_q_offsets))

    ca_pareto_points = {}
    aegis_pareto_points = {m: {} for m in ALL_ARMS}
    app_raw_sim_results = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_simulate_single_app, task): task[0] for task in sim_tasks}
        completed = 0
        for fut in as_completed(futures):
            app_id, ca_pts, ae_pts_dict, raw_res = fut.result()
            ca_pareto_points[app_id] = ca_pts
            for m in ALL_ARMS:
                aegis_pareto_points[m][app_id] = ae_pts_dict[m]
            app_raw_sim_results[app_id] = raw_res
            completed += 1
            if completed % 5 == 0 or completed == len(sim_tasks):
                logger.info(f"Progress: {completed}/{len(sim_tasks)} apps simulated.")

    # Step 4: Matched-Shortfall Pareto Calculation across targets
    logger.info("Computing matched-shortfall Pareto frontiers, CIs, degenerate checks, and tertiles...")
    pareto_report = {}
    total_eval_minutes = len(test_streams[test_apps[0]][0])

    for target_pct in targets_pct:
        target_minutes = compute_target_minutes(target_pct, total_eval_minutes)
        target_label = f"{target_pct:.1f}%"
        pareto_report[target_label] = {}

        for m in ALL_ARMS:
            ca_energies = []
            aegis_energies = []
            deltas = []
            deltas_above_floor = []

            ca_extrap_count = 0
            aegis_extrap_count = 0
            ca_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}
            aegis_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}

            interpolated_only_deltas = []
            interpolated_app_ids = []
            non_degenerate_deltas = []
            non_degenerate_app_ids = []
            clean_cohort_deltas = []  # neither extrapolated NOR degenerate
            clean_cohort_app_ids = []

            losing_apps = []
            degenerate_apps = []
            per_app_dict = {}

            for app in test_apps:
                ca_pts = ca_pareto_points[app]
                ae_pts = aegis_pareto_points[m][app]

                ca_interp = interpolate_energy_at_shortfall(ca_pts, target_minutes)
                ae_interp = interpolate_energy_at_shortfall(ae_pts, target_minutes)

                ca_e = float(ca_interp["energy"])
                ae_e = float(ae_interp["energy"])
                d_e = ae_e - ca_e

                ca_e_above = max(0.0, ca_e - E_FLOOR_KWH)
                ae_e_above = max(0.0, ae_e - E_FLOOR_KWH)
                d_e_above = ae_e_above - ca_e_above

                ca_energies.append(ca_e)
                aegis_energies.append(ae_e)
                deltas.append(d_e)
                deltas_above_floor.append(d_e_above)

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

                # Degenerate tracking
                if ae_interp["is_degenerate"]:
                    degenerate_apps.append({
                        "app_id": app,
                        "min_shortfall": round(ae_interp["min_shortfall"], 2),
                        "max_shortfall": round(ae_interp["max_shortfall"], 2),
                    })
                else:
                    non_degenerate_deltas.append(d_e)
                    non_degenerate_app_ids.append(app)

                # Extrapolation sensitivity: neither frontier extrapolated
                is_clean_interp = not ca_interp["is_extrapolated"] and not ae_interp["is_extrapolated"]
                if is_clean_interp:
                    interpolated_only_deltas.append(d_e)
                    interpolated_app_ids.append(app)

                if is_clean_interp and not ae_interp["is_degenerate"]:
                    clean_cohort_deltas.append(d_e)
                    clean_cohort_app_ids.append(app)

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
                    "ca_energy_above_floor": round(ca_e_above, 2),
                    "aegis_energy_above_floor": round(ae_e_above, 2),
                    "delta_energy_above_floor": round(d_e_above, 2),
                    "ca_is_extrapolated": ca_interp["is_extrapolated"],
                    "ca_extrapolation_side": ca_interp["extrapolation_side"],
                    "ca_min_shortfall": round(ca_interp["min_shortfall"], 2),
                    "ca_max_shortfall": round(ca_interp["max_shortfall"], 2),
                    "aegis_is_extrapolated": ae_interp["is_extrapolated"],
                    "aegis_extrapolation_side": ae_interp["extrapolation_side"],
                    "aegis_min_shortfall": round(ae_interp["min_shortfall"], 2),
                    "aegis_max_shortfall": round(ae_interp["max_shortfall"], 2),
                    "aegis_is_degenerate": ae_interp["is_degenerate"],
                }

            # All-apps statistics
            m_delta, ci_l, ci_u = paired_bootstrap_ci(np.array(aegis_energies), np.array(ca_energies))
            m_delta_above, ci_l_above, ci_u_above = paired_bootstrap_ci(np.array(deltas_above_floor), np.zeros(len(deltas_above_floor)))
            ca_med = float(np.median(ca_energies))
            ae_med = float(np.median(aegis_energies))
            diff_of_meds = ae_med - ca_med
            cheaper_pct = float(np.mean(np.array(aegis_energies) < np.array(ca_energies)) * 100.0)

            # Tertile stratification
            tertile_results = {}
            for t_name, t_apps in tertiles.items():
                t_ca_e = [per_app_dict[a]["ca_energy"] for a in t_apps]
                t_ae_e = [per_app_dict[a]["aegis_energy"] for a in t_apps]
                t_delta, t_ci_l, t_ci_u = paired_bootstrap_ci(np.array(t_ae_e), np.array(t_ca_e))
                t_ca_med = float(np.median(t_ca_e))
                t_ae_med = float(np.median(t_ae_e))
                tertile_results[t_name] = {
                    "n_apps": len(t_apps),
                    "ca_median_energy": round(t_ca_med, 2),
                    "aegis_median_energy": round(t_ae_med, 2),
                    "median_diff_energy": round(t_ae_med - t_ca_med, 2),
                    "mean_delta_energy": round(t_delta, 2),
                    "bootstrap_ci95": [round(t_ci_l, 2), round(t_ci_u, 2)],
                    "cheaper_fraction_pct": round(float(np.mean(np.array(t_ae_e) < np.array(t_ca_e)) * 100.0), 2),
                }

            # Interpolated-only sensitivity
            n_interp = len(interpolated_only_deltas)
            if n_interp >= 8:
                interp_mean, interp_ci_l, interp_ci_u = paired_bootstrap_ci(
                    np.array(interpolated_only_deltas), np.zeros(n_interp)
                )
                interp_res = {
                    "n_included": n_interp,
                    "status": "valid",
                    "mean_delta_energy": round(interp_mean, 2),
                    "bootstrap_ci95": [round(interp_ci_l, 2), round(interp_ci_u, 2)],
                }
            else:
                interp_res = {
                    "n_included": n_interp,
                    "status": "underpowered",
                    "note": f"Fewer than 8 apps remain ({n_interp}/20) without extrapolation at this target",
                    "mean_delta_energy": round(float(np.mean(interpolated_only_deltas)), 2) if n_interp > 0 else None,
                    "bootstrap_ci95": None,
                }

            # Clean cohort sensitivity (non-extrapolated AND non-degenerate)
            n_clean = len(clean_cohort_deltas)
            if n_clean >= 8:
                clean_mean, clean_ci_l, clean_ci_u = paired_bootstrap_ci(
                    np.array(clean_cohort_deltas), np.zeros(n_clean)
                )
                clean_res = {
                    "n_included": n_clean,
                    "status": "valid",
                    "mean_delta_energy": round(clean_mean, 2),
                    "bootstrap_ci95": [round(clean_ci_l, 2), round(clean_ci_u, 2)],
                }
            else:
                clean_res = {
                    "n_included": n_clean,
                    "status": "underpowered",
                    "note": f"Fewer than 8 apps remain ({n_clean}/20) in clean non-degenerate cohort",
                    "mean_delta_energy": round(float(np.mean(clean_cohort_deltas)), 2) if n_clean > 0 else None,
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
                "mean_delta_energy_above_floor": round(m_delta_above, 3),
                "bootstrap_ci95_above_floor": [round(ci_l_above, 3), round(ci_u_above, 3)],
                "ca_extrapolations": ca_extrap_count,
                "aegis_extrapolations": aegis_extrap_count,
                "ca_extrapolation_sides": ca_extrap_sides,
                "aegis_extrapolation_sides": aegis_extrap_sides,
                "degenerate_frontiers_count": len(degenerate_apps),
                "degenerate_apps": degenerate_apps,
                "interpolated_only": interp_res,
                "clean_cohort": clean_res,
                "tertiles": tertile_results,
                "per_app_results": per_app_dict,
                "losing_apps": losing_apps,
            }

    # Step 5: Natural Operating Points Comparison (tau=0.90 vs CA U=0.50, U=0.60)
    logger.info("Computing natural operating point comparisons (tau=0.90 vs CA U=0.50, U=0.60)...")
    operating_points_report = {}
    p_values_to_correct = []
    p_meta = []

    for m in ALL_ARMS:
        operating_points_report[m] = {}
        for ca_u in [0.50, 0.60]:
            u_key = f"ca_u_{int(ca_u*100)}"
            ae_energies = []
            ca_energies = []
            ae_shortfalls = []
            ca_shortfalls = []
            delta_e_list = []
            delta_s_list = []
            per_app_op = {}

            n_dominant = 0
            n_dominated = 0
            n_tradeoff = 0
            n_identical = 0

            for app in test_apps:
                raw = app_raw_sim_results[app]
                ae_pt = raw["aegis_operating_points"][m][0.90]
                ca_pt = raw["ca_operating_points"][round(ca_u, 2)]

                ae_e = float(ae_pt["energy"])
                ca_e = float(ca_pt["energy"])
                ae_s = float(ae_pt["shortfall"])
                ca_s = float(ca_pt["shortfall"])

                d_e = ae_e - ca_e
                d_s = ae_s - ca_s

                ae_energies.append(ae_e)
                ca_energies.append(ca_e)
                ae_shortfalls.append(ae_s)
                ca_shortfalls.append(ca_s)
                delta_e_list.append(d_e)
                delta_s_list.append(d_s)

                # Dominance check
                if (ae_e <= ca_e and ae_s <= ca_s) and (ae_e < ca_e or ae_s < ca_s):
                    dominance = "dominant"
                    n_dominant += 1
                elif (ae_e >= ca_e and ae_s >= ca_s) and (ae_e > ca_e or ae_s > ca_s):
                    dominance = "dominated"
                    n_dominated += 1
                elif (ae_e == ca_e and ae_s == ca_s):
                    dominance = "identical"
                    n_identical += 1
                else:
                    dominance = "tradeoff"
                    n_tradeoff += 1

                per_app_op[app] = {
                    "aegis_energy": round(ae_e, 2),
                    "ca_energy": round(ca_e, 2),
                    "delta_energy": round(d_e, 2),
                    "aegis_shortfall": round(ae_s, 2),
                    "ca_shortfall": round(ca_s, 2),
                    "delta_shortfall": round(d_s, 2),
                    "dominance": dominance,
                }

            # Statistics
            m_delta_e, ci_l_e, ci_u_e = paired_bootstrap_ci(np.array(ae_energies), np.array(ca_energies))
            m_delta_s, ci_l_s, ci_u_s = paired_bootstrap_ci(np.array(ae_shortfalls), np.array(ca_shortfalls))
            ae_med_e = float(np.median(ae_energies))
            ca_med_e = float(np.median(ca_energies))
            ae_med_s = float(np.median(ae_shortfalls))
            ca_med_s = float(np.median(ca_shortfalls))

            r_rb, p_two, p_less = compute_rank_biserial(np.array(delta_e_list))
            p_values_to_correct.append(p_two)
            p_meta.append((m, u_key))

            # Tertile breakdown for operating point
            tertile_op = {}
            for t_name, t_apps in tertiles.items():
                t_ae_e = [per_app_op[a]["aegis_energy"] for a in t_apps]
                t_ca_e = [per_app_op[a]["ca_energy"] for a in t_apps]
                t_ae_s = [per_app_op[a]["aegis_shortfall"] for a in t_apps]
                t_ca_s = [per_app_op[a]["ca_shortfall"] for a in t_apps]
                t_delta_e, t_ci_l_e, t_ci_u_e = paired_bootstrap_ci(np.array(t_ae_e), np.array(t_ca_e))
                t_delta_s, t_ci_l_s, t_ci_u_s = paired_bootstrap_ci(np.array(t_ae_s), np.array(t_ca_s))
                tertile_op[t_name] = {
                    "n_apps": len(t_apps),
                    "ca_median_energy": round(float(np.median(t_ca_e)), 2),
                    "aegis_median_energy": round(float(np.median(t_ae_e)), 2),
                    "mean_delta_energy": round(t_delta_e, 2),
                    "bootstrap_ci95_energy": [round(t_ci_l_e, 2), round(t_ci_u_e, 2)],
                    "ca_median_shortfall": round(float(np.median(t_ca_s)), 2),
                    "aegis_median_shortfall": round(float(np.median(t_ae_s)), 2),
                    "mean_delta_shortfall": round(t_delta_s, 2),
                    "bootstrap_ci95_shortfall": [round(t_ci_l_s, 2), round(t_ci_u_s, 2)],
                    "cheaper_fraction_pct": round(float(np.mean(np.array(t_ae_e) < np.array(t_ca_e)) * 100.0), 2),
                }

            operating_points_report[m][u_key] = {
                "aegis_tau": 0.90,
                "ca_target_utilization": ca_u,
                "ca_median_energy": round(ca_med_e, 2),
                "aegis_median_energy": round(ae_med_e, 2),
                "median_diff_energy": round(ae_med_e - ca_med_e, 2),
                "mean_delta_energy": round(m_delta_e, 3),
                "bootstrap_ci95_energy": [round(ci_l_e, 3), round(ci_u_e, 3)],
                "ca_median_shortfall": round(ca_med_s, 2),
                "aegis_median_shortfall": round(ae_med_s, 2),
                "median_diff_shortfall": round(ae_med_s - ca_med_s, 2),
                "mean_delta_shortfall": round(m_delta_s, 3),
                "bootstrap_ci95_shortfall": [round(ci_l_s, 3), round(ci_u_s, 3)],
                "cheaper_fraction_pct": round(float(np.mean(np.array(ae_energies) < np.array(ca_energies)) * 100.0), 2),
                "lower_shortfall_fraction_pct": round(float(np.mean(np.array(ae_shortfalls) < np.array(ca_shortfalls)) * 100.0), 2),
                "dominance_counts": {
                    "dominant": n_dominant,
                    "dominated": n_dominated,
                    "tradeoff": n_tradeoff,
                    "identical": n_identical,
                },
                "wilcoxon_two_sided_p": round(p_two, 6),
                "wilcoxon_one_sided_p_less": round(p_less, 6),
                "rank_biserial_effect_size": round(r_rb, 4),
                "tertiles": tertile_op,
                "per_app_results": per_app_op,
            }

    # Step 6: Holm-Bonferroni correction across operating point comparisons
    adj_p_values = holm_bonferroni(p_values_to_correct)
    for (m, u_key), adj_p in zip(p_meta, adj_p_values):
        operating_points_report[m][u_key]["wilcoxon_holm_bonferroni_p"] = round(adj_p, 6)

    # Step 7: Load Audit Controls baseline for comparison
    equal_headroom_control = None
    if os.path.exists(AUDIT_CONTROLS_JSON):
        try:
            with open(AUDIT_CONTROLS_JSON, "r", encoding="utf-8") as f:
                ac_data = json.load(f)
            dist = ac_data.get("control_arms_distributions", {})
            equal_headroom_control = {
                "source_file": AUDIT_CONTROLS_JSON,
                "calibrated_static_headroom_cores": 8.6468,
                "control_arm_a_reactive_headroom": dist.get("reactive_plus_headroom"),
                "control_arm_b_ca_hpa_guards": dist.get("cluster_autoscaler_faithful"),
                "aegis_conformal_baseline": dist.get("full_aegis_conformal"),
            }
        except Exception as e:
            logger.warning(f"Could not load audit controls results: {e}")

    # Step 8: Coverage summary
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

    # Final Payload
    final_payload = {
        "schema_version": "v4",
        "study_name": "Aegis Clean Headline Benchmark Study",
        "git_commit": prov["git_commit"],
        "dirty_flag": prov["dirty_flag"],
        "config_hash": prov["config_sha256"],
        "timestamp_utc": prov["timestamp_utc"],
        "python_version": sys.version,
        "seeds": [42],
        "configuration": config_dict,
        "app_partition": {
            "calibrate_apps_count": len(calib_apps),
            "test_apps_count": len(test_apps),
            "calibrate_apps": calib_apps,
            "test_apps": test_apps,
            "tertiles": {
                "low_load": tertiles["low_load"],
                "mid_load": tertiles["mid_load"],
                "high_load": tertiles["high_load"],
            },
        },
        "coverage_summary": cov_summary,
        "matched_shortfall_pareto": pareto_report,
        "natural_operating_points": operating_points_report,
        "equal_headroom_control": equal_headroom_control,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(final_payload, f, indent=2)
    logger.info(f"Clean headline study completed. Output saved to {output_json}")


def main():
    parser = argparse.ArgumentParser(description="Run Aegis Clean Headline Study (v4).")
    parser.add_argument("--workers", type=int, default=6, help="Number of parallel worker processes")
    parser.add_argument("--output", "-o", default=OUTPUT_JSON, help="Output JSON path")
    args = parser.parse_args()

    run_headline_study(
        DEFAULT_CA_UTILS,
        DEFAULT_AEGIS_TAUS,
        max_workers=args.workers,
        output_json=args.output,
        targets_pct=TARGET_PERCENTAGES,
    )


if __name__ == "__main__":
    main()

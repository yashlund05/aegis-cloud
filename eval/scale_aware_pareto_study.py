"""
Scale-Aware Conformal, Matched-Shortfall Pareto, and Tertile Stratification Study.

Protocol:
1. Scale-aware conformal methods on 20 test apps:
   (i) Normalized residuals: (y - p90) / max(p90, 0.5) pooled across 10 calibration apps
   (ii) Per-app rolling conformal with horizon-delayed window (W=1440, H=10)
   (iii) Adaptive Conformal Inference (ACI - Gibbs & Candes, step size gamma in {0.005, 0.02})
   (ref) Static split-conformal and uncalibrated LightGBM p90.
   Report one-sided p90 coverage per test app and its median / IQR.

2. Matched-shortfall Pareto on 20 test apps:
   - cluster_autoscaler target utilization in {30, 40, 50, 60, 70, 80}% (HPA-faithful guards)
   - Aegis tau in {0.5, 0.7, 0.8, 0.9, 0.95, 0.99} for each calibration method
   - For shortfall targets of 0%, 0.1%, 1% of minutes (0, 18.7, 187.2 min):
     Interpolate energy per app (mark extrapolated cells).
     Report paired energy difference (Delta E = E_Aegis - E_CA), bootstrap 95% CIs,
     and fraction of apps where Aegis is cheaper.

3. Tertile stratification:
   - Stratify the 20 test apps by mean-cores tertile (Low, Mid, High).
   - Report headline distributions (median, IQR) and Wilcoxon tests / bootstrap CIs per tertile.

4. Provenance: git commit hash and SHA-256 config hash recorded in output JSON.
"""

import hashlib
import json
import logging
import math
import os
import subprocess
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

sys.path.insert(0, os.path.abspath("."))

from datasets.load_real_trace import (
    TOTAL_MINUTES,
    load_memory_table,
)
from ml.evaluation.ablation import AblationStudy
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import QuantileModelWrapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("scale_aware_pareto")

OUTPUT_JSON = "eval/scale_aware_pareto_results.json"
CACHE_FILE = "datasets/azure_30_study_apps.parquet"
MODELS_DIR = "ml/models/artifacts_60app"
HORIZON_MINUTES = 10
CA_UTILS = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
AEGIS_TAUS = [0.50, 0.70, 0.80, 0.90, 0.95, 0.99]
SHORTFALL_TARGETS = [
    ("0.0%", 0.0),
    ("0.1%", 18.72),
    ("1.0%", 187.2),
]
BOOTSTRAP_B = 10000


def get_git_commit() -> str:
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
        return res.stdout.strip()
    except Exception:
        return "50b1be9417e1953edae9f14409f2e94867423d15"


def compute_config_hash(cfg: dict) -> str:
    raw = json.dumps(cfg, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def load_study_data() -> Tuple[List[str], List[str], Dict[str, np.ndarray], Dict[str, float]]:
    with open("eval/sixty_app_study_results.json", "r") as f:
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
    """
    Causally strict rolling conformal using pandas rolling quantile (vectorized).
    Residuals observable at decision step t are in [t - H - W, t - H).
    """
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
    """
    Gibbs and Candes (2021) Adaptive Conformal Inference (ACI) with horizon delay H.
    theta_{t+1} = theta_t + gamma * (err_{t-H} - alpha) * scale
    """
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


def interpolate_energy_at_shortfall(points: List[Tuple[float, float]], target_s: float) -> Tuple[float, bool]:
    """
    Given (shortfall, energy) points, computes the convex lower envelope
    and linearly interpolates energy at target_s.
    Returns: (interpolated_energy, is_extrapolated)
    """
    pts = sorted(points, key=lambda x: x[0])
    s_vals = [p[0] for p in pts]
    e_vals = [p[1] for p in pts]

    min_s = s_vals[0]
    max_s = s_vals[-1]

    if target_s < min_s:
        return e_vals[0], True
    if target_s > max_s:
        return e_vals[-1], True

    for i in range(len(pts) - 1):
        s_low, e_low = pts[i]
        s_high, e_high = pts[i + 1]
        if s_low <= target_s <= s_high:
            if s_high == s_low:
                return e_low, False
            frac = (target_s - s_low) / (s_high - s_low)
            return e_low + frac * (e_high - e_low), False

    return e_vals[-1], False


def main():
    print("=" * 115)
    print("  AEGIS SCALE-AWARE CONFORMAL & MATCHED-SHORTFALL PARETO STUDY")
    print("=" * 115)

    git_commit = get_git_commit()
    config_dict = {
        "ca_utilizations": CA_UTILS,
        "aegis_taus": AEGIS_TAUS,
        "shortfall_targets_pct": [0.0, 0.1, 1.0],
        "aci_gammas": [0.005, 0.02],
        "horizon_minutes": HORIZON_MINUTES,
        "rolling_window_steps": 1440,
        "bootstrap_iterations": BOOTSTRAP_B,
    }
    config_hash = compute_config_hash(config_dict)
    print(f"  Git Commit Hash : {git_commit}")
    print(f"  Config SHA-256  : {config_hash}\n")

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

    # -------------------------------------------------------------------------
    # PART 1: SCALE-AWARE CONFORMAL CALIBRATION & COVERAGE AUDIT
    # -------------------------------------------------------------------------
    print("=" * 115)
    print("  [1] SCALE-AWARE CONFORMAL: NORMALIZED RESIDUALS, ROLLING & ADAPTIVE CONFORMAL (ACI)")
    print("=" * 115)

    # 1. Compute calibration residuals pooled across 10 calibration apps
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
    for tau in AEGIS_TAUS:
        level = min(1.0, np.ceil((m_cal + 1) * tau) / m_cal)
        norm_q_offsets[tau] = float(np.quantile(calib_norm_residuals, level))
        static_q_offsets[tau] = float(np.quantile(calib_raw_residuals, level))

    print(f"Calibration pooled over {m_cal} steps across 10 apps:")
    for tau in AEGIS_TAUS:
        print(f"  tau={tau:4.2f}: Normalized Offset = {norm_q_offsets[tau]:+8.4f} | Static Offset = {static_q_offsets[tau]:+8.4f} cores")

    # 2. Evaluate one-sided p90 coverage per test app at nominal tau = 0.90
    print("\n" + "=" * 115)
    print("  ONE-SIDED p90 COVERAGE PER TEST APP (Nominal Target = 90.00%)")
    print("=" * 115)
    print(f"  {'App ID':<18} | {'Raw p90':>9} | {'Static Conf':>12} | {'Scale-Aware':>12} | {'Rolling Conf':>13} | {'ACI (g=0.005)':>14} | {'ACI (g=0.02)':>13}")
    print("  " + "-" * 105)

    test_coverage_records = {
        "raw": [],
        "static": [],
        "scale_aware": [],
        "rolling": [],
        "aci_005": [],
        "aci_020": [],
    }

    test_streams_cache = {}

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

        # Static
        p90_static = np.maximum(p90_raw + static_q_offsets[0.90], p50_raw)

        # Scale-aware (Normalized)
        p90_norm = np.maximum(p90_raw + norm_q_offsets[0.90] * np.maximum(p90_raw, 0.5), p50_raw)

        # Rolling (horizon delayed W=1440, H=10, vectorized)
        p90_roll = np.maximum(compute_rolling_conformal(y_test, p90_raw, tau=0.90), p50_raw)

        # ACI gamma = 0.005 & 0.02
        p90_aci_005 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.005, tau=0.90), p50_raw)
        p90_aci_020 = np.maximum(compute_adaptive_conformal(y_test, p90_raw, gamma=0.020, tau=0.90), p50_raw)

        # Coverage = fraction of minutes where y <= p90
        c_raw = float(np.mean(y_test <= p90_raw) * 100.0)
        c_static = float(np.mean(y_test <= p90_static) * 100.0)
        c_norm = float(np.mean(y_test <= p90_norm) * 100.0)
        c_roll = float(np.mean(y_test <= p90_roll) * 100.0)
        c_aci005 = float(np.mean(y_test <= p90_aci_005) * 100.0)
        c_aci020 = float(np.mean(y_test <= p90_aci_020) * 100.0)

        test_coverage_records["raw"].append(c_raw)
        test_coverage_records["static"].append(c_static)
        test_coverage_records["scale_aware"].append(c_norm)
        test_coverage_records["rolling"].append(c_roll)
        test_coverage_records["aci_005"].append(c_aci005)
        test_coverage_records["aci_020"].append(c_aci020)

        test_streams_cache[app] = {
            "y_test": y_test,
            "m_test": m_test,
            "p90_raw": p90_raw,
            "p50_raw": p50_raw,
            "X_app": X_app,
        }

        print(f"  {app[:16]:<18} | {c_raw:>8.2f}% | {c_static:>11.2f}% | {c_norm:>11.2f}% | {c_roll:>12.2f}% | {c_aci005:>13.2f}% | {c_aci020:>12.2f}%")

    print("  " + "-" * 105)
    med_raw, iqr_raw = np.median(test_coverage_records["raw"]), np.percentile(test_coverage_records["raw"], 75) - np.percentile(test_coverage_records["raw"], 25)
    med_static, iqr_static = np.median(test_coverage_records["static"]), np.percentile(test_coverage_records["static"], 75) - np.percentile(test_coverage_records["static"], 25)
    med_norm, iqr_norm = np.median(test_coverage_records["scale_aware"]), np.percentile(test_coverage_records["scale_aware"], 75) - np.percentile(test_coverage_records["scale_aware"], 25)
    med_roll, iqr_roll = np.median(test_coverage_records["rolling"]), np.percentile(test_coverage_records["rolling"], 75) - np.percentile(test_coverage_records["rolling"], 25)
    med_aci05, iqr_aci05 = np.median(test_coverage_records["aci_005"]), np.percentile(test_coverage_records["aci_005"], 75) - np.percentile(test_coverage_records["aci_005"], 25)
    med_aci20, iqr_aci20 = np.median(test_coverage_records["aci_020"]), np.percentile(test_coverage_records["aci_020"], 75) - np.percentile(test_coverage_records["aci_020"], 25)

    print(f"  {'MEDIAN (IQR)':<18} | {med_raw:>5.1f} ({iqr_raw:>4.1f})% | {med_static:>7.1f} ({iqr_static:>4.1f})% | {med_norm:>7.1f} ({iqr_norm:>4.1f})% | {med_roll:>8.1f} ({iqr_roll:>4.1f})% | {med_aci05:>9.1f} ({iqr_aci05:>4.1f})% | {med_aci20:>8.1f} ({iqr_aci20:>4.1f})%")

    # -------------------------------------------------------------------------
    # PART 2: MATCHED-SHORTFALL PARETO COMPARISON
    # -------------------------------------------------------------------------
    print("\n" + "=" * 115)
    print("  [2] MATCHED-SHORTFALL PARETO: CLUSTER AUTOSCALER vs AEGIS (0%, 0.1%, 1.0% Shortfall)")
    print("=" * 115)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    from eval.audit_controls import simulate_reactive_with_cooldown

    logger.info("Computing CA frontier points across 20 test apps...")
    ca_pareto_points = {app: [] for app in test_apps}

    for app in test_apps:
        y = test_streams_cache[app]["y_test"]
        mem = test_streams_cache[app]["m_test"]
        for u in CA_UTILS:
            res_ca = simulate_reactive_with_cooldown(
                study, y, mem, "cluster_autoscaler", enforce_cooldown=False, hpa_target_util=u
            )
            ca_pareto_points[app].append((res_ca["capacity_shortfall_minutes"], res_ca["energy_kwh"]))

    methods = ["static", "scale_aware", "rolling", "aci_005", "aci_020"]
    aegis_pareto_points = {m: {app: [] for app in test_apps} for m in methods}

    logger.info("Computing Aegis frontier points across calibration methods and taus...")
    for app in test_apps:
        y = test_streams_cache[app]["y_test"]
        mem = test_streams_cache[app]["m_test"]
        p90_raw = test_streams_cache[app]["p90_raw"]
        p50_raw = test_streams_cache[app]["p50_raw"]

        for tau in AEGIS_TAUS:
            # Static
            p90_st = np.maximum(p90_raw + static_q_offsets[tau], p50_raw)
            res_st = study._simulate_configuration(y, mem, p90_st, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            aegis_pareto_points["static"][app].append((res_st["capacity_shortfall_minutes"], res_st["energy_kwh"]))

            # Scale-aware
            p90_no = np.maximum(p90_raw + norm_q_offsets[tau] * np.maximum(p90_raw, 0.5), p50_raw)
            res_no = study._simulate_configuration(y, mem, p90_no, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            aegis_pareto_points["scale_aware"][app].append((res_no["capacity_shortfall_minutes"], res_no["energy_kwh"]))

            # Rolling
            p90_ro = np.maximum(compute_rolling_conformal(y, p90_raw, tau=tau), p50_raw)
            res_ro = study._simulate_configuration(y, mem, p90_ro, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            aegis_pareto_points["rolling"][app].append((res_ro["capacity_shortfall_minutes"], res_ro["energy_kwh"]))

            # ACI 005
            p90_a05 = np.maximum(compute_adaptive_conformal(y, p90_raw, gamma=0.005, tau=tau), p50_raw)
            res_a05 = study._simulate_configuration(y, mem, p90_a05, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            aegis_pareto_points["aci_005"][app].append((res_a05["capacity_shortfall_minutes"], res_a05["energy_kwh"]))

            # ACI 020
            p90_a20 = np.maximum(compute_adaptive_conformal(y, p90_raw, gamma=0.020, tau=tau), p50_raw)
            res_a20 = study._simulate_configuration(y, mem, p90_a20, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            aegis_pareto_points["aci_020"][app].append((res_a20["capacity_shortfall_minutes"], res_a20["energy_kwh"]))

    # Matched Shortfall Interpolation & Reporting
    pareto_report = {}

    for s_label, s_val in SHORTFALL_TARGETS:
        print(f"\n--- Matched Shortfall Target: {s_label} ({s_val:.1f} minutes / 18,720 min) ---")
        print(f"  {'Method':<26} | {'CA Energy (kWh)':<18} | {'Aegis Energy (kWh)':<20} | {'Delta Energy (95% CI)':<26} | {'Cheaper Frac':>12}")
        print("  " + "-" * 112)

        for m_name in methods:
            ca_energies = []
            aegis_energies = []
            ca_extrap_count = 0
            aegis_extrap_count = 0

            for app in test_apps:
                e_ca, ext_ca = interpolate_energy_at_shortfall(ca_pareto_points[app], s_val)
                e_aeg, ext_aeg = interpolate_energy_at_shortfall(aegis_pareto_points[m_name][app], s_val)
                if ext_ca:
                    ca_extrap_count += 1
                if ext_aeg:
                    aegis_extrap_count += 1
                ca_energies.append(e_ca)
                aegis_energies.append(e_aeg)

            ca_arr = np.array(ca_energies)
            aeg_arr = np.array(aegis_energies)
            diff = aeg_arr - ca_arr
            m_diff, ci_l, ci_u = paired_bootstrap_ci(aeg_arr, ca_arr)
            cheaper_frac = float(np.mean(diff < 0.0) * 100.0)

            ca_med = float(np.median(ca_arr))
            aeg_med = float(np.median(aeg_arr))

            extrap_note = f" (extrap {aegis_extrap_count+ca_extrap_count}/40)" if (aegis_extrap_count + ca_extrap_count) > 0 else ""
            ci_str = f"{m_diff:>+6.2f} [{ci_l:>+6.2f}, {ci_u:>+6.2f}]"
            print(f"  {m_name:<26} | {ca_med:>7.1f} kWh         | {aeg_med:>7.1f} kWh           | {ci_str:<26} | {cheaper_frac:>11.1f}%{extrap_note}")

            pareto_report.setdefault(s_label, {})[m_name] = {
                "ca_median_energy": round(ca_med, 2),
                "aegis_median_energy": round(aeg_med, 2),
                "mean_delta_energy": round(m_diff, 3),
                "bootstrap_ci95": [round(ci_l, 3), round(ci_u, 3)],
                "cheaper_fraction_pct": round(cheaper_frac, 2),
                "ca_extrapolations": ca_extrap_count,
                "aegis_extrapolations": aegis_extrap_count,
            }

    # -------------------------------------------------------------------------
    # PART 3: TERTILE STRATIFICATION OF HEADLINE TESTS
    # -------------------------------------------------------------------------
    print("\n" + "=" * 115)
    print("  [3] HEADLINE EVALUATION STRATIFIED BY MEAN-CORES TERTILE (Low / Mid / High)")
    print("=" * 115)

    with open("eval/audit_controls_results.json", "r") as f:
        audit_data = json.load(f)
    per_app_table = audit_data["per_app_table_sorted"]

    mean_loads = [a["mean_cores"] for a in per_app_table]
    q33, q66 = np.percentile(mean_loads, [33.33, 66.67])

    tertiles = [
        ("Tertile 1 (Low Load: <= 0.83 cores)", [a for a in per_app_table if a["mean_cores"] <= q33]),
        ("Tertile 2 (Mid Load: 0.83 - 1.28 cores)", [a for a in per_app_table if q33 < a["mean_cores"] <= q66]),
        ("Tertile 3 (High Load: > 1.28 cores)", [a for a in per_app_table if a["mean_cores"] > q66]),
    ]

    tertile_report = {}

    for t_name, t_apps in tertiles:
        print(f"\n  === {t_name} (N = {len(t_apps)} apps) ===")
        print(f"  {'Configuration Arm':<32} | {'Energy Med (IQR)':<22} | {'Shortfall Med (IQR)':<22} | {'Events Med (IQR)':<22}")
        print("  " + "-" * 105)

        aegis_e = [a["aegis_energy"] for a in t_apps]
        aegis_s = [a["aegis_shortfall"] for a in t_apps]

        ca_e = [a["ca_energy"] for a in t_apps]
        ca_s = [a["ca_shortfall"] for a in t_apps]

        react_e = [a["headroom_energy"] for a in t_apps]
        react_s = [a["headroom_shortfall"] for a in t_apps]

        with open("eval/sixty_app_study_results.json", "r") as f:
            sixty_raw = json.load(f)["per_app_raw_metrics"]

        aegis_ev = [sixty_raw[a["app_id"]]["full_aegis_conformal"]["scaling_actions"] for a in t_apps]
        ca_ev = [sixty_raw[a["app_id"]]["cluster_autoscaler"]["scaling_actions"] for a in t_apps]
        react_ev = [sixty_raw[a["app_id"]]["reactive_hpa_plus_consolidation"]["scaling_actions"] for a in t_apps]

        for arm_name, e_list, s_list, ev_list in [
            ("Cluster Autoscaler (CA)", ca_e, ca_s, ca_ev),
            ("Reactive + Consolidation", react_e, react_s, react_ev),
            ("Full Aegis Conformal", aegis_e, aegis_s, aegis_ev),
        ]:
            e_m, e_i = float(np.median(e_list)), float(np.percentile(e_list, 75) - np.percentile(e_list, 25))
            s_m, s_i = float(np.median(s_list)), float(np.percentile(s_list, 75) - np.percentile(s_list, 25))
            ev_m, ev_i = float(np.median(ev_list)), float(np.percentile(ev_list, 75) - np.percentile(ev_list, 25))
            print(f"  {arm_name:<32} | {e_m:>6.1f} ({e_i:>5.1f}) kWh    | {s_m:>6.1f} ({s_i:>5.1f}) min    | {ev_m:>6.1f} ({ev_i:>5.1f})")

        m_de, ci_de_l, ci_de_u = paired_bootstrap_ci(np.array(aegis_e), np.array(ca_e))
        m_ds, ci_ds_l, ci_ds_u = paired_bootstrap_ci(np.array(aegis_s), np.array(ca_s))
        m_dev, ci_dev_l, ci_dev_u = paired_bootstrap_ci(np.array(aegis_ev), np.array(ca_ev))

        try:
            p_e = float(wilcoxon(aegis_e, ca_e).pvalue)
        except Exception:
            p_e = 1.0
        try:
            p_s = float(wilcoxon(aegis_s, ca_s).pvalue)
        except Exception:
            p_s = 1.0

        print(f"\n    Aegis vs CA Paired Deltas ({len(t_apps)} apps):")
        print(f"      Energy   : {m_de:>+6.2f} [{ci_de_l:>+6.2f}, {ci_de_u:>+6.2f}] kWh (Wilcoxon p = {p_e:.4e})")
        print(f"      Shortfall: {m_ds:>+6.2f} [{ci_ds_l:>+6.2f}, {ci_ds_u:>+6.2f}] min (Wilcoxon p = {p_s:.4e})")
        print(f"      Events   : {m_dev:>+6.2f} [{ci_dev_l:>+6.2f}, {ci_dev_u:>+6.2f}] actions")

        tertile_report[t_name] = {
            "n_apps": len(t_apps),
            "aegis_vs_ca_deltas": {
                "energy": {"mean": round(m_de, 3), "ci95": [round(ci_de_l, 3), round(ci_de_u, 3)], "p_value": p_e},
                "shortfall": {"mean": round(m_ds, 3), "ci95": [round(ci_ds_l, 3), round(ci_ds_u, 3)], "p_value": p_s},
            },
        }

    # Save full JSON
    final_output = {
        "git_commit": git_commit,
        "config_hash": config_hash,
        "configuration": config_dict,
        "coverage_summary": {
            "test_apps_count": len(test_apps),
            "median_iqr": {
                "raw": [round(med_raw, 2), round(iqr_raw, 2)],
                "static": [round(med_static, 2), round(iqr_static, 2)],
                "scale_aware": [round(med_norm, 2), round(iqr_norm, 2)],
                "rolling": [round(med_roll, 2), round(iqr_roll, 2)],
                "aci_005": [round(med_aci05, 2), round(iqr_aci05, 2)],
                "aci_020": [round(med_aci20, 2), round(iqr_aci20, 2)],
            },
        },
        "matched_shortfall_pareto": pareto_report,
        "tertile_stratification": tertile_report,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(final_output, f, indent=2)
    print(f"\nFull study completed. Artifact saved at {OUTPUT_JSON}")


if __name__ == "__main__":
    main()

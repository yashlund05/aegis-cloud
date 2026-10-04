"""
eval/baselines_study.py

Task W3: Baselines and ablations evaluated through the frozen v5 simulation pipeline.
Evaluates alternative forecasters (seasonal_naive, holt_winters, quantile_linear,
lightgbm_point_rolling) and component ablations (fixed_margin, no_cpsat_ffd) along with
the reference Aegis rolling conformal arm on the 20 validation applications.
"""

import argparse
import json
import logging
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import wilcoxon
from statsmodels.tsa.holtwinters import ExponentialSmoothing

sys.path.insert(0, os.path.abspath("."))

from datasets.load_real_trace import TOTAL_MINUTES, load_memory_table
from eval.audit_controls import simulate_reactive_with_cooldown
from eval.headline_study_v4 import (
    BOOTSTRAP_B,
    CACHE_FILE,
    DEFAULT_AEGIS_TAUS,
    DEFAULT_CA_UTILS,
    E_FLOOR_KWH,
    HORIZON_MINUTES,
    MODELS_DIR,
    POORLY_COVERED_APPS,
    TARGET_PERCENTAGES,
    compute_rank_biserial,
    compute_rolling_conformal,
    compute_target_minutes,
    holm_bonferroni,
    interpolate_energy_at_shortfall,
    load_study_data,
    paired_bootstrap_ci,
)
from eval.provenance import compute_config_hash, get_provenance
from ml.evaluation.ablation import AblationStudy
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import QuantileModelWrapper

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("baselines_study")

OUTPUT_JSON = "eval/baselines_results_v1.json"
LINEAR_MODELS_DIR = "ml/models/artifacts_linear"

FORECASTER_ARMS = [
    "rolling",  # Primary Aegis reference (LightGBM p90 + rolling conformal)
    "lightgbm_point_rolling",  # Control: LightGBM p50 + rolling conformal
    "seasonal_naive",  # Lagged actual demand at t-1440 + rolling conformal
    "holt_winters",  # Daily refit ExponentialSmoothing + rolling conformal
    "quantile_linear",  # Linear model (30 train apps) + rolling conformal
]

ABLATION_ARMS = [
    "fixed_margin",  # Raw LightGBM p90 + fixed margin
    "no_cpsat_ffd",  # Aegis rolling conformal with joint placement disabled (FFD fallback)
]

ALL_STUDY_ARMS = FORECASTER_ARMS + ABLATION_ARMS

FIXED_MARGINS = [0.0, 0.5, 1.0, 2.0, 4.0, 8.6468]


def generate_holt_winters_forecast(y_full: np.ndarray) -> np.ndarray:
    """
    Fits ExponentialSmoothing on 10-minute averages with daily refit strictly before
    the scored window, and upsamples to 1-minute steps.
    """
    T = len(y_full)
    hw_stream = np.zeros(T, dtype=np.float64)

    # First 2 days (warmup): lag 1440
    hw_stream[:2880] = np.roll(y_full, 1440)[:2880]
    hw_stream[:1440] = y_full[:1440]

    for d in range(1, 14):
        train_slice = pd.Series(y_full[: d * 1440])
        s_10m = train_slice.groupby(np.arange(len(train_slice)) // 10).mean()
        if d < 2:
            m = ExponentialSmoothing(
                s_10m, trend="add", seasonal=None, initialization_method="heuristic"
            ).fit()
        else:
            m = ExponentialSmoothing(
                s_10m, seasonal_periods=144, trend="add", seasonal="add", initialization_method="heuristic"
            ).fit()
        pred_10m = m.forecast(144).to_numpy()
        pred_1m = np.repeat(pred_10m, 10)
        start_t = d * 1440
        end_t = min(T, (d + 1) * 1440)
        hw_stream[start_t:end_t] = np.maximum(0.0, pred_1m[: end_t - start_t])

    return hw_stream


def _simulate_single_app_baselines(args: Tuple) -> Tuple[str, List[Tuple[float, float]], Dict[str, List[Tuple[float, float]]], Dict[str, Any]]:
    """Worker function for parallel per-app simulation across baselines and ablations."""
    (
        app_id,
        y_test,
        m_test,
        p90_lgb,
        p50_lgb,
        point_streams,
        ca_utils,
        aegis_taus,
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

    # 2. Arm simulations
    arm_pts: Dict[str, List[Tuple[float, float]]] = {m: [] for m in ALL_STUDY_ARMS}
    arm_operating_points: Dict[str, Dict[Any, Dict[str, float]]] = {m: {} for m in ALL_STUDY_ARMS}

    # Primary reference arm: LightGBM p90 + rolling conformal
    for tau in aegis_taus:
        tau_key = round(tau, 3)
        p90_ro = np.maximum(compute_rolling_conformal(y_test, p90_lgb, tau=tau), p50_lgb)
        res_ro = study._simulate_configuration(y_test, m_test, p90_ro, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        ro_s, ro_e = float(res_ro["capacity_shortfall_minutes"]), float(res_ro["energy_kwh"])
        arm_pts["rolling"].append((ro_s, ro_e))
        arm_operating_points["rolling"][tau_key] = {"shortfall": ro_s, "energy": ro_e}

    # Forecaster arms with uniform rolling conformal wrapper
    for arm_name in ["lightgbm_point_rolling", "seasonal_naive", "holt_winters", "quantile_linear"]:
        pt_forecast = point_streams[arm_name]
        for tau in aegis_taus:
            tau_key = round(tau, 3)
            p90_stream = np.maximum(compute_rolling_conformal(y_test, pt_forecast, tau=tau), pt_forecast)
            res = study._simulate_configuration(y_test, m_test, p90_stream, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
            s_val, e_val = float(res["capacity_shortfall_minutes"]), float(res["energy_kwh"])
            arm_pts[arm_name].append((s_val, e_val))
            arm_operating_points[arm_name][tau_key] = {"shortfall": s_val, "energy": e_val}

    # Component ablation: no_cpsat_ffd (rolling conformal with FFD placement fallback, solver bypassed)
    for tau in aegis_taus:
        tau_key = round(tau, 3)
        p90_ro = np.maximum(compute_rolling_conformal(y_test, p90_lgb, tau=tau), p50_lgb)
        res_ffd = study._simulate_configuration(
            y_test, m_test, p90_ro, "forecast_plus_power_no_placement", forecast_horizon_minutes=HORIZON_MINUTES
        )
        ffd_s, ffd_e = float(res_ffd["capacity_shortfall_minutes"]), float(res_ffd["energy_kwh"])
        arm_pts["no_cpsat_ffd"].append((ffd_s, ffd_e))
        arm_operating_points["no_cpsat_ffd"][tau_key] = {"shortfall": ffd_s, "energy": ffd_e}

    # Component ablation: fixed_margin swept over margin grid
    for margin in FIXED_MARGINS:
        m_key = round(float(margin), 4)
        p90_margin = np.maximum(p90_lgb + margin, p50_lgb)
        res_m = study._simulate_configuration(y_test, m_test, p90_margin, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
        m_s, m_e = float(res_m["capacity_shortfall_minutes"]), float(res_m["energy_kwh"])
        arm_pts["fixed_margin"].append((m_s, m_e))
        arm_operating_points["fixed_margin"][m_key] = {"shortfall": m_s, "energy": m_e}

    raw_sim_results = {
        "ca_operating_points": ca_operating_points,
        "arm_operating_points": arm_operating_points,
    }

    return app_id, ca_pts, arm_pts, raw_sim_results


def run_baselines_study(
    ca_utils: List[float] = DEFAULT_CA_UTILS,
    aegis_taus: List[float] = DEFAULT_AEGIS_TAUS,
    max_workers: int = 6,
    output_json: str = OUTPUT_JSON,
    targets_pct: Optional[List[float]] = None,
) -> None:
    targets_pct = targets_pct or TARGET_PERCENTAGES

    config_dict = {
        "protocol": "SPLIT_PROTOCOL",
        "primary_arm": "rolling",
        "forecaster_arms": FORECASTER_ARMS,
        "ablation_arms": ABLATION_ARMS,
        "all_arms": ALL_STUDY_ARMS,
        "horizon_minutes": HORIZON_MINUTES,
        "bootstrap_b": BOOTSTRAP_B,
        "ca_utilizations": [round(float(x), 2) for x in ca_utils],
        "aegis_taus": [round(float(x), 3) for x in aegis_taus],
        "fixed_margins": FIXED_MARGINS,
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

    tertiles = {
        "low_load": sorted_test_apps[:7],
        "mid_load": sorted_test_apps[7:14],
        "high_load": sorted_test_apps[14:],
    }

    # Load LightGBM models
    models = {}
    for q in (0.1, 0.5, 0.9):
        path = os.path.join(MODELS_DIR, f"aegis_h{HORIZON_MINUTES}m_q{int(q*100)}.txt")
        booster = lgb.Booster(model_file=path)
        models[q] = QuantileModelWrapper(booster, backend="lightgbm", feature_names=booster.feature_name())

    # Load linear models
    with open(os.path.join(LINEAR_MODELS_DIR, "feature_columns.json"), "r") as f:
        linear_feat_cols = json.load(f)
    qr_linear_50 = joblib.load(os.path.join(LINEAR_MODELS_DIR, "quantile_linear_q50.joblib"))
    qr_linear_90 = joblib.load(os.path.join(LINEAR_MODELS_DIR, "quantile_linear_q90.joblib"))

    # Step 1: Generate forecaster streams and evaluate forecast quality on validation apps
    logger.info("Generating forecaster streams and measuring forecast quality across validation apps...")
    test_streams = {}
    forecast_quality_rows = []

    for app in test_apps:
        y_full = cores_cols[app]
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": y_full,
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        eval_mask = (target_idx < TOTAL_MINUTES) & (target_idx >= 1440)

        feat_cols = [c for c in feat.columns if c not in ("cpu_usage", "timestamp", "workload_id") and pd.api.types.is_numeric_dtype(feat[c])]
        X_app = feat.reset_index(drop=True)[eval_mask][feat_cols]
        y_test = y_full[target_idx[eval_mask]]
        m_test = df_app["memory_usage"].to_numpy()[target_idx[eval_mask]]

        # 1. LightGBM forecasts
        p90_lgb = models[0.9].predict(X_app)
        p50_lgb = models[0.5].predict(X_app)

        # 2. Seasonal naive forecast (lag 1440)
        target_positions = target_idx[eval_mask]
        lag_positions = target_positions - 1440
        naive_point = y_full[lag_positions]

        # 3. Holt-Winters daily refit forecast
        hw_stream_full = generate_holt_winters_forecast(y_full)
        hw_point = hw_stream_full[target_positions]

        # 4. Quantile linear forecast
        X_linear = feat.reset_index(drop=True)[eval_mask][linear_feat_cols].to_numpy()
        linear_point_50 = qr_linear_50.predict(X_linear)
        linear_point_90 = qr_linear_90.predict(X_linear)

        point_streams = {
            "lightgbm_point_rolling": p50_lgb,
            "seasonal_naive": naive_point,
            "holt_winters": hw_point,
            "quantile_linear": linear_point_90,
        }

        test_streams[app] = (y_test, m_test, p90_lgb, p50_lgb, point_streams)

        # Compute forecast quality metrics for this app
        def compute_metrics(y_true, y_p50, y_p90):
            wmape = float(np.sum(np.abs(y_true - y_p50)) / np.maximum(np.sum(y_true), 1e-4))
            # pinball loss for tau=0.5 and tau=0.9
            e50 = y_true - y_p50
            pb50 = float(np.mean(np.maximum(0.5 * e50, (0.5 - 1.0) * e50)))
            e90 = y_true - y_p90
            pb90 = float(np.mean(np.maximum(0.9 * e90, (0.9 - 1.0) * e90)))
            cov_raw = float(np.mean(y_true <= y_p90) * 100.0)
            return wmape, pb50, pb90, cov_raw

        # LightGBM (native)
        w_lgb, pb50_lgb, pb90_lgb, cov_lgb = compute_metrics(y_test, p50_lgb, p90_lgb)
        forecast_quality_rows.append({"app": app, "forecaster": "lightgbm", "wmape": w_lgb, "pinball_50": pb50_lgb, "pinball_90": pb90_lgb, "raw_coverage_90": cov_lgb})

        # Seasonal naive (point forecast serves as both 50 and 90 raw)
        w_sn, pb50_sn, pb90_sn, cov_sn = compute_metrics(y_test, naive_point, naive_point)
        forecast_quality_rows.append({"app": app, "forecaster": "seasonal_naive", "wmape": w_sn, "pinball_50": pb50_sn, "pinball_90": pb90_sn, "raw_coverage_90": cov_sn})

        # Holt-Winters (point forecast serves as both 50 and 90 raw)
        w_hw, pb50_hw, pb90_hw, cov_hw = compute_metrics(y_test, hw_point, hw_point)
        forecast_quality_rows.append({"app": app, "forecaster": "holt_winters", "wmape": w_hw, "pinball_50": pb50_hw, "pinball_90": pb90_hw, "raw_coverage_90": cov_hw})

        # Quantile linear
        w_lin, pb50_lin, pb90_lin, cov_lin = compute_metrics(y_test, linear_point_50, linear_point_90)
        forecast_quality_rows.append({"app": app, "forecaster": "quantile_linear", "wmape": w_lin, "pinball_50": pb50_lin, "pinball_90": pb90_lin, "raw_coverage_90": cov_lin})

    # Save forecast quality CSV
    fq_df = pd.DataFrame(forecast_quality_rows)
    os.makedirs("eval/reports", exist_ok=True)
    fq_df.to_csv("eval/reports/forecast_quality.csv", index=False)
    logger.info(f"Wrote {len(fq_df)} rows to eval/reports/forecast_quality.csv")

    # Step 2: Parallel simulation
    logger.info(f"Starting parallel simulation across 20 validation apps with {max_workers} processes...")
    sim_tasks = []
    for app in test_apps:
        y_test, m_test, p90_lgb, p50_lgb, point_streams = test_streams[app]
        sim_tasks.append((app, y_test, m_test, p90_lgb, p50_lgb, point_streams, ca_utils, aegis_taus))

    ca_pareto_points: Dict[str, List[Tuple[float, float]]] = {}
    arm_pareto_points: Dict[str, Dict[str, List[Tuple[float, float]]]] = {m: {} for m in ALL_STUDY_ARMS}
    app_raw_sim_results: Dict[str, Dict[str, Any]] = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_simulate_single_app_baselines, task): task[0] for task in sim_tasks}
        completed = 0
        for fut in as_completed(futures):
            app_id, ca_pts, a_pts_dict, raw_res = fut.result()
            ca_pareto_points[app_id] = ca_pts
            for m in ALL_STUDY_ARMS:
                arm_pareto_points[m][app_id] = a_pts_dict[m]
            app_raw_sim_results[app_id] = raw_res
            completed += 1
            if completed % 5 == 0 or completed == len(sim_tasks):
                logger.info(f"Progress: {completed}/{len(sim_tasks)} apps simulated.")

    # Step 3: Compute matched-shortfall Pareto analysis across targets
    logger.info("Computing matched-shortfall Pareto frontiers, CIs, and arm comparisons...")
    pareto_report: Dict[str, Any] = {}
    total_eval_minutes = len(test_streams[test_apps[0]][0])

    for target_pct in targets_pct:
        target_minutes = compute_target_minutes(target_pct, total_eval_minutes)
        target_label = f"{target_pct:.1f}%"
        pareto_report[target_label] = {}

        # Collect p-values across arms at this target for Holm correction
        target_p_vals = []
        target_p_meta = []

        for m in ALL_STUDY_ARMS:
            ca_energies = []
            arm_energies = []
            deltas = []

            ca_extrap_count = 0
            arm_extrap_count = 0
            ca_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}
            arm_extrap_sides = {"below_min_shortfall": 0, "above_max_shortfall": 0, "none": 0}
            degenerate_apps = []
            per_app_dict = {}

            for app in test_apps:
                ca_pts = ca_pareto_points[app]
                ae_pts = arm_pareto_points[m][app]

                ca_interp = interpolate_energy_at_shortfall(ca_pts, target_minutes)
                ae_interp = interpolate_energy_at_shortfall(ae_pts, target_minutes)

                ca_e = float(ca_interp["energy"])
                ae_e = float(ae_interp["energy"])
                d_e = ae_e - ca_e

                ca_energies.append(ca_e)
                arm_energies.append(ae_e)
                deltas.append(d_e)

                if ca_interp["is_extrapolated"]:
                    ca_extrap_count += 1
                    ca_extrap_sides[ca_interp["extrapolation_side"]] += 1
                else:
                    ca_extrap_sides["none"] += 1

                if ae_interp["is_extrapolated"]:
                    arm_extrap_count += 1
                    arm_extrap_sides[ae_interp["extrapolation_side"]] += 1
                else:
                    arm_extrap_sides["none"] += 1

                if ae_interp["is_degenerate"]:
                    degenerate_apps.append({
                        "app_id": app,
                        "min_shortfall": round(ae_interp["min_shortfall"], 2),
                        "max_shortfall": round(ae_interp["max_shortfall"], 2),
                    })

                per_app_dict[app] = {
                    "ca_energy": round(ca_e, 4),
                    "aegis_energy": round(ae_e, 4),
                    "delta_energy": round(d_e, 4),
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

            m_delta, ci_l, ci_u = paired_bootstrap_ci(np.array(arm_energies), np.array(ca_energies))
            ca_med = float(np.median(ca_energies))
            ae_med = float(np.median(arm_energies))
            cheaper_pct = float(np.mean(np.array(arm_energies) < np.array(ca_energies)) * 100.0)

            # Statistical test vs CA
            r_rb, p_two, p_less = compute_rank_biserial(np.array(deltas))
            target_p_vals.append(p_two)
            target_p_meta.append(m)

            pareto_report[target_label][m] = {
                "target_shortfall_minutes": target_minutes,
                "ca_median_energy": round(ca_med, 2),
                "aegis_median_energy": round(ae_med, 2),
                "median_diff_energy": round(ae_med - ca_med, 2),
                "mean_delta_energy": round(m_delta, 3),
                "bootstrap_ci95": [round(ci_l, 3), round(ci_u, 3)],
                "cheaper_fraction_pct": round(cheaper_pct, 2),
                "ca_extrapolations": ca_extrap_count,
                "aegis_extrapolations": arm_extrap_count,
                "ca_extrapolation_sides": ca_extrap_sides,
                "aegis_extrapolation_sides": arm_extrap_sides,
                "degenerate_frontiers_count": len(degenerate_apps),
                "degenerate_apps": degenerate_apps,
                "wilcoxon_two_sided_p": round(p_two, 6),
                "per_app_results": per_app_dict,
            }

        # Holm correction across arms at this target
        adj_p_vals = holm_bonferroni(target_p_vals)
        for arm_name, adj_p in zip(target_p_meta, adj_p_vals):
            pareto_report[target_label][arm_name]["wilcoxon_holm_adj_p"] = round(adj_p, 6)

        # Pairwise comparison vs primary Aegis rolling arm: Delta = E_Aegis_rolling - E_arm
        primary_energies = np.array([pareto_report[target_label]["rolling"]["per_app_results"][a]["aegis_energy"] for a in test_apps])
        vs_rolling_dict = {}
        for m in ALL_STUDY_ARMS:
            if m == "rolling":
                continue
            m_energies = np.array([pareto_report[target_label][m]["per_app_results"][a]["aegis_energy"] for a in test_apps])
            # Sign convention: Aegis minus baseline
            diff_vs_roll = primary_energies - m_energies
            mean_d, ci_l_d, ci_u_d = paired_bootstrap_ci(primary_energies, m_energies)
            r_rb_d, p_two_d, _ = compute_rank_biserial(diff_vs_roll)
            vs_rolling_dict[m] = {
                "mean_delta_vs_aegis": round(mean_d, 3),
                "bootstrap_ci95": [round(ci_l_d, 3), round(ci_u_d, 3)],
                "wilcoxon_two_sided_p": round(p_two_d, 6),
                "rank_biserial": round(r_rb_d, 4),
            }
        pareto_report[target_label]["vs_primary_aegis_rolling"] = vs_rolling_dict

    # Step 4: Natural operating points (tau=0.90 vs CA U=0.50, 0.60)
    logger.info("Computing natural operating point comparisons (tau=0.90 vs CA U=0.50, U=0.60)...")
    operating_points_report: Dict[str, Any] = {}
    p_values_to_correct = []
    p_meta = []

    for m in ALL_STUDY_ARMS:
        operating_points_report[m] = {}
        # For fixed_margin, operating point is nominal 1.0 core margin
        op_key_val = 1.0 if m == "fixed_margin" else 0.90

        for ca_u in [0.50, 0.60]:
            u_key = f"ca_u_{int(ca_u*100)}"
            ae_energies = []
            ca_energies = []
            ae_shortfalls = []
            ca_shortfalls = []
            delta_e_list = []
            delta_s_list = []

            for app in test_apps:
                raw = app_raw_sim_results[app]
                ae_pt = raw["arm_operating_points"][m][op_key_val]
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

            m_delta_e, ci_l_e, ci_u_e = paired_bootstrap_ci(np.array(ae_energies), np.array(ca_energies))
            m_delta_s, ci_l_s, ci_u_s = paired_bootstrap_ci(np.array(ae_shortfalls), np.array(ca_shortfalls))
            ae_med_e = float(np.median(ae_energies))
            ca_med_e = float(np.median(ca_energies))
            ae_med_s = float(np.median(ae_shortfalls))
            ca_med_s = float(np.median(ca_shortfalls))

            r_rb, p_two, p_less = compute_rank_biserial(np.array(delta_e_list))
            p_values_to_correct.append(p_two)
            p_meta.append((m, u_key))

            operating_points_report[m][u_key] = {
                "arm_operating_point": op_key_val,
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
                "wilcoxon_two_sided_p": round(p_two, 6),
                "rank_biserial_effect_size": round(r_rb, 4),
            }

    adj_p_values = holm_bonferroni(p_values_to_correct)
    for (m, u_key), adj_p in zip(p_meta, adj_p_values):
        operating_points_report[m][u_key]["wilcoxon_holm_bonferroni_p"] = round(adj_p, 6)

    # Compile final JSON document
    full_output = {
        "schema_version": "v4",
        "study_name": "Task W3: Baselines and Ablations Study",
        "git_commit": prov["git_commit"],
        "dirty_flag": prov["dirty_flag"],
        "config_hash": prov["config_sha256"],
        "timestamp_utc": prov["timestamp_utc"],
        "python_version": sys.version,
        "seeds": [42],
        "configuration": config_dict,
        "app_partition": {
            "test_apps_count": len(test_apps),
            "test_apps": test_apps,
            "tertiles": tertiles,
        },
        "matched_shortfall_pareto": pareto_report,
        "natural_operating_points": operating_points_report,
    }

    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(full_output, f, indent=2)
    logger.info(f"Baselines study completed. Output saved to {output_json}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Task W3 Baselines & Ablations Study.")
    parser.add_argument("--output", default=OUTPUT_JSON, help="Output JSON path")
    parser.add_argument("--workers", type=int, default=6, help="Parallel worker count")
    args = parser.parse_args()

    run_baselines_study(output_json=args.output, max_workers=args.workers)

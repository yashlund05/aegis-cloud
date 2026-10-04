#!/usr/bin/env python3
"""
Step 6 Cause Test script comparing four rolling variants:
(i) v3 code as is (rolling.quantile().bfill())
(ii) v3 with bfill removed (rolling.quantile().fillna(0.0))
(iii) v3 quantile with v4's causal loop (np.quantile on history without finite sample level)
(iv) v4 as is (finite sample ceil((n+1)*tau)/n with causal window)
"""
import os
import json
import math
import numpy as np
import pandas as pd
import lightgbm as lgb
from datasets.load_real_trace import TOTAL_MINUTES
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import QuantileModelWrapper
from eval.headline_study_v4 import load_study_data, interpolate_energy_at_shortfall
from eval.provenance import get_provenance, compute_config_hash
from ml.evaluation.ablation import AblationStudy

HORIZON_MINUTES = 10
W = 1440
MODELS_DIR = "ml/models/artifacts_60app"

def rolling_v3_asis(y_test, p90_raw, tau, H=10, W=1440):
    residuals = pd.Series(y_test - p90_raw).shift(H)
    offset = residuals.rolling(window=W, min_periods=20).quantile(tau).bfill().fillna(0.0).to_numpy()
    return p90_raw + offset

def rolling_v3_nobfill(y_test, p90_raw, tau, H=10, W=1440):
    residuals = pd.Series(y_test - p90_raw).shift(H)
    offset = residuals.rolling(window=W, min_periods=20).quantile(tau).fillna(0.0).to_numpy()
    return p90_raw + offset

def rolling_v3_quant_v4_causal(y_test, p90_raw, tau, H=10, W=1440):
    T = len(y_test)
    p90_rolling = np.empty(T, dtype=np.float64)
    calib_residuals = []
    for t in range(T):
        if t >= H:
            t_eval = t - H
            calib_residuals.append(y_test[t_eval] - p90_raw[t_eval])
            if len(calib_residuals) > W:
                calib_residuals.pop(0)
        if len(calib_residuals) < 20:
            p90_rolling[t] = p90_raw[t]
        else:
            q_offset = np.quantile(calib_residuals, tau)
            p90_rolling[t] = p90_raw[t] + q_offset
    return p90_rolling

def rolling_v4_asis(y_test, p90_raw, tau, H=10, W=1440):
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

def main():
    calib_apps, test_apps, cores_cols, app_mems = load_study_data()
    stamps = pd.date_range("2024-01-01", periods=TOTAL_MINUTES, freq="1min")

    models = {}
    for q in (0.5, 0.9):
        path = f"{MODELS_DIR}/aegis_h{HORIZON_MINUTES}m_q{int(q*100)}.txt"
        booster = lgb.Booster(model_file=path)
        models[q] = QuantileModelWrapper(booster, backend="lightgbm", feature_names=booster.feature_name())

    # Load CA points and raw streams
    with open("eval/headline_results_v4.json", "r") as f:
        v4_data = json.load(f)
    with open("eval/scale_aware_pareto_results_v3.json", "r") as f:
        v3_data = json.load(f)

    variants = {
        "v3_asis": rolling_v3_asis,
        "v3_nobfill": rolling_v3_nobfill,
        "v3_quant_v4_causal": rolling_v3_quant_v4_causal,
        "v4_asis": rolling_v4_asis,
    }

    results = {}
    worst_apps = [
        "0e18802d31bf22abefa07cef938d2563cbba9a7155145618501ce2b447bc8e46",
        "fe5c01bb7981a5dcb7aebd13280cebe229cf6e04670b1ccf9442ed0bb0c87381"
    ]

    study = AblationStudy()

    # Precompute test streams
    test_streams = {}
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

    aegis_taus = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.975, 0.99, 0.995, 0.999]
    target_shortfall_10 = 187.2 # 1.0%

    for vname, fn in variants.items():
        cov_list = []
        worst_cov = {}
        delta_energies = []

        for app in test_apps:
            y_test, m_test, p90_raw, p50_raw = test_streams[app]

            # Nominal coverage at tau=0.90
            p90_ro_90 = np.maximum(fn(y_test, p90_raw, tau=0.90), p50_raw)
            c = float(np.mean(y_test <= p90_ro_90) * 100.0)
            cov_list.append(c)

            if app in worst_apps:
                worst_cov[app[:16]] = round(c, 4)

            # Build Pareto frontier across taus for 1.0% target evaluation
            points = []
            for tau in aegis_taus:
                p90_ro = np.maximum(fn(y_test, p90_raw, tau=tau), p50_raw)
                res_sim = study._simulate_configuration(y_test, m_test, p90_ro, "full_aegis_conformal", forecast_horizon_minutes=HORIZON_MINUTES)
                points.append((float(res_sim["capacity_shortfall_minutes"]), float(res_sim["energy_kwh"])))

            interp = interpolate_energy_at_shortfall(points, target_shortfall_10)
            ca_e = v4_data["matched_shortfall_pareto"]["1.0%"]["rolling"]["per_app_results"][app]["ca_energy"]
            delta_energies.append(interp["energy"] - ca_e)

        cov_median = float(np.median(cov_list))
        cov_iqr = float(np.percentile(cov_list, 75) - np.percentile(cov_list, 25))
        mean_delta = float(np.mean(delta_energies))

        results[vname] = {
            "coverage_median": round(cov_median, 4),
            "coverage_iqr": round(cov_iqr, 4),
            "worst_apps_coverage": worst_cov,
            "mean_delta_energy_1pct": round(mean_delta, 4)
        }

    prov = get_provenance()
    config = {
        "study": "rolling_variants_cause_test",
        "variants": list(variants.keys()),
        "horizon_minutes": 10,
        "window_steps": 1440,
        "target_shortfall_minutes": target_shortfall_10,
    }
    config_hash = compute_config_hash(config)

    output_payload = {
        **prov,
        "config_hash": config_hash,
        "configuration": config,
        "seeding_mechanism": "eval/headline_study_v4.py:468 (eval_mask targets >= 1440 min). Residual buffer starts empty at first scored minute (t=0 of y_test, which corresponds to minute 1440 of full trace). The 1-day warmup does NOT seed the rolling buffer.",
        "results": results
    }

    with open("eval/rolling_variants_results.json", "w", encoding="utf-8") as f:
        json.dump(output_payload, f, indent=2)

    print("================================================================================")
    print("STEP 6: ROLLING VARIANTS CAUSE TEST RESULTS")
    print("================================================================================")
    print(json.dumps(output_payload, indent=2))

if __name__ == "__main__":
    main()

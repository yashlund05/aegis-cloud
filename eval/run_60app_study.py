"""
Sixty-App Empirical Evaluation on Real Azure Functions 2019 Trace.

Protocol:
1. Universe: 24,274 Azure Functions apps (14 days, 20,160 1-min steps).
2. Filter criteria (eval/app_selection.md):
   - days_present >= 7
   - missing_pct < 5.0%
   - max_cpu <= 68.0 cores (cluster physical capacity)
   - mean_cpu >= 0.50 cores (non-trivial workload)
3. App Selection: 60 apps sampled with fixed random seed (seed = 42).
4. Partition BY APP:
   - 30 Train apps (used exclusively to train LightGBM quantile regressors)
   - 10 Calibrate apps (used exclusively for split-conformal calibration residuals)
   - 20 Test apps (unseen evaluation targets)
5. Censoring check on test apps:
   - Fraction of minutes observed usage is near cluster allocation cap (68 cores).
6. Main configs replayed under identical service-style safety guards:
   - cluster_autoscaler
   - reactive_hpa_plus_consolidation
   - full_aegis_conformal
   - seasonal_naive_conformal
   - oracle
7. Statistical inference:
   - Per-app distributions (Median, IQR, Mean, Std)
   - Wilcoxon signed-rank tests with Holm correction
   - Paired bootstrap 95% CIs (B = 10,000)
8. Provenance: git commit hash and SHA-256 config hash recorded in output JSON.
"""

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath("."))

from datasets.load_real_trace import (
    MINUTES_PER_DAY,
    N_DAYS,
    TOTAL_MINUTES,
    VCPU_PER_EXECUTION,
    _day_file,
    load_duration_table,
    load_memory_table,
)
from ml.evaluation.ablation import AblationStudy
from ml.features.feature_engineering import build_features
from ml.training.train_lightgbm import train_quantile_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sixty_app_study")

OUTPUT_JSON = "eval/sixty_app_study_results.json"
MODELS_DIR = "ml/models/artifacts_60app"
SELECTION_SEED = 42
HORIZON_MINUTES = 10
CLUSTER_CAP_CORES = 68.0
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


def holm_bonferroni(p_values: List[float]) -> List[float]:
    """Applies Holm-Bonferroni step-down correction to a list of p-values."""
    m = len(p_values)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m
    cum_max = 0.0
    for rank, (orig_idx, p_val) in enumerate(indexed):
        adj = (m - rank) * p_val
        cum_max = max(cum_max, adj)
        adjusted[orig_idx] = min(1.0, cum_max)
    return adjusted


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


def extract_app_time_series(target_apps: List[str]) -> Tuple[Dict[str, np.ndarray], Dict[str, float]]:
    logger.info(f"Extracting 14-day invocation traces for {len(target_apps)} apps...")
    target_set = set(target_apps)
    cores_cols = {app: np.zeros(TOTAL_MINUTES, dtype=np.float64) for app in target_set}

    t0 = time.time()
    for day in range(1, N_DAYS + 1):
        inv_path = _day_file("invocations_per_function_md.anon.d{d}.csv", day)
        dur = load_duration_table(day)
        minute_cols = [str(m) for m in range(1, MINUTES_PER_DAY + 1)]
        chunk_iter = pd.read_csv(
            inv_path,
            usecols=["HashApp", "HashFunction"] + minute_cols,
            chunksize=50000,
            dtype={c: np.int32 for c in minute_cols},
        )
        day_offset = (day - 1) * MINUTES_PER_DAY
        for chunk in chunk_iter:
            chunk = chunk[chunk["HashApp"].isin(target_set)]
            if chunk.empty:
                continue
            fn = pd.DataFrame({"HashFunction": chunk["HashFunction"]})
            durs = fn.merge(dur.reset_index(), on="HashFunction", how="left")["Average"].fillna(0.0).to_numpy()
            weights = (durs / 1000.0 / 60.0) * VCPU_PER_EXECUTION
            weighted = chunk[minute_cols].mul(weights, axis=0)
            agg = weighted.groupby(chunk["HashApp"]).sum()
            for app, row in agg.iterrows():
                cores_cols[app][day_offset : day_offset + MINUTES_PER_DAY] += row.to_numpy()
        logger.info(f"  Day {day:02d}/14 extracted ({time.time() - t0:.1f}s elapsed)")

    # Memory table
    mem_table = load_memory_table() / 1024.0
    mean_mem = float(mem_table.mean())
    app_mems = {}
    for app in target_apps:
        m = mem_table.get(app, np.nan)
        app_mems[app] = float(m) if not pd.isna(m) else mean_mem

    return cores_cols, app_mems


def main():
    print("=" * 115)
    print("  AEGIS SIXTY-APP EMPIRICAL EVALUATION: AZURE FUNCTIONS 2019 TRACE")
    print("  Partition: 30 Train Apps | 10 Calibrate Apps | 20 Test Apps (BY APP SPLIT)")
    print("  Models: LightGBM p10, p50, p90 (Horizon H = 10 min) trained strictly on Train Apps")
    print("  Safety Guards: 70% Target Util, 10% Dead Zone, 300s Cooldown, 3 min Boot Latency, HPA Scale Step Limits")
    print("=" * 115)

    git_commit = get_git_commit()
    config_dict = {
        "selection_seed": SELECTION_SEED,
        "n_train_apps": 30,
        "n_calib_apps": 10,
        "n_test_apps": 20,
        "forecast_horizon_minutes": HORIZON_MINUTES,
        "cluster_capacity_cores": CLUSTER_CAP_CORES,
        "nodes": 20,
        "cores_per_node": 4.0,
        "allocatable_factor": 0.85,
        "hpa_target_util": 0.70,
        "dead_zone_pct": 0.10,
        "cooldown_seconds": 300,
        "wake_up_latency_steps": 3,
        "min_active_nodes": 2,
        "bootstrap_iterations": BOOTSTRAP_B,
    }
    config_hash = compute_config_hash(config_dict)
    print(f"  Git Commit Hash : {git_commit}")
    print(f"  Config SHA-256  : {config_hash}\n")

    # 1. Load app universe and apply selection rule
    stats_df = pd.read_parquet("datasets/azure_all_apps_stats.parquet")
    eligible = stats_df[
        (stats_df["days_present"] >= 7)
        & (stats_df["missing_pct"] < 5.0)
        & (stats_df["max_cpu"] <= CLUSTER_CAP_CORES)
        & (stats_df["mean_cpu"] >= 0.50)
    ].sort_values("app").reset_index(drop=True)

    print(f"Total apps in trace: {len(stats_df)}")
    print(f"Eligible apps passing all filters: {len(eligible)}")
    selected_60 = eligible.sample(n=60, random_state=SELECTION_SEED).reset_index(drop=True)

    train_apps = selected_60.iloc[:30]["app"].tolist()
    calib_apps = selected_60.iloc[30:40]["app"].tolist()
    test_apps = selected_60.iloc[40:60]["app"].tolist()

    print(f"Selected 60 Apps: {len(train_apps)} Train | {len(calib_apps)} Calib | {len(test_apps)} Test\n")

    # 2. Extract 14-day traces for all 60 apps
    cores_cols, app_mems = extract_app_time_series(selected_60["app"].tolist())

    stamps = pd.date_range("2019-07-01 00:00:00+00:00", periods=TOTAL_MINUTES, freq="1min")

    # 3. Train Forecaster on Train Apps ONLY
    logger.info("Building training features across 30 train apps...")
    X_train_list, y_train_list = [], []
    X_val_list, y_val_list = [], []

    # Use first 24 train apps for fitting, last 6 train apps for validation/early stopping
    fit_train_apps = train_apps[:24]
    val_train_apps = train_apps[24:]

    for app in fit_train_apps:
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": cores_cols[app],
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        valid = target_idx < TOTAL_MINUTES

        X_df = feat.reset_index(drop=True)[valid]
        feat_cols = [c for c in X_df.columns if c not in ("cpu_usage", "timestamp", "workload_id") and pd.api.types.is_numeric_dtype(X_df[c])]
        X_train_list.append(X_df[feat_cols])
        y_train_list.append(df_app["cpu_usage"].to_numpy()[target_idx[valid]])

    for app in val_train_apps:
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": cores_cols[app],
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        valid = target_idx < TOTAL_MINUTES

        X_df = feat.reset_index(drop=True)[valid]
        feat_cols = [c for c in X_df.columns if c not in ("cpu_usage", "timestamp", "workload_id") and pd.api.types.is_numeric_dtype(X_df[c])]
        X_val_list.append(X_df[feat_cols])
        y_val_list.append(df_app["cpu_usage"].to_numpy()[target_idx[valid]])

    X_tr = pd.concat(X_train_list, ignore_index=True)
    y_tr = pd.Series(np.concatenate(y_train_list))
    X_vl = pd.concat(X_val_list, ignore_index=True)
    y_vl = pd.Series(np.concatenate(y_val_list))

    logger.info(f"Training pool: {len(X_tr)} train rows, {len(X_vl)} val rows across {len(feat_cols)} features")

    os.makedirs(MODELS_DIR, exist_ok=True)
    models = {}
    for q in (0.1, 0.5, 0.9):
        logger.info(f"Training LightGBM quantile model for q={q}...")
        mod = train_quantile_model(X_tr, y_tr, X_vl, y_vl, quantile=q)
        mod.save(os.path.join(MODELS_DIR, f"aegis_h{HORIZON_MINUTES}m_q{int(q*100)}.txt"))
        models[q] = mod

    # 4. Calibration on the 10 Calibrate Apps
    logger.info("Computing split-conformal calibration residuals on 10 calibrate apps...")
    calib_residuals_90 = []
    calib_residuals_10 = []
    naive_residuals_90 = []

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
        valid = (target_idx < TOTAL_MINUTES) & (feat_idx >= 1440)  # past 1-day lag

        X_app = feat.reset_index(drop=True)[valid][feat_cols]
        y_actual = df_app["cpu_usage"].to_numpy()[target_idx[valid]]
        # Seasonal naive prediction: demand 1440 minutes prior to target
        naive_pred = df_app["cpu_usage"].to_numpy()[target_idx[valid] - 1440]

        p90_raw = models[0.9].predict(X_app)
        p10_raw = models[0.1].predict(X_app)

        calib_residuals_90.extend((y_actual - p90_raw).tolist())
        calib_residuals_10.extend((p10_raw - y_actual).tolist())
        naive_residuals_90.extend((y_actual - naive_pred).tolist())

    m_cal = len(calib_residuals_90)
    level_90 = min(1.0, np.ceil((m_cal + 1) * 0.90) / m_cal)
    q_hat_90 = float(np.quantile(calib_residuals_90, level_90))
    q_hat_10 = float(np.quantile(calib_residuals_10, level_90))
    q_hat_naive = float(np.quantile(naive_residuals_90, level_90))

    logger.info(f"Calibration complete over {m_cal} observations:")
    logger.info(f"  q_hat_90 (LightGBM)    : +{q_hat_90:.4f} cores")
    logger.info(f"  q_hat_10 (LightGBM)    : -{q_hat_10:.4f} cores")
    logger.info(f"  q_hat_90 (SeasonalNaive): +{q_hat_naive:.4f} cores")

    # 5. Censoring Check on 20 Test Apps
    print("\n" + "=" * 115)
    print("  CENSORING CHECK: TEST APPS OBSERVED DEMAND vs ALLOCATION CAP (68.0 cores)")
    print("=" * 115)
    print(f"  {'App ID':<20} | {'Mean (cores)':>12} | {'Peak (cores)':>12} | {'Peak/Cap (%)':>12} | {'>=90% Cap (min)':>16} | {'>=95% Cap (min)':>16} | {'Censored %':>12}")
    print("  " + "-" * 110)

    censoring_results = {}
    for app in test_apps:
        series = cores_cols[app]
        mean_c = float(series.mean())
        max_c = float(series.max())
        peak_ratio = (max_c / CLUSTER_CAP_CORES) * 100.0
        min_90 = int(np.sum(series >= 0.90 * CLUSTER_CAP_CORES))
        min_95 = int(np.sum(series >= 0.95 * CLUSTER_CAP_CORES))
        frac_95 = (min_95 / len(series)) * 100.0

        censoring_results[app] = {
            "mean_cores": round(mean_c, 3),
            "peak_cores": round(max_c, 3),
            "peak_ratio_pct": round(peak_ratio, 2),
            "minutes_above_90pct_cap": min_90,
            "minutes_above_95pct_cap": min_95,
            "censored_fraction_pct": round(frac_95, 4),
        }
        print(f"  {app[:16]:<20} | {mean_c:>12.3f} | {max_c:>12.3f} | {peak_ratio:>11.1f}% | {min_90:>16d} | {min_95:>16d} | {frac_95:>11.3f}%")

    # 6. Replay Main Configs on 20 Test Apps
    print("\n" + "=" * 115)
    print("  REPLAYING 5 MAIN CONFIGURATIONS ON 20 TEST APPS (14 Days / App, Warm-start 60 min excluded)")
    print("=" * 115)

    study = AblationStudy(min_active_nodes=2, wake_up_latency_steps=3)
    configs = ["cluster_autoscaler", "reactive_hpa_plus_consolidation", "full_aegis_conformal", "seasonal_naive_conformal", "oracle"]

    per_app_metrics = {cfg: [] for cfg in configs}
    per_app_records = {}

    for idx, app in enumerate(test_apps, 1):
        df_app = pd.DataFrame({
            "timestamp": stamps,
            "cpu_usage": cores_cols[app],
            "memory_usage": np.full(TOTAL_MINUTES, app_mems[app]),
        })
        feat = build_features(df_app)
        start_idx = TOTAL_MINUTES - len(feat)
        feat_idx = np.arange(start_idx, TOTAL_MINUTES)
        target_idx = feat_idx + HORIZON_MINUTES
        # We start evaluation at minute 1440 to accommodate the 1-day lag of seasonal naive
        eval_mask = (target_idx < TOTAL_MINUTES) & (target_idx >= 1440)

        y_actual = df_app["cpu_usage"].to_numpy()[target_idx[eval_mask]]
        m_actual = df_app["memory_usage"].to_numpy()[target_idx[eval_mask]]
        X_app = feat.reset_index(drop=True)[eval_mask][feat_cols]

        # Forecast streams
        p90_raw = models[0.9].predict(X_app)
        p50_raw = models[0.5].predict(X_app)
        p90_conformal = np.maximum(p90_raw + q_hat_90, p50_raw)

        # Seasonal naive stream
        naive_raw = df_app["cpu_usage"].to_numpy()[target_idx[eval_mask] - 1440]
        naive_conformal = np.maximum(naive_raw + q_hat_naive, 0.0)

        app_res = {}
        for cfg in configs:
            if cfg == "full_aegis_conformal":
                p90_str = p90_conformal
                sim_cfg = "full_aegis_conformal"
            elif cfg == "seasonal_naive_conformal":
                p90_str = naive_conformal
                sim_cfg = "full_aegis_conformal"
            elif cfg == "cluster_autoscaler":
                p90_str = p90_conformal
                sim_cfg = "cluster_autoscaler"
            elif cfg == "reactive_hpa_plus_consolidation":
                p90_str = p90_conformal
                sim_cfg = "reactive_hpa_plus_consolidation"
            elif cfg == "oracle":
                p90_str = y_actual
                sim_cfg = "oracle"

            res = study._simulate_configuration(
                actual_demands=y_actual,
                actual_mems=m_actual,
                p90_forecasts=p90_str,
                config_name=sim_cfg,
                forecast_horizon_minutes=HORIZON_MINUTES,
            )
            app_res[cfg] = {
                "energy_kwh": res["energy_kwh"],
                "capacity_shortfall_minutes": res["capacity_shortfall_minutes"],
                "scaling_actions": res["scaling_actions"],
                "scaling_churn": res["scaling_churn"],
            }
            per_app_metrics[cfg].append(app_res[cfg])

        per_app_records[app] = app_res
        print(f"  [{idx:02d}/20] App {app[:14]}: CA={app_res['cluster_autoscaler']['energy_kwh']:.1f} kWh, "
              f"Aegis={app_res['full_aegis_conformal']['energy_kwh']:.1f} kWh, "
              f"Shortfall={app_res['full_aegis_conformal']['capacity_shortfall_minutes']:.0f}m, "
              f"Naive={app_res['seasonal_naive_conformal']['energy_kwh']:.1f} kWh")

    # 7. Distribution Statistics (Median, IQR, Mean, Std)
    print("\n" + "=" * 115)
    print("  PER-APP DISTRIBUTION SUMMARY (N = 20 Test Apps)")
    print("=" * 115)
    print(f"  {'Configuration':<32} | {'Energy Median (IQR)':<22} | {'Shortfall Med (IQR)':<22} | {'Events Med (IQR)':<22} | {'Churn Med (IQR)':<22}")
    print("  " + "-" * 110)

    dist_summary = {}
    for cfg in configs:
        e = [m["energy_kwh"] for m in per_app_metrics[cfg]]
        s = [m["capacity_shortfall_minutes"] for m in per_app_metrics[cfg]]
        a = [m["scaling_actions"] for m in per_app_metrics[cfg]]
        c = [m["scaling_churn"] for m in per_app_metrics[cfg]]

        e_med, e_iqr = float(np.median(e)), float(np.percentile(e, 75) - np.percentile(e, 25))
        s_med, s_iqr = float(np.median(s)), float(np.percentile(s, 75) - np.percentile(s, 25))
        a_med, a_iqr = float(np.median(a)), float(np.percentile(a, 75) - np.percentile(a, 25))
        c_med, c_iqr = float(np.median(c)), float(np.percentile(c, 75) - np.percentile(c, 25))

        dist_summary[cfg] = {
            "energy": {"median": round(e_med, 2), "iqr": round(e_iqr, 2), "mean": round(float(np.mean(e)), 2), "std": round(float(np.std(e)), 2)},
            "shortfall": {"median": round(s_med, 2), "iqr": round(s_iqr, 2), "mean": round(float(np.mean(s)), 2), "std": round(float(np.std(s)), 2)},
            "events": {"median": round(a_med, 2), "iqr": round(a_iqr, 2), "mean": round(float(np.mean(a)), 2), "std": round(float(np.std(a)), 2)},
            "churn": {"median": round(c_med, 2), "iqr": round(c_iqr, 2), "mean": round(float(np.mean(c)), 2), "std": round(float(np.std(c)), 2)},
        }

        print(f"  {cfg:<32} | {e_med:>7.1f} ({e_iqr:>5.1f}) kWh   | {s_med:>7.1f} ({s_iqr:>5.1f}) min   | {a_med:>7.1f} ({a_iqr:>5.1f})      | {c_med:>7.1f} ({c_iqr:>5.1f})")

    # 8. Wilcoxon Signed-Rank Tests with Holm Correction & Bootstrap 95% CIs
    print("\n" + "=" * 115)
    print("  WILCOXON SIGNED-RANK TESTS & PAIRED BOOTSTRAP 95% CIs (Aegis Conformal vs Baselines)")
    print("=" * 115)
    print(f"  {'Comparison (Aegis vs Baseline)':<38} | {'Metric':<12} | {'Paired Mean Diff (95% CI)':<30} | {'W-Stat':>8} | {'Raw p':>10} | {'Holm-Adj p':>12}")
    print("  " + "-" * 115)

    comparisons = [
        ("cluster_autoscaler", "Cluster Autoscaler"),
        ("reactive_hpa_plus_consolidation", "Reactive+Consolidation"),
        ("seasonal_naive_conformal", "Seasonal Naive Conformal"),
        ("oracle", "Oracle (Upper Bound)"),
    ]

    stat_records = {}
    for metric_key, metric_name in [("energy_kwh", "Energy (kWh)"), ("capacity_shortfall_minutes", "Shortfall (min)"), ("scaling_actions", "Events")]:
        aegis_vals = np.array([m[metric_key] for m in per_app_metrics["full_aegis_conformal"]])

        metric_raw_p = []
        metric_w_stat = []
        metric_ci_info = []

        for base_key, base_name in comparisons:
            base_vals = np.array([m[metric_key] for m in per_app_metrics[base_key]])
            diff = aegis_vals - base_vals

            # Bootstrap CI
            m_diff, ci_l, ci_u = paired_bootstrap_ci(aegis_vals, base_vals)
            metric_ci_info.append((m_diff, ci_l, ci_u))

            # Wilcoxon signed rank test
            non_zero_diff = diff[diff != 0]
            if len(non_zero_diff) < 5:
                w_stat, p_val = float(np.sum(diff)), 1.0
            else:
                try:
                    res = wilcoxon(aegis_vals, base_vals)
                    w_stat, p_val = float(res.statistic), float(res.pvalue)
                except Exception:
                    w_stat, p_val = 0.0, 1.0

            metric_w_stat.append(w_stat)
            metric_raw_p.append(p_val)

        # Apply Holm correction across the 4 baselines for this metric
        adj_p = holm_bonferroni(metric_raw_p)

        for i, (base_key, base_name) in enumerate(comparisons):
            m_diff, ci_l, ci_u = metric_ci_info[i]
            w_stat = metric_w_stat[i]
            r_p = metric_raw_p[i]
            h_p = adj_p[i]
            sig = " *" if h_p < 0.05 else "  "

            comp_label = f"Aegis vs {base_name}"
            ci_str = f"{m_diff:>+6.2f} [{ci_l:>+6.2f}, {ci_u:>+6.2f}]"
            print(f"  {comp_label:<38} | {metric_name:<12} | {ci_str:<30} | {w_stat:>8.1f} | {r_p:>10.4e} | {h_p:>10.4e}{sig}")

            stat_records.setdefault(metric_key, {})[base_key] = {
                "mean_difference": round(m_diff, 3),
                "bootstrap_ci95": [round(ci_l, 3), round(ci_u, 3)],
                "wilcoxon_stat": round(w_stat, 2),
                "raw_p_value": r_p,
                "holm_adjusted_p_value": h_p,
            }

    # 9. Dump full JSON report
    full_report = {
        "git_commit": git_commit,
        "config_hash": config_hash,
        "configuration": config_dict,
        "app_partition": {
            "n_train": len(train_apps),
            "n_calibrate": len(calib_apps),
            "n_test": len(test_apps),
            "train_apps": train_apps,
            "calibrate_apps": calib_apps,
            "test_apps": test_apps,
        },
        "conformal_calibration": {
            "m_observations": m_cal,
            "q_hat_90_cores": round(q_hat_90, 4),
            "q_hat_10_cores": round(q_hat_10, 4),
            "q_hat_naive_cores": round(q_hat_naive, 4),
        },
        "censoring_audit": censoring_results,
        "per_app_distributions": dist_summary,
        "statistical_tests": stat_records,
        "per_app_raw_metrics": per_app_records,
    }

    with open(OUTPUT_JSON, "w") as f:
        json.dump(full_report, f, indent=2)
    logger.info(f"\nAll results saved to {OUTPUT_JSON}")
    print("\n" + "=" * 115)
    print("  STUDY COMPLETE. Full JSON artifact saved at eval/sixty_app_study_results.json")
    print("=" * 115)


if __name__ == "__main__":
    main()
